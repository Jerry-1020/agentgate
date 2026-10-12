"""Bind each in-bank conversation turn to independently retrieved SDK evidence."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from agentgate.domain import CaseTurn, FrozenJsonObject, Trace, TraceSpan
from agentgate.integrations.observability.trace_sdk import normalize_sdk_exports
from agentgate.integrations.observability.trace_server import TraceServerClient
from agentgate.integrations.targets.bank_protocol import BankChatResult
from agentgate.run.target_protocol import CaseExecutionRequest, TargetExecutionError

_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
LOGGER = logging.getLogger(__name__)


def normalize_turn_evidence(
    request: CaseExecutionRequest, turn: CaseTurn, *, project_id: str,
    request_id: str, events: list[dict],
) -> tuple[TraceSpan, ...]:
    """Validate one turn independently so a missing trace cannot erase other turns."""
    try:
        raw = "\n".join(
            json.dumps(event, ensure_ascii=False, allow_nan=False) for event in events
        ).encode("utf-8")
        trace = normalize_sdk_exports(
            replace(request, case=request.case.model_copy(update={"turns": (turn,)})),
            {turn.id: (request_id, raw)}, project_id=project_id,
        )
        source = next(e["inbank_source"] for e in events if e["event_type"] == "trace")
    except (ValueError, TypeError, KeyError, StopIteration):
        raise TargetExecutionError("protocol_error", "inbank Trace Server evidence is invalid") from None
    return tuple(
        span.model_copy(update={"attributes": FrozenJsonObject({
            **span.attributes.to_dict(), "trace_sdk.replay": False,
            "inbank.evidence_mode": "trace_server", "inbank.trace_source": source,
            "inbank.request_id": request_id,
        })}) if span.operation_type == "turn" else span
        for span in trace.spans
    )


def output_only_turn_span(
    request: CaseExecutionRequest, turn: CaseTurn, *, adapter: str,
    project_id: str, request_id: str, started_at: datetime, ended_at: datetime,
    error: TargetExecutionError,
) -> TraceSpan:
    """Record a successful conversation without inventing internal execution spans."""
    if error.code in {"invalid_request", "cancelled"}:
        raise error
    LOGGER.warning(
        "inbank_trace_fallback adapter=%s run_id=%r case_id=%r turn_id=%r "
        "project_id=%r request_id=%r evidence_mode=output_only reason=%s detail=%r "
        "action=evaluate_output_only",
        adapter, request.run_id, request.case.id, turn.id, project_id, request_id,
        error.code, error.message,
    )
    return TraceSpan(
        trace_id=request.traceparent.split("-")[1], span_id=uuid4().hex[:16],
        name=f"inbank.{adapter}.turn", operation_type="turn", sequence=0,
        started_at=started_at, ended_at=ended_at, status="ok",
        attributes={
            "agentgate.turn.id": turn.id, "agentgate.execution.id": request.execution_id,
            "inbank.evidence_mode": "output_only", "inbank.request_id": request_id,
            "inbank.trace_query_project_id": project_id,
            "inbank.trace_fallback_reason": error.code,
            "inbank.trace_fallback_detail": error.message,
        },
    )


@dataclass(frozen=True)
class TurnEvidence:
    """Retrieved bytes and their verified request/session binding."""

    source_trace_id: str
    raw: bytes
    session_id: str
    request_id: str


def configured_trace_source() -> tuple[str, TraceServerClient]:
    project = os.getenv("AGENTGATE_INBANK_TRACE_PROJECT_ID", "").strip()
    origin = os.getenv("AGENTGATE_TRACE_SERVER_URL", "").strip()
    if not _IDENTITY.fullmatch(project) or not origin:
        raise TargetExecutionError(
            "invalid_request", "in-bank evidence requires Trace Server URL and project ID"
        )
    try:
        return project, TraceServerClient(origin)
    except ValueError:
        raise TargetExecutionError(
            "invalid_request", "invalid in-bank Trace Server configuration"
        ) from None


def fetch_turn_evidence(
    client: TraceServerClient,
    project: str,
    chat: BankChatResult,
    *,
    session_id: str,
    request_id: str,
    input_field: str,
    turn_input: dict,
    agent_name: str,
    timeout: float,
) -> TurnEvidence:
    if len(chat.trace_payloads) != 1:
        raise TargetExecutionError(
            "protocol_error", "each in-bank turn requires exactly one Trace reference"
        )
    reference = chat.trace_payloads[0]
    if not isinstance(reference, dict):
        raise TargetExecutionError("protocol_error", "invalid in-bank Trace reference")
    source_id = reference.get("trace_id")
    if (
        reference.get("project_id") != project
        or not isinstance(source_id, str)
        or not _IDENTITY.fullmatch(source_id)
        or reference.get("simulated") is True
        or reference.get("session_id", session_id) != session_id
        or reference.get("request_id", request_id) != request_id
    ):
        raise TargetExecutionError("protocol_error", "in-bank Trace reference identity mismatch")
    events = client.fetch_events(project, source_id, timeout=timeout)
    roots = [e for e in events if e.get("event_type") == "trace"]
    if len(roots) != 1:
        raise TargetExecutionError("protocol_error", "in-bank Trace requires one completed root")
    root = roots[0]
    recorded_input = root.get("input")
    # Both wire protocols send txt even when the Case uses a configured input alias.
    recorded_text = (
        recorded_input.get("txt") if isinstance(recorded_input, dict) else recorded_input
    )
    output = root.get("output")
    recorded_output = output.get("output") if isinstance(output, dict) else output
    if (
        any(e.get("project_id") != project or e.get("trace_id") != source_id for e in events)
        or root.get("session_id") != session_id
        or root.get("status") != "success"
        or root.get("agent_name") != agent_name
        or recorded_text != turn_input[input_field]
        or recorded_output != chat.output
        or type(root.get("span_count")) is not int
        or root["span_count"] < 1
        or root["span_count"] != sum(e.get("event_type") == "span" for e in events)
    ):
        raise TargetExecutionError(
            "protocol_error", "in-bank Trace does not match the completed turn"
        )
    try:
        raw = (
            "\n".join(json.dumps(e, ensure_ascii=False, allow_nan=False) for e in events) + "\n"
        ).encode()
    except (TypeError, ValueError):
        raise TargetExecutionError("protocol_error", "invalid in-bank Trace JSON") from None
    return TurnEvidence(source_id, raw, session_id, request_id)


def assemble_evidence(
    request: CaseExecutionRequest,
    project: str,
    evidence: dict[str, TurnEvidence],
    outcomes: dict[str, dict],
) -> Trace:
    try:
        trace = normalize_sdk_exports(
            request,
            {turn: (item.source_trace_id, item.raw) for turn, item in evidence.items()},
            project_id=project,
        )
    except (ValueError, TypeError, KeyError):
        raise TargetExecutionError(
            "protocol_error", "in-bank Trace evidence is incomplete or invalid"
        ) from None
    by_source = {item.source_trace_id: item for item in evidence.values()}
    spans = []
    for span in trace.spans:
        item = by_source[span.attributes["trace_sdk.trace_id"]]
        spans.append(
            span.model_copy(
                update={
                    "attributes": FrozenJsonObject(
                        {
                            **span.attributes.to_dict(),
                            "inbank.evidence_mode": "trace_server",
                            "inbank.session_id": item.session_id,
                            "inbank.request_id": item.request_id,
                            "trace_sdk.replay": False,
                        }
                    )
                }
            )
        )
    # Preserve protocol-specific outputs (intent/slots) without fabricating execution spans.
    return Trace(
        trace_id=trace.trace_id,
        run_id=trace.run_id,
        case_id=trace.case_id,
        spans=tuple(spans),
        turn_outcomes=outcomes,
        final_output=outcomes[request.case.turns[-1].id]["output"],
        final_state={},
    )
