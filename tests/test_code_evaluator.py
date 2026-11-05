"""Code creation, publication, task execution and immutable report evidence."""

import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agentgate.domain import Case, CaseTurn, EvaluatorSpec, Outcome, Trace, TraceSpan
from agentgate.evaluator.executor import execute_evaluators
from agentgate.evaluator.rule.code import CodeRuleEvaluator, run_code, validate_code_config
from agentgate.integrations.job_dispatchers.execution import _execute
from agentgate.server.app import create_app

SOURCE = '''def exec_evaluation(turn_data):
    spans = turn_data["evaluate_target_output_fields"]["spans"]
    found = [s for s in spans if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    if len(found) > 0:
        return EvalOutput(score=1, reason="已调用人工复核", span_ids=[s["span_id"] for s in found])
    return EvalOutput(score=0, reason="缺少人工复核调用")
'''


def config(source=SOURCE, threshold=1):
    return {"language": "python-subset-v1", "source": source, "pass_threshold": threshold}


def definition(source=SOURCE):
    return dict(kind="rule", dimension="tool_use", metric="custom_review", severity="standard",
                implementation_id="code_rule", implementation_version="1", config=config(source),
                children=[], combination=None)


def evaluate(source=SOURCE, spans=(), threshold=1, output_only=False):
    case = Case(id="case", name="case", turns=(CaseTurn(id="turn", input={"txt": "hello"}),))
    trace = Trace(trace_id="a" * 32, case_id="case", run_id="run", spans=(
        TraceSpan(trace_id="a" * 32, span_id="b" * 16, name="turn", operation_type="turn",
                  sequence=0, status="ok", attributes={"agentgate.turn.id": "turn",
                    "inbank.evidence_mode": "output_only" if output_only else "trace_server"}),
        *spans,
    ))
    spec = EvaluatorSpec(id="custom", name="custom", **{**definition(source), "config": config(source, threshold)})
    return execute_evaluators(case, trace, (spec,), {("code_rule", "1"): CodeRuleEvaluator()})[0]


def tool():
    return TraceSpan(trace_id="a" * 32, span_id="c" * 16, name="request_human_review",
                     operation_type="tool", sequence=1, status="ok", attributes={"agentgate.turn.id": "turn"})


def test_code_scores_real_trace_without_case_expectations():
    result = evaluate(spans=(tool(),))
    assert result.outcome == Outcome.PASS and result.score == 1
    assert result.checks[0].span_ids == ("c" * 16,)
    assert result.checks[0].reason == "已调用人工复核"
    missing = evaluate()
    assert missing.outcome == Outcome.FAIL and missing.score == 0
    assert missing.checks[0].failure_stage is not None


@pytest.mark.parametrize("threshold,outcome", [(0.5, Outcome.PASS), (0.6, Outcome.FAIL)])
def test_fractional_score_threshold(threshold, outcome):
    result = evaluate('def exec_evaluation(turn_data):\n    return EvalOutput(score=0.5, reason="部分通过")', threshold=threshold)
    assert result.score == 0.5 and result.outcome == outcome


@pytest.mark.parametrize("statement", [
    'import os', 'return open("/etc/passwd")', 'return __import__("os")',
    'return turn_data.__class__', 'while True:\n        pass',
    'return eval("1")', 'turn_data["x"] = 1',
    'return exec_evaluation(turn_data)', 'return "{x}".format(x=1)',
])
def test_unsafe_language_rejected_before_execution(statement):
    with pytest.raises(ValueError):
        validate_code_config(config('def exec_evaluation(turn_data):\n    ' + statement + '\n    return EvalOutput(score=1, reason="ok")'))


@pytest.mark.parametrize("changes", [{"language": "python"}, {"pass_threshold": True},
                                      {"pass_threshold": -1}, {"pass_threshold": float("nan")},
                                      {"extra": True}, {"source": "x" * 17000}])
