"""Live checks of model-backed services after the upstream database migration."""
import json
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
out = root / "runtime/upstream-acceptance/model-services.json"
report = {"checks": {}}


def save():
    out.parent.mkdir(exist_ok=True, parents=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))


with httpx.Client(base_url="http://127.0.0.1:8097", timeout=240, trust_env=False) as client:
    def call(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()["data"]

    try:
        targets = call("GET", "/api/bank-targets")
        cloud = next(t for t in targets if t["snapshot"]["ref"]["external_target_id"] == "loan-cloudshrimp")
        datasets = call("GET", "/api/datasets")
        dataset = next(d for d in datasets if d["name"] == "独立贷款智能体 · cloudshrimp · test-policy-v1")
        evaluators = call("GET", "/api/evaluators")
        hybrid = next(e for e in evaluators if e["kind"] == "hybrid" and e["enabled"])
        launch = call("POST", "/api/bank-evaluations", json={"mode": "cloudshrimp",
            "dataset_id": dataset["id"], "dataset_version": dataset["version"], "case_ids": ["cloudshrimp-high"],
            "evaluator_ids": ["answer-quality", hybrid["id"]], "timeout_seconds": 300})
        rid = launch["run_id"]
        report["model_evaluation_run_id"] = rid
        save()
        print("MODEL_EVALUATION_CREATED", rid, flush=True)

        static = call("POST", "/api/skill-analysis/reports", json={"target_descriptor_sha256": cloud["descriptor"]["content_sha256"]})
        report["static_report"] = static
        assert static["status"] == "completed", static["status"]
        detail = call("GET", "/api/skill-analysis/reports/" + static["id"])
        assert detail["report"] == static
        report["checks"]["static_model_report_persisted"] = True
        save()
        print("STATIC_ANALYSIS_COMPLETED", static["id"], flush=True)

        deadline = time.monotonic() + 720
        while time.monotonic() < deadline:
            state = call("GET", f"/api/runs/{rid}/status")
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(2)
        assert state["status"] == "completed", state["status"]
        result = call("GET", f"/api/runs/{rid}")
        report["model_evaluation_report"] = result
        assert any(r["evaluator_id"] == "answer-quality" for r in result["results"])
        assert any(r["evaluator_id"] == hybrid["id"] for r in result["results"])
        assert all(r["outcome"] != "error" for r in result["results"])
        report["checks"]["llm_and_hybrid_evaluation_completed_without_errors"] = True
        task = call("GET", f"/api/evaluation-tasks/{rid}")
        linked = call("PUT", f"/api/evaluation-tasks/{rid}", json={
            "kind": task["kind"], "run_ids": task["run_ids"], "static_report_ids": [static["id"]]})
        assert linked["static_report_ids"] == [static["id"]]
        report["checks"]["static_report_linked_to_same_target_task"] = True
        save()

        # A new risky Demo run deliberately supplies failure evidence for root-cause analysis.
        risky = call("POST", "/api/evaluations", json={"version": "loan-agent-v1-risky",
            "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluator_ids": ["final-state", "required-tool", "forbidden-tool"], "max_parallel_cases": 2})
        risk_id = risky["run_id"]
        report["optimization_run_id"] = risk_id
        for _ in range(60):
            if call("GET", f"/api/runs/{risk_id}/status")["status"] == "completed":
                break
            time.sleep(1)
        optimized = call("GET", f"/api/runs/{risk_id}/optimization")
        assert optimized["hypotheses"], "expected model-backed root-cause hypotheses"
        report["optimization_report"] = optimized
        assert call("GET", f"/api/runs/{risk_id}/optimization") == optimized
        report["checks"]["optimization_model_report_persisted_and_reused"] = True
        report["passed"] = all(report["checks"].values())
        save()
        print(json.dumps({"passed": report["passed"], "checks": report["checks"]}), flush=True)
    except Exception as exc:
        report["passed"] = False
        report["error_type"] = type(exc).__name__
        save()
        raise
