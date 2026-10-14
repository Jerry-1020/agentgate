"""Bind in-bank turns and adapt observed facts to the existing Trace contract.

Raw SDK attributes stay intact. Skill loading is projected as a routing selection,
not a successful Skill execution or tool-ownership boundary. Adaptation diagnostics
are provenance only; existing evaluators retain their missing-value semantics.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from agentgate.domain import CaseTurn, FrozenJsonObject, Trace, TraceSpan, canonical_json
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
        root = next(e for e in events if e["event_type"] == "trace")
        source = root["inbank_source"]
    except (ValueError, TypeError, KeyError, StopIteration):
        raise TargetExecutionError("protocol_error", "inbank Trace Server evidence is invalid") from None
    spans = tuple(
        span.model_copy(update={"attributes": FrozenJsonObject({
            **span.attributes.to_dict(), "trace_sdk.replay": False,
            "inbank.evidence_mode": "trace_server", "inbank.trace_source": source,
            "inbank.request_id": request_id,
            "agentgate.turn.state": canonical_json({"execution_status": root["status"]}),
        })}) if span.operation_type == "turn" else span
        for span in trace.spans
    )
    return _adapt_turn_spans(trace.model_copy(update={"spans": spans}))


def _parse_tool_arguments(value: Any) -> FrozenJsonObject:
    """Accept bounded JSON-compatible literals only; never execute customer input."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate argument key")
            result[key] = item
        return result

    if isinstance(value, str):
        if len(value.encode("utf-8")) > 65536:
            raise ValueError("arguments too large")
        try:
            value = json.loads(value, object_pairs_hook=pairs)
        except (ValueError, RecursionError):
            try:
                tree = ast.parse(value, mode="eval")
                pending = [(tree, 0)]
                count = 0
                while pending:
                    node, depth = pending.pop()
                    count += 1
                    if depth > 32 or count > 10000 or not isinstance(
                        node, (ast.Expression, ast.Dict, ast.List, ast.Constant,
                               ast.Load, ast.UnaryOp, ast.USub, ast.UAdd)
                    ):
                        raise ValueError("unsupported argument literal")
                    if isinstance(node, ast.Dict):
                        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                        if (len(keys) != len(node.keys)
                                or any(not isinstance(k, str) for k in keys)
                                or len(set(keys)) != len(keys)):
                            raise ValueError("invalid argument keys")
                    pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
                value = ast.literal_eval(tree)
            except (SyntaxError, ValueError, TypeError, RecursionError, OverflowError):
                raise ValueError("arguments are not a bounded JSON object") from None
    if not isinstance(value, Mapping):
        raise TypeError("arguments must be an object")
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 32 or count > 10000:
            raise ValueError("arguments exceed structure limits")
        if isinstance(item, Mapping):
            if any(not isinstance(k, str) for k in item):
                raise ValueError("argument keys must be strings")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError("argument is not JSON compatible")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("argument number must be finite")
    return FrozenJsonObject(value)


def _tool_call_id(span: TraceSpan) -> str | None:
    output = span.attributes.get("trace_sdk.output")
    value = output.get("tool_call_id") if isinstance(output, Mapping) else None
    return value if isinstance(value, str) and value.strip() else None


def _tool_requests(trace: Trace) -> list[tuple[TraceSpan, int, Mapping]]:
    # Historical input messages and tool definitions are not new calls.
    calls = []
    for span in sorted(trace.spans, key=lambda item: item.sequence):
        output = span.attributes.get("trace_sdk.output")
        if span.operation_type != "llm" or not isinstance(output, Mapping):
            continue
        items = output.get("tool_calls")
        if isinstance(items, (list, tuple)):
            calls.extend((span, index, call) for index, call in enumerate(items)
                         if isinstance(call, Mapping))
    return calls


def _argument_object(raw: Any) -> FrozenJsonObject:
    return _parse_tool_arguments(raw.to_dict() if isinstance(raw, FrozenJsonObject) else raw)


