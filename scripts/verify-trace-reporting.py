"""Create six fresh local tasks and verify remotely collected evidence for every turn."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8097")
    args = parser.parse_args()
    parsed = urlsplit(args.api)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username
        or parsed.password
    ):
        parser.error("This acceptance command is for local external mode only.")
    opener = build_opener(ProxyHandler({}))

    def call(path, payload=None):
        request = Request(
            args.api.rstrip("/") + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "X-Agent-Platform-Token": "local"},
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)["data"]

    dataset = call(
        "/api/datasets",
        {
            "name": "Trace 主动上报 · 模拟协议验收",
            "description": "两轮合成回显，仅验证模拟轨迹上报与关联",
        },
    )["dataset"]["id"]
    call(
        f"/api/datasets/{dataset}/drafts/cases",
        {
            "name": "两轮模拟回显",
            "turns": [
                {
                    "input": {"txt": text},
                    "expectations": [
                        {
                            "kind": "output",
                            "path": "output",
                            "condition": {"kind": "matches_pattern", "pattern": ".*" + text + ".*"},
                        }
                    ],
                }
                for text in ("上报第一轮", "上报第二轮")
            ],
        },
    )
    call(f"/api/datasets/{dataset}/drafts/publish", {})
    runs = []
    for mode in ("base", "workflow", "claw"):
        name = "Trace 主动上报 · 本地模拟 · " + mode
        result = call(
            "/api/agent-platform/evaluations",
            {
                "name": name,
                "target": {
                    "team_id": "team-local",
                    "agent_id": "agent-" + mode,
                    "type_group": "abcclaw" if mode == "claw" else "base/workflow",
                    "agent_version": "2.0",
                    **(
                        {"branch_id": "branch-review"} if mode == "claw" else {"arrange_type": mode}
                    ),
                },
                "dataset_id": dataset,
                "dataset_version": 1,
                "evaluator_ids": ["final-output"],
                "timeout_seconds": 90,
                "max_retries": 0,
                "max_parallel_cases": 1,
                "repetitions": 1,
            },
        )
        runs.append({"id": result["run_ids"][0], "name": name, "simulated": True, "turns": 2})
    for mode, dataset in zip(
        ("base", "workflow", "cloudshrimp"),
        json.loads((ROOT / "src/agentgate/demo/loan-core-datasets.json").read_text()),
        strict=True,
    ):
        result = call(
            "/api/bank-evaluations",
            {
                "name": "Trace 主动上报 · 贷款 · " + mode,
                "mode": mode,
                "dataset_id": dataset["id"],
                "dataset_version": 3,
                "case_ids": [mode + "-core-low"],
                "evaluator_ids": ["final-state", "required-tool"],
                "timeout_seconds": 300,
            },
        )
        runs.append(
            {
                "id": result.get("run_id") or result.get("id"),
                "name": mode,
                "simulated": False,
                "turns": 1,
            }
        )
    directory = ROOT / "runtime/trace-reporting-acceptance" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True)
    (directory / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    print("已创建六项新任务；任务ID保存于 " + str(directory), flush=True)
    pending = {r["id"] for r in runs}
    deadline = time.monotonic() + 900
    while pending and time.monotonic() < deadline:
        for run in runs:
            if run["id"] not in pending:
                continue
            status = call("/api/runs/" + run["id"] + "/status")["status"]
            if status in ("completed", "failed", "cancelled"):
                run["status"] = status
                pending.remove(run["id"])
                print(run["name"] + ": " + status, flush=True)
        if pending:
            time.sleep(2)
    (directory / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    if pending:
        raise SystemExit("验收超时；保留已有任务，不重复执行业务。")
    for run in runs:
        samples = call("/api/runs/" + run["id"] + "/samples")
        assert run.get("status") == "completed", str(run)
        assert samples["results"] and all(
            r["outcome"] in ("pass", "not_applicable") for r in samples["results"]
        ), str(run)
        trace = call("/api/runs/" + run["id"] + "/traces/" + samples["results"][0]["case_id"])
        source_ids = {s["attributes"].get("trace_sdk.trace_id") for s in trace["spans"]} - {None}
        assert len(source_ids) == run["turns"], str(run)
        assert (
            all(s["attributes"].get("platform.simulated") is True for s in trace["spans"])
            if run["simulated"]
            else any(s["operation_type"] == "llm" for s in trace["spans"])
        )
        if run["simulated"]:
            assert not any(s["operation_type"] in ("llm", "tool") for s in trace["spans"])
        run["trace_ids"] = sorted(source_ids)
        run["spans"] = len(trace["spans"])
        (directory / (run["id"] + ".json")).write_text(
            json.dumps(trace, ensure_ascii=False, indent=2)
        )
    (directory / "summary.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    print("六类智能体共九轮远程轨迹验证通过：" + str(directory), flush=True)


if __name__ == "__main__":
    main()
