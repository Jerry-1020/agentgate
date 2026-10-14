"""Query the customer Trace Server and rebuild SDK events for normalization.

Evidence is requested from the central query plane, not runtime-local endpoints.
Standard and bank query contracts are explicitly selected by the caller. Responses
are camelCase projections, rebuilt into the SDK NDJSON shape validated by
``normalize_sdk_exports``; the caller owns the request-to-trace binding.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentgate.run.target_protocol import TargetExecutionError

DEFAULT_BASE_URL = "http://127.0.0.1:8210"
BASE_URL_ENV = "AGENTGATE_TRACE_SERVER_URL"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
INBANK_TRACE_SETTLE_SECONDS = 4.0
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InbankTraceSettings:
    """Shared wait limits for the in-bank adapters; callers own polling."""

    wait_seconds: float = 60.0
    poll_interval_seconds: float = 2.0
    settle_seconds: float = INBANK_TRACE_SETTLE_SECONDS
    stable_samples: int = 3

    def __post_init__(self) -> None:
        for name in ("wait_seconds", "poll_interval_seconds", "settle_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0
            ):
                raise ValueError(
                    f"AGENTGATE_INBANK_TRACE_{name.upper()} must be a finite positive number"
                )
        if (
            isinstance(self.stable_samples, bool) or not isinstance(self.stable_samples, int)
            or self.stable_samples <= 0
        ):
            raise ValueError("AGENTGATE_INBANK_TRACE_STABLE_SAMPLES must be a positive integer")


def load_inbank_trace_settings(
    environ: Mapping[str, str] | None = None,
) -> InbankTraceSettings:
    """Read the supplied environment at call time; startup owns loading .env."""
    values = os.environ if environ is None else environ
    overrides = {}
    for name, convert in (
        ("wait_seconds", float),
        ("poll_interval_seconds", float),
        ("settle_seconds", float),
        ("stable_samples", int),
    ):
        key = f"AGENTGATE_INBANK_TRACE_{name.upper()}"
        if key in values:
            try:
                overrides[name] = convert(values[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} has an invalid numeric value") from None
    return InbankTraceSettings(**overrides)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TraceServerClient:
    """Read-only query client; bank credentials belong to one task, not the process."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        mode: Literal["standard", "inbank"] = "standard",
        token: str | None = None,
        source_timezone: str | None = None,
        opener=urlopen,
    ):
        self.base = (
            base_url if base_url is not None else os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL)
        ).rstrip("/")
        parsed = urlsplit(self.base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or any(c.isspace() for c in self.base)):
            raise ValueError(f"{BASE_URL_ENV} must be an absolute HTTP(S) origin")
        if mode not in {"standard", "inbank"}:
            raise ValueError("unsupported trace server mode")
        if mode == "inbank" and not token:
            raise ValueError("inbank trace server requires an explicit task token")
        if token is not None and (
            not isinstance(token, str) or not token or any(c.isspace() for c in token)
        ):
            raise ValueError("trace server token must be a nonblank token without whitespace")
        self._mode = mode
        self._token = token
        if mode == "inbank" and source_timezone is None:
            source_timezone = "Asia/Shanghai"
        try:
            self._source_timezone = ZoneInfo(source_timezone) if source_timezone is not None else None
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("trace server source_timezone must be an IANA timezone") from None
        self._opener = build_opener(NoRedirect()).open if opener is urlopen else opener

    def fetch_events(
        self, project_id: str, trace_id: str, *, timeout: float = 30,
        customer_task_id: str | None = None,
    ) -> list[dict]:
        """Return real SDK-shaped events, without polling or synthetic evidence."""
        if self._mode == "inbank":
            if any(not isinstance(value, str) or not value.strip() for value in (project_id, trace_id)):
                raise ValueError("inbank trace query requires nonblank project_id and trace_id")
            if customer_task_id is not None and (
                not isinstance(customer_task_id, str) or not customer_task_id.strip()
            ):
                raise ValueError("inbank trace customer_task_id must be nonblank")
            payload = self._get(
                f"/web/agent_trace_otel/projects/{quote(project_id, safe='')}"
                f"/traces/{quote(trace_id, safe='')}",
                timeout=timeout,
            )
            return _inbank_events(
                payload, project_id, trace_id, source_timezone=self._source_timezone,
                customer_task_id=customer_task_id,
            )
        deadline = time.monotonic() + timeout
        detail = self._get(
            f"/api/v1/projects/{quote(project_id, safe='')}/traces/{quote(trace_id, safe='')}",
            timeout=timeout,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TargetExecutionError("unavailable", "trace server query deadline exceeded")
        llm = self._get(
            f"/api/v1/projects/{quote(project_id, safe='')}"
            f"/traces/{quote(trace_id, safe='')}/llm_requests",
            timeout=remaining,
        )
        if not isinstance(llm, dict) or not isinstance(llm.get("items"), list):
            raise TargetExecutionError("protocol_error", "trace server returned invalid LLM request list")
        return detail_to_events(detail, llm["items"])

    def _get(self, path: str, *, timeout: float = 30):
        token = self._token
        if token is None and self._mode == "standard":
            token = os.getenv("AGENTGATE_TRACE_SERVER_TOKEN")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base + path, headers=headers)
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
        except (URLError, TimeoutError, OSError):
            raise TargetExecutionError("unavailable", "trace server request failed") from None
        except (ValueError, UnicodeError):
            raise TargetExecutionError("protocol_error", "trace server returned invalid JSON") from None


