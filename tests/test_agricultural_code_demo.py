"""Mixed built-in/Code rules catch domain conditions the generic agent misses."""
import pytest
from fastapi.testclient import TestClient

from agentgate.domain import Case, CaseTurn, EvaluatorSpec, MetricPlan, Trace, TraceSpan
from agentgate.evaluator.executor import execute_evaluators
from agentgate.evaluator.rule.code import CodeRuleEvaluator
from agentgate.integrations.job_dispatchers.execution import _execute
from agentgate.result.metrics import calculate_metrics
from agentgate.server.app import create_app


AREA_SOURCE = '''def exec_evaluation(turn_data):
    data = turn_data["evaluate_dataset_fields"]["input"]
    target = turn_data["evaluate_target_output_fields"]
    # 演示规则：亩均额度由样本给定，不代表真实信贷政策。
    limit = data["planting_area_mu"] * data["demo_limit_per_mu"]
    if data["amount"] <= limit:
        return EvalOutput(score=1, reason="申请金额未超过演示亩均额度，无需额外复核")
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    passed = len(calls) > 0 and target["final_state"].get("human_review") == True and target["final_state"].get("approved") == False
    return EvalOutput(score=1 if passed else 0, reason="亩均额度超限，已转人工复核" if passed else "亩均额度超限，应转人工复核且不得直接批准", span_ids=[s["span_id"] for s in calls])
'''

DISASTER_SOURCE = '''def exec_evaluation(turn_data):
    data = turn_data["evaluate_dataset_fields"]["input"]
    target = turn_data["evaluate_target_output_fields"]
    # 演示规则：受灾标记必须是布尔值，字段缺失应报错。
    if data["disaster_affected"] == False:
        return EvalOutput(score=1, reason="未标记受灾，无需受灾专项复核")
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    passed = len(calls) > 0 and target["final_state"].get("human_review") == True and target["final_state"].get("approved") == False
    return EvalOutput(score=1 if passed else 0, reason="受灾农户已转人工复核" if passed else "受灾农户应转人工复核且不得直接批准", span_ids=[s["span_id"] for s in calls])
'''

RULES = [
    ("农贷演示 · 亩均额度复核", "agri_demo_area_review", AREA_SOURCE),
    ("农贷演示 · 受灾农户复核", "agri_demo_disaster_review", DISASTER_SOURCE),
]

# Synthetic fixtures for legacy and native Trace regression tests.
HANDOFF_SOURCE = '''def exec_evaluation(trace):
    reviews = [s for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    approvals = [s for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") == "approve_loan"]
    if len(reviews) == 0:
        return EvalOutput(score=1, reason="未转人工，不触发互斥检查")
    if len(approvals) > 0:
        return EvalOutput(score=0, reason="同一申请既转人工又自动批准，处理动作冲突", span_ids=[s["span_id"] for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") in ["request_human_review", "approve_loan"]])
    return EvalOutput(score=1, reason="已转人工，且整条 Trace 未自动批准", span_ids=[s["span_id"] for s in reviews])
'''


def _agricultural_cases():
    scenarios = [
        ("agri-normal", "正常农资申请：全部通过", 50000, False, "low"),
        ("agri-over-limit", "额度超限：通用通过，亩均复核失败", 80000, False, "low"),
        ("agri-disaster", "受灾申请：通用通过，受灾复核失败", 50000, True, "low"),
        ("agri-reviewed", "超限且受灾：已转人工，全部通过", 80000, True, "high"),
    ]
    return [{
        "id": cid, "name": name, "category": "boundary", "difficulty": "easy",
        "tags": ["农贷", "模拟数据", "组合评估"],
        "turns": [{
            "id": cid + "-turn", "input": {
                "skill": "loan_approval", "application_id": cid,
                "risk": risk, "amount": amount, "loan_purpose": "春耕农资采购",
                "crop": "水稻", "planting_area_mu": 20, "demo_limit_per_mu": 3000,
                "disaster_affected": disaster,
            },
            "expectations": [
                {"id": "credit-check", "kind": "tool_call", "tool": "credit_inquiry", "mode": "required"},
                {"id": "generic-status", "kind": "state", "path": "status",
                 "condition": {"kind": "equals", "expected": "pending_review" if risk == "high" else "approved"}},
            ],
            "notes": "仅演示：通用状态按 risk 判断；农贷专属条件由自定义规则独立检查。",
        }],
    } for cid, name, amount, disaster, risk in scenarios]


def _create_agricultural_fixture(client: TestClient):
    def call(method, path, payload=None):
        response = client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()["data"]

    created = call("POST", "/api/datasets", {
        "name": "农贷演示 · 预置与自定义规则组合",
        "description": "4 个合成样本；亩均 3000 元仅为演示阈值。运行现有本地 Loan Agent，不代表真实农贷审批。",
    })
    dataset_id = created["dataset"]["id"]
    for case in _agricultural_cases():
        call("POST", f"/api/datasets/{dataset_id}/drafts/cases", case)
    version = call("POST", f"/api/datasets/{dataset_id}/drafts/publish")
    ids = ["required-tool", "final-state"]
    for name, metric, source in RULES:
        config = {"language": "python-subset-v1", "source": source, "pass_threshold": 1}
        call("POST", "/api/evaluators/code/validate", {"config": config})
        evaluator = call("POST", "/api/evaluators", {
            "name": name, "description": "模拟农贷业务规则，仅用于说明自定义评估能力；可修改 Python。",
            "draft": {"kind": "rule", "dimension": "tool_use", "metric": metric,
                      "severity": "standard", "implementation_id": "code_rule",
                      "implementation_version": "1", "config": config},
        })
        eid = evaluator["evaluator"]["id"]
        call("POST", f"/api/evaluators/{eid}/drafts/publish")
        call("PATCH", f"/api/evaluators/{eid}", {"enabled": True})
        ids.append(eid)
    run = call("POST", "/api/evaluations", {
        "version": "loan-agent-v2-fixed", "dataset_id": dataset_id,
        "dataset_version": version["version"], "evaluator_ids": ids,
    })
    return {"dataset_id": dataset_id, "evaluator_ids": ids, "run_id": run["run_id"]}


class DeferredDispatcher:
    def submit(self, run_id):
        pass


def test_agricultural_mixed_rules_and_trace_evidence(tmp_path):
    with TestClient(create_app(tmp_path / "agri.db", dispatcher=DeferredDispatcher())) as client:
        created = _create_agricultural_fixture(client)
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
    config = {"language": "python-subset-v1", "input_format": "trace-v1",
              "source": HANDOFF_SOURCE, "pass_threshold": 1}
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
