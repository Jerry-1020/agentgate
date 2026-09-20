"""Translate the customer's Trace SDK JSONL export, not OTLP, into evidence.

Each export is explicitly bound to one CaseTurn. No business state or routing
decision is inferred from chain names, tool names, or protocol success.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from agentgate.domain import Trace, TraceSpan
from agentgate.run.target_protocol import CaseExecutionRequest


MAX_EXPORT_BYTES = 10 * 1024 * 1024
MAX_EVENTS = 20000


def _id(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()[:16]


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Trace SDK requires nonblank {field}")
    return value


def _timing(event: dict) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(_text(event.get("started_at"), "started_at").replace("Z", "+00:00"))
    duration = event.get("duration_ms")
    if start.tzinfo is None:
        raise ValueError("Trace SDK timestamps must include timezone")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
        raise ValueError("Trace SDK duration_ms must be finite and nonnegative")
    return start, start + timedelta(milliseconds=duration)


def _status(event: dict) -> str:
    value = event.get("status")
    if value not in {"success", "error"}:
        raise ValueError("Trace SDK export must contain completed success/error events")
    return "ok" if value == "success" else "error"


def _decode(raw: bytes, project_id: str, source_trace_id: str) -> list[dict]:
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError("Trace SDK export exceeds 10 MiB")
    events: dict[tuple[str, str], dict] = {}
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        if number > MAX_EVENTS:
            raise ValueError("Trace SDK export exceeds event limit")
        try:
            event = json.loads(line)
        except ValueError:
            raise ValueError(f"invalid Trace SDK JSON at line {number}") from None
        if not isinstance(event, dict):
            raise ValueError("Trace SDK event must be an object")
        kind = event.get("event_type")
        if kind not in {"trace", "span", "session", "observation", "llm_request"}:
            raise ValueError("unsupported Trace SDK event_type")
        if event.get("project_id") != project_id or event.get("trace_id") != source_trace_id:
            raise ValueError("Trace SDK project/trace binding mismatch")
        key = (kind, _text(event.get("event_id"), "event_id"))
        if key in events and events[key] != event:
            raise ValueError("conflicting Trace SDK event_id")
        events[key] = event
    return list(events.values())


def normalize_sdk_exports(
    request: CaseExecutionRequest,
    exports: Mapping[str, tuple[str, bytes]],
    *,
    project_id: str,
) -> Trace:
    """Bind every turn to (external trace ID, exact JSONL bytes).

    The caller owns access control and the run/turn-to-source binding. This pure
    converter deliberately does not search by timestamps or fetch arbitrary paths.
    Raw evidence stays canonical; existing application redaction protects its views.
    """
    _text(project_id, "project_id")
    if set(exports) != {turn.id for turn in request.case.turns}:
        raise ValueError("exactly one Trace SDK export is required for every CaseTurn")
    source_ids = [source for source, _ in exports.values()]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("each CaseTurn must have a distinct source trace")
    trace_id = request.traceparent.split("-")[1]
    spans: list[TraceSpan] = []
    outcomes: dict = {}
    for turn in request.case.turns:
        source_id, raw = exports[turn.id]
        events = _decode(raw, project_id, _text(source_id, "trace_id"))
        roots = [e for e in events if e["event_type"] == "trace"]
        if len(roots) != 1:
            raise ValueError("exactly one completed Trace SDK trace event is required")
        root = roots[0]
        if _status(root) != "ok":
            raise ValueError("Trace SDK execution failed; cannot replay as completed")
        start, end = _timing(root)
        turn_span_id = _id("turn", turn.id)
        output = root.get("output")
        if output is None:
            raise ValueError("Trace SDK completed trace has no output")
        output = output if isinstance(output, dict) else {"output": output}
        outcomes[turn.id] = {"output": output, "state": {}}
        spans.append(TraceSpan(
            trace_id=trace_id, span_id=turn_span_id, name="trace_sdk.turn",
            operation_type="turn", sequence=len(spans), started_at=start,
            ended_at=end, status="ok", attributes={
                "agentgate.turn.id": turn.id,
                "agentgate.execution.id": request.execution_id,
                "trace_sdk.project_id": project_id,
                "trace_sdk.trace_id": source_id,
                "trace_sdk.session_id": root.get("session_id"),
                "trace_sdk.export_sha256": hashlib.sha256(raw).hexdigest(),
                "trace_sdk.input": root.get("input"),
                "trace_sdk.replay": True,
            },
        ))
        source_spans: dict[str, dict] = {}
        for event in events:
            if event["event_type"] != "span":
                continue
            sid = _text(event.get("span_id"), "span_id")
            if sid in source_spans:
                raise ValueError("duplicate Trace SDK span_id")
            source_spans[sid] = event
        if not source_spans:
            raise ValueError("Trace SDK export contains no spans")
        if "span_count" in root and root["span_count"] != len(source_spans):
            raise ValueError("Trace SDK span_count does not match exported evidence")
        # Missing parents and cycles mean incomplete evidence, not 'no tool call'.
        for sid in source_spans:
            seen: set[str] = set()
            parent = sid
            while parent is not None:
                if parent in seen or parent not in source_spans:
                    raise ValueError("Trace SDK span tree has a cycle or missing parent")
                seen.add(parent)
                parent = source_spans[parent].get("parent_span_id")
        attachments: dict[str, list[dict]] = {}
        for event in events:
            if event["event_type"] in {"observation", "llm_request"}:
                sid = event.get("span_id")
                if sid not in source_spans:
                    raise ValueError("Trace SDK observation references unknown span")
                attachments.setdefault(sid, []).append(event)
        ordered = sorted(source_spans.items(), key=lambda item: (_timing(item[1])[0], item[0]))
        for sid, event in ordered:
            started, ended = _timing(event)
            tool_name = event.get("tool_name")
            operation = _text(event.get("span_type"), "span_type")
            if operation not in {"chain", "llm", "tool", "retriever", "agent", "span"}:
                raise ValueError("unsupported Trace SDK span_type")
            name = _text(event.get("name"), "name")
            if tool_name is not None:
                name = _text(tool_name, "tool_name")
                operation = "tool"
            elif operation == "tool":
                raise ValueError("Trace SDK tool span is missing tool_name")
            attributes = {"trace_sdk.span_id": sid, "trace_sdk.trace_id": source_id,
                          "trace_sdk.name": event["name"], "trace_sdk.input": event.get("input"),
                          "trace_sdk.output": event.get("output"), "trace_sdk.metadata": event.get("metadata"),
                          "trace_sdk.model": event.get("model"), "trace_sdk.error": event.get("error_info")}
            if operation == "tool":
                arguments = event.get("input")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        pass
                if isinstance(arguments, dict):
                    attributes["arguments"] = arguments
            parent = event.get("parent_span_id")
            spans.append(TraceSpan(
                trace_id=trace_id, span_id=_id(source_id, sid),
                parent_span_id=_id(source_id, parent) if parent else turn_span_id,
                name=name, operation_type=operation, sequence=len(spans),
                started_at=started, ended_at=ended, status=_status(event),
                attributes=attributes, events=tuple(attachments.get(sid, [])),
            ))
    return Trace(trace_id=trace_id, run_id=request.run_id, case_id=request.case.id,
                 spans=tuple(spans), turn_outcomes=outcomes,
                 final_output=outcomes[request.case.turns[-1].id]["output"], final_state={})
