"""Query the customer Trace Server and rebuild SDK events for normalization.

The tested runtime references its trace in the chat SSE ``trace`` event; the
evidence itself is requested from the central Trace Server query plane
(tracev2 ``trace_server``), not from runtime-local endpoints. Query responses
are trimmed camelCase projections, so events are rebuilt into the SDK NDJSON
shape that ``normalize_sdk_exports`` validates.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agentgate.run.target_protocol import TargetExecutionError

DEFAULT_BASE_URL = "http://127.0.0.1:8210"
BASE_URL_ENV = "AGENTGATE_TRACE_SERVER_URL"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class TraceServerClient:
    """Read-only client for the Trace Server ``/api/v1`` query plane."""

    def __init__(self, base_url: str | None = None, *, opener=urlopen):
        self.base = (
            base_url if base_url is not None else os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL)
        ).rstrip("/")
        parsed = urlsplit(self.base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError(f"{BASE_URL_ENV} must be an absolute HTTP(S) origin")
        self._opener = opener

    def fetch_events(self, project_id: str, trace_id: str, *, timeout: float = 30) -> list[dict]:
        """Return SDK events for one trace: detail plus real LLM requests."""
        detail = self._get(
            f"/api/v1/projects/{quote(project_id, safe='')}/traces/{quote(trace_id, safe='')}",
            timeout=timeout,
        )
        llm = self._get(
            f"/api/v1/projects/{quote(project_id, safe='')}"
            f"/traces/{quote(trace_id, safe='')}/llm_requests",
            timeout=timeout,
        )
        if not isinstance(llm, dict) or not isinstance(llm.get("items"), list):
            raise TargetExecutionError("protocol_error", "trace server returned invalid LLM request list")
        return detail_to_events(detail, llm["items"])

    def _get(self, path: str, *, timeout: float = 30):
        request = Request(self.base + path, headers={"Accept": "application/json"})
        try:
            with self._opener(request, timeout=timeout) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise TargetExecutionError("protocol_error", "trace server response exceeds limit")
                return json.loads(data)
        except HTTPError as exc:
            raise TargetExecutionError(
                "unavailable" if exc.code >= 500 else "rejected",
                f"trace server HTTP {exc.code}",
            ) from None
        except (URLError, TimeoutError):
            raise TargetExecutionError("unavailable", "trace server request failed") from None


def detail_to_events(detail: dict, llm_requests: list[dict]) -> list[dict]:
    """Rebuild SDK-shaped events from Trace Server detail and LLM request items."""
    trace = detail.get("trace") if isinstance(detail, dict) else None
    spans = detail.get("spans") if isinstance(detail, dict) else None
    observations = detail.get("observations") if isinstance(detail, dict) else None
    if not isinstance(trace, dict) or not isinstance(spans, list) or not isinstance(observations, list):
        raise TargetExecutionError("protocol_error", "trace server detail has an invalid shape")
    if not isinstance(trace.get("id"), str) or not trace["id"].strip():
        raise TargetExecutionError("protocol_error", "trace server detail is missing its trace id")

    def text(value, field):
        if not isinstance(value, str) or not value.strip():
            raise TargetExecutionError("protocol_error", f"trace server trace is missing {field}")
        return value

    def opt_text(value):
        return value if isinstance(value, str) and value.strip() else None

    def opt_int(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    events: list[dict] = [{
        "event_type": "trace",
        "event_id": trace["id"],
        "project_id": text(trace.get("projectId"), "projectId"),
        "trace_id": trace["id"],
        "session_id": opt_text(trace.get("sessionId")),
        "name": text(trace.get("name"), "name"),
        "agent_name": opt_text(trace.get("agentName")),
        "input": trace.get("input"),
        "output": trace.get("output"),
        "status": text(trace.get("status"), "status"),
        "duration_ms": opt_int(trace.get("durationMs")),
        "started_at": opt_text(trace.get("startedAt")),
        "span_count": opt_int(trace.get("spanCount")),
        "tool_count": opt_int(trace.get("toolCount")),
        "prompt_tokens": opt_int(trace.get("promptTokens")),
        "completion_tokens": opt_int(trace.get("completionTokens")),
    }]
    for span in spans:
        if not isinstance(span, dict) or not isinstance(span.get("id"), str):
            raise TargetExecutionError("protocol_error", "trace server span is invalid")
        events.append({
            "event_type": "span",
            "event_id": opt_text(span.get("eventId")) or span["id"],
            "project_id": trace["projectId"],
            "trace_id": trace["id"],
            "span_id": span["id"],
            "parent_span_id": opt_text(span.get("parentSpanId")),
            "name": span.get("name"),
            "span_type": span.get("spanType"),
            "tool_name": span.get("toolName"),
            "input": span.get("input"),
            "output": span.get("output"),
            "model": span.get("model"),
            "status": span.get("status"),
            "duration_ms": opt_int(span.get("durationMs")),
            "started_at": opt_text(span.get("startedAt")),
            "error_info": span.get("errorInfo"),
        })
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(observation.get("spanId"), str):
            raise TargetExecutionError("protocol_error", "trace server observation is invalid")
        events.append({
            "event_type": "observation",
            "event_id": text(observation.get("id"), "id"),
            "project_id": trace["projectId"],
            "trace_id": trace["id"],
            "span_id": observation["spanId"],
            "model": observation.get("model"),
            "prompt_tokens": opt_int(observation.get("promptTokens")),
            "completion_tokens": opt_int(observation.get("completionTokens")),
            "input": observation.get("input"),
            "output": observation.get("output"),
        })
    for item in llm_requests:
        if not isinstance(item, dict) or not isinstance(item.get("spanId"), str):
            raise TargetExecutionError("protocol_error", "trace server LLM request is invalid")
        events.append({
            "event_type": "llm_request",
            "event_id": text(item.get("eventId"), "eventId"),
            "project_id": trace["projectId"],
            "trace_id": trace["id"],
            "span_id": item["spanId"],
            "model": item.get("model"),
            "input": item.get("input"),
            "output": item.get("output"),
            "started_at": opt_text(item.get("startedAt")),
            "status": item.get("status"),
        })
    return events
