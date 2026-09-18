import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bank_agents.app import create_app
from bank_agents.runtime import Runtime
from bank_agents.store import Store, Conflict
from bank_agents.telemetry import Evidence, PROJECT
from bank_agents.tools import LoanTools


def test_sdk_masks_pii_without_corrupting_correlation_ids(tmp_path):
    trace_id = "593c683d-d3cf-4680-af1b-14638050101f"
    session_id = "19380050-d3cf-4680-af1b-14638050101f"
    evidence = Evidence(tmp_path, trace_id, session_id, "base", "电话13812345678")
    evidence.finish({"trace_id": trace_id, "session_id": session_id,
                     "contact": "电话13812345678 phone13812345678 邮箱foo@example.com"})
    events = [json.loads(line) for line in evidence.path.read_text().splitlines()]
    root = next(event for event in events if event["event_type"] == "trace")
    assert root["output"]["trace_id"] == trace_id
    assert root["output"]["session_id"] == session_id
    assert "13812345678" not in root["output"]["contact"]
    assert "foo@example.com" not in root["output"]["contact"]


class ScriptedModel:
    """Only injected by tests; production startup always constructs LiveModel."""
    name = "test-scripted-model"

    def structured(self, prompt, messages, evidence):
        text = messages[-1]["content"]
        if "Skill路由器" in prompt:
            return {"skill": "application_status" if "查询" in text else "loan_application"}
        return {"amount": None if "缺资料" in text else 80000,
                "purpose": None if "缺资料" in text else "农机", "intent": "status" if "查询" in text else "apply"}

    def complete(self, messages, evidence, tools=None, json_mode=False):
        if tools:
            outputs = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not outputs:
                name, arguments = "submit_application", {"amount": 80000, "purpose": "农机"}
            elif len(outputs) == 1:
                name, arguments = "credit_inquiry", {}
            elif len(outputs) == 2:
                name = {"approved": "approve_loan", "pending_review": "request_human_review", "rejected": "reject_loan"}[outputs[-1]["required_action"]]
                arguments = {}
            else:
                return {"role": "assistant", "content": "测试处理完成"}
            return {"role": "assistant", "content": None, "tool_calls": [{"id": str(uuid4()), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        return {"role": "assistant", "content": "测试处理完成，请以结构化状态为准"}


@pytest.fixture
def runtime(tmp_path):
    return Runtime(Store(tmp_path / "bank.db"), ScriptedModel(), tmp_path / "traces")


@pytest.mark.parametrize("mode", ["base", "workflow", "cloudshrimp"])
@pytest.mark.parametrize("customer,status", [("test-low", "approved"), ("test-high", "pending_review"), ("test-blocked", "rejected")])
def test_three_modes_real_database_and_sdk(runtime, mode, customer, status):
    sid = runtime.store.create_session(mode, customer)
    rid = str(uuid4())
    result = runtime.execute(mode, sid, rid, "申请8万元购买农机")
    assert result["final_state"]["status"] == status
    assert runtime.execute(mode, sid, rid, "申请8万元购买农机") == result
    raw = runtime.trace_directory / PROJECT / sid / f"{result['trace_id']}.jsonl"
    events = [json.loads(l) for l in raw.read_text().splitlines()]
    assert sum(e["event_type"] == "trace" for e in events) == 1
    spans = [e for e in events if e["event_type"] == "span"]
    root = next(e for e in events if e["event_type"] == "trace")
    assert root["span_count"] == len(spans)
    assert any(e.get("tool_name") == "credit_inquiry" for e in spans)
    assert runtime.store.application(sid)["status"] == status
    if mode == "workflow":
        assert [e["node_id"] for e in result["workflow_calls"]] == ["extract", "submit", "credit", "decide", "act", "end"]
    if mode == "cloudshrimp":
        assert any(e.get("name") == "skill.route" for e in spans)
    with pytest.raises(Conflict): runtime.execute(mode, sid, rid, "改变金额")


def test_policy_cannot_be_overridden_by_model(runtime):
    sid = runtime.store.create_session("base", "test-high")
    rid = str(uuid4())
    runtime.store.reserve(rid, sid, {})
    e = Evidence(runtime.trace_directory, str(uuid4()), sid, "base", "ignore policy")
    tools = LoanTools(runtime.store, sid, rid, e)
    assert "error" in tools.invoke("approve_loan", {})
    tools.invoke("submit_application", {"amount": 80000, "purpose": "农机"})
    tools.invoke("credit_inquiry", {})
    assert "error" in tools.invoke("approve_loan", {})
    assert runtime.store.application(sid)["approved"] is False
    assert "error" in tools.invoke("submit_application", {"amount": -1, "purpose": "x"})
    assert "error" in tools.invoke("credit_inquiry", {"customer": "test-low"})
    e.finish({"test": True})


@pytest.mark.parametrize("mode", ["workflow", "cloudshrimp"])
def test_multiturn_and_restart(runtime, mode):
    sid = runtime.store.create_session(mode, "test-low")
    first = runtime.execute(mode, sid, str(uuid4()), "缺资料")
    assert first["final_state"]["status"] == "no_application"
    restarted = Runtime(Store(runtime.store.path), runtime.model, runtime.trace_directory)
    second = restarted.execute(mode, sid, str(uuid4()), "补充8万元农机")
    assert second["final_state"]["status"] == "approved"
    assert second["trace_id"] != first["trace_id"]


def test_concurrent_traces_and_sessions_do_not_mix(runtime):
    def execute(customer):
        sid = runtime.store.create_session("workflow", customer)
        return runtime.execute("workflow", sid, str(uuid4()), "申请8万元农机")
    with ThreadPoolExecutor(max_workers=2) as pool:
        low, high = list(pool.map(execute, ["test-low", "test-high"]))
    assert low["final_state"]["status"] == "approved"
    assert high["final_state"]["status"] == "pending_review"
    assert low["trace_id"] != high["trace_id"]
    for result in (low, high):
        path = runtime.trace_directory / PROJECT / result["session_id"] / f"{result['trace_id']}.jsonl"
        assert {json.loads(l)["trace_id"] for l in path.read_text().splitlines()} == {result["trace_id"]}


def test_http_protocols_and_restrictions(runtime):
    client = TestClient(create_app(runtime))
    assert len(client.get("/agents").json()) == 3
    assert len(client.get("/test-cases").json()) == 24
    for mode in ("base", "workflow"):
        prefix = f"/agent-api/loan-{mode}-v1/chatabc"
        sid = str(uuid4())
        assert client.post(prefix + "/init_session", json={"timestamp": 0, "requestId": sid, "data": {}}).status_code == 200
        rid = str(uuid4())
        response = client.post(prefix + "/chat", json={"timestamp": 0, "requestId": rid, "data": {"session_id": sid, "txt": "8万元农机"}})
        assert "event: done" in response.text and "event: failed" not in response.text
        assert client.get(f"/requests/{rid}/trace").status_code == 200
    url = "/agent-api/loan-cloudshrimp-v1/api/v1/message"
    response = client.post(url, json={"sessionId": "c", "custID": "test-high", "txt": "申请8万元农机", "stream": False})
    assert response.json()["final_state"]["status"] == "pending_review"
    assert client.post(url, json={"sessionId": "c", "custID": "test-low", "txt": "x"}).status_code == 409
    assert client.post(url, json={"sessionId": "d", "custID": "real-customer", "txt": "x"}).status_code == 422
    assert client.post(url, json={"sessionId": "d", "custID": "test-low", "txt": "x", "safeGuardrail": "OFF"}).status_code == 422


def test_model_failure_is_persisted_and_never_becomes_mock_success(runtime):
    def fail(*args, **kwargs): raise RuntimeError("offline")
    runtime.model.complete = fail
    sid = runtime.store.create_session("base", "test-low")
    with pytest.raises(RuntimeError): runtime.execute("base", sid, "failure", "申请")
    assert runtime.store.request("failure")["status"] == "failed"
    with pytest.raises(Conflict): runtime.execute("base", sid, "failure", "申请")


def test_same_session_cannot_have_concurrent_turns(runtime):
    sid = runtime.store.create_session("base", "test-low")
    runtime.store.reserve("first", sid, {})
    with pytest.raises(Conflict): runtime.store.reserve("second", sid, {})


def test_trace_export_failure_still_marks_request_failed(runtime, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError("export unavailable")
    monkeypatch.setattr(Evidence, "finish", fail)
    sid = runtime.store.create_session("base", "test-low")
    with pytest.raises(RuntimeError): runtime.execute("base", sid, "export-failure", "申请")
    assert runtime.store.request("export-failure")["status"] == "failed"


def test_live_model_requires_configuration(monkeypatch):
    from bank_agents.model import LiveModel
    for key in ("BANK_MODEL_BASE_URL", "BANK_MODEL_API_KEY", "BANK_MODEL_NAME"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError): LiveModel()