def _resolve_tool_arguments(
    executed: Mapping[str, Any] | None, requested: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Keep execution values; fill missing fields from agreeing request evidence."""
    executed = executed if executed is not None else {}
    arguments: dict[str, Any] = {}
    conflict = False
    keys = set(executed).union(*(set(item) for item in requested))
    for key in sorted(keys):
        values = [item[key] for item in requested if key in item]
        objects = [value for value in values if isinstance(value, Mapping)]
        if key in executed:
            value = executed[key]
            if isinstance(value, Mapping):
                arguments[key], nested_conflict = _resolve_tool_arguments(value, objects)
                conflict |= nested_conflict or len(objects) != len(values)
            else:
                arguments[key] = value
                conflict |= any(canonical_json(item) != canonical_json(value) for item in values)
        elif len(objects) == len(values):
            arguments[key], nested_conflict = _resolve_tool_arguments(None, objects)
            conflict |= nested_conflict
        elif len({canonical_json(value) for value in values}) == 1:
            arguments[key] = values[0]
        else:
            # Lists are atomic: merging their elements would invent a new argument.
            conflict = True
    return arguments, conflict


def _enrich_tool_arguments(trace: Trace) -> Trace:
    calls = _tool_requests(trace)
    counts = Counter(_tool_call_id(s) for s in trace.spans if s.operation_type == "tool")
    spans = []
    for span in trace.spans:
        if span.operation_type != "tool":
            spans.append(span)
            continue
        attributes = span.attributes.to_dict()
        attributes.pop("arguments", None)
        call_id = _tool_call_id(span)
        matches = [(s, index, call) for s, index, call in calls
                   if call_id and call.get("id") == call_id]
        ambiguous = call_id is not None and (
            counts[call_id] > 1 or any(c.get("name") != span.name for _, _, c in matches)
        )
        candidates = []
        values = [(attributes.get("trace_sdk.input"), span.span_id, "trace_sdk.input")]
        if not ambiguous:
            values.extend((call.get("args"), s.span_id, f"trace_sdk.output.tool_calls.{index}.args")
                          for s, index, call in matches if call.get("name") == span.name)
        for raw, sid, path in values:
            try:
                candidates.append((_argument_object(raw), sid, path))
            except (TypeError, ValueError):
                continue
        # Ambiguous linkage prevents enrichment, not use of the tool's own input.
        diagnostic = "ambiguous_tool_call" if ambiguous else None
        if candidates:
            arguments, _, source_path = candidates[0]
            has_execution = source_path == "trace_sdk.input"
            resolved, conflict = _resolve_tool_arguments(
                arguments if has_execution else None,
                [value for value, _, _ in candidates[1 if has_execution else 0:]],
            )
            attributes["arguments"] = resolved
            attributes["inbank.argument_sources"] = [
                {"span_id": sid, "path": path} for _, sid, path in candidates
            ]
            if conflict:
                diagnostic = "conflicting_arguments"
        elif diagnostic is None:
            diagnostic = "unparseable_arguments"
        if call_id:
            attributes["tool_call_id"] = call_id
        if diagnostic:
            attributes["inbank.argument_diagnostic"] = diagnostic
            event = ("inbank_trace_argument_diagnostic" if "arguments" in attributes
                     else "inbank_trace_argument_unmapped")
            LOGGER.warning("%s case_id=%r span_id=%r reason=%s",
                           event, trace.case_id, span.span_id, diagnostic)
        spans.append(span.model_copy(update={"attributes": FrozenJsonObject(attributes)}))
    return trace.model_copy(update={"spans": tuple(spans)})


def _skill_catalog(trace: Trace) -> dict[str, set[str]]:
    catalog: dict[str, set[str]] = {}
    for span in trace.spans:
        value = span.attributes.get("trace_sdk.input")
        if span.operation_type != "chain" or not isinstance(value, Mapping):
            continue
        entries = value.get("skills_metadata")
        for item in entries if isinstance(entries, (list, tuple)) else ():
            if (isinstance(item, Mapping) and isinstance(item.get("path"), str)
                    and isinstance(item.get("name"), str) and item["name"].strip()):
                catalog.setdefault(item["path"], set()).add(item["name"])
    return catalog


def _project_skill_selection(trace: Trace) -> tuple[TraceSpan, ...]:
    catalog = _skill_catalog(trace)
    requests = _tool_requests(trace)
    groups: dict[str, list[tuple[TraceSpan, int, Mapping]]] = {}
    for span, index, call in requests:
        call_id = call.get("id")
        key = call_id if isinstance(call_id, str) and call_id.strip() else f"{span.span_id}:{index}"
        groups.setdefault(key, []).append((span, index, call))
    executions: dict[str, list[TraceSpan]] = {}
    for span in sorted(trace.spans, key=lambda item: item.sequence):
        if span.operation_type == "tool" and (call_id := _tool_call_id(span)):
            executions.setdefault(call_id, []).append(span)
    candidates = []
    diagnostics = []
    # Repeated call IDs do not hide an agreeing Skill path or merge tool executions.
    for key in dict.fromkeys((*groups, *executions)):
        group = groups.get(key, ())
        tools = executions.get(key, ())
        if not (any(call.get("name") == "read_file" for _, _, call in group)
                or any(tool.name == "read_file" for tool in tools)):
            continue
        if (any(call.get("name") != "read_file" for _, _, call in group)
                or any(tool.name != "read_file" for tool in tools)):
            diagnostics.append("ambiguous_skill_call")
            continue
        requested_paths = []
        unparseable = False
        for span, index, call in group:
            try:
                args = _argument_object(call.get("args"))
            except (TypeError, ValueError):
                unparseable = True
                continue
            if "file_path" in args:
                requested_paths.append((span, index, key, args["file_path"],
                                        f"trace_sdk.output.tool_calls.{index}.args.file_path"))
        # Missing or malformed copies do not contradict an explicit path.
        if len({canonical_json(item[3]) for item in requested_paths}) > 1:
            diagnostics.append("conflicting_skill_arguments")
            continue
        executed_paths = []
        for tool in tools:
            try:
                executed = _argument_object(tool.attributes.get("trace_sdk.input"))
            except (TypeError, ValueError):
                continue
            if "file_path" in executed:
                executed_paths.append((tool, 0, key, executed["file_path"], "trace_sdk.input.file_path"))
        paths = [*requested_paths, *executed_paths]
        if len({canonical_json(item[3]) for item in paths}) > 1:
            diagnostics.append("ambiguous_skill_call")
            continue
        if paths:
            candidates.append(paths[0])
        elif unparseable:
            diagnostics.append("unparseable_skill_arguments")
    for span in trace.spans:
        if span.operation_type != "tool" or span.name != "read_file":
            continue
        call_id = _tool_call_id(span)
        if call_id is not None:
            continue
        args = span.attributes.get("arguments")
        if not isinstance(args, Mapping):
            continue
        # Without a call ID, a request/result pair cannot safely be counted twice.
        if any(path == args.get("file_path") for _, _, _, path, _ in candidates):
            continue
        candidates.append((span, 0, span.span_id, args.get("file_path"),
                           "trace_sdk.input.file_path"))
    root = next(s for s in trace.spans if s.operation_type == "turn")
    projected: dict[str, list[TraceSpan]] = {}
    for span, index, key, path, field in candidates:
        if not isinstance(path, str) or not path.endswith("/SKILL.md"):
            continue
        parts = PurePosixPath(path).parts
        if ".." in parts or not path.startswith("/") or "__PHOTO_UNRECOVERED_" in path:
            diagnostics.append("invalid_skill_path")
            continue
        names = catalog.get(path)
        if names is None:
            match = re.fullmatch(r"/mnt/oneagent-skills/[^/]+/skills/([^/]+)/SKILL\.md", path)
            names = {match[1]} if match else set()
        if len(names) != 1:
            diagnostics.append("unresolved_skill_name")
            continue
        sid = hashlib.sha256(
            f"skill-selection:{trace.trace_id}:{trace.case_id}:{root.span_id}:{key}".encode()
        ).hexdigest()[:16]
        derived = TraceSpan(
            trace_id=trace.trace_id, span_id=sid, parent_span_id=root.span_id,
            name="inbank.skill_selection", operation_type="routing", sequence=0,
            started_at=span.started_at, ended_at=span.started_at, status="unset",
            attributes={
                "selected_skill": next(iter(names)),
                "agentgate.turn.id": root.attributes["agentgate.turn.id"],
                "inbank.skill_selection": {
                    "derived": True, "basis": "skill_load_request",
                    "source_span_id": span.span_id, "source_path": field,
                    "tool_call_id": key, "file_path": path,
                    "timing": "source_start_reference",
                },
            },
        )
        projected.setdefault(span.span_id, []).append(derived)
    spans = []
    for span in sorted(trace.spans, key=lambda item: item.sequence):
        if span.span_id == root.span_id and diagnostics:
            span = span.model_copy(update={"attributes": FrozenJsonObject({
                **span.attributes.to_dict(),
                "inbank.skill_selection_diagnostics": sorted(set(diagnostics)),
            })})
        for item in (*projected.get(span.span_id, ()), span):
            spans.append(item.model_copy(update={"sequence": len(spans)}))
    if diagnostics:
        LOGGER.warning("inbank_trace_skill_unmapped case_id=%r turn_id=%r reasons=%s",
                       trace.case_id, root.attributes["agentgate.turn.id"],
                       ",".join(sorted(set(diagnostics))))
    return tuple(spans)


def _adapt_turn_spans(trace: Trace) -> tuple[TraceSpan, ...]:
    spans = _project_skill_selection(_enrich_tool_arguments(trace))
    LOGGER.info(
        "inbank_trace_adapted case_id=%r tools=%d skill_selections=%d unmapped_arguments=%d",
        trace.case_id, sum(s.operation_type == "tool" for s in spans),
        sum(s.operation_type == "routing" for s in spans),
        sum(s.operation_type == "tool" and "arguments" not in s.attributes for s in spans),
    )
    return spans



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
    trace = Trace(
        trace_id=trace.trace_id,
        run_id=trace.run_id,
        case_id=trace.case_id,
        spans=tuple(spans),
        turn_outcomes=outcomes,
        final_output=outcomes[request.case.turns[-1].id]["output"],
        final_state={},
    )
    adapted_spans = []
    for turn in request.case.turns:
        for span in _adapt_turn_spans(trace.for_turn(turn.id)):
            adapted_spans.append(span.model_copy(update={"sequence": len(adapted_spans)}))
    return trace.model_copy(update={"spans": tuple(adapted_spans)})
