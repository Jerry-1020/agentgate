"""Real in-bank adapters execute persisted Runs through the shared engine."""

import json
import logging
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_run_engine import pending_run
from test_target_execution_factory import configure_inbank, target_snapshot

from agentgate.domain import Case, CaseTurn, EvaluationRun, RunStatus, transition_run
from agentgate.integrations.job_dispatchers import execution
from agentgate.integrations.job_dispatchers.celery import execute_evaluation_run
from agentgate.integrations.targets.inbank import chatabc, yunxia
from agentgate.run.target_protocol import TargetExecutionError
from agentgate.storage.sqlite import SQLiteRepository


class RecordingTransport:
    """Return current adapter-contract fixtures without connecting to a bank."""

    def __init__(self):
        self.created = 0
        self.create_requests = []
        self.deleted = 0
        self.delete_requests = []
        self.sessions = []
        self.messages = []
        self.fail_chat = False
        self.chat_error_event = False

    def request_json(self, method, url, *, payload=None, **kwargs):
        if "createAgent" in url:
            self.created += 1
            self.create_requests.append({"method": method, "url": url, "payload": payload})
            return {"code": "0000", "data": {"agentName": "test-pod"}}
        if "deleteAgent" in url or "delete_agent" in url:
            self.deleted += 1
            self.delete_requests.append(
                {"method": method, "url": url, "payload": payload}
            )
            if "/agent-manager/chatabc/delete_agent" in url:
                return {"resCode": "FAIAG0000"}
            return {"code": "0000"}
        if "health_check" in url:
            return {"data": {"status": "ok"}}
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/init_session"):
            session = f"session-{len(self.sessions)}"
            self.sessions.append(session)
            return {"resCode": "FAIAG0000", "data": {"session_id": session}}
        raise AssertionError(f"unexpected request: {method} {url}")

    def request_bytes(self, method, url, *, payload, headers, **kwargs):
        if self.fail_chat:
            raise TargetExecutionError("rejected", "test chat failed")
        if url.endswith("/chat"):
            self.messages.append(payload["data"])
            if self.chat_error_event:
                return (
                    "event: error\n"
                    'data: {"errorCode": "BASE-001", '
                    '"message": "customer base failed"}\n\n'
                ).encode()
            events = [("message", {"content": "answer"})]
        else:
            assert url.endswith("/api/v1/message")
            self.messages.append(payload)
            events = [
                (
                    "start",
                    {"request_id": headers["X-Request-ID"], "session_id": payload["sessionId"]},
                ),
                ("message", {"status": "completed", "output": "answer"}),
            ]
        return (
            "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
            + "event: done\ndata: [DONE]\n\n"
        ).encode()


@pytest.fixture(params=["inbank_chatabc", "inbank_yunxia"])
def persisted_target(request, tmp_path, monkeypatch):
    adapter_type = request.param
    configure_inbank(monkeypatch, adapter_type)
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "execution.db"))
    monkeypatch.setattr(execution, "load_judge_model_from_environment", lambda: None)
    transport = RecordingTransport()
    module = chatabc if adapter_type == "inbank_chatabc" else yunxia
    monkeypatch.setattr(module, "_UrlLibTransport", lambda: transport)
    cases = tuple(
        Case(
            id=f"case-{index}",
            name=f"Case {index}",
            turns=(
                CaseTurn(id="first", input={"txt": "hello"}),
                CaseTurn(id="second", input={"txt": "continue"}),
            ),
        )
        for index in range(2)
    )
    original = pending_run(cases=cases, target=target_snapshot(adapter_type))
    run = EvaluationRun(
        id="12345678-1234-1234-1234-abcdef987654",
        manifest=original.manifest,
    )
    with closing(SQLiteRepository(tmp_path / "execution.db")) as repository:
        repository.save_run(run)
        yield SimpleNamespace(repository=repository, run=run, transport=transport)


