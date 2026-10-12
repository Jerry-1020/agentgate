import json
from copy import deepcopy
from datetime import datetime, timedelta
from urllib.error import HTTPError

import pytest

from agentgate.integrations.observability.trace_server import (
    TraceServerClient,
    detail_to_events,
    prepare_inbank_trace_events,
)
from agentgate.run.target_protocol import TargetExecutionError


class Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return self._body


DETAIL = {
    "trace": {"id": "t-1", "projectId": "bank-tested-agents", "sessionId": "s-1",
              "name": "loan.base", "agentName": "loan-base-v1", "input": {"txt": "hi"},
              "output": {"status": "completed", "output": "answer"}, "status": "success",
              "durationMs": 5, "startedAt": "2026-09-17T00:00:00Z", "spanCount": 1, "toolCount": 0,
              "promptTokens": 10, "completionTokens": 2},
    "spans": [{"id": "sp-1", "eventId": "e-1", "parentSpanId": None, "name": "agent",
               "spanType": "agent", "toolName": None, "input": {"txt": "hi"},
               "output": "answer", "model": None, "status": "success", "durationMs": 5,
               "startedAt": "2026-09-17T00:00:00Z", "errorInfo": None, "traceId": "t-1"}],
    "observations": [{"id": "o-1", "spanId": "sp-1", "model": "m", "promptTokens": 10,
                      "completionTokens": 2, "input": None, "output": None}],
}
LLM = {"items": [{"eventId": "l-1", "spanId": "sp-1", "model": "m", "input": {"messages": []},
                  "output": {"role": "assistant"}, "startedAt": "2026-09-17T00:00:00Z",
                  "status": "success"}]}


def test_fetch_events_rebuilds_sdk_events_from_query_plane():
    paths = []

    def opener(request, *, timeout):
        paths.append(request.full_url)
        return Response(DETAIL if "llm_requests" not in request.full_url else LLM)

    client = TraceServerClient("http://127.0.0.1:8210", opener=opener)
    events = client.fetch_events("bank-tested-agents", "t-1", timeout=5)
    assert paths == ["http://127.0.0.1:8210/api/v1/projects/bank-tested-agents/traces/t-1",
                     "http://127.0.0.1:8210/api/v1/projects/bank-tested-agents/traces/t-1/llm_requests"]
    by_type = {event["event_type"]: event for event in events}
    assert by_type["trace"]["span_count"] == 1 and by_type["trace"]["duration_ms"] == 5
    assert by_type["span"]["parent_span_id"] is None and by_type["span"]["span_id"] == "sp-1"
    assert by_type["observation"]["prompt_tokens"] == 10
    assert by_type["llm_request"]["event_id"] == "l-1"
    assert all(event["project_id"] == "bank-tested-agents" and event["trace_id"] == "t-1"
               for event in events)


@pytest.mark.parametrize("url", ["ftp://x", "http://", "http://host/p?q=1", "notaurl"])
def test_client_rejects_invalid_origins(url):
    with pytest.raises(ValueError):
        TraceServerClient(url)


def test_client_maps_http_errors_to_target_errors():
    def opener(request, *, timeout):
        raise HTTPError(request.full_url, 500, "boom", None, None)

    client = TraceServerClient("http://127.0.0.1:8210", opener=opener)
    with pytest.raises(TargetExecutionError) as exc:
        client.fetch_events("p", "t")
    assert exc.value.code == "unavailable"

    def not_found(request, *, timeout):
        raise HTTPError(request.full_url, 404, "missing", None, None)

    client = TraceServerClient("http://127.0.0.1:8210", opener=not_found)
    with pytest.raises(TargetExecutionError) as exc:
        client.fetch_events("p", "t")
    assert exc.value.code == "rejected"


@pytest.mark.parametrize("detail", [
    {}, {"trace": None, "spans": [], "observations": []},
    {"trace": {"id": ""}, "spans": [], "observations": []},
    {"trace": {"id": "t", "projectId": "p", "name": "n", "status": "success"},
     "spans": [{"id": 1}], "observations": []},
])
def test_detail_to_events_rejects_invalid_shapes(detail):
    with pytest.raises(TargetExecutionError):
        detail_to_events(detail, [])