def test_invalid_config_rejected(changes):
    with pytest.raises(ValueError):
        validate_code_config({**config(), **changes})


@pytest.mark.parametrize("expression", ['EvalOutput(score=2, reason="bad")',
    'EvalOutput(score=True, reason="bad")', 'EvalOutput(score=1, reason="")',
    'EvalOutput(score=1, reason="bad", span_ids=["foreign"])',
    'EvalOutput(score=1, reason="bad", arbitrary=1)', '1 / 0',
    'EvalOutput(score=1, reason="bad", span_ids="bad")', 'None'])
def test_invalid_output_becomes_error_not_zero(expression):
    result = evaluate('def exec_evaluation(turn_data):\n    return ' + expression)
    assert result.outcome == Outcome.ERROR and result.score is None
    assert result.error_detail is not None


def test_output_only_is_not_applicable():
    result = evaluate(output_only=True)
    assert result.outcome == Outcome.NOT_APPLICABLE and result.score is None


def test_timeout_input_and_step_limits():
    with patch('agentgate.evaluator.rule.code.subprocess.run', side_effect=subprocess.TimeoutExpired('child', 3)):
        assert evaluate().error_detail.category == "timeout"
    with pytest.raises(ValueError, match="1 MB"):
        run_code(SOURCE, {"data": "x" * 1048576})
    source = '''def exec_evaluation(turn_data):
    for a in turn_data["items"]:
        for b in turn_data["items"]:
            value = a + b
    return EvalOutput(score=1, reason="ok")
'''
    with pytest.raises(ValueError, match="步数"):
        run_code(source, {"items": list(range(200))})


class Dispatcher:
    def submit(self, run_id):
        pass


def test_api_publish_task_worker_report_and_version_pin(tmp_path):
    with TestClient(create_app(tmp_path / "code.db", dispatcher=Dispatcher())) as client:
        assert client.post('/api/evaluators/code/validate', json={"config": config()}).json()["data"] == {"valid": True}
        invalid = client.post('/api/evaluators/code/validate', json={"config": config('import os')})
        assert invalid.status_code == 422
        created = client.post('/api/evaluators', json={"name": "人工复核 Code", "draft": definition()})
        assert created.status_code == 201, created.text
        eid = created.json()["data"]["evaluator"]["id"]
        task = {"version": "loan-agent-v2-fixed", "dataset_id": "loan-risk-policy",
                "dataset_version": 1, "evaluator_ids": [eid]}
        assert client.post('/api/evaluations', json=task).status_code >= 400
        first = client.post(f'/api/evaluators/{eid}/drafts/publish').json()["data"]
        assert first["version"] == "1"
        assert client.patch(f'/api/evaluators/{eid}', json={"enabled": True}).status_code == 200
        launched = client.post('/api/evaluations', json=task)
        assert launched.status_code == 202, launched.text
        run_id = launched.json()["data"]["run_id"]
        # Publish changed code after the task was created, before worker execution.
        assert client.post(f'/api/evaluators/{eid}/drafts', json={}).status_code == 201
        changed = definition('def exec_evaluation(turn_data):\n    return EvalOutput(score=0, reason="v2")')
        assert client.put(f'/api/evaluators/{eid}/drafts/current', json=changed).status_code == 200
        assert client.post(f'/api/evaluators/{eid}/drafts/publish').json()["data"]["version"] == "2"
        repo = client.app.state.dependencies.repository
        assert _execute(repo, run_id) == "completed"
        saved = repo.list_results(run_id)
        assert saved and all(r.evaluator_version == "1" for r in saved)
        assert all(r.evaluator_content_sha256 == first["content_sha256"] for r in saved)
        assert all(r.outcome == Outcome.PASS and r.score == 1 for r in saved)
        assert all(r.checks[0].span_ids for r in saved)
        assert repo.list_traces(run_id)
        assert client.get(f'/api/evaluation-tasks/{run_id}').status_code == 200
        report = client.get(f'/api/runs/{run_id}')
        assert report.status_code == 200, report.text
        # New tasks use v2 and persist failures without overwriting v1 history.
        later = client.post('/api/evaluations', json=task).json()["data"]["run_id"]
        assert _execute(repo, later) == "completed"
        assert all(r.evaluator_version == "2" and r.outcome == Outcome.FAIL for r in repo.list_results(later))
        # Release history must use the frozen publication, not the current draft/latest.
        for version, expected_run in (("1", run_id), ("2", later)):
            path = f"/api/evaluators/{eid}/versions/{version}/related-tasks"
            history = client.get(path)
            assert history.status_code == 200, history.text
            items = history.json()["data"]["items"]
            assert len(items) == 1
            assert items[0]["run_id"] == expected_run
            assert items[0]["evaluator_version"] == version
            assert client.get(path, headers={"X-Team-Id": "other-team"}).status_code == 404
        events = client.get(f"/api/runs/{run_id}/events").json()["data"]
        checks = [event for event in events if event["stage"] == "evaluator"]
        assert len(checks) == 1 and checks[0]["evaluator_id"] == eid
        assert checks[0]["status"] == "completed" and checks[0]["duration_ms"] is not None