def _inbank_events(
    payload: object,
    project_id: str,
    trace_id: str,
    *,
    source_timezone: ZoneInfo | None,
    customer_task_id: str | None = None,
) -> list[dict]:
    """Adapt the bank's detail response; no second LLM endpoint is assumed."""
    if not isinstance(payload, dict) or "code" not in payload:
        raise TargetExecutionError("protocol_error", "inbank trace response has an invalid shape")
    if payload["code"] != "0":
        if payload.get("message") == "trace not found":
            raise TargetExecutionError("unavailable", "inbank trace not found")
        raise TargetExecutionError("rejected", "inbank trace server rejected the query")
    detail = payload.get("data")
    trace = detail.get("trace") if isinstance(detail, dict) else None
    if not isinstance(trace, dict):
        raise TargetExecutionError("protocol_error", "inbank trace detail is missing its trace")
    allowed_projects = (project_id,) if customer_task_id is None else (project_id, customer_task_id)
    if trace.get("projectId") not in allowed_projects or trace.get("id") != trace_id:
        raise TargetExecutionError("protocol_error", "inbank trace project/trace binding mismatch")
    detail = {
        **detail,
        "trace": {**trace, "name": trace.get("name") or "inbank.trace"},
        "observations": detail.get("observations", []),
    }
    events = detail_to_events(detail, [])
    for child in (*detail["spans"], *detail["observations"]):
        if child.get("projectId", trace["projectId"]) != trace["projectId"]:
            raise TargetExecutionError("protocol_error", "inbank trace child belongs to another project")

    root = events[0]
    root["event_id"] = trace.get("eventId") or trace_id
    root["error_info"] = trace.get("errorInfo")
    root["inbank_source"] = {
        "query_project_id": project_id,
        "response_project_id": trace["projectId"],
        "raw_trace": trace,
        "derived_fields": {},
    }
    if not trace.get("name"):
        root["inbank_source"]["derived_fields"]["name"] = "display_label"
    if "spanCount" not in trace:
        root.pop("span_count")
    elif root["span_count"] is None:
        raise TargetExecutionError("protocol_error", "inbank trace spanCount is invalid")
    for event, source in zip(events, [trace, *detail["spans"]]):
        event["started_at"] = _inbank_timestamp(source.get("startedAt"), source_timezone)
        duration = source.get("durationMs")
        if duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration < 0
        ):
            raise TargetExecutionError("protocol_error", "inbank trace durationMs is invalid")
        event["duration_ms"] = duration
        if event["event_type"] != "span":
            continue
        kind = source.get("spanType")
        if not isinstance(kind, str) or not kind.strip():
            raise TargetExecutionError("protocol_error", "inbank trace spanType is missing")
        if kind not in {"chain", "llm", "tool", "retriever", "agent", "span"}:
            metadata = source.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise TargetExecutionError("protocol_error", "inbank trace span metadata is invalid")
            event["span_type"] = "span"
            event["metadata"] = {**(metadata or {}), "trace_server.span_type": kind}
    return events


def inbank_trace_snapshot(events: list[dict]) -> str:
    """Fingerprint response contents and log structural diagnostics only."""
    encoded = sorted(json.dumps(e, sort_keys=True, ensure_ascii=True) for e in events)
    fingerprint = hashlib.sha256("\n".join(encoded).encode()).hexdigest()
    root = next(e for e in events if e.get("event_type") == "trace")
    spans = [e for e in events if e.get("event_type") == "span"]
    LOGGER.info(
        "inbank_trace_snapshot source_trace_id=%r declared_spans=%r received_spans=%d "
        "tool_spans=%d span_ids=%r snapshot=%s",
        root.get("trace_id"), root.get("span_count"), len(spans),
        sum(e.get("span_type") == "tool" or bool(e.get("tool_name")) for e in spans),
        [e.get("span_id") for e in spans], fingerprint,
    )
    return fingerprint