def test_detail_to_events_defaults_span_event_id_to_span_id():
    detail = {"trace": DETAIL["trace"], "observations": [],
              "spans": [dict(DETAIL["spans"][0], eventId=None)]}
    events = detail_to_events(detail, [])
    span = next(e for e in events if e["event_type"] == "span")
    assert span["event_id"] == "sp-1"


@pytest.mark.parametrize("kind", ["span", "observation", "llm"])
def test_foreign_child_trace_is_rejected(kind):
    from copy import deepcopy

    detail = deepcopy(DETAIL)
    llm = []
    if kind == "span":
        detail["spans"][0]["traceId"] = "foreign"
    elif kind == "observation":
        detail["observations"] = [{"spanId": "sp-1", "traceId": "foreign"}]
    else:
        llm = [{"spanId": "sp-1", "traceId": "foreign"}]
    with pytest.raises(TargetExecutionError, match="another trace"):
        detail_to_events(detail, llm)


def test_bad_json_is_a_sanitized_protocol_error():
    response = Response({})
    response._body = b'private-response-not-json'
    client = TraceServerClient("https://trace.example", opener=lambda *a, **k: response)
    with pytest.raises(TargetExecutionError, match="invalid JSON") as error:
        client.fetch_events("project", "trace")
    assert "private-response" not in str(error.value)


def test_query_budget_is_shared_between_detail_and_attachments(monkeypatch):
    from agentgate.integrations.observability import trace_server

    clock = iter([0, 3])
    monkeypatch.setattr(trace_server.time, "monotonic", lambda: next(clock))
    timeouts = []
    def opener(request, *, timeout):
        timeouts.append(timeout)
        return Response(LLM if request.full_url.endswith("llm_requests") else DETAIL)
    TraceServerClient("https://trace.example", opener=opener).fetch_events("project", "trace", timeout=10)
    assert timeouts == [10, 7]


def test_default_opener_path_fetches_over_real_http():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(LLM if "llm_requests" in self.path else DETAIL).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TraceServerClient(f"http://127.0.0.1:{server.server_port}")
        events = client.fetch_events("bank-tested-agents", "t-1", timeout=5)
        assert {event["event_type"] for event in events} == {"trace", "span", "observation", "llm_request"}
    finally:
        server.shutdown()


@pytest.fixture
def inbank_detail():
    """Synthetic contract fixture shaped after the customer screenshots, not a captured trace."""
    detail = deepcopy(DETAIL)
    detail.pop("observations")
    detail["trace"].update(
        eventId="root-event", name="LangGraph", agentName="test-agent",
        startedAt="2026-09-23T09:53:36.717", durationMs=7657, spanCount=3,
        output={"messages": [{"type": "ai", "content": "最终回答"}]}, errorInfo=None,
    )
    parent = detail["spans"][0]
    parent.update(name="LangGraph", spanType="chain", startedAt="2026-09-23T09:53:36.717")
    detail["spans"].extend([
        dict(parent, id="context-1", eventId="context-event", parentSpanId="sp-1",
             name="router.context.window", spanType="context", durationMs=0,
             input={"model": "test-model", "window_tokens": 32768}, output=None,
             metadata={"origin": "customer"}),
        dict(parent, id="llm-1", eventId="llm-event", parentSpanId="sp-1",
             name="RouterChatOpenAI", spanType="llm", model="test-model", durationMs=5.5,
             input={"messages": [{"role": "user", "content": "你好"}]},
             output={"messages": [{"type": "ai", "content": "最终回答"}]}),
    ])
    return detail


def fetch_inbank(detail, *, source_timezone=None, **kwargs):
    client = TraceServerClient(
        "https://trace.example", mode="inbank", token="task-token",
        source_timezone=source_timezone,
        opener=lambda *_a, **_k: Response({"code": "0", "message": "success", "data": detail}),
    )
    return client.fetch_events("bank-tested-agents", "t-1", **kwargs)


def sparse_inbank_detail(detail, customer_task_id):
    """Synthetic sparse-root variant from screenshots, not captured customer JSON."""
    detail = deepcopy(detail)
    detail["trace"].update(
        projectId=customer_task_id, sessionId=None, name=None, agentName=None,
        input=None, output=None, durationMs=None, spanCount=0, toolCount=0,
        startedAt="2026-10-10T11:52:09.502",
    )
    return detail


