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


def workflow_graph():
    return {
        "composition": "工作流 · 条件分支",
        "nodes": [
            {"id": "extract", "kind": "workflow", "label": "信息提取", "description": "提取资料",
             "node_type": "llm", "trace_name": "workflow.extract"},
            {"id": "end", "kind": "workflow", "label": "生成回复", "description": "缺资料时追问",
             "node_type": "llm", "trace_name": "workflow.end"},
        ],
        "edges": [{"source": "extract", "target": "end", "relation": "缺资料或咨询"}],
    }


class Client:
    def __init__(self, mode="base"):
        self.mode, self.requests, self.inputs, self.session = mode, {}, {}, None
        self.trace_server = TraceServer()
        self.corrupt = False

    def call(self, path, payload=None, **kwargs):
        if path == "/agents":
            return [{"mode": self.mode, "agent_version": "v1", "test_only": True, "agent_name": f"loan-{self.mode}-v1",
                     "prompt": "test", "summary_prompt": "test", "model": "test", "policy_version": "test-policy-v1",
                     "implementation_sha256": "1" * 64, "tools": [], "skills": [],
                     **({"topology": workflow_graph()} if self.mode == "workflow" else {})}]
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
        response = http.post("/api/bank-evaluations", json={"name": "真实贷款验收", "mode": "base", "dataset_id": ds.id, "dataset_version": 1})
        assert response.status_code == 202, response.text
        run = deps.repository.get_run(response.json()["data"]["run_id"])
        assert deps.repository.get_evaluation_task(run.id).name == "真实贷款验收"
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


def test_local_bank_target_derives_declared_topology():
    from agentgate.integrations.targets.local_bank import declared_topology

    class CapableClient:
        def call(self, path, **kwargs):
            assert path == "/agents"
            return [{
                "mode": "cloudshrimp", "agent_version": "v1", "test_only": True,
                "agent_name": "loan-cloudshrimp-v1", "prompt": "p", "summary_prompt": "s",
                "model": "m", "policy_version": "pv", "implementation_sha256": "1" * 64,
                "tools": [
                    {"function": {"name": "submit_application", "description": "提交申请", "parameters": {}}},
                    {"function": {"name": "get_application", "description": "查询申请", "parameters": {}}},
                ],
                "skills": [
                    {"id": "loan_application", "version": "v1", "name": "贷款申请",
                     "description": "收集资料并提交", "tools": ["submit_application"]},
                ],
            }]

    descriptor, _ = local_bank_target(CapableClient(), "cloudshrimp")
    topology = descriptor.metadata["topology"]
    assert topology["composition"] == "Agent → Skill → Tool"
    kinds = [n["kind"] for n in topology["nodes"]]
    assert kinds.count("agent") == 1 and kinds.count("skill") == 1 and kinds.count("tool") == 2
    assert {"source": "agent", "target": "skill:loan_application", "relation": "declares"} in topology["edges"]
    assert {"source": "skill:loan_application", "target": "tool:submit_application", "relation": "binds"} in topology["edges"]

    assert declared_topology("a", (), ()) is None
    tools_only = declared_topology("a", (), ({"name": "t", "description": ""},))
    assert tools_only["composition"] == "Agent → Tool"
    assert {"source": "agent", "target": "tool:t", "relation": "uses"} in tools_only["edges"]