def test_code_runtime_error_is_recorded_in_release_execution_flow(tmp_path):
    with TestClient(create_app(tmp_path / "error-flow.db", dispatcher=Dispatcher())) as client:
        created = client.post("/api/evaluators", json={
            "name": "异常规则", "draft": definition(
                'def exec_evaluation(turn_data):\n    return EvalOutput(score=1 / 0, reason="error")'
            ),
        })
        eid = created.json()["data"]["evaluator"]["id"]
        assert client.post(f"/api/evaluators/{eid}/drafts/publish").status_code == 200
        client.patch(f"/api/evaluators/{eid}", json={"enabled": True})
        launched = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed", "dataset_id": "loan-risk-policy",
            "dataset_version": 1, "evaluator_ids": [eid],
        })
        run_id = launched.json()["data"]["run_id"]
        repo = client.app.state.dependencies.repository
        assert _execute(repo, run_id) == "completed"
        result = repo.list_results(run_id)[0]
        assert result.outcome == Outcome.ERROR and result.score is None
        events = client.get(f"/api/runs/{run_id}/events").json()["data"]
        checks = [event for event in events if event["stage"] == "evaluator"]
        assert len(checks) == 1 and checks[0]["status"] == "failed"
        assert checks[0]["error_code"] and checks[0]["ended_at"]


def test_publish_rejects_unsafe_code_and_keeps_editable_draft(tmp_path):
    with TestClient(create_app(tmp_path / "bad.db", dispatcher=Dispatcher())) as client:
        created = client.post('/api/evaluators', json={"name": "bad", "draft": definition('import os')})
        eid = created.json()["data"]["evaluator"]["id"]
        assert client.post(f'/api/evaluators/{eid}/drafts/publish').status_code == 422
        detail = client.get(f'/api/evaluators/{eid}').json()["data"]
        assert detail["draft"] and detail["latest"] is None


def trial_data():
    return {
        "evaluate_dataset_fields": {"input": {"application_id": "TEST-001"}, "expectations": []},
        "evaluate_target_output_fields": {
            "actual_output": {"output": "已提交人工复核"}, "final_state": {},
            "spans": [tool().model_dump(mode="json")],
        },
        "ext": {"turn_id": "turn", "case_id": "case", "trace_id": "a" * 32},
    }


