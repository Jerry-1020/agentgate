from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import pytest
from test_trace_server_client import DETAIL, Response, sparse_inbank_detail

from agentgate.domain import Case, CaseTurn, TargetRef, TargetSnapshot, TargetType
from agentgate.integrations.observability.trace_server import TraceServerClient
from agentgate.integrations.targets.inbank.chatabc import (
    ChatABCSettings,
    InbankChatABCTargetAdapter,
)
from agentgate.integrations.targets.inbank.yunxia import (
    InbankYunxiaTargetAdapter,
    YunxiaSettings,
)
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionStatus,
    TargetExecutionError,
)


class _TraceServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def fetch_events(
        self, project_id: str, trace_id: str, *, timeout: float = 30,
        customer_task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((project_id, trace_id, timeout))
        common = {
            "project_id": project_id,
            "trace_id": trace_id,
            "started_at": "2026-09-23T00:00:00Z",
            "duration_ms": 5,
            "status": "success",
        }
        return [
            {
                **common,
                "event_type": "trace",
                "event_id": f"trace-event-{trace_id}",
                "input": {"txt": "recorded input"},
                "output": {"output": "customer answer"},
                "span_count": 1,
            },
            {
                **common,
                "event_type": "span",
                "event_id": f"span-event-{trace_id}",
                "span_id": f"span-{trace_id}",
                "parent_span_id": None,
                "name": "customer.lookup",
                "span_type": "tool",
                "tool_name": "lookup",
                "input": {"city": "上海"},
                "output": {"found": True},
            },
        ]


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _Response:
    def __init__(self, data=None, raw=b""):
        self.data = data
        self.raw = raw
        self.status_code = 200
        self.encoding = "utf-8"
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_lines(self, decode_unicode=False):
        yield from self.raw.decode(self.encoding).splitlines()


class _Transport:
    def __init__(self, arrange_type: str, *, references: list[list[Any]] | None = None) -> None:
        self.arrange_type = arrange_type
        self.references = references
        self.chat_count = 0
        self.request_ids = []
        self.deleted = False

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method, url, *, json=None, stream=False, **kwargs):
        if stream:
            return _Response(raw=self.request_bytes(method, url, payload=json, **kwargs))
        return _Response(data=self.request_json(method, url, payload=json, **kwargs))

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        if "/createAgent" in url:
            if self.arrange_type == "yunxia":
                assert payload["branchId"] == "customer-branch"
            return {"code": "0", "data": {"agentName": "customer-agent"}}
        if url.endswith("/health_check"):
            return {"data": {"status": "ok"}}
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/init_session"):
            return {
                "resCode": "FAIAG0000",
                "data": {"session_id": "customer-session"},
            }
        if url.endswith("/delete_agent"):
            self.deleted = True
            return {"resCode": "FAIAG0000", "data": {"agent_name": "customer-agent"}}
        raise AssertionError(f"unexpected JSON request: {method} {url}")

    def request_bytes(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> bytes:
        if self.arrange_type == "yunxia":
            assert url.endswith("/api/v1/message")
            assert payload["debugTrace"] is True
        elif not url.endswith("/chat"):
            raise AssertionError(f"unexpected byte request: {method} {url}")
        request_id = headers["X-Request-ID"]
        if self.arrange_type != "yunxia":
            assert payload["requestId"] == request_id
        self.request_ids.append(request_id)
        self.chat_count += 1
        output = "customer answer"
        if self.arrange_type == "workflow":
            message = {
                "node_id": "end",
                "additional_kwargs": {"node_output": {"output": output}},
            }
        elif self.arrange_type == "yunxia":
            message = {
                "status": "completed",
                "message": output,
                "intent_code": "lookup-intent",
                "slots": {"city": "上海"},
                "workflow_calls": [{"id": "workflow-one"}],
            }
        else:
            message = {"content": output}
        frames = [f"event: message\ndata: {json.dumps(message)}\n\n"]
        references = (
            self.references[self.chat_count - 1]
            if self.references is not None
            else [
                {
                    "project_id": "customer-project",
                    "trace_id": f"customer-trace-{self.chat_count}",
                }
            ]
        )
        for reference in references:
            frames.append(f"event: trace\ndata: {json.dumps(reference)}\n\n")
        frames.append("event: done\ndata: [DONE]\n\n")
        return "".join(frames).encode()


def _request(arrange_type: str) -> CaseExecutionRequest:
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="customer-platform",
            target_type=TargetType.AGENT,
            external_target_id="customer-agent-id",
            external_version_id="customer-version",
        ),
        display_name="Customer Agent",
        adapter_type="inbank_yunxia" if arrange_type == "yunxia" else "inbank_chatabc",
        adapter_version="1",
        descriptor_sha256="a" * 64,
        invocation_config={
            "arrange_type": arrange_type,
            "agent_version": "customer-version",
            **({"branch_id": "customer-branch"} if arrange_type == "yunxia" else {}),
        },
    )
    case = Case(
        id="case-1",
        name="Two-turn customer case",
        turns=(
            CaseTurn(id="turn-1", input={"txt": "first"}),
            CaseTurn(id="turn-2", input={"txt": "second"}),
        ),
    )
    return CaseExecutionRequest(
        execution_id="execution-1",
        run_id="run-12345678",
        case=case,
        target=target,
        timeout_seconds=30,
        traceparent=f"00-{'1' * 32}-{'2' * 16}-01",
    )


