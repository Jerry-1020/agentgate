import json

import pytest
from fastapi.testclient import TestClient

from agentgate.domain import Case, CaseTurn
from agentgate.application.dataset_management import DatasetManagement
from agentgate.integrations.targets.local_bank import LocalBankAdapter, LocalBankClient, local_bank_target
from agentgate.run.target_protocol import CaseExecutionRequest, TargetExecutionError
from agentgate.server.app import create_app


class TraceServer:
    def __init__(self):
        self.traces = {}
        self.corrupt = False

    def record(self, trace_id, result, turn_input):
        self.traces[trace_id] = (result, turn_input)

    def fetch_events(self, project_id, trace_id, *, timeout=30):
        result, turn_input = self.traces[trace_id]
        common = {"project_id": project_id, "trace_id": trace_id}
        return [
            {"event_type": "span", "event_id": "s", "span_id": "s", "name": "agent",
             "span_type": "agent", "parent_span_id": None, "status": "success",
             "started_at": "2026-09-17T00:00:00Z", "duration_ms": 1, **common},
            {"event_type": "observation", "event_id": "o", "span_id": "s",
             "model": "test", "prompt_tokens": 1, "completion_tokens": 1, **common},
            {"event_type": "trace", "event_id": "t", "input": turn_input,
             "output": {} if self.corrupt else result, "status": "success",
             "started_at": "2026-09-17T00:00:00Z", "duration_ms": 1,
             "session_id": result["session_id"], **common},
        ]


class Client:
    def __init__(self, mode="base"):
        self.mode, self.requests, self.inputs, self.session = mode, {}, {}, None
        self.trace_server = TraceServer()
        self.corrupt = False

    def call(self, path, payload=None, **kwargs):
        if path == "/agents":
            return [{"mode": self.mode, "agent_version": "v1", "test_only": True, "agent_name": f"loan-{self.mode}-v1",
                     "prompt": "test", "summary_prompt": "test", "model": "test", "policy_version": "test-policy-v1",
                     "implementation_sha256": "1" * 64, "tools": [], "skills": []}]
        if path.endswith("init_session"):
            self.session = payload["requestId"]
            return {"resCode": "FAIAG0000", "data": {"session_id": self.session}}
        if payload is not None:
            rid = kwargs["request_id"]
            self.session = payload.get("sessionId", self.session)
            result = {"mode": self.mode, "status": "completed", "agent_version": "v1", "request_id": rid,
                      "session_id": self.session, "output": "test answer", "final_state": {"status": "pending_review"},
                      "trace_id": rid}
            self.requests[rid] = result
            self.inputs[rid] = {"txt": payload["txt"] if self.mode == "cloudshrimp" else payload["data"]["txt"]}
            self.trace_server.record(rid, result, self.inputs[rid])
            if self.mode == "workflow":
                message = {"node_id": "end", "additional_kwargs": {"node_output": {"output": "test answer"}}}
            elif self.mode == "base":
                message = {"content": "test answer"}
            else:
                message = result
            trace = {"project_id": "bank-tested-agents", "trace_id": rid, "request_id": rid}
            return (f'event: message\ndata: {json.dumps(message)}\n\n'
                    f'event: trace\ndata: {json.dumps(trace)}\n\n'
                    f'event: done\ndata: [DONE]\n\n').encode()
        raise AssertionError(f"unexpected path: {path}")


@pytest.mark.parametrize("mode", ["base", "workflow", "cloudshrimp"])
def test_live_adapter_correlates_each_turn_and_preserves_business_state(mode):
    client = Client(mode)
    _, snapshot = local_bank_target(client, mode)
    case = Case(id="case", name="Test", turns=(CaseTurn(id="one", input={"txt": "hello"}), CaseTurn(id="two", input={"txt": "details"})))
    request = CaseExecutionRequest("exec", "run", case, snapshot, 30, "00-" + "a"*32 + "-" + "b"*16 + "-01")
    adapter = LocalBankAdapter(client, client.trace_server)
    result = adapter.wait(adapter.start(request), 30)
    assert result.inline_trace.final_state["status"] == "pending_review"
    assert len(client.requests) == 2
    for turn in case.turns:
        assert result.inline_trace.turn_outcomes[turn.id]["input"] == turn.input
        trace = result.inline_trace.for_turn(turn.id)
        assert trace.spans[0].attributes["trace_sdk.replay"] is False
        assert trace.spans[0].attributes["bank.request_id"] in client.requests
    client.trace_server.corrupt = True
    with pytest.raises(TargetExecutionError): LocalBankAdapter(client, client.trace_server).start(request)