@pytest.mark.parametrize("entry", [execution.execute_persisted_run, execute_evaluation_run.run])
def test_persisted_run_produces_traces_results_and_cleans_pod(persisted_target, entry):
    context = persisted_target
    assert entry(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    traces = context.repository.list_traces(context.run.id)
    results = context.repository.list_results(context.run.id)
    assert len(traces) == len(results) == 2
    assert all(trace.final_output["output"] == "answer" for trace in traces)
    assert all(len(trace.turn_outcomes) == 2 for trace in traces)
    assert context.transport.created == context.transport.deleted == 1
    assert context.transport.create_requests == [
        {
            "method": "POST",
            "url": "http://bank.invalid/web/agent_endpoint/createAgent?taskId=ef987654",
            "payload": {
                "agentId": "loan-agent",
                "agentVersion": "loan-agent-v2-fixed",
            },
        }
    ]
    if context.run.manifest.target.adapter_type == "inbank_chatabc":
        assert context.transport.delete_requests == [
            {
                "method": "POST",
                "url": "http://bank.invalid/agent-api/agent-manager/chatabc/delete_agent",
                "payload": {
                    "appId": "",
                    "trCode": "",
                    "trVersion": "",
                    "timestamp": 1,
                    "requestId": "",
                    "data": {
                        "agent_name": "test-pod",
                        "agent_namespace": "chatabc",
                    },
                },
            }
        ]
    messages = context.transport.messages
    session_key = "session_id" if "session_id" in messages[0] else "sessionId"
    assert messages[0][session_key] == messages[1][session_key]
    assert messages[2][session_key] == messages[3][session_key]
    assert messages[0][session_key] != messages[2][session_key]
    assert entry(context.run.id) == "completed"
    assert context.transport.created == context.transport.deleted == 1
    assert context.repository.list_traces(context.run.id) == traces
    assert context.repository.list_results(context.run.id) == results


def test_execution_failure_cleans_pod_and_records_failed_run(persisted_target):
    context = persisted_target
    context.transport.fail_chat = True
    with pytest.raises(TargetExecutionError, match="test chat failed"):
        execution.execute_persisted_run(context.run.id)
    assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
    assert context.transport.created == context.transport.deleted == 1


@pytest.mark.parametrize("debug_enabled", [False, True])
def test_chatabc_sse_error_diagnostics_are_opt_in(
    persisted_target, monkeypatch, caplog, debug_enabled
):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_chatabc":
        pytest.skip("ChatABC-only SSE diagnostics")
    context.transport.chat_error_event = True
    if debug_enabled:
        monkeypatch.setenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", "1")
    else:
        monkeypatch.delenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", raising=False)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            TargetExecutionError, match="customer chat returned an error event"
        ):
            execution.execute_persisted_run(context.run.id)

    assert ("inbank_sse_failure" in caplog.text) is debug_enabled
    assert ("BASE-001" in caplog.text) is debug_enabled
    assert ("customer base failed" in caplog.text) is debug_enabled
    assert context.transport.created == context.transport.deleted == 1


def test_cancelled_delivery_does_not_create_pod(persisted_target):
    context = persisted_target
    context.repository.save_run(transition_run(context.run, RunStatus.CANCELLED))
    assert execution.execute_persisted_run(context.run.id) == "cancelled"
    assert context.transport.created == context.transport.deleted == 0


def test_run_id_must_provide_an_eight_character_customer_task_id(persisted_target):
    context = persisted_target
    run = EvaluationRun(id="short", manifest=context.run.manifest)
    context.repository.save_run(run)

    with pytest.raises(TargetExecutionError, match="at least 8 characters"):
        execution.execute_persisted_run(run.id)

    assert context.transport.created == 0


@pytest.mark.parametrize("override", [{"max_retries": 1}, {"max_parallel_cases": 2}])
def test_invalid_execution_limits_are_rejected_before_creation(persisted_target, override):
    context = persisted_target
    run = pending_run(target=context.run.manifest.target, **override)
    run = EvaluationRun(manifest=run.manifest)
    context.repository.save_run(run)
    with pytest.raises(ValueError, match="no retries and serial cases"):
        execution.execute_persisted_run(run.id)
    assert context.transport.created == 0


def test_judge_initialization_failure_closes_target(persisted_target, monkeypatch):
    context = persisted_target
    module = chatabc if context.run.manifest.target.adapter_type == "inbank_chatabc" else yunxia
    adapter_class = (
        module.InbankChatABCTargetAdapter if module is chatabc else module.InbankYunxiaTargetAdapter
    )
    close = Mock()
    monkeypatch.setattr(adapter_class, "close", close)
    monkeypatch.setattr(
        execution,
        "load_judge_model_from_environment",
        Mock(side_effect=ValueError("invalid judge")),
    )
    with pytest.raises(ValueError, match="invalid judge"):
        execution.execute_persisted_run(context.run.id)
    close.assert_called_once_with()
    assert context.transport.created == 0
