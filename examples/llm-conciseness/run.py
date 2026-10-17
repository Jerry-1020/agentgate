"""Persist a local mock-Agent evaluation using the server's real LLM Judge."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError("仅接受本机 HTTP API 地址；行内任务请使用已登录的页面。")
    return value.rstrip("/")


def api_client(origin: str):
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(path: str, payload=None, *, method: str | None = None):
        request = Request(
            origin + "/api" + path,
            method=method or ("POST" if payload is not None else "GET"),
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "X-Agent-Platform-Token": "local"},
        )
        try:
            with opener.open(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"{request.method} {path}: HTTP {error.code}") from None
        except (URLError, TimeoutError):
            raise RuntimeError(
                f"{request.method} {path}: 请求失败或超时；若为提交请求，请先查看任务列表，勿自动重试。"
            ) from None
        if isinstance(result, dict) and "code" in result and "data" in result:
            if str(result["code"]) != "0":
                raise RuntimeError(f"{request.method} {path}: 服务端返回失败状态。")
            return result["data"]
        return result

    return call


def example_dataset() -> dict:
    return json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))


def validate_dataset(published: dict) -> None:
    expected = example_dataset()["version"]
    for field in ("id", "dataset_id", "version", "status", "content_sha256"):
        if published.get(field) != expected[field]:
            raise RuntimeError("运行的数据集不是工程保留的示例快照；请核对数据集身份和内容。")


def ensure_dataset(call) -> dict:
    document = example_dataset()
    identity = document["dataset"]["id"]
    if not any(item["id"] == identity for item in call("/datasets")):
        call("/datasets/import", document)
    published = call(f"/datasets/{identity}/versions/1")
    validate_dataset(published)
    return published


def published_evaluator(call, identity: str | None, source: Path | None) -> dict:
    if source is not None:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if set(payload) - {"name", "description", "draft"} or "draft" not in payload:
            raise ValueError("评估器文件必须为 {name, description, draft} API 创建请求。")
        model = payload["draft"].get("config", {}).get("model", {})
        if set(model) - {"provider_id", "model_id", "credential_ref"}:
            raise ValueError("model 仅保存模型标识和凭据引用，不能包含 API Key。")
        created = call("/evaluators", payload)
        identity = created["evaluator"]["id"]
        print(f"已保存评估器：{identity}", flush=True)
        path = "/evaluators/" + quote(identity, safe="")
        call(path + "/drafts/publish", {}, method="POST")
        call(path, {"enabled": True}, method="PATCH")
    detail = call("/evaluators/" + quote(identity or "", safe=""))
    spec = detail.get("latest")
    if not detail["evaluator"]["enabled"] or not spec or spec["kind"] != "llm_judge":
        raise RuntimeError("请选择已发布并启用的 LLM 评估器。")
    connections = call("/model-runtime")["connections"]
    model = spec["config"]["model"]
    if not any(
        row["role"] == "LLM 评估器默认连接"
        and row["configured"]
        and row.get("provider_id") == model["provider_id"]
        and row["model"] == model["model_id"]
        for row in connections
    ):
        raise RuntimeError("服务端未配置该评估模型；请通过本机配置接入后再运行。")
    return spec


def validate_manifest(manifest: dict, evaluator_id: str) -> tuple[dict, list[str]]:
    validate_dataset(manifest["dataset"])
    target = manifest["target"]
    config = target.get("invocation_config", {})
    if (
        target["adapter_type"] != "agent_platform_mock"
        or target["ref"].get("external_target_id") != "agent-base"
        or target["ref"].get("external_version_id") != "1.0"
        or config.get("simulated") is not True
        or config.get("agent_id") != "agent-base"
        or config.get("runtime_type") != "base"
    ):
        raise RuntimeError("运行未使用指定的本地基础编排模拟 Agent v1.0。")
    try:
        local_origin(config.get("origin", ""))
    except argparse.ArgumentTypeError:
        raise RuntimeError("运行的模拟 Agent 地址不是本机回环地址。") from None
    if manifest["primary_evaluator_ids"] != [evaluator_id]:
        raise RuntimeError("运行的主评估器与指定评估器不一致。")
    specs = manifest["evaluator_specs"]
    if len(specs) != 1 or specs[0]["id"] != evaluator_id or specs[0]["kind"] != "llm_judge":
        raise RuntimeError("运行未固定指定 LLM 评估器的发布版本。")
    available = [case["id"] for case in manifest["dataset"]["cases"]]
    selected = manifest.get("selected_case_ids") or available
    if selected not in (available, available[:1]):
        raise RuntimeError("运行样本不属于完整示例或首条 smoke 样本。")
    return specs[0], selected


def resume_snapshot(call, run_id: str, evaluator_id: str) -> tuple[dict, dict, list[str], str]:
    manifest = call(f"/runs/{quote(run_id, safe='')}/manifest")
    evaluator, case_ids = validate_manifest(manifest, evaluator_id)
    tasks = [
        task for task in call("/evaluation-tasks")
        if run_id in task["run_ids"] + task.get("previous_run_ids", [])
    ]
    if len(tasks) != 1 or tasks[0]["kind"] != "single":
        raise RuntimeError("无法确认该运行所属的单次测评任务。")
    return evaluator, manifest["dataset"], case_ids, tasks[0]["id"]


def result_rows(samples: dict, evaluator: dict, case_ids: list[str], run_id: str) -> list[dict]:
    if samples["run"]["id"] != run_id or not samples["complete"]:
        raise RuntimeError("样本结果不属于已完成的指定运行。")
    results = [
        item for item in samples["results"] if item["evaluator_id"] == evaluator["id"]
    ]
    if len(results) != len(case_ids) or {item["case_id"] for item in results} != set(case_ids):
        raise RuntimeError("运行缺少样本的 LLM 评分，不能判定端到端验证成功。")
    rows = []
    for item in results:
        score = item.get("score")
        record = item.get("judge_record") or {}
        if (
            item["run_id"] != run_id
            or item["outcome"] not in {"pass", "fail", "review"}
            or item.get("error_detail")
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or not item.get("reason", "").strip()
        ):
            raise RuntimeError(f"样本 {item['case_id']} 未得到有效评分：{item['outcome']}。")
        if (
            not record.get("raw_response")
            or not record.get("request_sha256")
            or not record.get("request_id")
            or record.get("requested_model") != evaluator["config"]["model"]["model_id"]
            or record.get("provider_id") != evaluator["config"]["model"]["provider_id"]
            or item.get("evaluator_content_sha256") != evaluator["content_sha256"]
        ):
            raise RuntimeError(f"样本 {item['case_id']} 缺少真实 Judge 审计证据或版本不一致。")
        rows.append(
            {
                "case_id": item["case_id"],
                "score": score,
                "outcome": item["outcome"],
                "reason": item["reason"],
                "model": record.get("resolved_model") or record["requested_model"],
                "provider_id": record["provider_id"],
                "request_id": record["request_id"],
                "request_sha256": record["request_sha256"],
                "input_tokens": record.get("input_tokens"),
                "output_tokens": record.get("output_tokens"),
                "latency_ms": record.get("latency_ms"),
            }
        )
    return rows


def save_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=local_origin, default="http://127.0.0.1:15197")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--evaluator-id", help="页面已发布并启用的评估器 ID")
    source.add_argument("--evaluator-file", type=Path, help="无密钥的评估器创建请求 JSON")
    parser.add_argument("--smoke", action="store_true", help="仅执行第一条合成样本")
    parser.add_argument("--resume-run", help="只查询已提交的运行，不重复创建任务")
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    if args.wait_seconds <= 0:
        parser.error("--wait-seconds 必须大于 0")
    if args.resume_run and args.evaluator_file:
        parser.error("恢复查询请使用 --evaluator-id，不应再次创建评估器。")
    report = {"end_to_end_verified": False, "api": args.api, "login_mode": "external"}
    call = api_client(args.api)
    try:
        if args.resume_run:
            run_id = args.resume_run
            report["run_id"] = run_id
            evaluator, dataset, case_ids, task_id = resume_snapshot(call, run_id, args.evaluator_id)
            report["task_id"] = task_id
        else:
            evaluator = published_evaluator(call, args.evaluator_id, args.evaluator_file)
            dataset = ensure_dataset(call)
            case_ids = [case["id"] for case in dataset["cases"]]
            if args.smoke:
                case_ids = case_ids[:1]
            payload = {
                "name": "简洁性 · 真实 LLM 端到端示例",
                "target": {
                    "agent_id": "agent-base",
                    "agent_version": "1.0",
                    "type_group": "base/workflow",
                    "arrange_type": "base",
                },
                "dataset_id": dataset["dataset_id"],
                "dataset_version": dataset["version"],
                "case_ids": case_ids,
                "evaluator_refs": [
                    {"evaluator_id": evaluator["id"], "evaluator_version": evaluator["version"]}
                ],
                "max_parallel_cases": 1,
                "timeout_seconds": 900,
                "max_retries": 0,
                "repetitions": 1,
            }
            created = call("/agent-platform/evaluations", payload)
            run_id = created["run_ids"][0]
            report["task_id"] = created["id"]
        report.update(
            run_id=run_id,
            evaluator_id=evaluator["id"],
            evaluator_version=evaluator["version"],
            dataset_id=dataset["dataset_id"],
            dataset_version=dataset["version"],
            case_ids=case_ids,
            status="pending",
        )
        save_report(args.output, report)
        print(f"运行已保留：{run_id}；等待真实 LLM 评分。", flush=True)
        manifest = call(f"/runs/{run_id}/manifest")
        pinned, selected = validate_manifest(manifest, evaluator["id"])
        if selected != case_ids or pinned["content_sha256"] != evaluator["content_sha256"]:
            raise RuntimeError("运行固定的评估器版本或样本选择不一致。")
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline:
            progress = call(f"/runs/{run_id}/status")
            report["status"] = progress["status"]
            if progress["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        else:
            raise RuntimeError("等待超时；任务仍保留，可带 --resume-run 查询，勿重复提交。")
        if report["status"] != "completed":
            raise RuntimeError(f"运行未完成：{report['status']}。")
        samples = call(f"/runs/{run_id}/samples")
        report["results"] = result_rows(samples, evaluator, case_ids, run_id)
        report.update(end_to_end_verified=True, verified_at=datetime.now(UTC).isoformat())
        save_report(args.output, report)
        print(f"端到端验证成功，{len(report['results'])} 条真实评分已保存：{args.output}")
        return 0
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        report["error"] = str(error)
        save_report(args.output, report)
        print(f"端到端验证未通过：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
