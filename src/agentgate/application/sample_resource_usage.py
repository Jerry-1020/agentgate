"""Resource summaries from persisted execution evidence, never Judge usage."""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from agentgate.domain import Trace


class SampleResourceUsage(BaseModel):
    case_id: str
    total_tokens: int | None = None
    duration_ms: float | None = None
    token_status: Literal["available", "partial", "unavailable"] = "unavailable"
    duration_source: Literal["case_span", "turn_bounds", "unavailable"] = "unavailable"


class SampleResourceUsageResponse(BaseModel):
    items: list[SampleResourceUsage]


def summarize_sample(
    case_id: str, trace: Trace | None, expected_turn_ids: Iterable[str] = ()
) -> SampleResourceUsage:
    expected_turn_ids = set(expected_turn_ids)
    result = SampleResourceUsage(case_id=case_id)
    if trace is None:
        return result
    # A source observation can be repeated on multiple normalized nodes.
    observations: dict[tuple, tuple[int | None, int | None]] = {}
    conflicts: set[tuple] = set()
    partial = False
    turns = [s for s in trace.spans if s.operation_type == "turn"]
    timed_turns = [s for s in turns if {"started_at", "ended_at"} <= s.model_fields_set]
    recorded_turns = {s.attributes.get("agentgate.turn.id") for s in turns}
    partial |= bool(set(expected_turn_ids) - recorded_turns)
    for span in trace.spans:
        attrs = span.attributes
        partial |= attrs.get("inbank.evidence_mode") == "output_only"
        found = False
        for event in span.events:
            if event.get("event_type") != "observation":
                continue
            found = True
            source = event.get("trace_id") or attrs.get("trace_sdk.trace_id") or trace.trace_id
            identity = event.get("event_id")
            values = (_count(event.get("prompt_tokens")), _count(event.get("completion_tokens")))
            if not isinstance(identity, str) or not identity:
                # Without an event identity, report a conservative partial subtotal.
                key = (str(source), span.span_id, *values)
                partial = True
            else:
                key = (str(source), identity)
            if key in observations and observations[key] != values:
                conflicts.add(key)
            observations[key] = values
        if span.operation_type == "llm" and not found:
            partial = True
    counts = []
    for key, values in observations.items():
        if key in conflicts:
            partial = True
            continue
        partial |= None in values
        counts.extend(v for v in values if v is not None)
    if counts:
        result.total_tokens = sum(counts)
        result.token_status = "partial" if partial else "available"

    cases = [
        s
        for s in trace.spans
        if s.operation_type == "case"
        and not s.attributes.get("platform.simulated")
        and {"started_at", "ended_at"} <= s.model_fields_set
    ]
    if len(cases) == 1:
        result.duration_ms = (cases[0].ended_at - cases[0].started_at).total_seconds() * 1000
        result.duration_source = "case_span"
    elif (
        timed_turns and len(timed_turns) == len(turns) and not (expected_turn_ids - recorded_turns)
    ):
        result.duration_ms = (
            max(s.ended_at for s in timed_turns) - min(s.started_at for s in timed_turns)
        ).total_seconds() * 1000
        result.duration_source = "turn_bounds"
    return result


def _count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None