def test_manual_trial_matches_task_scoring_and_does_not_persist(tmp_path):
    app = create_app(tmp_path / "trial.db", dispatcher=Dispatcher())
    repo = app.state.dependencies.repository
    with TestClient(app) as client:
        original = client.get("/api/evaluators").json()["data"]
        payload = {"config": config(), "turn_data": trial_data()}
        response = client.post("/api/evaluators/code/try-run", json=payload)
        assert response.status_code == 200, response.text
        result = response.json()["data"]
        real = evaluate(spans=(tool(),)).checks[0]
        assert (result["outcome"], result["score"], result["reason"], result["span_ids"]) == (
            real.outcome.value, real.score, real.reason, list(real.span_ids),
        )
        assert result["duration_ms"] >= 0
        payload["turn_data"]["evaluate_target_output_fields"]["spans"] = []
        failed = client.post("/api/evaluators/code/try-run", json=payload).json()["data"]
        assert failed["outcome"] == "fail" and failed["score"] == 0
        assert client.get("/api/evaluators").json()["data"] == original
        assert not repo.list_runs(user_team_id="")


@pytest.mark.parametrize("source", [
    'def exec_evaluation(turn_data):\n    return EvalOutput(score=1 / 0, reason="bad")',
    'def exec_evaluation(turn_data):\n    return EvalOutput(score=2, reason="bad")',
    'def exec_evaluation(turn_data):\n    return EvalOutput(score=1, reason="bad", span_ids=["foreign"])',
    'def exec_evaluation(turn_data):\n    return EvalOutput(score=1, reason=turn_data["missing"])',
])
def test_manual_trial_runtime_errors_have_no_score(tmp_path, source):
    with TestClient(create_app(tmp_path / "trial-errors.db", dispatcher=Dispatcher())) as client:
        result = client.post("/api/evaluators/code/try-run", json={
            "config": config(source), "turn_data": trial_data(),
        }).json()["data"]
        assert result["outcome"] == "error" and result["score"] is None
        assert result["reason"] and result["span_ids"] == []


def test_manual_trial_validates_json_shape_and_unsafe_code(tmp_path):
    with TestClient(create_app(tmp_path / "trial-invalid.db", dispatcher=Dispatcher())) as client:
        for data in ({}, {"evaluate_dataset_fields": []}, {"ext": None}):
            assert client.post("/api/evaluators/code/try-run", json={
                "config": config(), "turn_data": data,
            }).status_code == 422
        data = trial_data()
        data["evaluate_target_output_fields"]["spans"] *= 2
        assert client.post("/api/evaluators/code/try-run", json={
            "config": config(), "turn_data": data,
        }).status_code == 422
        assert client.post("/api/evaluators/code/try-run", json={
            "config": config("import os"), "turn_data": trial_data(),
        }).status_code == 422


def test_manual_trial_keeps_timeout_size_limit_and_output_only_semantics(tmp_path):
    with TestClient(create_app(tmp_path / "trial-limits.db", dispatcher=Dispatcher())) as client:
        payload = {"config": config(), "turn_data": trial_data()}
        with patch("agentgate.evaluator.rule.code.subprocess.run", side_effect=subprocess.TimeoutExpired("child", 3)):
            result = client.post("/api/evaluators/code/try-run", json=payload).json()["data"]
            assert result["outcome"] == "error" and result["score"] is None
            assert "3 秒" in result["reason"]
        payload["turn_data"]["ext"]["large"] = "x" * 1048576
        result = client.post("/api/evaluators/code/try-run", json=payload).json()["data"]
        assert result["outcome"] == "error" and "1 MB" in result["reason"]
        payload["turn_data"] = trial_data()
        payload["turn_data"]["evaluate_target_output_fields"]["spans"] = [{
            "span_id": "b" * 16, "operation_type": "turn",
            "attributes": {"inbank.evidence_mode": "output_only"},
        }]
        with patch("agentgate.evaluator.rule.code.subprocess.run") as execute:
            result = client.post("/api/evaluators/code/try-run", json=payload).json()["data"]
            assert result["outcome"] == "not_applicable" and result["score"] is None
            execute.assert_not_called()