def _adapter(
    arrange_type: str, transport, trace_server, *, base_url="https://bank.test", **options
):
    settings = {
        "create_base_url": base_url,
        "health_base_url": base_url,
        "pod_api_base_url": base_url,
        "delete_base_url": base_url,
        "request_timeout_seconds": 10,
        "health_wait_seconds": 10,
        "health_poll_interval_seconds": 1,
    }
    if arrange_type == "yunxia":
        return InbankYunxiaTargetAdapter(
            YunxiaSettings(**settings, agent_namespace="chatabc", test_customer_prefix="test"),
            http=transport,
            trace_client=trace_server,
            **options,
        )
    return InbankChatABCTargetAdapter(
        ChatABCSettings(**settings), http=transport, trace_client=trace_server, **options
    )


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
def test_builds_multiturn_trace_from_trace_server(arrange_type: str) -> None:
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    adapter = _adapter(arrange_type, transport, trace_server)
    request = _request(arrange_type)

    try:
        result = adapter.wait(adapter.start(request), 30)
    finally:
        adapter.close()

    assert result.inline_trace is not None
    assert transport.deleted is True
    assert [call[:2] for call in trace_server.calls] == [
        ("customer-agent-id", request_id) for request_id in transport.request_ids
    ]
    assert len(set(transport.request_ids)) == 2
    assert len(result.inline_trace.spans) == 4
    for sequence, turn in enumerate(request.case.turns, 1):
        outcome = result.inline_trace.turn_outcomes[turn.id]
        assert outcome["input"] == turn.input
        assert outcome["output"]["output"] == "customer answer"
        if arrange_type == "yunxia":
            assert outcome["output"]["intent_code"] == "lookup-intent"
            assert outcome["output"]["slots"] == {"city": "上海"}
            assert outcome["output"]["workflow_calls"][0]["id"] == "workflow-one"
        turn_trace = result.inline_trace.for_turn(turn.id)
        assert turn_trace.spans[0].attributes["trace_sdk.trace_id"] == (
            transport.request_ids[sequence - 1]
        )
        assert turn_trace.spans[0].attributes["trace_sdk.replay"] is False
        assert turn_trace.spans[1].operation_type == "tool"
        assert turn_trace.spans[1].name == "lookup"
        assert turn_trace.spans[1].attributes["arguments"] == {"city": "上海"}


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize(
    "references",
    [
        [[]],
        [[None]],
        [[{"trace_id": "trace"}]],
        [[{"project_id": "project", "trace_id": " "}]],
        [[{"project_id": "project", "trace_id": "trace"}] * 2],
        [
            [{"project_id": "project", "trace_id": "trace"}],
            [{"project_id": "other-project", "trace_id": "trace-2"}],
        ],
        [
            [{"project_id": "project", "trace_id": "trace"}],
            [{"project_id": "project", "trace_id": "trace"}],
        ],
    ],
)
def test_sse_trace_references_are_not_used_for_query_binding(arrange_type, references) -> None:
    transport = _Transport(arrange_type, references=references + [[]])
    trace_server = _TraceServer()
    adapter = _adapter(arrange_type, transport, trace_server)

    try:
        result = adapter.wait(adapter.start(_request(arrange_type)), 30)
    finally:
        adapter.close()

    trace = result.inline_trace
    assert trace.final_output["output"] == "customer answer"
    assert len(trace.turn_outcomes) == transport.chat_count == 2
    assert len(trace.spans) == 4
    assert all(span.attributes["inbank.evidence_mode"] == "trace_server"
               for span in trace.spans if span.operation_type == "turn")
    assert adapter.get_status("execution-1") is CaseExecutionStatus.COMPLETED
    assert [call[:2] for call in trace_server.calls] == [
        ("customer-agent-id", request_id) for request_id in transport.request_ids
    ]
    assert transport.deleted is True


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("trace_available", [True, False])
def test_trace_or_output_fallback_does_not_hide_later_chat_failure(arrange_type, trace_available, monkeypatch):
    transport = _Transport(arrange_type, references=[[], []])
    chat = transport.request_bytes

    def fail_second_chat(*args, **kwargs):
        if transport.chat_count == 1:
            raise TargetExecutionError("rejected", "customer chat rejected second Turn")
        return chat(*args, **kwargs)

    monkeypatch.setattr(transport, "request_bytes", fail_second_chat)
    trace_server = _TraceServer()
    if not trace_available:
        def reject(*_args, **_kwargs):
            raise TargetExecutionError("rejected", "trace not integrated")
        monkeypatch.setattr(trace_server, "fetch_events", reject)
    adapter = _adapter(arrange_type, transport, trace_server)
    try:
        with pytest.raises(TargetExecutionError, match="second Turn"):
            adapter.start(_request(arrange_type))
        assert adapter.get_status("execution-1") is CaseExecutionStatus.FAILED
    finally:
        adapter.close()
    assert transport.deleted is True


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("failure", ["unavailable", "not-found", "empty", "wrong-trace", "failed-trace"])
def test_trace_failure_keeps_output_without_synthetic_evidence(arrange_type, failure, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    fetch = trace_server.fetch_events

    def failing_fetch(project_id, trace_id, *, timeout, customer_task_id):
        if failure == "unavailable":
            raise TargetExecutionError("unavailable", "trace server request failed")
        if failure == "not-found":
            raise TargetExecutionError("unavailable", "inbank trace not found")
        events = fetch(project_id, trace_id, timeout=timeout)
        if failure == "empty":
            return []
        if failure == "wrong-trace":
            events[0]["trace_id"] = "unrelated"
        else:
            events[0]["status"] = "error"
        return events

    monkeypatch.setattr(trace_server, "fetch_events", failing_fetch)
    clock = _Clock()
    adapter = _adapter(
        arrange_type, transport, trace_server, sleep=clock.sleep, monotonic=clock.monotonic
    )
    try:
        result = adapter.wait(adapter.start(_request(arrange_type)), 30)
        assert adapter.get_status("execution-1") is CaseExecutionStatus.COMPLETED
        trace = result.inline_trace
        assert len(trace.spans) == 2
        assert trace.final_output["output"] == "customer answer"
        for span, request_id in zip(trace.spans, transport.request_ids, strict=True):
            assert span.operation_type == "turn"
            assert span.attributes["inbank.evidence_mode"] == "output_only"
            assert span.attributes["inbank.request_id"] == request_id
            assert span.attributes["inbank.trace_query_project_id"] == "customer-agent-id"
            assert span.attributes["inbank.trace_fallback_reason"] == (
                "timeout" if failure in {"unavailable", "not-found"} else "protocol_error"
            )
            assert "trace_sdk.trace_id" not in span.attributes
        warnings = [r for r in caplog.records if r.msg.startswith("inbank_trace_fallback ")]
        assert len(warnings) == 2 and all(r.levelno == logging.WARNING for r in warnings)
        assert all("evidence_mode=output_only" in r.getMessage() for r in warnings)
        if failure == "not-found":
            assert all("trace_not_found" in r.getMessage() for r in warnings)
    finally:
        adapter.close()
    assert transport.chat_count == 2
    assert transport.deleted is True


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize(
    "pending",
    ["404", "409", "429", "unavailable", "running", "spans", "output", "duration", "span-running",
     "no-spans", "started-at", "span-duration", "span-started-at"],
)
def test_trace_readiness_retries_without_replaying_chat(arrange_type, pending, monkeypatch):
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    fetch = trace_server.fetch_events
    clock = _Clock()

    def delayed(project_id, trace_id, *, timeout, customer_task_id):
        events = fetch(project_id, trace_id, timeout=timeout)
        if len(trace_server.calls) <= 2:
            if pending.isdigit():
                raise TargetExecutionError("rejected", f"trace server HTTP {pending}")
            if pending == "unavailable":
                raise TargetExecutionError("unavailable", "trace server request failed")
            if pending == "running":
                events[0]["status"] = "running"
            elif pending == "span-running":
                events[1]["status"] = "running"
            elif pending == "spans":
                events[0]["span_count"] = 1
                events.pop()
            elif pending == "output":
                events[0]["output"] = None
            elif pending == "duration":
                events[0]["duration_ms"] = None
            elif pending == "started-at":
                events[0]["started_at"] = None
            elif pending == "span-duration":
                events[1]["duration_ms"] = None
            elif pending == "span-started-at":
                events[1]["started_at"] = None
            elif pending == "no-spans":
                events.pop()
                events[0].pop("span_count")
        return events

    monkeypatch.setattr(trace_server, "fetch_events", delayed)
    adapter = _adapter(
        arrange_type, transport, trace_server, sleep=clock.sleep, monotonic=clock.monotonic
    )
    try:
        result = adapter.wait(adapter.start(_request(arrange_type)), 30)
        assert result.inline_trace.final_output["output"] == "customer answer"
        if pending in {"output", "duration", "started-at"}:
            assert [call[1] for call in trace_server.calls] == transport.request_ids
            assert clock.sleeps == []
        else:
            assert [call[1] for call in trace_server.calls] == [
                *([transport.request_ids[0]] * 3), transport.request_ids[1],
            ]
            assert clock.sleeps == [2, 2]
            assert [call[2] for call in trace_server.calls] == [10, 8, 6, 10]
        assert transport.chat_count == 2
    finally:
        adapter.close()
    assert transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_trace_permanent_rejection_does_not_retry(arrange_type, status, monkeypatch):
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    calls = []
    clock = _Clock()

    def rejected(*args, **kwargs):
        calls.append(args)
        raise TargetExecutionError("rejected", f"trace server HTTP {status}")

    monkeypatch.setattr(trace_server, "fetch_events", rejected)
    adapter = _adapter(
        arrange_type, transport, trace_server, sleep=clock.sleep, monotonic=clock.monotonic
    )
    try:
        trace = adapter.wait(adapter.start(_request(arrange_type)), 30).inline_trace
        assert all(s.attributes["inbank.trace_fallback_detail"] == f"trace server HTTP {status}"
                   for s in trace.spans)
        assert adapter.get_status("execution-1") is CaseExecutionStatus.COMPLETED
    finally:
        adapter.close()
    assert len(calls) == 2 and clock.sleeps == []
    assert transport.chat_count == 2 and transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow"])
@pytest.mark.parametrize("failed_turn", [None, 1, 2])
def test_chatabc_query_ids_logged_before_trace_rejection(
    arrange_type, failed_turn, caplog, monkeypatch,
):
    caplog.set_level(logging.INFO)
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    fetch = trace_server.fetch_events
    request = _request(arrange_type)

    def query(project_id, trace_id, **kwargs):
        records = [record for record in caplog.records
                   if record.msg.startswith("inbank_trace_query ")]
        assert len(records) == transport.chat_count
        record = records[-1]
        assert record.levelno == logging.INFO
        message = record.getMessage()
        assert f"project_id={project_id!r}" in message
        assert f"request_id={trace_id!r}" in message
        assert trace_id == transport.request_ids[-1]
        assert f"arrange_type={arrange_type}" in message
        assert f"run_id={request.run_id!r}" in message
        assert f"case_id={request.case.id!r}" in message
        assert f"turn_id={request.case.turns[transport.chat_count - 1].id!r}" in message
        if transport.chat_count == failed_turn:
            raise TargetExecutionError("rejected", "inbank trace server rejected the query")
        return fetch(project_id, trace_id, **kwargs)

    monkeypatch.setattr(trace_server, "fetch_events", query)
    adapter = _adapter(arrange_type, transport, trace_server)
    try:
        trace = adapter.wait(adapter.start(request), 30).inline_trace
        assert adapter.get_status(request.execution_id) is CaseExecutionStatus.COMPLETED
        for index, turn in enumerate(request.case.turns, 1):
            turn_trace = trace.for_turn(turn.id)
            expected = "output_only" if index == failed_turn else "trace_server"
            assert turn_trace.spans[0].attributes["inbank.evidence_mode"] == expected
            assert sum(s.operation_type == "tool" for s in turn_trace.spans) == (index != failed_turn)
    finally:
        adapter.close()

    assert transport.chat_count == 2
    assert len(set(transport.request_ids)) == transport.chat_count
    assert transport.deleted is True
    completed = [record for record in caplog.records
                 if record.msg.startswith("inbank_turn_complete ")]
    assert len(completed) == 2


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("problem", [
    "cycle", "cycle-with-boundary", "unknown-observation", "duplicate-span", "invalid-duration", "empty",
])
def test_sparse_root_never_repairs_or_fabricates_source_spans(arrange_type, problem):
    transport = _Transport(arrange_type)
    clock = _Clock()

    def opener(request, **_kwargs):
        detail = sparse_inbank_detail(DETAIL, "12345678")
        request_id = request.full_url.rsplit("/", 1)[1]
        detail["trace"]["id"] = request_id
        detail["spans"][0]["traceId"] = request_id
        if problem in {"cycle", "cycle-with-boundary"}:
            detail["spans"][0]["parentSpanId"] = "sp-1"
            if problem == "cycle-with-boundary":
                detail["spans"].append(dict(detail["spans"][0], id="boundary", eventId="boundary-event",
                                            parentSpanId="not-returned"))
        elif problem == "unknown-observation":
            detail["spans"][0]["parentSpanId"] = "not-returned"
            detail["observations"][0]["spanId"] = "not-returned"
        elif problem == "duplicate-span":
            detail["spans"][0]["parentSpanId"] = "not-returned"
            detail["spans"].append(dict(detail["spans"][0], eventId="duplicate-event"))
        elif problem == "invalid-duration":
            detail["spans"][0]["durationMs"] = -1
        else:
            detail["spans"] = []
            detail["observations"] = []
        return Response({"code": "0", "data": detail})

    trace_server = TraceServerClient(
        "https://trace.example", mode="inbank", token="test-token",
        source_timezone="Asia/Shanghai", opener=opener,
    )
    adapter = _adapter(
        arrange_type, transport, trace_server, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    try:
        trace = adapter.wait(adapter.start(_request(arrange_type)), 30).inline_trace
        assert len(trace.spans) == 2
        assert all(s.operation_type == "turn" and s.attributes["inbank.evidence_mode"] == "output_only"
                   for s in trace.spans)
        assert all(s.attributes["inbank.trace_fallback_reason"] == (
            "timeout" if problem == "empty" else "protocol_error") for s in trace.spans)
    finally:
        adapter.close()
    assert transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
def test_export_boundary_keeps_seven_real_spans_and_observations_per_turn(arrange_type):
    """Synthetic structural fixture from screenshots, not the original private payload."""
    transport = _Transport(arrange_type)
    queried = []
    rows = [
        ("context-first", "model-first", "router.context.window", "context", None),
        ("llm-first", "model-first", "RouterChatOpenAI", "llm", None),
        ("model-first", "outer-first", "model", "chain", None),
        ("read-skill", "tools", "read_file", "tool", "read_file"),
        ("tools", "outer-first", "tools", "chain", None),
        ("context-second", "outer-second", "router.context.window", "context", None),
        ("llm-second", "outer-second", "RouterChatOpenAI", "llm", None),
    ]

    def opener(request, **_kwargs):
        detail = sparse_inbank_detail(DETAIL, "12345678")
        request_id = request.full_url.rsplit("/", 1)[1]
        queried.append(request_id)
        detail["trace"]["id"] = request_id
        template = detail["spans"][0]
        detail["spans"] = [
            dict(template, id=sid, eventId=f"event-{sid}", traceId=request_id,
                 parentSpanId=parent, name=name, spanType=kind, toolName=tool)
            for sid, parent, name, kind, tool in rows
        ]
        detail["observations"] = [
            dict(DETAIL["observations"][0], id=f"observation-{sid}", spanId=sid)
            for sid in ("llm-first", "llm-second")
        ]
        return Response({"code": "0", "data": detail})

    trace_server = TraceServerClient(
        "https://trace.example", mode="inbank", token="test-token",
        source_timezone="Asia/Shanghai", opener=opener,
    )
    adapter = _adapter(arrange_type, transport, trace_server)
    request = _request(arrange_type)
    try:
        result = adapter.wait(adapter.start(request), 30)
    finally:
        adapter.close()
    assert queried == transport.request_ids
    assert len(queried) == 2 and transport.deleted
    for turn in request.case.turns:
        spans = result.inline_trace.for_turn(turn.id).spans
        assert len(spans) == 8  # Seven source spans plus the existing turn wrapper.
        wrapper = next(s for s in spans if s.operation_type == "turn")
        assert wrapper.attributes["inbank.evidence_mode"] == "trace_server"
        assert wrapper.attributes["inbank.trace_source"]["unreturned_parent_span_ids"] == (
            "outer-first", "outer-second",
        )
        by_source = {s.attributes["trace_sdk.span_id"]: s for s in spans if s is not wrapper}
        assert set(by_source) == {row[0] for row in rows}
        for sid, parent, *_ in rows:
            span = by_source[sid]
            if parent in by_source:
                assert span.parent_span_id == by_source[parent].span_id
            else:
                assert span.parent_span_id == wrapper.span_id
                assert span.attributes["trace_sdk.metadata"]["inbank.original_parent_span_id"] == parent
                assert span.attributes["trace_sdk.metadata"]["inbank.parent_span_not_returned"] is True
        assert by_source["read-skill"].operation_type == "tool"
        assert sum(len(span.events) for span in spans) == 2
        assert result.inline_trace.turn_outcomes[turn.id]["output"]["output"] == "customer answer"


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("pending", ["404", "running"])
def test_trace_readiness_deadline_falls_back_and_cleans_up(
    arrange_type, pending, monkeypatch
):
    transport = _Transport(arrange_type)
    trace_server = _TraceServer()
    fetch = trace_server.fetch_events
    clock = _Clock()

    def delayed(project_id, trace_id, *, timeout, customer_task_id):
        events = fetch(project_id, trace_id, timeout=timeout)
        if pending == "404":
            raise TargetExecutionError("rejected", "trace server HTTP 404")
        events[0]["status"] = "running"
        return events

    monkeypatch.setattr(trace_server, "fetch_events", delayed)
    adapter = _adapter(
        arrange_type, transport, trace_server, sleep=clock.sleep, monotonic=clock.monotonic
    )
    try:
        trace = adapter.wait(adapter.start(_request(arrange_type)), 30).inline_trace
        assert all(s.attributes["inbank.evidence_mode"] == "output_only" for s in trace.spans)
        assert all("not ready within 10s" in s.attributes["inbank.trace_fallback_detail"] for s in trace.spans)
        assert adapter.get_status("execution-1") is CaseExecutionStatus.COMPLETED
    finally:
        adapter.close()
    assert clock.now == 20 and clock.sleeps == [2] * 10
    assert len(trace_server.calls) == 10
    assert transport.chat_count == 2 and transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("missing_turn", [1, 2])
def test_each_turn_preserves_its_own_evidence_mode(arrange_type, missing_turn, monkeypatch):
    transport = _Transport(arrange_type)
    server = _TraceServer()
    fetch = server.fetch_events

    def query(*args, **kwargs):
        if transport.chat_count == missing_turn:
            raise TargetExecutionError("rejected", "trace not integrated")
        return fetch(*args, **kwargs)

    monkeypatch.setattr(server, "fetch_events", query)
    adapter = _adapter(arrange_type, transport, server)
    request = _request(arrange_type)
    try:
        trace = adapter.wait(adapter.start(request), 30).inline_trace
        for index, turn in enumerate(request.case.turns, 1):
            evidence = trace.for_turn(turn.id)
            assert evidence.spans[0].attributes["inbank.evidence_mode"] == (
                "output_only" if index == missing_turn else "trace_server"
            )
            assert sum(s.operation_type != "turn" for s in evidence.spans) == (index != missing_turn)
            assert evidence.final_output["output"] == "customer answer"
        assert [s.sequence for s in trace.spans] == list(range(len(trace.spans)))
    finally:
        adapter.close()
    assert transport.chat_count == 2 and transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("code", ["cancelled", "invalid_request"])
def test_trace_fallback_does_not_swallow_cancellation_or_configuration_errors(arrange_type, code, monkeypatch):
    transport = _Transport(arrange_type)
    server = _TraceServer()

    def query(*_args, **_kwargs):
        raise TargetExecutionError(code, "stop execution")

    monkeypatch.setattr(server, "fetch_events", query)
    adapter = _adapter(arrange_type, transport, server)
    try:
        with pytest.raises(TargetExecutionError, match="stop execution"):
            adapter.start(_request(arrange_type))
    finally:
        adapter.close()
    assert transport.chat_count == 1 and transport.deleted


@pytest.mark.parametrize("arrange_type", ["base", "workflow", "yunxia"])
@pytest.mark.parametrize("initial_404", [False, True])
def test_adapters_fetch_trace_server_over_http(arrange_type, initial_404, monkeypatch):
    peer = _Transport(arrange_type)
    queried = []
    clock = _Clock()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, body, content_type="application/json", status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith(("/chat", "/api/v1/message")):
                body = peer.request_bytes("POST", self.path, payload=payload, headers=self.headers, timeout=5)
                self.respond(body, "text/event-stream")
            else:
                result = peer.request_json("POST", self.path, payload=payload, timeout=5)
                self.respond(json.dumps(result).encode())

        def do_GET(self):
            if self.path.startswith("/web/agent_trace_otel/projects/"):
                queried.append(self.path)
                assert self.headers["Authorization"] == "Bearer bank-task-token"
                if initial_404 and len(queried) == 1:
                    self.respond(b"{}", status=404)
                    return
                detail = deepcopy(DETAIL)
                detail["trace"].update(
                    id=self.path.rsplit("/", 1)[-1],
                    projectId="customer-agent-id",
                    output={"messages": [{"type": "ai", "content": "raw trace answer"}]},
                )
                for span in detail["spans"]:
                    span["traceId"] = detail["trace"]["id"]
                result = {"code": "0", "data": detail}
            else:
                result = peer.request_json("GET", self.path, timeout=5)
            self.respond(json.dumps(result).encode())

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setenv("AGENTGATE_TRACE_SERVER_URL", origin)
        adapter = _adapter(
            arrange_type,
            None,
            TraceServerClient(origin, mode="inbank", token="bank-task-token"),
            base_url=origin,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        try:
            result = adapter.wait(adapter.start(_request(arrange_type)), 30)
            trace = result.inline_trace
            assert trace is not None
            assert trace.final_output["output"] == "customer answer"
            assert len(trace.turn_outcomes) == 2
            assert any(
                event["event_type"] == "observation"
                for span in trace.spans
                for event in span.events
            )
            expected = [
                f"/web/agent_trace_otel/projects/customer-agent-id/traces/{request_id}"
                for request_id in peer.request_ids
            ]
            if initial_404:
                expected.insert(0, expected[0])
            assert [urlparse(path).path for path in queried] == expected
            assert clock.sleeps == ([2] if initial_404 else [])
            assert peer.chat_count == 2
        finally:
            adapter.close()
            server.shutdown()
            thread.join(timeout=5)
    assert peer.deleted is True
