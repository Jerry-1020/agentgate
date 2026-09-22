import json

import pytest
from urllib.error import HTTPError

from agentgate.integrations.observability.trace_server import TraceServerClient, detail_to_events
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
