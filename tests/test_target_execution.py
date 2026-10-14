"""Real in-bank adapters execute persisted Runs through the shared engine."""

import base64
import json
import logging
from contextlib import closing
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_agent_platform_target import RecordingDispatcher, submission
from test_inbank_trace_server_adapters import _Clock, _TraceServer, _Transport
from test_run_engine import pending_run
from test_target_execution_factory import configure_inbank, target_snapshot
from test_trace_server_client import DETAIL, Response, sparse_inbank_detail

from agentgate.application import ResultReader
from agentgate.application.credential_management import ApiKeyManagement
from agentgate.domain import (
    Case,
    CaseTurn,
    EvaluationRun,
    EvaluatorSpec,
    RunStatus,
    TargetSnapshot,
    transition_run,
)
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.job_dispatchers import execution
from agentgate.integrations.job_dispatchers.celery import execute_evaluation_run
from agentgate.integrations.observability.trace_server import TraceServerClient
from agentgate.integrations.targets import execution_factory
from agentgate.integrations.targets.inbank import chatabc, yunxia
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionStatus,
    TargetExecutionError,
)
from agentgate.server.app import create_app
from agentgate.storage.sqlite import SQLiteRepository


class RecordingTransport(_Transport):
    """Return current adapter-contract fixtures without connecting to a bank."""

    def __init__(self):
        self.created = 0
        self.create_requests = []
        self.deleted = 0
        self.delete_requests = []
        self.sessions = []
        self.messages = []
        self.request_ids = []
        self.fail_chat = False
        self.chat_error_event = False
        self.yunxia_auxiliary_events = False
        self.yunxia_error_event = False
        self.arrange_type = "base"
        self.missing_trace = False

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
        self.request_ids.append(headers["X-Request-ID"])
        if url.endswith("/chat"):
            assert payload["requestId"] == headers["X-Request-ID"]
            self.messages.append(payload["data"])
            if self.chat_error_event:
                return (
                    b"event: error\n"
                    b'data: {"errorCode": "BASE-001", '
                    b'"message": "customer base failed"}\n\n'
                )
            message = (
                {"node_id": "end", "additional_kwargs": {"node_output": {"output": "answer"}}}
                if self.arrange_type == "workflow" else {"content": "answer"}
            )
            events = [("message", message)]
        else:
            assert url.endswith("/api/v1/message")
            self.messages.append(payload)
            if self.yunxia_error_event:
                events = [("failed", {"message": "customer Yunxia failed"})]
            elif self.yunxia_auxiliary_events:
                events = [
                    ("chat_started", {"chat_id": "chat-1"}),
                    ("node_started", {"node_id": "intentClassification"}),
                    ("chunk", {"content": "partial"}),
                    ("message", {"status": "completed", "output": "answer"}),
                ]
            else:
                events = [
                    (
                        "start",
                        {
                            "request_id": headers["X-Request-ID"],
                            "session_id": payload["sessionId"],
                        },
                    ),
                    ("message", {"status": "completed", "output": "answer"}),
                ]
        if not self.missing_trace:
            events.append(("trace", {
                "project_id": "customer-project",
                "trace_id": headers["X-Request-ID"],
            }))
        return (
            "".join(
                f"event: {name}\ndata: {json.dumps(data)}\n\n"
                for name, data in events
            )
            + ("" if self.yunxia_auxiliary_events else "event: done\ndata: [DONE]\n\n")
        ).encode()