def test_adapter_requires_a_single_trace_reference_per_turn():
    client = Client("base")
    _, snapshot = local_bank_target(client, "base")
    case = Case(id="case", name="Test", turns=(CaseTurn(id="one", input={"txt": "hello"}),))
    request = CaseExecutionRequest("exec", "run", case, snapshot, 30, "00-" + "a"*32 + "-" + "b"*16 + "-01")

    class NoTraceServer:
        def fetch_events(self, project_id, trace_id, *, timeout=30):
            raise AssertionError("must not be reached")

    original = client.call

    def call_without_trace(path, payload=None, **kwargs):
        data = original(path, payload, **kwargs)
        if isinstance(data, bytes):
            return b'event: message\ndata: {"content": "test answer"}\n\nevent: done\ndata: [DONE]\n\n'
        return data

    client.call = call_without_trace
    with pytest.raises(TargetExecutionError): LocalBankAdapter(client, NoTraceServer()).start(request)


@pytest.mark.parametrize("url", ["http://example.com", "http://localhost.evil.test", "http://user:pw@localhost", "http://127.0.0.1/path", "https://127.0.0.1"])
def test_adapter_rejects_external_or_credential_bearing_origins(monkeypatch, url):
    monkeypatch.setenv("AGENTGATE_BANK_BASE_URL", url)
    with pytest.raises(ValueError): LocalBankClient()


def test_launch_persists_task_before_dispatch_and_rejects_demo_payload(tmp_path, monkeypatch):
    from agentgate.server.routes import bank_targets
    class Dispatcher:
        def submit(self, run_id):
            assert app.state.dependencies.repository.get_evaluation_task(run_id) is not None
        def cancel(self, run_id): pass
    monkeypatch.setattr(bank_targets, "LocalBankClient", Client)
    app = create_app(tmp_path / "db.sqlite", dispatcher=Dispatcher())
    with TestClient(app) as http:
        deps = app.state.dependencies
        datasets = DatasetManagement(deps.repository)
        ds = datasets.create_dataset("Bank test")
        datasets.create_draft(ds.id)
        datasets.save_case(ds.id, Case(name="real input", turns=(CaseTurn(input={"txt": "loan"}),)))
        datasets.publish_draft(ds.id)
        response = http.post("/api/bank-evaluations", json={"mode": "base", "dataset_id": ds.id, "dataset_version": 1})
        assert response.status_code == 202, response.text
        run = deps.repository.get_run(response.json()["data"]["run_id"])
        assert run.manifest.max_retries == 0
        assert run.manifest.target.adapter_type == "local_bank"
        pinned = http.get('/api/runs/'+run.id+'/target-descriptor')
        assert pinned.status_code == 200
        assert pinned.json()['data']['content_sha256'] == run.manifest.target.descriptor_sha256
        body={"mode":"base","dataset_id":ds.id,"dataset_version":1}
        assert http.post('/api/bank-evaluations',json={**body,"target_descriptor_sha256":"f"*64}).status_code==422
        repeated=http.post('/api/bank-evaluations',json={**body,"repetitions":2})
        assert repeated.status_code==202
        ids=repeated.json()['data']['run_ids']
        assert len(ids)==2
        assert deps.repository.get_run(ids[0]).manifest==deps.repository.get_run(ids[1]).manifest
        assert http.post('/api/bank-evaluations',json={**body,"repetitions":2,"scheduled_for":"2099-01-01T00:00:00Z"}).status_code==422
        scheduled=http.post('/api/bank-evaluations',json={**body,"scheduled_for":"2099-01-01T00:00:00Z"})
        assert scheduled.status_code==202
        assert deps.repository.get_run(scheduled.json()['data']['run_id']).status=='scheduled'
        assert http.get('/api/runs/unknown/target-descriptor').status_code==404
        invalid = http.post("/api/bank-evaluations", json={"mode": "base", "dataset_id": "loan-risk-policy", "dataset_version": 1})
        assert invalid.status_code == 422


def test_model_metadata_never_exposes_credentials(tmp_path,monkeypatch):
    from agentgate.server.routes import bank_targets
    monkeypatch.setattr(bank_targets,'LocalBankClient',Client)
    app=create_app(tmp_path/'db.sqlite')
    monkeypatch.setenv('AGENTGATE_JUDGE_BASE_URL','https://user:password@example.test/v1?api_key=secret')
    monkeypatch.setenv('AGENTGATE_JUDGE_API_KEY','private-test-key')
    with TestClient(app) as http:
        response=http.get('/api/model-runtime')
        assert response.status_code==200
        assert all(x not in response.text for x in ('private-test-key','password','secret'))
        assert response.json()['data']['connections'][0]['base_url']=='https://example.test/v1'