def test_manual_trial_rejects_excess_concurrency(tmp_path):
    from agentgate.server.routes.evaluators import _code_trial_slots
    with TestClient(create_app(tmp_path / "trial-busy.db", dispatcher=Dispatcher())) as client:
        with _code_trial_slots, _code_trial_slots:
            response = client.post("/api/evaluators/code/try-run", json={
                "config": config(), "turn_data": trial_data(),
            })
            assert response.status_code == 429
        assert client.post("/api/evaluators/code/try-run", json={
            "config": config(), "turn_data": trial_data(),
        }).status_code == 200


NATIVE_SOURCE = '''def exec_evaluation(trace):
    calls = [s for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    return EvalOutput(score=1 if len(calls) > 0 else 0, reason="检查人工复核", span_ids=[s["span_id"] for s in calls])
'''


def test_native_trace_creation_task_and_trial_with_scoped_history(tmp_path):
    from agentgate.domain import FrozenJsonObject
    with TestClient(create_app(tmp_path / "native.db", dispatcher=Dispatcher())) as client:
        native_config = {**config(NATIVE_SOURCE), "input_format": "trace-v1"}
        native_definition = {**definition(NATIVE_SOURCE), "config": native_config}
        eid = client.post('/api/evaluators', json={"name": "Trace 规则", "draft": native_definition}).json()["data"]["evaluator"]["id"]
        assert client.post(f'/api/evaluators/{eid}/drafts/publish').status_code == 200
        client.patch(f'/api/evaluators/{eid}', json={"enabled": True})
        run_id = client.post('/api/evaluations', json={"version": "loan-agent-v2-fixed", "dataset_id": "loan-risk-policy", "dataset_version": 1, "evaluator_ids": [eid]}).json()["data"]["run_id"]
        repo = client.app.state.dependencies.repository
        assert _execute(repo, run_id) == 'completed'
        assert all(r.outcome == Outcome.PASS for r in repo.list_results(run_id))
        response = client.get('/api/evaluators/code/trace-targets', params={"mode": "external"})
        assert response.status_code == 200, response.text
        targets = response.json()["data"]["items"]
        assert len(targets) == 1 and targets[0]["target_id"] == 'loan-agent'
        assert client.get('/api/evaluators/code/trace-targets?mode=inbank').json()["data"]["items"] == []
        assert client.get('/api/evaluators/code/trace-targets?mode=external', headers={"X-Team-Id": "other"}).json()["data"]["items"] == []
        params = {k: targets[0][k] for k in ('source_id', 'target_id', 'version')}
        params.update(mode='external', limit=1)
        another = client.post('/api/evaluations', json={"version": "loan-agent-v2-fixed", "dataset_id": "loan-risk-policy", "dataset_version": 1, "evaluator_ids": [eid]}).json()["data"]["run_id"]
        assert _execute(repo, another) == 'completed'
        page = client.get('/api/evaluators/code/traces', params=params).json()["data"]
        assert len(page['items']) == 1 and page['has_more']
        second = client.get('/api/evaluators/code/traces', params={**params, 'offset': 1}).json()["data"]
        assert second['items'][0]['trace_id'] != page['items'][0]['trace_id']
        assert client.get('/api/evaluators/code/traces', params={**params, 'version': 'wrong'}).json()["data"]['items'] == []
        choice = page['items'][0]
        run_id = choice['run_id']
        data_params = {"mode": "external", "run_id": run_id, "case_id": choice['case_id']}
        original = repo.get_trace(run_id, choice['case_id'])
        assert original
        # Redaction must happen before the native test copy is exposed.
        protected_span = original.spans[0].model_copy(update={'attributes': FrozenJsonObject({
            **original.spans[0].attributes.to_dict(), 'encoded_input': '{"api_key":"secret"}',
        })})
        repo.save_trace(original.model_copy(update={'final_state': FrozenJsonObject({'api_key': 'secret'}),
                                                   'spans': (protected_span, *original.spans[1:])}))
        generated = client.get('/api/evaluators/code/trace-data', params=data_params)
        assert generated.status_code == 200, generated.text
        trace = generated.json()["data"]['trace']
        assert 'evaluate_dataset_fields' not in trace and 'spans' in trace
        assert 'secret' not in str(trace)
        assert repo.get_trace(run_id, choice['case_id']).final_state['api_key'] == 'secret'
        result = client.post('/api/evaluators/code/try-run', json={'config': native_config, 'trace': trace}).json()["data"]
        actual = next(r for r in repo.list_results(run_id) if r.case_id == choice['case_id'])
        assert (result['outcome'], result['score']) == (actual.outcome.value, actual.score)
        trace['spans'] = []
        assert client.post('/api/evaluators/code/try-run', json={'config': native_config, 'trace': trace}).json()["data"]['score'] == 0
        assert client.post('/api/evaluators/code/try-run', json={'config': native_config, 'turn_data': trial_data()}).status_code == 422
        assert client.get('/api/evaluators/code/trace-data', params={**data_params, 'mode': 'inbank'}).status_code == 404
        assert client.get('/api/evaluators/code/trace-data', params=data_params, headers={"X-Team-Id": "other"}).status_code == 404


