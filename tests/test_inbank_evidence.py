"""Complete evidence is mandatory; no invented spans or output-only fallback."""

from unittest.mock import Mock

import pytest
from test_target_execution_factory import target_snapshot

from agentgate.domain import Case, CaseTurn
from agentgate.integrations.observability.trace_server import detail_to_events
from agentgate.integrations.targets.bank_protocol import BankChatResult
from agentgate.integrations.targets.inbank.evidence import (
    assemble_evidence,
    configured_trace_source,
    fetch_turn_evidence,
)
from agentgate.run.target_protocol import CaseExecutionRequest, TargetExecutionError


def trace_detail(source, session, text):
    start = "2026-10-08T00:00:00Z"
    root = {"id": source, "projectId": "inbank-tests", "sessionId": session,
            "name": "agent", "agentName": "test-pod", "input": {"txt": text},
            "output": "answer", "status": "success", "spanCount": 4,
            "durationMs": 5, "startedAt": start}
    spans = []
    for sid, parent, kind, name in [("root", None, "agent", "agent"),
                                   ("skill", "root", "chain", "skill.review"),
                                   ("llm", "skill", "llm", "model"),
                                   ("tool", "skill", "tool", "credit_inquiry")]:
        spans.append({"id": sid, "traceId": source, "eventId": sid,
                      "parentSpanId": parent, "spanType": kind, "name": name,
                      "toolName": name if kind == "tool" else None,
                      "status": "success", "durationMs": 1, "startedAt": start,
                      "input": {"txt": text}, "output": "answer"})
    return {"trace": root, "spans": spans, "observations": []}


def chat(reference=None):
    return BankChatResult(
        "answer",
        "request",
        None,
        ({"project_id": "inbank-tests", "trace_id": "source"} if reference is None else reference,),
        {},
        (),
    )


def fetch(client, result=None):
    return fetch_turn_evidence(
        client,
        "inbank-tests",
        result or chat(),
        session_id="session",
        request_id="request",
        input_field="txt",
        turn_input={"txt": "hello"},
        agent_name="test-pod",
        timeout=2,
    )


@pytest.fixture
def source():
    return Mock(
        fetch_events=Mock(
            return_value=detail_to_events(trace_detail("source", "session", "hello"), [])
        )
    )


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"project_id": "other", "trace_id": "source"},
        {"project_id": "inbank-tests", "trace_id": "../source"},
        {"project_id": "inbank-tests", "trace_id": "source", "simulated": True},
        {"project_id": "inbank-tests", "trace_id": "source", "request_id": "different"},
        {"project_id": "inbank-tests", "trace_id": "source", "session_id": "different"},
    ],
)
def test_reference_mismatch_never_queries_server(source, reference):
    result = (
        chat(reference)
        if reference is not None
        else BankChatResult("answer", "request", None, (), {}, ())
    )
    with pytest.raises(TargetExecutionError):
        fetch(source, result)
    source.fetch_events.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "foreign"),
        ("trace_id", "foreign"),
        ("session_id", "foreign"),
        ("agent_name", "foreign"),
        ("input", "wrong"),
        ("output", "wrong"),
        ("status", "running"),
        ("span_count", None),
        ("span_count", 5),
    ],
)
def test_remote_root_must_match_turn(source, field, value):
    source.fetch_events.return_value[0][field] = value
    with pytest.raises(TargetExecutionError):
        fetch(source)


def execution_request(two_turns=False):
    turns = [CaseTurn(id="first", input={"txt": "hello"})]
    if two_turns:
        turns.append(CaseTurn(id="second", input={"txt": "hello"}))
    return CaseExecutionRequest(
        "execution",
        "run",
        Case(id="case", name="case", turns=tuple(turns)),
        target_snapshot("inbank_chatabc"),
        30,
        "00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    )


def test_normalized_evidence_preserves_tree_and_protocol_output(source):
    evidence = fetch(source)
    output = {"output": "answer", "intent_code": "review", "slots": {"amount": 42}}
    trace = assemble_evidence(
        execution_request(),
        "inbank-tests",
        {"first": evidence},
        {"first": {"input": {"txt": "hello"}, "output": output, "state": {}}},
    )
    assert trace.final_output.to_dict() == output
    skill = next(s for s in trace.spans if s.name == "skill.review")
    tool = next(s for s in trace.spans if s.name == "credit_inquiry")
    assert tool.parent_span_id == skill.span_id
    assert tool.operation_type == "tool"
    assert all(s.attributes["trace_sdk.replay"] is False for s in trace.spans)


def test_case_input_alias_is_compared_to_actual_wire_txt(source):
    result = fetch_turn_evidence(
        source,
        "inbank-tests",
        chat(),
        session_id="session",
        request_id="request",
        input_field="question",
        turn_input={"question": "hello"},
        agent_name="test-pod",
        timeout=2,
    )
    assert result.source_trace_id == "source"


@pytest.mark.parametrize("damage", ["duplicate", "orphan", "cycle", "missing_turn"])
def test_partial_or_reused_evidence_is_rejected(source, damage):
    events = source.fetch_events.return_value
    if damage == "orphan":
        events[1]["parent_span_id"] = "missing"
    if damage == "cycle":
        events[1]["parent_span_id"] = events[1]["span_id"]
    item = fetch(source)
    evidence = {"first": item}
    if damage == "duplicate":
        evidence["second"] = item
    with pytest.raises(TargetExecutionError, match="incomplete or invalid"):
        assemble_evidence(
            execution_request(damage in {"duplicate", "missing_turn"}), "inbank-tests", evidence, {}
        )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://user:secret@trace.example",
        "https://trace.example/arbitrary",
        "ftp://trace.example",
    ],
)
def test_explicit_trace_origin_required(monkeypatch, url):
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_URL", url)
    monkeypatch.setenv("AGENTGATE_INBANK_TRACE_PROJECT_ID", "inbank-tests")
    with pytest.raises(TargetExecutionError) as error:
        configured_trace_source()
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "required,expected", [("credit_inquiry", "pass"), ("approve_loan", "fail")]
)
def test_tool_checks_use_retrieved_execution_evidence(source, required, expected):
    from test_rule_tool_use import evaluator_spec, resolve_unexpected

    from agentgate.domain import ToolCallExpectation
    from agentgate.evaluator.rule.tool_use import RequiredToolEvaluator

    request = execution_request()
    trace = assemble_evidence(
        request,
        "inbank-tests",
        {"first": fetch(source)},
        {"first": {"input": {"txt": "hello"}, "output": {"output": "answer"}, "state": {}}},
    )
    turn = CaseTurn(
        id="first", input={"txt": "hello"}, expectations=(ToolCallExpectation(tool=required),)
    )
    evaluation = RequiredToolEvaluator().evaluate(
        evaluator_spec("required_tool"), turn, trace, resolve_unexpected
    )
    assert evaluation.checks[0].outcome == expected
    if expected == "pass":
        tool = next(s for s in trace.spans if s.name == required)
        assert tool.span_id in evaluation.checks[0].span_ids