@pytest.fixture(params=["base", "workflow", "yunxia"])
def persisted_target(request, tmp_path, monkeypatch):
    adapter_type = "inbank_yunxia" if request.param == "yunxia" else "inbank_chatabc"
    configure_inbank(monkeypatch, adapter_type)
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "execution.db"))
    monkeypatch.setenv("AGENTGATE_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    monkeypatch.setattr(execution, "load_judge_model_from_environment", lambda: None)
    transport = RecordingTransport()
    transport.arrange_type = request.param
    module = chatabc if adapter_type == "inbank_chatabc" else yunxia
    adapter_class = module.InbankChatABCTargetAdapter if module is chatabc else module.InbankYunxiaTargetAdapter
    clock = _Clock()
    constructor = Mock(side_effect=lambda settings, **kwargs: adapter_class(
        settings, sleep=clock.sleep, monotonic=clock.monotonic, **kwargs,
    ))
    constructor.adapter_type = adapter_class.adapter_type
    monkeypatch.setattr(execution_factory, adapter_class.__name__, constructor)
    for method in ("request", "post", "get"):
        monkeypatch.setattr(module.requests, method, getattr(transport, method))
    trace_server = _TraceServer()
    trace_client_factory = Mock(return_value=trace_server)
    monkeypatch.setattr(execution_factory, "TraceServerClient", trace_client_factory)
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
    target = target_snapshot(adapter_type)
    if request.param == "workflow":
        values = target.model_dump(exclude={"content_sha256"})
        values["invocation_config"] = {"arrange_type": "workflow"}
        target = TargetSnapshot(**values)
    with closing(SQLiteRepository(tmp_path / "execution.db")) as repository:
        credentials = ApiKeyManagement(repository, execution.load_api_key_encryptor())
        metadata = credentials.create_api_key(name="Bank task", provider_id="agent-platform-inbank",
                                              scope="private", plaintext="bank-task-secret")
        target = TargetSnapshot(**{
            **target.model_dump(exclude={"content_sha256"}), "credential_ref": metadata.id,
        })
        original = pending_run(cases=cases, target=target)
        run = EvaluationRun(id="12345678-1234-1234-1234-abcdef987654", manifest=original.manifest)
        repository.save_run(run)
        yield SimpleNamespace(
            repository=repository, run=run, transport=transport, trace_server=trace_server,
            trace_client_factory=trace_client_factory,
        )


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
    assert all(sum(span.operation_type == "tool" for span in trace.spans) == 2 for trace in traces)
    assert len(context.trace_server.calls) == 12
    assert len({trace_id for _, trace_id, _ in context.trace_server.calls}) == 4
    assert [call[:2] for call in context.trace_server.calls] == [
        (context.run.manifest.target.ref.external_target_id, request_id)
        for request_id in context.transport.request_ids for _ in range(3)
    ]
    context.trace_client_factory.assert_called_once_with(
        "http://trace.invalid", mode="inbank", token="bank-task-secret", source_timezone="Asia/Shanghai",
    )
    report = ResultReader(context.repository).get_report(context.run.id)
    assert report.run.id == context.run.id
    assert len(report.results) == 2
    assert context.transport.created == context.transport.deleted == 1
    assert context.transport.create_requests == [
        {
            "method": "POST",
            "url": "http://bank.invalid/web/agent_endpoint/createAgent?taskId=ef987654",
            "payload": {
                "agentId": "loan-agent",
                "agentVersion": "loan-agent-v2-fixed",
                **(
                    {"branchId": "branch-review"}
                    if context.run.manifest.target.adapter_type == "inbank_yunxia"
                    else {}
                ),
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
    if context.run.manifest.target.adapter_type == "inbank_yunxia":
        assert messages[0]["custID"] == messages[1]["custID"]
        assert messages[2]["custID"] == messages[3]["custID"]
        assert messages[0]["custID"] != messages[2]["custID"]
        assert all(message["custID"].startswith("test-customer-") for message in messages)
    assert entry(context.run.id) == "completed"
    assert context.transport.created == context.transport.deleted == 1
    assert context.repository.list_traces(context.run.id) == traces
    assert context.repository.list_results(context.run.id) == results


def test_real_tool_evidence_drives_evaluator_results(persisted_target):
    context = persisted_target
    case = Case(
        id="tool-evidence-case",
        name="Evaluate actual tool calls from Trace Server",
        turns=tuple(
            CaseTurn(
                id=f"turn-{index}",
                input={"txt": "lookup"},
                expectations=(
                    {"kind": "tool_call", "mode": "required", "tool": "lookup"},
                    {"kind": "tool_call", "mode": "required", "tool": "absent_tool"},
                ),
            )
            for index in range(2)
        ),
    )
    run = pending_run(
        cases=(case,),
        target=context.run.manifest.target,
        evaluator_specs=(EvaluatorSpec(
            id="required-tool",
            name="Required tools",
            dimension="tool_use",
            metric="tool_coverage",
            implementation_id="required_tool",
        ),),
        primary_evaluator_ids=("required-tool",),
    )
    run = EvaluationRun(id="tool-evidence-run-12345678", manifest=run.manifest)
    context.repository.save_run(run)

    assert execution.execute_persisted_run(run.id) == "completed"

    report = ResultReader(context.repository).get_report(run.id)
    assert len(report.results) == 1
    checks = report.results[0].checks
    assert [check.outcome.value for check in checks] == ["pass", "fail", "pass", "fail"]
    trace = context.repository.list_traces(run.id)[0]
    for index, turn in enumerate(case.turns):
        check = checks[index * 2]
        assert check.turn_id == turn.id
        assert set(check.span_ids) == {
            span.span_id for span in trace.for_turn(turn.id).spans
            if span.operation_type == "tool"
        }
    assert checks[0].span_ids != checks[2].span_ids
    assert context.transport.created == context.transport.deleted == 1


def test_execution_failure_cleans_pod_and_records_failed_run(persisted_target):
    context = persisted_target
    context.transport.fail_chat = True
    with pytest.raises(TargetExecutionError, match="test chat failed"):
        execution.execute_persisted_run(context.run.id)
    assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
    assert context.transport.created == context.transport.deleted == 1


def test_missing_sse_reference_still_fetches_real_trace(persisted_target):
    context = persisted_target
    context.transport.missing_trace = True
    assert execution.execute_persisted_run(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    traces = context.repository.list_traces(context.run.id)
    assert len(traces) == len(context.repository.list_results(context.run.id)) == 2
    assert all(trace.final_output["output"] == "answer" for trace in traces)
    assert all(len(trace.turn_outcomes) == 2 and len(trace.spans) == 4 for trace in traces)
    assert all(
        span.attributes["inbank.evidence_mode"] == "trace_server"
        for trace in traces for span in trace.spans if span.operation_type == "turn"
    )
    report = ResultReader(context.repository).get_report(context.run.id)
    assert len(report.results) == 2
    assert len(context.transport.messages) == 4
    assert context.transport.created == context.transport.deleted == 1


def test_trace_unavailable_completes_output_evaluation_and_cleans_pod(persisted_target, monkeypatch):
    context = persisted_target
    monkeypatch.setenv("AGENTGATE_INBANK_REQUEST_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(context.trace_server, "fetch_events", Mock(
        side_effect=TargetExecutionError("unavailable", "trace server request failed")
    ))
    assert execution.execute_persisted_run(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    traces = context.repository.list_traces(context.run.id)
    assert len(traces) == len(context.repository.list_results(context.run.id)) == 2
    assert all(trace.final_output["output"] == "answer" for trace in traces)
    assert all(len(trace.spans) == 2 for trace in traces)
    assert all(s.operation_type == "turn" and s.attributes["inbank.evidence_mode"] == "output_only"
               for trace in traces for s in trace.spans)
    assert len(ResultReader(context.repository).get_report(context.run.id).results) == 2
    assert len(context.transport.messages) == 4
    assert context.transport.created == context.transport.deleted == 1


@pytest.mark.parametrize("problem", ["missing-ref", "deleted-key", "missing-key", "wrong-key"])
def test_worker_credential_failure_is_sanitized_before_pod_creation(
    persisted_target, monkeypatch, caplog, problem,
):
    context = persisted_target
    run = context.run
    if problem == "missing-ref":
        target = TargetSnapshot(**{
            **run.manifest.target.model_dump(exclude={"content_sha256"}), "credential_ref": None,
        })
        run = pending_run(target=target)
        context.repository.save_run(run)
    elif problem == "deleted-key":
        context.repository.delete_api_key(run.manifest.target.credential_ref)
    elif problem == "missing-key":
        monkeypatch.delenv("AGENTGATE_API_KEY_ENCRYPTION_KEY")
    else:
        monkeypatch.setenv(
            "AGENTGATE_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode(),
        )
    with caplog.at_level(logging.ERROR):
        assert execution.execute_persisted_run(run.id) == "failed"
    failed = context.repository.get_run(run.id)
    assert failed.error == "In-bank execution configuration or credential is unavailable"
    assert context.transport.created == context.transport.deleted == 0
    context.trace_client_factory.assert_not_called()
    assert "bank-task-secret" not in caplog.text + failed.model_dump_json()


@pytest.mark.parametrize("mode", ["base", "workflow", "claw"])
@pytest.mark.parametrize("sparse_root", [False, True])
def test_bank_submission_to_worker_evaluation_and_report(mode, sparse_root, tmp_path, monkeypatch):
    """Exercise the real API, credential store, query client, normalizer and evaluators.

    Only the bank network is replaced; the response shape is a synthetic fixture
    patterned after the customer screenshots, not a captured customer response.
    """
    adapter_type = "inbank_yunxia" if mode == "claw" else "inbank_chatabc"
    configure_inbank(monkeypatch, adapter_type)
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "inbank")
    monkeypatch.setenv("AGENTGATE_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_TOKEN", "must-not-use-process-token")
    monkeypatch.setattr(execution, "load_judge_model_from_environment", lambda: None)
    transport = RecordingTransport()
    transport.arrange_type = mode
    transport.missing_trace = True
    module = yunxia if mode == "claw" else chatabc
    adapter_class = module.InbankYunxiaTargetAdapter if module is yunxia else module.InbankChatABCTargetAdapter
    clock = _Clock()
    constructor = Mock(side_effect=lambda settings, **kwargs: adapter_class(
        settings, sleep=clock.sleep, monotonic=clock.monotonic, **kwargs,
    ))
    constructor.adapter_type = adapter_class.adapter_type
    monkeypatch.setattr(execution_factory, adapter_class.__name__, constructor)
    for method in ("request", "post", "get"):
        monkeypatch.setattr(module.requests, method, getattr(transport, method))
    queries = []

    def opener(request, *, timeout):
        request_id = transport.request_ids[-1]
        assert request.full_url == (
            f"http://trace.invalid/web/agent_trace_otel/projects/agent-{mode}/traces/{request_id}"
        )
        assert request.get_header("Authorization") == "Bearer task-login-token"
        queries.append(request_id)
        detail = deepcopy(DETAIL)
        detail.pop("observations")
        detail["trace"].update({
            "id": request_id, "projectId": f"agent-{mode}", "spanCount": 2, "toolCount": 1,
            "startedAt": "2026-10-10T10:29:00", "durationMs": 5.5,
            "output": {"messages": [{"type": "ai", "content": "trace response"}]},
        })
        tool = detail["spans"][0]
        tool.update({
            "traceId": request_id, "spanType": "tool", "toolName": "lookup", "name": "lookup",
            "startedAt": "2026-10-10T10:29:00", "durationMs": 5.5,
        })
        detail["spans"].append({
            **tool, "id": "context-1", "eventId": "context-event", "spanType": "context",
            "name": "router.context.window", "toolName": None,
        })
        if sparse_root:
            detail = sparse_inbank_detail(detail, module._task_id_from_run_id(run_id))
            detail["spans"][0].update(
                name="read_file", toolName="read_file",
                input={"file_path": "/mnt/oneagent-skills/skills/hello-ces-skills/SKILL.md", "limit": 1000},
            )
        return Response({"code": "0", "message": "success", "data": detail})

    monkeypatch.setattr(execution_factory, "TraceServerClient", partial(TraceServerClient, opener=opener))
    dispatcher = RecordingDispatcher()
    path = tmp_path / "bank-api.db"
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", str(path))
    app = create_app(path, dispatcher, ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    with TestClient(app) as client:
        dataset = deps.datasets.create_dataset("Bank trace and answer", "Two cases, two turns")
        deps.datasets.create_draft(dataset.id)
        for index in range(2):
            deps.datasets.save_case(dataset.id, Case(
                name=f"case-{index}",
                turns=tuple(CaseTurn(
                    input={"txt": "hello"},
                    expectations=(
                        {"kind": "tool_call", "mode": "required", "tool": "read_file" if sparse_root else "lookup"},
                        {"kind": "output", "path": "output",
                         "condition": {"kind": "matches_pattern", "pattern": "^answer$"}},
                    ) + ((
                        {"kind": "tool_argument", "tool": "read_file", "path": "arguments.file_path",
                         "condition": {"kind": "matches_pattern", "pattern": "/skills/hello-ces-skills/SKILL[.]md$"}},
                        {"kind": "tool_call", "mode": "forbidden", "tool": "delete"},
                        {"kind": "skill_route", "condition": {"kind": "equals", "expected": "hello-ces-skills"}},
                    ) if sparse_root else ()),
                ) for _ in range(2)),
            ))
        deps.datasets.publish_draft(dataset.id)
        body = {**submission(dataset.id, mode), "max_parallel_cases": 1,
                "evaluator_ids": ["final-output", "required-tool"] + (
                    ["tool-arguments", "forbidden-tool", "skill-routing"] if sparse_root else []
                )}
        response = client.post("/api/agent-platform/evaluations", json=body,
                               headers={"X-Agent-Platform-Token": "task-login-token"})
        assert response.status_code == 202, response.text
        run_id = response.json()["data"]["run_ids"][0]
        assert dispatcher.ids == [run_id]
        stored = deps.repository.get_run(run_id)
        assert stored.manifest.target.credential_ref
        assert "task-login-token" not in stored.model_dump_json()
        assert execution.execute_persisted_run(run_id) == "completed"
        report_response = client.get(f"/api/runs/{run_id}")
        assert report_response.status_code == 200
        report = report_response.json()["data"]
        assert report["run"]["status"] == "completed"
        assert len(report["results"]) == (10 if sparse_root else 4)
        for result in report["results"]:
            if result["evaluator_id"] == "skill-routing":
                # Reading SKILL.md is not an explicit routing decision.
                assert result["outcome"] == "fail"
                assert all(check["actual_missing"] for check in result["checks"])
            else:
                assert result["outcome"] == "pass"
        assert "task-login-token" not in report_response.text
        traces = deps.repository.list_traces(run_id)
        assert len(traces) == 2
        assert all(trace.final_output["output"] == "answer" for trace in traces)
        assert all(len(trace.turn_outcomes) == 2 for trace in traces)
        assert all(sum(span.operation_type == "tool" for span in trace.spans) == 2 for trace in traces)
        assert all(
            span.attributes["inbank.evidence_mode"] == "trace_server"
            for trace in traces for span in trace.spans if span.operation_type == "turn"
        )
        if sparse_root:
            for trace in traces:
                assert not any(span.operation_type == "routing" for span in trace.spans)
                for span in trace.spans:
                    if span.operation_type == "turn":
                        source = span.attributes["inbank.trace_source"]
                        assert source["response_project_id"] == module._task_id_from_run_id(run_id)
                        assert source["raw_trace"]["output"] is None
                        assert source["raw_trace"]["spanCount"] == 0
                        assert source["derived_fields"]["output"] == "dialogue"
        assert queries == [request_id for request_id in transport.request_ids for _ in range(3)]
        assert len(set(queries)) == 4
        assert transport.created == transport.deleted == 1
        assert len(transport.messages) == 4
    assert b"task-login-token" not in path.read_bytes()


def test_yunxia_accepts_auxiliary_events_without_start_or_done(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE compatibility")
    context.transport.yunxia_auxiliary_events = True

    assert execution.execute_persisted_run(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    assert context.transport.created == context.transport.deleted == 1


def test_yunxia_still_rejects_failure_events(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE compatibility")
    context.transport.yunxia_error_event = True

    with pytest.raises(TargetExecutionError, match="customer Yunxia failed"):
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

    with caplog.at_level(logging.ERROR), pytest.raises(
        TargetExecutionError, match="customer base failed"
    ):
        execution.execute_persisted_run(context.run.id)

    assert ("inbank_sse_failure" in caplog.text) is debug_enabled
    assert ("BASE-001" in caplog.text) is debug_enabled
    assert "customer base failed" in caplog.text
    assert context.transport.created == context.transport.deleted == 1


@pytest.mark.parametrize("debug_enabled", [False, True])
def test_yunxia_sse_error_diagnostics_are_opt_in(
    persisted_target, monkeypatch, caplog, debug_enabled
):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE diagnostics")
    context.transport.yunxia_error_event = True
    if debug_enabled:
        monkeypatch.setenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", "1")
    else:
        monkeypatch.delenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", raising=False)

    with caplog.at_level(logging.ERROR), pytest.raises(
        TargetExecutionError, match="customer Yunxia failed"
    ):
        execution.execute_persisted_run(context.run.id)

    assert ("inbank_sse_failure" in caplog.text) is debug_enabled
    assert ("response_body=" in caplog.text) is debug_enabled
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


def test_yunxia_requires_branch_before_creation(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only branch contract")
    values = context.run.manifest.target.model_dump(exclude={"content_sha256"})
    values["invocation_config"] = {"agent_version": "loan-agent-v2-fixed"}
    target = TargetSnapshot(**values)
    run = EvaluationRun(manifest=pending_run(target=target).manifest)
    context.repository.save_run(run)

    with pytest.raises(TargetExecutionError, match="branch_id is required"):
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


@pytest.fixture
def lifecycle_target(persisted_target):
    context = persisted_target
    clock = _Clock()
    sleep = Mock(side_effect=clock.sleep)
    kwargs = {
        "trace_client": context.trace_server,
        "sleep": sleep,
        "monotonic": clock.monotonic,
    }
    if context.run.manifest.target.adapter_type == "inbank_yunxia":
        adapter = yunxia.InbankYunxiaTargetAdapter(
            yunxia.load_yunxia_settings(), http=context.transport, **kwargs)
    else:
        adapter = chatabc.InbankChatABCTargetAdapter(
            chatabc.load_chatabc_settings(), http=context.transport, **kwargs)
    request = CaseExecutionRequest(
        execution_id="lifecycle-retry-case",
        run_id=context.run.id,
        case=context.run.manifest.dataset.cases[0],
        target=context.run.manifest.target,
        timeout_seconds=600,
        traceparent=f"00-{'1' * 32}-{'2' * 16}-01",
    )
    with closing(adapter):
        yield SimpleNamespace(
            adapter=adapter, request=request, sleep=sleep,
            transport=context.transport, trace_server=context.trace_server,
        )


def inject_json_failures(monkeypatch, transport, endpoint, failures):
    original = transport.request_json
    outcomes = iter(failures)

    def request_json(method, url, **kwargs):
        if endpoint in url:
            outcome = next(outcomes, None)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
        return original(method, url, **kwargs)

    calls = Mock(side_effect=request_json)
    monkeypatch.setattr(transport, "request_json", calls)
    return calls


@pytest.mark.parametrize("failure_count", [0, 1, 2, 3])
@pytest.mark.parametrize("failure,error_code", [
    pytest.param({"code": "-1"}, "rejected", id="business-rejection"),
    pytest.param({"code": "0", "data": {}}, "protocol_error", id="missing-agent-name"),
    pytest.param(TargetExecutionError("timeout", "create timeout"), "timeout", id="timeout"),
    pytest.param(
        TargetExecutionError("unavailable", "create HTTP 502"), "unavailable", id="http-502"
    ),
])
def test_create_pod_retries_only_creation(
    lifecycle_target, monkeypatch, caplog, failure_count, failure, error_code
):
    context = lifecycle_target
    calls = inject_json_failures(
        monkeypatch, context.transport, "/createAgent", [failure] * failure_count
    )

    if failure_count == 3:
        with pytest.raises(TargetExecutionError) as caught:
            context.adapter.start(context.request)
        assert caught.value.code == error_code
        assert context.adapter.get_status(context.request.execution_id) is CaseExecutionStatus.FAILED
        assert context.adapter.pod_lifecycle["create"] == "failed"
        assert context.adapter.pod_lifecycle["health"] == "not_attempted"
        assert len(calls.call_args_list) == 3
        assert context.transport.sessions == context.transport.messages == []
        assert context.trace_server.calls == []
    else:
        result = context.adapter.wait(context.adapter.start(context.request), 600)
        assert result.inline_trace.final_output["output"] == "answer"
        assert context.adapter.pod_lifecycle["create"] == "succeeded"
        assert context.adapter.pod_lifecycle["health"] == "succeeded"
        assert len(context.transport.messages) == 2
        assert len(context.trace_server.calls) == 6
        health_calls = [call for call in calls.call_args_list if "/health" in call.args[1]]
        assert len(health_calls) == 1

    attempts = [call for call in calls.call_args_list if "/createAgent" in call.args[1]]
    assert len(attempts) == min(failure_count + 1, 3)
    assert all(call == attempts[0] for call in attempts)
    assert attempts[0].args == (
        "POST", "http://bank.invalid/web/agent_endpoint/createAgent?taskId=ef987654"
    )
    assert attempts[0].kwargs["payload"] == {
        "agentId": "loan-agent",
        "agentVersion": "loan-agent-v2-fixed",
        **({"branchId": "branch-review"}
           if context.request.target.adapter_type == "inbank_yunxia" else {}),
    }
    assert [call.args[0] for call in context.sleep.call_args_list] == (
        [10] * min(failure_count, 2) + ([2] * 4 if failure_count < 3 else [])
    )
    if failure_count:
        assert "phase=create attempt=1 max_attempts=3 retry_delay_seconds=10" in caplog.text
    context.adapter.close()
    context.adapter.close()
    assert context.transport.deleted == (0 if failure_count == 3 else 1)


@pytest.mark.parametrize("failure_count", [0, 1, 9, 10])
@pytest.mark.parametrize("failure,error_code", [
    pytest.param({"resCode": "FAIAG1005"}, "rejected", id="business-rejection"),
    pytest.param(
        {"resCode": "FAIAG0000", "data": {}}, "protocol_error", id="missing-session-id"
    ),
    pytest.param(TargetExecutionError("timeout", "session timeout"), "timeout", id="timeout"),
])
def test_init_session_retries_without_recreating_pod_or_replaying_turns(
    lifecycle_target, monkeypatch, caplog, failure_count, failure, error_code
):
    context = lifecycle_target
    if context.request.target.adapter_type == "inbank_yunxia":
        pytest.skip("Yunxia has no init_session endpoint")
    calls = inject_json_failures(
        monkeypatch, context.transport, "/init_session", [failure] * failure_count
    )

    if failure_count == 10:
        with pytest.raises(TargetExecutionError) as caught:
            context.adapter.start(context.request)
        assert caught.value.code == error_code
        assert context.adapter.get_status(context.request.execution_id) is CaseExecutionStatus.FAILED
        assert context.transport.sessions == context.transport.messages == []
        assert context.trace_server.calls == []
    else:
        result = context.adapter.wait(context.adapter.start(context.request), 600)
        assert result.inline_trace.final_output["output"] == "answer"
        assert len(context.transport.sessions) == 1
        assert len(context.transport.messages) == 2
        assert len(context.trace_server.calls) == 6
        assert all(message["session_id"] == "session-0" for message in context.transport.messages)

    attempts = [call for call in calls.call_args_list if "/init_session" in call.args[1]]
    assert len(attempts) == min(failure_count + 1, 10)
    assert all(call == attempts[0] for call in attempts)
    assert attempts[0].kwargs["payload"]["requestId"]
    assert attempts[0].kwargs["headers"]["traceparent"] == context.request.traceparent
    assert [call.args[0] for call in context.sleep.call_args_list] == (
        [5] * min(failure_count, 9) + ([2] * 4 if failure_count < 10 else [])
    )
    assert context.transport.created == 1
    health_calls = [call for call in calls.call_args_list if "/health" in call.args[1]]
    assert len(health_calls) == 1
    if failure_count:
        assert "phase=init_session attempt=1 max_attempts=10" in caplog.text
    context.adapter.close()
    context.adapter.close()
    assert context.transport.deleted == 1
    assert context.adapter.pod_lifecycle["delete"] == "succeeded"


@pytest.mark.parametrize("exhausted", [False, True])
@pytest.mark.parametrize("endpoint,max_attempts,delay", [
    ("/createAgent", 3, 10),
    ("/init_session", 10, 5),
])
def test_worker_persists_outcome_after_lifecycle_retries(
    persisted_target, monkeypatch, endpoint, max_attempts, delay, exhausted
):
    context = persisted_target
    is_yunxia = context.run.manifest.target.adapter_type == "inbank_yunxia"
    if endpoint == "/init_session" and is_yunxia:
        pytest.skip("Yunxia has no init_session endpoint")
    adapter_class = (
        yunxia.InbankYunxiaTargetAdapter if is_yunxia else chatabc.InbankChatABCTargetAdapter
    )
    clock = _Clock()
    sleep = Mock(side_effect=clock.sleep)
    constructor = Mock(side_effect=lambda settings, **kwargs: adapter_class(
        settings, sleep=sleep, monotonic=clock.monotonic, **kwargs,
    ))
    constructor.adapter_type = adapter_class.adapter_type
    monkeypatch.setattr(execution_factory, adapter_class.__name__, constructor)
    failure_count = max_attempts if exhausted else max_attempts - 1
    calls = inject_json_failures(
        monkeypatch, context.transport, endpoint,
        [TargetExecutionError("unavailable", "customer endpoint temporarily unavailable")]
        * failure_count,
    )

    if exhausted:
        with pytest.raises(TargetExecutionError, match="customer endpoint temporarily unavailable"):
            execution.execute_persisted_run(context.run.id)
        assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
        assert context.repository.list_results(context.run.id) == []
        assert context.repository.list_traces(context.run.id) == []
        assert context.transport.messages == []
    else:
        assert execution.execute_persisted_run(context.run.id) == "completed"
        report = ResultReader(context.repository).get_report(context.run.id)
        assert report.run.status is RunStatus.COMPLETED
        assert len(report.results) == 2
        assert len(context.repository.list_traces(context.run.id)) == 2
        assert len(context.transport.messages) == 4

    attempts = [call for call in calls.call_args_list if endpoint in call.args[1]]
    expected_calls = max_attempts + (endpoint == "/init_session" and not exhausted)
    assert len(attempts) == expected_calls
    assert [call.args[0] for call in sleep.call_args_list] == (
        [delay] * (max_attempts - 1) + ([] if exhausted else [2] * 8)
    )
    assert context.transport.deleted == (0 if exhausted and endpoint == "/createAgent" else 1)