def prepare_inbank_trace_events(
    events: list[dict], *, project_id: str, customer_task_id: str,
    trace_id: str, final_output: dict,
) -> list[dict] | None:
    """Bind real evidence and preserve parent links outside the returned span set."""
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        raise TargetExecutionError("protocol_error", "Trace Server evidence is invalid")
    roots = [e for e in events if e.get("event_type") == "trace"]
    if len(roots) != 1:
        raise TargetExecutionError("protocol_error", "Trace Server evidence is invalid")
    root = roots[0]
    response_project_id = root.get("project_id")
    if response_project_id not in (project_id, customer_task_id) or any(
        e.get("project_id") != response_project_id or e.get("trace_id") != trace_id
        for e in events
    ):
        raise TargetExecutionError("protocol_error", "inbank trace project/trace binding mismatch")
    spans = [e for e in events if e.get("event_type") == "span"]
    count = root.get("span_count")
    if root.get("status") in {"pending", "running"} or (
        root.get("status") == "success" and (
            not spans
            or (isinstance(count, int) and count > len(spans))
            or any(e.get("status") in {"pending", "running"} for e in spans)
            or any(e.get("duration_ms") is None or e.get("started_at") is None for e in spans)
        )
    ):
        return None

    # The customer's count may exclude context spans. Preserve every source span
    # and its original count; other positive-count discrepancies must keep waiting.
    context_count = sum(
        e.get("span_type") == "context"
        or (isinstance(e.get("metadata"), dict)
            and e["metadata"].get("trace_server.span_type") == "context")
        for e in spans
    )
    excludes_context = (
        isinstance(count, int) and count > 0 and context_count > 0
        and count == len(spans) - context_count
    )
    if isinstance(count, int) and count > 0 and count != len(spans) and not excludes_context:
        return None

    source = {**root.get("inbank_source", {
        "query_project_id": project_id, "response_project_id": response_project_id,
    })}
    derived = dict(source.get("derived_fields", {}))
    prepared_root = {**root}
    if root.get("status") == "success":
        if root.get("output") is None:
            prepared_root["output"] = final_output
            derived["output"] = "dialogue"
        if root.get("duration_ms") is None or root.get("started_at") is None:
            try:
                starts = [datetime.fromisoformat(e["started_at"]) for e in spans]
                durations = [e["duration_ms"] for e in spans]
                if any(t.tzinfo is None for t in starts) or any(
                    isinstance(d, bool) or not isinstance(d, (int, float))
                    or not math.isfinite(d) or d < 0 for d in durations
                ):
                    raise ValueError
                start = min(starts)
                end = max(t + timedelta(milliseconds=d) for t, d in zip(starts, durations))
            except (ValueError, TypeError, OverflowError):
                raise TargetExecutionError("protocol_error", "inbank trace span timing is invalid") from None
            prepared_root["started_at"] = start.isoformat()
            prepared_root["duration_ms"] = (end - start).total_seconds() * 1000
            derived["started_at"] = derived["duration_ms"] = "span_bounds"
        if count == 0:
            prepared_root["span_count"] = len(spans)
            derived["span_count"] = "received_spans"
        elif excludes_context:
            prepared_root["span_count"] = len(spans)
            derived["span_count"] = "received_spans_including_context"
    if response_project_id != project_id:
        derived["project_id"] = "current_pod_task_binding"
    span_ids = {e["span_id"] for e in spans if isinstance(e.get("span_id"), str)}
    unreturned_parents: set[str] = set()
    prepared_events = []
    for event in events:
        prepared = {**(prepared_root if event is root else event), "project_id": project_id}
        parent = event.get("parent_span_id")
        if event.get("event_type") == "span" and isinstance(parent, str) and parent not in span_ids:
            metadata = event.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise TargetExecutionError("protocol_error", "inbank trace span metadata is invalid")
            # This is an export boundary, not proof that the source span has no parent.
            prepared["parent_span_id"] = None
            prepared["metadata"] = {
                **(metadata or {}),
                "inbank.original_parent_span_id": parent,
                "inbank.parent_span_not_returned": True,
            }
            unreturned_parents.add(parent)
        prepared_events.append(prepared)
    if unreturned_parents:
        source["unreturned_parent_span_ids"] = sorted(unreturned_parents)
        derived["span_parent_links"] = "returned_span_boundary"
    source["derived_fields"] = derived
    next(e for e in prepared_events if e["event_type"] == "trace")["inbank_source"] = source
    return prepared_events


def _inbank_timestamp(value: object, source_timezone: ZoneInfo | None) -> str | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str):
            raise TypeError
        timestamp = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise TargetExecutionError("protocol_error", "inbank trace startedAt is invalid") from None
    if timestamp.tzinfo is None:
        if source_timezone is None:
            raise TargetExecutionError(
                "protocol_error", "inbank trace startedAt has no timezone; configure source_timezone",
            )
        timestamp = timestamp.replace(tzinfo=source_timezone)
    return timestamp.isoformat()


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
        if span.get("traceId", trace["id"]) != trace["id"]:
            raise TargetExecutionError("protocol_error", "trace server span belongs to another trace")
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
            "metadata": span.get("metadata"),
        })
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(observation.get("spanId"), str):
            raise TargetExecutionError("protocol_error", "trace server observation is invalid")
        if observation.get("traceId", trace["id"]) != trace["id"]:
            raise TargetExecutionError("protocol_error", "trace server observation belongs to another trace")
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
        if item.get("traceId", trace["id"]) != trace["id"]:
            raise TargetExecutionError("protocol_error", "trace server model request belongs to another trace")
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
