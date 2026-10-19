"""Run the retained LLM group against one synthetic local Agent case."""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

HERE = Path(__file__).resolve().parent


def local_origin(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise argparse.ArgumentTypeError(
            "Only a local HTTP API is supported; use the signed-in UI for in-bank evaluation."
        )
    return value.rstrip("/")


def verify_results(manifest: dict, samples: dict, group_id: str) -> dict:
    parent = next(spec for spec in manifest["evaluator_specs"] if spec["id"] == group_id)
    if parent["kind"] != "llm_group" or manifest["primary_evaluator_ids"] != [group_id]:
        raise ValueError("The run must select the group as its only primary evaluator")
    selected = manifest["selected_case_ids"]
    if len(selected) != 1 or not samples["complete"] or samples["run"]["status"] != "completed":
        raise ValueError("The single-case run has not completed")
    rows = {row["evaluator_id"]: row for row in samples["results"] if row["case_id"] == selected[0]}
    children = []
    weighted = 0.0
    for ref in parent["children"]:
        row = rows[ref["evaluator_id"]]
        record = row.get("judge_record") or {}
        child_spec = next(
            spec
            for spec in manifest["evaluator_specs"]
            if spec["id"] == ref["evaluator_id"] and spec["version"] == ref["evaluator_version"]
        )
        if (
            row["evaluator_version"] != ref["evaluator_version"]
            or row["outcome"] not in {"pass", "fail", "review"}
            or row["score"] is None
            or not record.get("raw_response")
            or not record.get("request_sha256")
            or record.get("requested_model") != child_spec["config"]["model"]["model_id"]
        ):
            raise ValueError("A child is missing a real, version-pinned model result")
        weighted += ref["weight"] * row["score"]
        children.append(
            {
                "id": row["evaluator_id"],
                "name": row["evaluator_name"],
                "version": row["evaluator_version"],
                "weight": ref["weight"],
                "score": row["score"],
                "outcome": row["outcome"],
                "reason": "；".join(check["reason"] for check in row["checks"]),
                "provider": record["provider_id"],
                "requested_model": record["requested_model"],
                "resolved_model": record.get("resolved_model"),
                "request_id": record.get("request_id"),
                "request_sha256": record["request_sha256"],
            }
        )
    result = rows[group_id]
    if (
        result["evaluator_version"] != parent["version"]
        or result["outcome"] not in {"pass", "fail", "review"}
        or result["score"] is None
        or not math.isclose(result["score"], weighted, abs_tol=1e-12)
    ):
        raise ValueError("The group score does not match its weighted child scores")
    return {"score": result["score"], "outcome": result["outcome"], "children": children}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=local_origin, default="http://127.0.0.1:18097")
    parser.add_argument("--group-id", help="Reuse an enabled, published group")
    parser.add_argument(
        "--resume-run", help="Inspect an existing run without making new model calls"
    )
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    parser.add_argument("--wait-seconds", type=int, default=900)
    args = parser.parse_args()
    if args.resume_run and not args.group_id:
        parser.error("--resume-run requires --group-id")
    if args.wait_seconds <= 0:
        parser.error("--wait-seconds must be positive")
    report = {"end_to_end_verified": False, "login_mode": "external", "target": "local mock Agent"}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    with httpx.Client(
        base_url=args.api + "/api",
        trust_env=False,
        timeout=30,
        headers={"X-Agent-Platform-Token": "local"},
    ) as client:

        def call(method, path, payload=None):
            response = client.request(method, path, json=payload)
            if not response.is_success:
                raise RuntimeError(
                    f"{method} {path}: HTTP {response.status_code}; inspect the retained server state before retrying a write"
                )
            value = response.json()
            if "code" in value and str(value["code"]) != "0":
                raise RuntimeError(f"{method} {path}: server rejected the request")
            return value.get("data", value) if isinstance(value, dict) else value

        try:
            group_id = args.group_id
            if not group_id:
                payload = json.loads((HERE / "group.json").read_text())
                created = call("POST", "/evaluators/llm-groups", payload)
                group_id = created["evaluator"]["id"]
                report["evaluator_id"] = group_id
                save()
                group = call(
                    "POST",
                    f"/evaluators/{group_id}/llm-group/publish",
                    {
                        "expected_draft_id": created["definition"]["id"],
                        "expected_draft_updated_at": created["definition"]["updated_at"],
                    },
                )
            else:
                group = call("GET", f"/evaluators/{group_id}/llm-group")
            if args.resume_run:
                run_id = args.resume_run
            else:
                if group["viewing_draft"] or not group["evaluator"]["enabled"]:
                    raise ValueError("Use a published and enabled group")
                document = json.loads(
                    (HERE.parent / "llm-conciseness" / "dataset.json").read_text()
                )
                dataset_id = document["dataset"]["id"]
                if not any(item["id"] == dataset_id for item in call("GET", "/datasets")):
                    call("POST", "/datasets/import", document)
                dataset = call("GET", f"/datasets/{dataset_id}/versions/1")
                if dataset["content_sha256"] != document["version"]["content_sha256"]:
                    raise ValueError("The retained example dataset has a different fingerprint")
                task = call(
                    "POST",
                    "/agent-platform/evaluations",
                    {
                        "name": "LLM 子评估器 · 真实评分端到端示例",
                        "target": {
                            "agent_id": "agent-base",
                            "agent_version": "1.0",
                            "type_group": "base/workflow",
                            "arrange_type": "base",
                        },
                        "dataset_id": dataset_id,
                        "dataset_version": 1,
                        "case_ids": [dataset["cases"][0]["id"]],
                        "evaluator_refs": [
                            {
                                "evaluator_id": group_id,
                                "evaluator_version": group["definition"]["version"],
                            }
                        ],
                        "max_parallel_cases": 1,
                        "timeout_seconds": 900,
                        "max_retries": 0,
                        "repetitions": 1,
                    },
                )
                run_id = task["run_ids"][0]
                report["task_id"] = task["id"]
            report.update(evaluator_id=group_id, run_id=run_id)
            save()
            print(f"Retained group {group_id}; run {run_id}", flush=True)
            deadline = time.monotonic() + args.wait_seconds
            while time.monotonic() < deadline:
                report["status"] = call("GET", f"/runs/{run_id}/status")["status"]
                if report["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            if report["status"] != "completed":
                raise RuntimeError(
                    "Run is not completed; use --resume-run to inspect without resubmission"
                )
            manifest = call("GET", f"/runs/{run_id}/manifest")
            report["result"] = verify_results(
                manifest, call("GET", f"/runs/{run_id}/samples"), group_id
            )
            report.update(end_to_end_verified=True, verified_at=datetime.now(UTC).isoformat())
            save()
            print(
                f"Verified group and {len(report['result']['children'])} independent model results"
            )
            return 0
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, StopIteration) as error:
            report["error"] = (
                type(error).__name__ if isinstance(error, httpx.HTTPError) else str(error)
            )
            save()
            print("Verification failed:", report["error"])
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
