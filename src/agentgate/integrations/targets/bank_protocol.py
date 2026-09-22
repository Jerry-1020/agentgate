"""Strict wire translation for the customer factory's documented chat protocols.

No network, resource creation, retries, database writes, or business-state guesses.
The factory/runtime composition layer supplies HTTP transport and authorization.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from agentgate.run.target_protocol import TargetExecutionError

BankProtocol = Literal["base", "workflow", "cloudshrimp"]
SSEFormat = Literal["event_lines", "json_envelope"]


@dataclass(frozen=True)
class BankChatResult:
    output: str
    request_id: str
    intent_code: str | None
    trace_payloads: tuple[Any, ...]
    slots: dict[str, Any]
    workflow_calls: tuple[Any, ...]


def build_chatabc_payload(data: dict, *, request_id: str, timestamp_ms: int) -> dict:
    if not request_id.strip() or timestamp_ms < 0:
        raise ValueError("request ID and nonnegative timestamp are required")
    return {"appId": "BDC201704_01", "trCode": "AISPNLPCHATBOT", "trVersion": "1",
            "timestamp": timestamp_ms, "requestId": request_id, "data": data}


def build_cloudshrimp_payload(*, session_id: str, customer_id: str, text: str,
                             guardrail: Literal["ON_BLOCK", "ON_PASS"],
                             config_variables: list | None = None) -> dict:
    if not all(isinstance(v, str) and v.strip() for v in (session_id, customer_id, text)):
        raise ValueError("session, approved test customer identity and input are required")
    if guardrail not in {"ON_BLOCK", "ON_PASS"}:
        raise ValueError("explicit enabled guardrail mode is required")
    return {"sessionId": session_id, "custID": customer_id, "txt": text,
            "executionMode": "execute", "stream": True, "debugTrace": True,
            "safeGuardrail": guardrail, "config_variables": config_variables or [],
            "appHistory": []}


def parse_bank_sse(
    lines: Iterable[str],
    *,
    protocol: BankProtocol,
    wire_format: SSEFormat,
    request_id: str,
    session_id: str | None = None,
) -> BankChatResult:
    """Require a complete framed response; explicitly select documented encoding.

    Use the request ID sent by the caller; a returned start ID must agree. Error
    details are intentionally not exposed because the server can echo credentials.
    """
    if protocol not in {"base", "workflow", "cloudshrimp"} or wire_format not in {
        "event_lines",
        "json_envelope",
    }:
        raise ValueError("unsupported bank protocol or SSE format")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required")
    event_name = ""
    data_lines: list[str] = []
    messages: list[dict] = []
    traces: list[Any] = []
    done = False
    start_seen = False
    size = 0

    def consume() -> None:
        nonlocal done, start_seen
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        if raw == "[DONE]":
            payload = "[DONE]"
        else:
            try:
                payload = json.loads(raw)
            except ValueError:
                raise TargetExecutionError("protocol_error", "invalid SSE JSON") from None
        name = event_name
        if wire_format == "json_envelope":
            if not isinstance(payload, dict) or set(("event", "data")) - payload.keys():
                raise TargetExecutionError("protocol_error", "expected SSE event/data envelope")
            envelope_name = payload["event"]
            if not isinstance(envelope_name, str):
                raise TargetExecutionError("protocol_error", "SSE event name must be text")
            if name and name.strip().lower() != envelope_name.strip().lower():
                raise TargetExecutionError("protocol_error", "conflicting SSE event names")
            name, payload = envelope_name, payload["data"]
        if not isinstance(name, str) or not name.strip():
            raise TargetExecutionError("protocol_error", "SSE event name is missing")
        name = name.strip().lower()
        if done:
            raise TargetExecutionError("protocol_error", "SSE data after terminal event")
        if name in {"error", "failed"}:
            raise TargetExecutionError("rejected", "customer chat returned an error event")
        if name == "done":
            done = True
        elif name == "message":
            if not isinstance(payload, dict):
                raise TargetExecutionError("protocol_error", "SSE message must be an object")
            messages.append(payload)
        elif name == "trace":
            traces.append(payload)
        elif name == "start":
            if start_seen or not isinstance(payload, dict):
                raise TargetExecutionError(
                    "protocol_error", "customer returned invalid start events"
                )
            start_seen = True
            returned_request_id = payload.get(
                "request_id", payload.get("requestId", request_id)
            )
            if returned_request_id != request_id:
                raise TargetExecutionError("protocol_error", "customer request ID mismatch")
            returned_session_id = payload.get("session_id", payload.get("sessionId"))
            if (
                session_id is not None
                and returned_session_id is not None
                and returned_session_id != session_id
            ):
                raise TargetExecutionError(
                    "protocol_error", "customer session ID mismatch"
                )
        else:
            # Customer streams may add non-terminal progress and node events.
            return

    for line in lines:
        size += len(line.encode("utf-8"))
        if size > 10 * 1024 * 1024:
            raise TargetExecutionError("protocol_error", "SSE response exceeds 10 MiB")
        line = line.rstrip("\r\n")
        if not line:
            consume()
            event_name, data_lines = "", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)
    if data_lines or not messages or (protocol != "cloudshrimp" and not done):
        raise TargetExecutionError("protocol_error", "incomplete SSE response")
    last = messages[-1]
    intent = None
    slots: dict[str, Any] = {}
    workflow_calls: list[Any] = []
    if protocol == "workflow":
        endings = [
            message
            for message in messages
            if message.get("node_id") == "end"
            or (
                isinstance(message.get("additional_kwargs"), dict)
                and message["additional_kwargs"].get("node_id") == "end"
            )
        ]
        if len(endings) != 1:
            raise TargetExecutionError("protocol_error", "workflow requires one end node")
        additional = endings[0].get("additional_kwargs")
        output = additional.get("node_output") if isinstance(additional, dict) else None
        if isinstance(output, dict):
            output = output.get("output")
    elif protocol == "cloudshrimp":
        if last.get("status") != "completed":
            raise TargetExecutionError("protocol_error", "cloudshrimp message did not complete")
        output = last.get("output")
        if not isinstance(output, str) or not output.strip():
            output = last.get("message")
        intent = last.get("intent_code")
        if intent is not None and not isinstance(intent, str):
            raise TargetExecutionError("protocol_error", "intent_code must be text")
        raw_slots = last.get("slots", {})
        raw_workflow_calls = last.get("workflow_calls", [])
        if not isinstance(raw_slots, dict) or not isinstance(raw_workflow_calls, list):
            raise TargetExecutionError(
                "protocol_error", "cloudshrimp message metadata has invalid types"
            )
        slots = raw_slots
        workflow_calls = raw_workflow_calls
    else:
        output = last.get("content")
    if not isinstance(output, str) or not output.strip():
        raise TargetExecutionError("protocol_error", "completed chat has no text output")
    return BankChatResult(
        output,
        request_id,
        intent,
        tuple(traces),
        slots,
        tuple(workflow_calls),
    )