def test_sparse_root_is_completed_from_real_spans_and_dialogue_without_mutation(inbank_detail):
    detail = sparse_inbank_detail(inbank_detail, "48b2b018")
    events = fetch_inbank(detail, customer_task_id="48b2b018")
    original = deepcopy(events)
    prepared = prepare_inbank_trace_events(
        events, project_id="bank-tested-agents", customer_task_id="48b2b018",
        trace_id="t-1", final_output={"output": "dialogue answer"},
    )
    root = prepared[0]
    assert events == original
    assert len(prepared) == len(events)  # No manufactured source spans.
    assert root["name"] == "inbank.trace"
    assert root["output"] == {"output": "dialogue answer"}
    assert root["span_count"] == 3
    assert root["started_at"] == events[1]["started_at"]
    assert root["duration_ms"] == 5.5
    assert root["inbank_source"]["raw_trace"] == detail["trace"]
    assert root["inbank_source"]["response_project_id"] == "48b2b018"
    assert root["inbank_source"]["derived_fields"] == {
        "name": "display_label", "output": "dialogue", "started_at": "span_bounds",
        "duration_ms": "span_bounds", "span_count": "received_spans",
        "project_id": "current_pod_task_binding",
    }
    for before, after in zip(events[1:], prepared[1:]):
        assert after == {**before, "project_id": "bank-tested-agents"}


def test_inbank_export_boundary_preserves_original_parents_without_new_spans(inbank_detail):
    detail = deepcopy(inbank_detail)
    detail["spans"][0]["parentSpanId"] = "outer-first"
    detail["spans"][2]["parentSpanId"] = "outer-second"
    detail["spans"][0]["metadata"] = {"customer": "unchanged"}
    events = fetch_inbank(detail)
    original = deepcopy(events)
    options = {"project_id": "bank-tested-agents", "customer_task_id": "12345678",
               "trace_id": "t-1", "final_output": {"output": "answer"}}
    prepared = prepare_inbank_trace_events(events, **options)

    assert events == original
    assert len(prepared) == len(events)
    assert [e["span_id"] for e in prepared[1:]] == [e["span_id"] for e in events[1:]]
    assert prepared[2] == events[2]  # The returned context's real parent remains intact.
    for index, parent in [(1, "outer-first"), (3, "outer-second")]:
        assert prepared[index]["parent_span_id"] is None
        assert prepared[index]["metadata"] == {
            **(events[index].get("metadata") or {}),
            "inbank.original_parent_span_id": parent,
            "inbank.parent_span_not_returned": True,
        }
        for field in ("input", "output", "status", "started_at", "duration_ms"):
            assert prepared[index][field] == events[index][field]
    assert prepared[0]["inbank_source"]["unreturned_parent_span_ids"] == ["outer-first", "outer-second"]
    assert prepared[0]["inbank_source"]["derived_fields"]["span_parent_links"] == "returned_span_boundary"
    assert prepare_inbank_trace_events(prepared, **options) == prepared


def test_inbank_returned_parent_is_not_detached_when_it_appears_later(inbank_detail):
    events = fetch_inbank(inbank_detail)
    reordered = [events[0], events[2], events[3], events[1]]
    prepared = prepare_inbank_trace_events(
        reordered, project_id="bank-tested-agents", customer_task_id="12345678",
        trace_id="t-1", final_output={"output": "answer"},
    )
    assert prepared[1:] == reordered[1:]
    assert "unreturned_parent_span_ids" not in prepared[0]["inbank_source"]


@pytest.mark.parametrize("customer_task_id", [None, "another-task"])
def test_task_project_alias_requires_explicit_current_pod_binding(customer_task_id):
    with pytest.raises(TargetExecutionError, match="binding mismatch"):
        fetch_inbank(sparse_inbank_detail(DETAIL, "48b2b018"), customer_task_id=customer_task_id)


@pytest.mark.parametrize("part, field", [
    ("trace", "id"), ("trace", "projectId"), ("spans", "traceId"),
    ("spans", "projectId"), ("observations", "traceId"), ("observations", "projectId"),
])
def test_task_project_alias_does_not_relax_request_or_child_binding(part, field):
    detail = sparse_inbank_detail(DETAIL, "48b2b018")
    target = detail[part] if part == "trace" else detail[part][0]
    target[field] = "foreign"
    with pytest.raises(TargetExecutionError):
        fetch_inbank(detail, customer_task_id="48b2b018")


