import json

import pytest

from agentgate.integrations.targets.bank_protocol import (
    build_chatabc_payload, build_cloudshrimp_payload, parse_bank_sse,
)
from agentgate.run.target_protocol import TargetExecutionError


def stream(events, envelope=False):
    for name, payload in events:
        if envelope:
            yield "data: " + json.dumps({"event": name, "data": payload})
        else:
            yield "event: " + name
            yield "data: " + (payload if payload == "[DONE]" else json.dumps(payload))
        yield ""


@pytest.mark.parametrize("envelope", [True, False])
@pytest.mark.parametrize("protocol,payload", [
    ("base", {"content": "answer"}),
    ("workflow", {"node_id": "end", "additional_kwargs": {"node_output": {"output": "answer"}}}),
    ("cloudshrimp", {"status": "completed", "output": "answer", "intent_code": "loan"}),
])
def test_documented_responses(protocol, payload, envelope):
    result = parse_bank_sse(stream([("message", payload), ("done", "[DONE]")], envelope),
        protocol=protocol, wire_format="json_envelope" if envelope else "event_lines", request_id="request")
    assert result.output == "answer"
    assert result.request_id == "request"


def test_workflow_accepts_customer_auxiliary_events_and_nested_end_node():
    result = parse_bank_sse(
        stream([
            ("chat_started", {
                "chat_id": "chat-1",
                "agent_id": "workflow-agent",
                "agent_version": "1",
            }),
            ("chunk", {
                "content": "",
                "additional_kwargs": {
                    "node_id": "intentClassification",
                    "chunk_position": "last",
                },
            }),
            ("node_started", {
                "node_id": "intentClassification",
                "node_title": "意图识别",
            }),
            ("message", {
                "content": "",
                "additional_kwargs": {
                    "node_id": "intentClassification",
                    "node_output": {"intentID": "0"},
                },
            }),
            ("message", {
                "content": "",
                "additional_kwargs": {
                    "node_id": "end",
                    "node_output": {"output": "customer answer"},
                },
            }),
            ("done", {"status": "success", "rescode": "FAIAG0000"}),
        ]),
        protocol="workflow",
        wire_format="event_lines",
        request_id="request",
    )

    assert result.output == "customer answer"


def test_cloudshrimp_accepts_auxiliary_events_without_lifecycle_events():
    result = parse_bank_sse(
        stream([
            ("chat_started", {"chat_id": "chat-1"}),
            ("node_started", {"node_id": "intentClassification"}),
            ("chunk", {"content": "partial"}),
            ("message", {
                "status": "completed",
                "output": "customer answer",
                "intent_code": "loan",
                "slots": {"amount": 1000},
                "workflow_calls": [{"node_id": "end"}],
            }),
        ]),
        protocol="cloudshrimp",
        wire_format="event_lines",
        request_id="request",
        session_id="session",
    )

    assert result.output == "customer answer"
    assert result.intent_code == "loan"
    assert result.slots == {"amount": 1000}
    assert result.workflow_calls == ({"node_id": "end"},)


def test_cloudshrimp_rejects_failure_and_mismatched_session_events():
    with pytest.raises(TargetExecutionError, match="error event"):
        parse_bank_sse(
            stream([("failed", {"message": "customer failed"})]),
            protocol="cloudshrimp",
            wire_format="event_lines",
            request_id="request",
            session_id="session",
        )

    with pytest.raises(TargetExecutionError, match="session ID mismatch"):
        parse_bank_sse(
            stream([
                ("start", {"request_id": "request", "session_id": "wrong"}),
                ("message", {"status": "completed", "output": "answer"}),
            ]),
            protocol="cloudshrimp",
            wire_format="event_lines",
            request_id="request",
            session_id="session",
        )


@pytest.mark.parametrize("frames", [[], [("message", {"content": "answer"})],
    [("done", "[DONE]")], [("error", {"message": "password=private"}), ("done", "[DONE]")],
    [("message", {"content": ""}), ("done", "[DONE]")],
    [("start", {"request_id": "wrong"}), ("done", "[DONE]")],
    [("message", {"content": "answer"}), ("done", "[DONE]"), ("error", {})]])
def test_errors_are_not_success_and_do_not_leak_payload(frames):
    with pytest.raises(TargetExecutionError) as error:
        parse_bank_sse(stream(frames), protocol="base", wire_format="event_lines", request_id="request")
    assert "private" not in str(error.value)


def test_request_contract_does_not_rewrite_customer_identity_or_disable_guardrail():
    payload = build_cloudshrimp_payload(session_id="isolated-session", customer_id="approved-test-id",
                                        text="hello", guardrail="ON_BLOCK")
    assert payload["custID"] == "approved-test-id"
    assert payload["safeGuardrail"] == "ON_BLOCK"
    with pytest.raises(ValueError):
        build_cloudshrimp_payload(session_id="s", customer_id="c", text="x", guardrail="OFF")
    assert build_chatabc_payload({"txt": "hello"}, request_id="r", timestamp_ms=1)["requestId"] == "r"