def test_native_whole_trace_sdk_input_and_cross_turn_execution():
    from agentgate.evaluator.rule.code import trace_code_data
    spans = []
    for index, tid in enumerate(('first', 'second')):
        root_id = str(index * 2 + 1) * 16
        spans.extend([
            TraceSpan(trace_id='a'*32, span_id=root_id, name=tid, operation_type='turn', sequence=index*2,
                      attributes={'agentgate.turn.id': tid, 'trace_sdk.input': {'txt': tid}}),
            TraceSpan(trace_id='a'*32, span_id=str(index*2+2)*16, parent_span_id=root_id,
                      name='tool', operation_type='tool', sequence=index*2+1),
        ])
    trace = Trace(trace_id='a'*32, run_id='run', case_id='case', spans=spans,
                  turn_outcomes={t: {'output': {'text': t}, 'state': {}} for t in ('first', 'second')})
    data = trace_code_data(trace)
    assert data['turn_outcomes']['first']['input'] == {'txt': 'first'}
    assert data['turn_outcomes']['second']['input'] == {'txt': 'second'}
    assert len(data['spans']) == 4
    assert data['final_output'] == trace.final_output.to_dict()
    # The new rule can link evidence across turns and is called once, not once per turn.
    source = '''def exec_evaluation(trace):
    calls = [s for s in trace["spans"] if s["operation_type"] == "tool"]
    return EvalOutput(score=1 if len(calls) == 2 else 0, reason="跨轮证据", span_ids=[s["span_id"] for s in calls])
'''
    case = Case(id='case', name='multi', turns=[CaseTurn(id=t, input={'txt': t}) for t in ('first', 'second')])
    native = EvaluatorSpec(id='native', name='native', **{**definition(source), 'config': {**config(source), 'input_format': 'trace-v1'}})
    legacy = EvaluatorSpec(id='legacy', name='legacy', **definition('def exec_evaluation(turn_data):\n    return EvalOutput(score=1, reason="旧版按轮")'))
    with patch('agentgate.evaluator.rule.code.run_code', wraps=run_code) as runner:
        results = execute_evaluators(case, trace, (native, legacy), {('code_rule', '1'): CodeRuleEvaluator()})
    assert runner.call_count == 3
    assert results[0].outcome == Outcome.PASS and len(results[0].checks) == 1
    assert results[0].checks[0].turn_id is None
    assert set(results[0].checks[0].span_ids) == {'2'*16, '4'*16}
    assert len(results[1].checks) == 2
    assert {c.turn_id for c in results[1].checks} == {'first', 'second'}
    legacy_trace = Trace(trace_id='a'*32, run_id='run', case_id='case', spans=())
    assert trace_code_data(legacy_trace)['turn_outcomes'] == {}