@pytest.mark.parametrize("pending", ["running", "empty", "span-running", "span-time", "partial-count"])
def test_sparse_root_still_waits_for_real_completed_spans(pending):
    events = fetch_inbank(sparse_inbank_detail(DETAIL, "48b2b018"), customer_task_id="48b2b018")
    if pending == "running":
        events[0]["status"] = "running"
    elif pending == "empty":
        events = events[:1]
    elif pending == "span-running":
        events[1]["status"] = "running"
    elif pending == "span-time":
        events[1]["duration_ms"] = None
    else:
        events[0]["span_count"] = 2
    assert prepare_inbank_trace_events(
        events, project_id="bank-tested-agents", customer_task_id="48b2b018",
        trace_id="t-1", final_output={"output": "answer"},
    ) is None


def test_inbank_query_uses_one_authenticated_detail_endpoint(inbank_detail):
    requests = []
    detail_before = deepcopy(inbank_detail)

    def opener(request, *, timeout):
        requests.append((request, timeout))
        return Response({"code": "0", "message": "success", "data": inbank_detail})

    events = TraceServerClient(
        "https://trace.example", mode="inbank", token="task-token",
        source_timezone="Asia/Shanghai", opener=opener,
    ).fetch_events("bank-tested-agents", "t-1", timeout=7)

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "https://trace.example/web/agent_trace_otel/projects/bank-tested-agents/traces/t-1"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer task-token"
    assert request.get_header("Accept") == "application/json"
    assert timeout == 7
    assert [event["event_type"] for event in events] == ["trace", "span", "span", "span"]
    assert events[0]["event_id"] == "root-event"
    assert events[0]["output"] == inbank_detail["trace"]["output"]
    assert events[0]["started_at"] == "2026-09-23T09:53:36.717000+08:00"
    assert events[2]["span_type"] == "span"
    assert events[2]["metadata"] == {"origin": "customer", "trace_server.span_type": "context"}
    assert events[3]["span_type"] == "llm"
    assert events[3]["model"] == "test-model"
    assert events[3]["duration_ms"] == 5.5
    assert events[3]["input"] == inbank_detail["spans"][2]["input"]
    assert inbank_detail == detail_before


def test_inbank_escapes_query_identifiers():
    detail = deepcopy(DETAIL)
    project_id, trace_id = "agent/a ?", "request/b#"
    detail["trace"].update(projectId=project_id, id=trace_id)
    detail["spans"][0]["traceId"] = trace_id
    urls = []

    def opener(request, **_kwargs):
        urls.append(request.full_url)
        return Response({"code": "0", "data": detail})

    TraceServerClient("https://trace.example", mode="inbank", token="t", opener=opener).fetch_events(
        project_id, trace_id,
    )
    assert urls == ["https://trace.example/web/agent_trace_otel/projects/agent%2Fa%20%3F/traces/request%2Fb%23"]


def test_task_tokens_are_isolated_and_standard_env_token_still_works(monkeypatch):
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_TOKEN", "standard-env-token")
    headers = []

    def opener(request, **_kwargs):
        headers.append(request.get_header("Authorization"))
        if "/web/" in request.full_url:
            return Response({"code": "0", "data": DETAIL})
        return Response(LLM if request.full_url.endswith("llm_requests") else DETAIL)

    first = TraceServerClient("https://trace.example", mode="inbank", token="first", opener=opener)
    second = TraceServerClient("https://trace.example", mode="inbank", token="second", opener=opener)
    standard = TraceServerClient("https://trace.example", opener=opener)
    first.fetch_events("bank-tested-agents", "t-1")
    second.fetch_events("bank-tested-agents", "t-1")
    first.fetch_events("bank-tested-agents", "t-1")
    standard.fetch_events("bank-tested-agents", "t-1")
    assert headers == ["Bearer first", "Bearer second", "Bearer first",
                       "Bearer standard-env-token", "Bearer standard-env-token"]
    import os
    assert os.environ["AGENTGATE_TRACE_SERVER_TOKEN"] == "standard-env-token"


@pytest.mark.parametrize("token", [None, "", " ", "Bearer secret", "secret\r\nX-Injected: yes", 3])
def test_inbank_requires_explicit_valid_token_even_when_env_is_set(monkeypatch, token):
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_TOKEN", "not-a-task-token")
    with pytest.raises(ValueError) as error:
        TraceServerClient("https://trace.example", mode="inbank", token=token)
    assert "secret" not in str(error.value)
    assert "not-a-task-token" not in str(error.value)


