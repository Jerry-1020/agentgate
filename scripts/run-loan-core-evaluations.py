"""Submit new local-only loan runs; historical artifacts are never imported as runs."""

from __future__ import annotations

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
    parser.add_argument(
        "--smoke", action="store_true", help="one low-risk case per run; still calls real models"
    )
    parser.add_argument("--wait-seconds", type=int, default=3600)
    args = parser.parse_args()
    parsed = urlsplit(args.api)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
    ):
        parser.error(
            "Only the local external-mode API is supported; in-bank runs must use the authenticated UI."
        )
    opener = build_opener(ProxyHandler({}))

    def call(path, payload=None):
        request = Request(
            args.api.rstrip("/") + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        )
        with opener.open(request, timeout=30) as response:
            value = json.load(response)
            if isinstance(value, dict) and "code" in value and "data" in value:
                return value["data"]
            return value

    records = json.loads((ROOT / "src/agentgate/demo/loan-core-evaluators.json").read_text())
    ids = {r["key"]: r["id"] for r in records}
    datasets = json.loads((ROOT / "src/agentgate/demo/loan-core-datasets.json").read_text())
    # Preflight every dataset/evaluator before creating the first billable run.
    catalog = {e["id"]: e for e in call("/api/evaluators")}
    for identity in ids.values():
        if identity not in catalog or not catalog[identity]["enabled"]:
            raise RuntimeError("专项评估器未就绪；配置Judge模型后重新运行启动器。")
    plans = []
    for mode, dataset in zip(("base", "workflow", "cloudshrimp"), datasets, strict=True):
        detail = call("/api/datasets/" + dataset["id"])
        published = [v for v in detail["versions"] if v["status"] == "published"]
        version = max(published, key=lambda v: v["version"])
        rules = ["final-state", "required-tool", "forbidden-tool", "tool-arguments", ids["path"]]
        if mode == "cloudshrimp":
            rules.append("skill-routing")
        for kind, evaluator_ids in [
            ("rule", rules),
            ("llm", [ids[mode + "-llm"]]),
            ("hybrid", [ids[mode + "-hybrid"]]),
        ]:
            plans.append(
                dict(
                    name=f"贷款专项新验收 · {mode} · {kind}",
                    mode=mode,
                    dataset_id=dataset["id"],
                    dataset_version=version["version"],
                    evaluator_ids=evaluator_ids,
                    timeout_seconds=300,
                    **({"case_ids": [mode + "-core-low"]} if args.smoke else {}),
                )
            )
    output = ROOT / "runtime/loan-core-acceptance" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    runs = []
    for payload in plans:
        response = call("/api/bank-evaluations", payload)
        identity = response.get("run_id") or response.get("id")
        if not identity:
            raise RuntimeError("Missing run ID in submission response")
        runs.append(
            {"id": identity, "name": payload["name"], "dataset_version": payload["dataset_version"]}
        )
        (output / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2))
        print(f"已创建 {payload['name']}: {identity}", flush=True)
    deadline = time.monotonic() + args.wait_seconds
    pending = {run["id"] for run in runs}
    while pending and time.monotonic() < deadline:
        for identity in list(pending):
            progress = call(f"/api/runs/{identity}/status")
            if progress["status"] in ("completed", "failed", "cancelled"):
                report = call(f"/api/runs/{identity}/samples")
                (output / f"{identity}.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
                print(f"{identity}: {progress['status']}", flush=True)
                pending.remove(identity)
        if pending:
            time.sleep(3)
    print(f"结果目录：{output}", flush=True)
    if pending:
        raise SystemExit("等待超时；任务继续运行，可在页面查看，不自动重复提交。")


if __name__ == "__main__":
    main()
