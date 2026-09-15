import json
import math

import pytest

from agentgate.optimizer.root_cause_contract import (
    MAX_EXPLANATION_CHARS,
    MAX_REFERENCES_PER_FIELD,
    MAX_RESPONSE_CHARS,
    RootCauseContractError,
    parse_root_cause_response,
)


def response(**overrides: object) -> str:
    payload: dict[str, object] = {
        "cluster_id": "cluster-1",
        "category": "routing_confusion",
        "title": "Overlapping Skill descriptions",
        "explanation": "The route differs from the expected Skill.",
        "confidence": 0.82,
        "result_ids": ["result-2", "result-1"],
        "span_ids": ["b" * 16],
        "static_finding_ids": ["finding-1"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def parse(text: str):
    return parse_root_cause_response(
        text,
        expected_cluster_id="cluster-1",
        allowed_result_ids={"result-1", "result-2"},
        allowed_span_ids={"b" * 16},
        allowed_static_finding_ids={"finding-1"},
    )


def test_parses_and_normalizes_valid_response() -> None:
    parsed = parse(response())

    assert parsed.cluster_id == "cluster-1"
    assert parsed.category == "routing_confusion"
    assert parsed.title == "Overlapping Skill descriptions"
    assert parsed.confidence == 0.82
    assert parsed.result_ids == ("result-1", "result-2")
    assert parsed.span_ids == ("b" * 16,)
    assert parsed.static_finding_ids == ("finding-1",)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not-json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ("x" * (MAX_RESPONSE_CHARS + 1), "exceeds"),
    ],
)
def test_rejects_invalid_response_envelopes(text: str, message: str) -> None:
    with pytest.raises(RootCauseContractError, match=message):
        parse(text)


def test_requires_exact_response_fields() -> None:
    with pytest.raises(RootCauseContractError, match="missing fields: title"):
        parse(response(title=None).replace(', "title": null', ""))

    with pytest.raises(RootCauseContractError, match="unknown fields: verdict"):
        parse(response(verdict="review"))


@pytest.mark.parametrize("confidence", [True, "high", -0.1, 1.1, math.inf])
def test_rejects_invalid_confidence(confidence: object) -> None:
    with pytest.raises(RootCauseContractError, match="confidence"):
        parse(response(confidence=confidence))


def test_rejects_cluster_mismatch_and_unbounded_text() -> None:
    with pytest.raises(RootCauseContractError, match="does not match"):
        parse(response(cluster_id="cluster-2"))

    with pytest.raises(RootCauseContractError, match="explanation.*exceeds"):
        parse(response(explanation="x" * (MAX_EXPLANATION_CHARS + 1)))


def test_requires_at_least_one_supporting_result() -> None:
    with pytest.raises(RootCauseContractError, match="result_ids.*must not be empty"):
        parse(response(result_ids=[]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result_ids", ["invented-result"]),
        ("span_ids", ["c" * 16]),
        ("static_finding_ids", ["invented-finding"]),
    ],
)
def test_rejects_invented_evidence_references(
    field: str,
    value: list[str],
) -> None:
    with pytest.raises(RootCauseContractError, match="unknown references"):
        parse(response(**{field: value}))


def test_rejects_duplicate_and_excessive_references() -> None:
    with pytest.raises(RootCauseContractError, match="unique references"):
        parse(response(result_ids=["result-1", "result-1"]))

    too_many = [f"result-{index}" for index in range(MAX_REFERENCES_PER_FIELD + 1)]
    with pytest.raises(RootCauseContractError, match="exceeds 50 references"):
        parse(response(result_ids=too_many))


def test_rejects_invalid_internal_allowlists() -> None:
    with pytest.raises(TypeError, match="collection of strings"):
        parse_root_cause_response(
            response(),
            expected_cluster_id="cluster-1",
            allowed_result_ids="result-1",
            allowed_span_ids=(),
            allowed_static_finding_ids=(),
        )