def test_local_catalog_preserves_sources_versions_and_offline_entries(tmp_path, monkeypatch):
    from agentgate.server.routes import catalogs
    class Dispatcher:
        def submit(self, run_id): pass
        def cancel(self, run_id): pass
    def resolve(client, mode):
        return local_bank_target(Client(mode), mode)
    monkeypatch.setattr(catalogs, "local_bank_target", resolve)
    app = create_app(tmp_path / "catalog.db", dispatcher=Dispatcher())
    with TestClient(app) as http:
        data = http.get('/api/local-targets').json()['data']
        assert data['unavailable'] == []
        assert len(data['targets']) == 5
        assert {(r['descriptor']['ref']['source_id'], r['adapter_type']) for r in data['targets']} == {
            ('agentgate-demo', 'demo_loan'), ('local-bank-runtime', 'local_bank')}
        assert len({r['descriptor']['ref']['external_target_id'] for r in data['targets']}) == 4
        cloud = next(r for r in data['targets'] if r['mode'] == 'cloudshrimp')
        assert cloud['descriptor']['ref']['external_target_id'] == 'loan-cloudshrimp'
        def offline(*args): raise TargetExecutionError('unavailable', 'offline')
        monkeypatch.setattr(catalogs, "local_bank_target", offline)
        data = http.get('/api/local-targets').json()['data']
        assert len(data['targets']) == 2
        assert {r['agent_id'] for r in data['unavailable']} == {'loan-base', 'loan-workflow', 'loan-cloudshrimp'}


class GraphClient(Client):
    def __init__(self, mode="workflow"):
        super().__init__(mode)
        self.graph = workflow_graph()

    def call(self, path, payload=None, **kwargs):
        records = super().call(path, payload, **kwargs)
        if path == "/agents":
            records[0]["topology"] = self.graph
            records[0]["tools"] = [{"function": {
                "name": "get_application", "description": "查询申请", "parameters": {},
            }}]
            if self.mode == "cloudshrimp":
                records[0]["skills"] = [{"id": "status", "version": "v1", "name": "查询",
                                         "description": "查询申请", "tools": ["get_application"]}]
        return records


@pytest.mark.parametrize("mode,composition", [
    ("workflow", "工作流 · 条件分支"), ("base", "Agent → Tool"),
    ("cloudshrimp", "Agent → Skill → Tool"),
])
def test_local_topology_preserves_each_agent_structure(mode, composition):
    client = GraphClient(mode)
    descriptor, snapshot = local_bank_target(client, mode)
    graph = descriptor.model_dump(mode="json")["metadata"]["topology"]
    assert graph["composition"] == composition
    assert snapshot.descriptor_sha256 == descriptor.content_sha256
    if mode == "workflow":
        assert graph == client.graph
    else:
        assert all(node["kind"] != "workflow" for node in graph["nodes"])


@pytest.mark.parametrize("fault", [
    "missing", "empty_nodes", "empty_edges", "duplicate", "dangling", "bad_label",
    "bad_node_type", "bad_trace", "bad_relation", "bad_endpoint", "bad_composition",
])
def test_invalid_workflow_topology_is_rejected_instead_of_tool_fallback(fault):
    client = GraphClient()
    graph = client.graph
    if fault == "missing": client.graph = None
    elif fault == "empty_nodes": graph["nodes"] = []
    elif fault == "empty_edges": graph["edges"] = []
    elif fault == "duplicate": graph["nodes"].append(dict(graph["nodes"][0]))
    elif fault == "dangling": graph["edges"][0]["target"] = "unknown"
    elif fault == "bad_label": graph["nodes"][0]["label"] = " "
    elif fault == "bad_node_type": graph["nodes"][0]["node_type"] = "unknown"
    elif fault == "bad_trace": graph["nodes"][0]["trace_name"] = 123
    elif fault == "bad_relation": graph["edges"][0]["relation"] = None
    elif fault == "bad_endpoint": graph["edges"][0]["target"] = []
    elif fault == "bad_composition": graph["composition"] = ""
    with pytest.raises(ValueError, match="workflow topology"):
        local_bank_target(client, "workflow")


def test_workflow_graph_change_creates_new_snapshot_without_mutating_old():
    client = GraphClient()
    original, original_snapshot = local_bank_target(client, "workflow")
    saved = original.model_dump(mode="json")
    client.graph["edges"][0]["relation"] = "新的分支说明"
    changed, changed_snapshot = local_bank_target(client, "workflow")
    assert changed.content_sha256 != original.content_sha256
    assert changed_snapshot.descriptor_sha256 != original_snapshot.descriptor_sha256
    assert original.model_dump(mode="json") == saved
    assert original_snapshot.descriptor_sha256 == original.content_sha256
