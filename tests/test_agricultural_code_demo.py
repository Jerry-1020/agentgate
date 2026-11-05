"""Mixed built-in/Code rules catch domain conditions the generic agent misses."""
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentgate.domain import Case, CaseTurn, EvaluatorSpec, MetricPlan, Trace, TraceSpan
from agentgate.evaluator.executor import execute_evaluators
from agentgate.evaluator.rule.code import CodeRuleEvaluator
from agentgate.integrations.job_dispatchers.execution import _execute
from agentgate.result.metrics import calculate_metrics
from agentgate.server.app import create_app


class DeferredDispatcher:
    def submit(self, run_id):
        pass


def test_agricultural_mixed_rules_and_trace_evidence(tmp_path):
    demo = runpy.run_path(str(Path(__file__).parents[1] / "scripts/demo-agricultural-code.py"))
    with TestClient(create_app(tmp_path / "agri.db", dispatcher=DeferredDispatcher())) as client:
        created = demo["create_demo"](client)
        repo = client.app.state.dependencies.repository
        assert _execute(repo, created["run_id"]) == "completed"
        results = repo.list_results(created["run_id"])
        assert len(results) == 16
        expected_failures = {
            ("agri-over-limit", "agri_demo_area_review"),
            ("agri-disaster", "agri_demo_disaster_review"),
        }
        assert {(r.case_id, r.metric) for r in results if r.outcome == "fail"} == expected_failures
        assert all(r.outcome in {"pass", "fail"} for r in results)
        for result in results:
            trace = repo.get_trace(created["run_id"], result.case_id)
            known_ids = {span.span_id for span in trace.spans}
            assert all(set(check.span_ids) <= known_ids for check in result.checks)
            if result.case_id == "agri-reviewed" and result.metric.startswith("agri_demo"):
                assert result.checks[0].span_ids
        overall = calculate_metrics(results, tuple(created["evaluator_ids"]), MetricPlan())[0]
        assert overall.score == pytest.approx(0.875)
        assert client.get(f'/api/runs/{created["run_id"]}').status_code == 200


@pytest.mark.parametrize("actions,expected", [
    (["approve_loan"], "pass"),
    (["request_human_review"], "pass"),
    (["request_human_review", "approve_loan"], "fail"),
    (["approve_loan", "request_human_review"], "fail"),
    (["request_human_review", "request_human_review"], "pass"),
])
def test_native_handoff_rule_across_turns_matches_trial(tmp_path, actions, expected):
    demo = runpy.run_path(str(Path(__file__).parents[1] / "scripts/demo-agricultural-code.py"))
    config = {"language": "python-subset-v1", "input_format": "trace-v1",
              "source": demo["HANDOFF_SOURCE"], "pass_threshold": 1}
    spec = EvaluatorSpec(id="handoff", name="农贷人工复核与自动批准互斥", kind="rule",
                         dimension="tool_use", metric="agri_handoff", severity="standard",
                         implementation_id="code_rule", implementation_version="1", config=config)
    turns, spans = [], []
    for index, action in enumerate(actions):
        tid = f"turn-{index}"
        root = f"{index * 2 + 1:016x}"
        turns.append(CaseTurn(id=tid, input={"application_id": "DEMO-001"}))
        spans.extend([
            TraceSpan(trace_id="a" * 32, span_id=root, name=tid, operation_type="turn",
                      sequence=index * 2, attributes={"agentgate.turn.id": tid}),
            TraceSpan(trace_id="a" * 32, span_id=f"{index * 2 + 2:016x}", parent_span_id=root,
                      name=action, operation_type="tool", sequence=index * 2 + 1, status="ok"),
        ])
    case = Case(id="handoff-case", name="合成农贷申请", turns=turns)
    # The rule must not rely on array order or only inspect the last turn.
    trace = Trace(trace_id="a" * 32, case_id=case.id, run_id="handoff-run", spans=list(reversed(spans)))
    result = execute_evaluators(case, trace, (spec,), {("code_rule", "1"): CodeRuleEvaluator()})[0]
    assert result.outcome == expected
    assert len(result.checks) == 1 and result.checks[0].turn_id is None
    if expected == "fail":
        assert set(result.checks[0].span_ids) == {s.span_id for s in spans if s.operation_type == "tool"}
    with TestClient(create_app(tmp_path / "handoff.db", dispatcher=DeferredDispatcher())) as client:
        trial = client.post("/api/evaluators/code/try-run", json={
            "config": config, "trace": trace.model_dump(mode="json"),
        })
        assert trial.status_code == 200, trial.text
        data = trial.json()["data"]
        assert (data["outcome"], data["score"], data["reason"]) == (
            result.outcome.value, result.score, result.checks[0].reason)
        assert data["span_ids"] == list(result.checks[0].span_ids)