@pytest.mark.parametrize("options", [{"mode": "unknown"}, {"source_timezone": "invalid/zone"},
                                    {"source_timezone": ""}, {"source_timezone": "/etc/passwd"}])
def test_invalid_client_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        TraceServerClient("https://trace.example", **options)


@pytest.mark.parametrize("payload, code", [
    ({"code": "-1", "message": "trace not found", "data": None}, "unavailable"),
    ({"code": "-1", "message": "private-response"}, "rejected"),
    ({"code": 0, "data": DETAIL}, "rejected"),
    ([], "protocol_error"), ({}, "protocol_error"),
    ({"code": "0", "data": None}, "protocol_error"),
    ({"code": "0", "data": {}}, "protocol_error"),
])
def test_inbank_business_failure_or_bad_envelope_is_not_evidence(payload, code):
    client = TraceServerClient("https://trace.example", mode="inbank", token="secret-token",
                               opener=lambda *_a, **_k: Response(payload))
    with pytest.raises(TargetExecutionError) as error:
        client.fetch_events("bank-tested-agents", "t-1")
    assert error.value.code == code
    assert "private-response" not in str(error.value)
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize("status, code", [(401, "rejected"), (403, "rejected"), (500, "unavailable")])
def test_inbank_http_failure_is_sanitized_and_not_retried(status, code):
    calls = []

    def opener(request, **_kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, status, "private-token private-body", None, None)

    client = TraceServerClient("https://trace.example", mode="inbank", token="private-token", opener=opener)
    with pytest.raises(TargetExecutionError) as error:
        client.fetch_events("bank-tested-agents", "t-1")
    assert error.value.code == code
    assert str(status) in str(error.value)
    assert "private" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("part, field", [
    ("trace", "projectId"), ("trace", "id"),
    ("spans", "projectId"), ("spans", "traceId"),
    ("observations", "projectId"), ("observations", "traceId"),
])
def test_inbank_rejects_foreign_root_or_children(part, field):
    detail = deepcopy(DETAIL)
    target = detail[part] if part == "trace" else detail[part][0]
    target[field] = "foreign"
    with pytest.raises(TargetExecutionError):
        fetch_inbank(detail)


@pytest.mark.parametrize("value", [None, {}, "not-a-list"])
def test_present_but_malformed_observations_are_not_silently_ignored(value):
    detail = dict(DETAIL, observations=value)
    with pytest.raises(TargetExecutionError, match="invalid shape"):
        fetch_inbank(detail)


def test_embedded_observations_are_preserved():
    events = fetch_inbank(DETAIL)
    observation = next(event for event in events if event["event_type"] == "observation")
    assert observation["span_id"] == "sp-1"
    assert observation["prompt_tokens"] == 10
    assert not any(event["event_type"] == "llm_request" for event in events)


@pytest.mark.parametrize("source_timezone, offset", [
    (None, "+08:00"), ("Asia/Shanghai", "+08:00"), ("UTC", "+00:00"),
])
def test_naive_bank_timestamps_default_to_beijing_with_explicit_override(
    inbank_detail, source_timezone, offset,
):
    original = deepcopy(inbank_detail)
    events = fetch_inbank(inbank_detail, source_timezone=source_timezone)
    assert len(events) == 4
    assert all(event["started_at"] == "2026-09-23T09:53:36.717000" + offset for event in events)
    assert inbank_detail == original


@pytest.mark.parametrize("timestamp, expected", [
    ("2026-09-23T09:53:36.717Z", "2026-09-23T09:53:36.717000+00:00"),
    ("2026-09-23T09:53:36+02:00", "2026-09-23T09:53:36+02:00"),
])
def test_aware_timestamps_are_not_reinterpreted(timestamp, expected):
    detail = deepcopy(DETAIL)
    detail["trace"]["startedAt"] = timestamp
    for span in detail["spans"]:
        span["startedAt"] = timestamp
    for configured_zone in (None, "Asia/Shanghai", "UTC"):
        events = fetch_inbank(detail, source_timezone=configured_zone)
        assert all(event["started_at"] == expected for event in events
                   if event["event_type"] in {"trace", "span"})


@pytest.mark.parametrize("field, value", [
    ("startedAt", "private-invalid-date"), ("startedAt", 123),
    ("durationMs", -1), ("durationMs", True), ("durationMs", "5"),
    ("durationMs", float("nan")), ("durationMs", float("inf")),
    ("spanType", None), ("spanType", ""), ("spanType", []),
])
def test_invalid_bank_span_fields_are_rejected_without_echoing_values(field, value):
    detail = deepcopy(DETAIL)
    detail["spans"][0][field] = value
    with pytest.raises(TargetExecutionError) as error:
        fetch_inbank(detail)
    assert "private-invalid-date" not in str(error.value)


def test_unknown_node_type_is_preserved_as_generic_span():
    detail = deepcopy(DETAIL)
    detail["spans"][0]["spanType"] = "customer-node"
    event = fetch_inbank(detail)[1]
    assert event["span_type"] == "span"
    assert event["metadata"] == {"trace_server.span_type": "customer-node"}


def test_running_trace_is_not_falsely_marked_successful():
    detail = deepcopy(DETAIL)
    detail["trace"].update(status="running", output=None, durationMs=None)
    root = fetch_inbank(detail)[0]
    assert root["status"] == "running"
    assert root["output"] is None
    assert root["duration_ms"] is None


def test_inbank_events_normalize_without_fabricating_span_content(inbank_detail):
    from agentgate.domain import Case, CaseTurn, TargetRef, TargetSnapshot
    from agentgate.integrations.observability.trace_sdk import normalize_sdk_exports
    from agentgate.run.target_protocol import CaseExecutionRequest

    snapshot = TargetSnapshot(
        ref=TargetRef(source_id="test", target_type="agent", external_target_id="bank-tested-agents",
                      external_version_id="v1"),
        display_name="Contract test", descriptor_sha256="a" * 64,
        adapter_type="inbank-yunxia", adapter_version="1", invocation_config={},
    )
    request = CaseExecutionRequest(
        "execution", "run", Case(id="case", name="Contract test", turns=(
            CaseTurn(id="turn", input={"txt": "你好"}),
        )), snapshot, 30, "00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    )
    events = fetch_inbank(inbank_detail)
    raw = "\n".join(json.dumps(event, ensure_ascii=False) for event in events).encode()
    trace = normalize_sdk_exports(request, {"turn": ("t-1", raw)}, project_id="bank-tested-agents")
    assert len(trace.spans) == 4  # One turn wrapper plus three real source spans.
    spans = {span.attributes.get("trace_sdk.span_id"): span for span in trace.spans[1:]}
    assert spans["context-1"].operation_type == "span"
    assert spans["context-1"].parent_span_id == spans["sp-1"].span_id
    assert spans["context-1"].attributes["trace_sdk.metadata"]["trace_server.span_type"] == "context"
    assert spans["llm-1"].operation_type == "llm"
    attributes = spans["llm-1"].model_dump(mode="json")["attributes"]
    assert attributes["trace_sdk.input"] == inbank_detail["spans"][2]["input"]
    assert attributes["trace_sdk.output"] == inbank_detail["spans"][2]["output"]
    assert spans["llm-1"].started_at == datetime.fromisoformat("2026-09-23T09:53:36.717+08:00")
    assert spans["llm-1"].ended_at - spans["llm-1"].started_at == timedelta(milliseconds=5.5)
    assert trace.model_dump(mode="json")["final_output"] == inbank_detail["trace"]["output"]
    assert not any(span.operation_type in {"tool", "routing"} for span in trace.spans)


@pytest.mark.parametrize("redirect", [False, True])
def test_bank_default_opener_sends_auth_and_does_not_follow_redirects(redirect):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/must-not-receive-token")
                self.end_headers()
                return
            body = json.dumps({"code": "0", "data": DETAIL}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TraceServerClient(f"http://127.0.0.1:{server.server_port}", mode="inbank", token="bank-token")
        if redirect:
            with pytest.raises(TargetExecutionError, match="HTTP 302"):
                client.fetch_events("bank-tested-agents", "t-1", timeout=5)
        else:
            assert len(client.fetch_events("bank-tested-agents", "t-1", timeout=5)) == 3
        assert requests == [("/web/agent_trace_otel/projects/bank-tested-agents/traces/t-1", "Bearer bank-token")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
