"""Strict validation for LLM-generated root-cause hypotheses."""

from __future__ import annotations

import json
import math
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any


MAX_RESPONSE_CHARS = 32_000
MAX_CATEGORY_CHARS = 100
MAX_TITLE_CHARS = 240
MAX_EXPLANATION_CHARS = 4_000
MAX_REFERENCE_ID_CHARS = 240
MAX_REFERENCES_PER_FIELD = 50

_RESPONSE_FIELDS = frozenset(
    {
        "cluster_id",
        "category",
        "title",
        "explanation",
        "confidence",
        "result_ids",
        "span_ids",
        "static_finding_ids",
    }
)


class RootCauseContractError(ValueError):
    """The model response violates the root-cause response contract."""


@dataclass(frozen=True, slots=True)
class ParsedRootCauseHypothesis:
    """Normalized root-cause content accepted from a model response."""

    cluster_id: str
    category: str
    title: str
    explanation: str
    confidence: float
    result_ids: tuple[str, ...]
    span_ids: tuple[str, ...]
    static_finding_ids: tuple[str, ...]


def _bounded_text(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RootCauseContractError(
            f"root-cause response {field_name!r} must not be blank"
        )
    normalized = value.strip()
    if len(normalized) > maximum:
        raise RootCauseContractError(
            f"root-cause response {field_name!r} exceeds {maximum} characters"
        )
    return normalized


def _allowed_ids(values: Collection[str], field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Collection):
        raise TypeError(f"{field_name} must be a collection of strings")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must contain only nonblank strings")
        normalized.add(value.strip())
    return frozenset(normalized)


def _reference_ids(
    value: Any,
    field_name: str,
    allowed: frozenset[str],
    *,
    required: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RootCauseContractError(
            f"root-cause response {field_name!r} must be a list"
        )
    if required and not value:
        raise RootCauseContractError(
            f"root-cause response {field_name!r} must not be empty"
        )
    if len(value) > MAX_REFERENCES_PER_FIELD:
        raise RootCauseContractError(
            f"root-cause response {field_name!r} exceeds "
            f"{MAX_REFERENCES_PER_FIELD} references"
        )

    normalized = tuple(
        _bounded_text(item, f"{field_name} item", MAX_REFERENCE_ID_CHARS)
        for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise RootCauseContractError(
            f"root-cause response {field_name!r} must contain unique references"
        )
    unknown = set(normalized).difference(allowed)
    if unknown:
        raise RootCauseContractError(
            f"root-cause response {field_name!r} contains unknown references: "
            + ", ".join(sorted(unknown))
        )
    return tuple(sorted(normalized))


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RootCauseContractError(
            "root-cause response 'confidence' must be a number"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise RootCauseContractError(
            "root-cause response 'confidence' must be between 0 and 1"
        )
    return normalized


def _validate_fields(payload: dict[str, Any]) -> None:
    actual = set(payload)
    missing = _RESPONSE_FIELDS.difference(actual)
    unknown = actual.difference(_RESPONSE_FIELDS)
    if missing:
        raise RootCauseContractError(
            "root-cause response is missing fields: "
            + ", ".join(sorted(missing))
        )
    if unknown:
        raise RootCauseContractError(
            "root-cause response has unknown fields: "
            + ", ".join(sorted(unknown))
        )


def parse_root_cause_response(
    text: str,
    *,
    expected_cluster_id: str,
    allowed_result_ids: Collection[str],
    allowed_span_ids: Collection[str],
    allowed_static_finding_ids: Collection[str],
) -> ParsedRootCauseHypothesis:
    """Parse one model response and reject unsupported evidence references."""

    if not isinstance(text, str):
        raise RootCauseContractError("root-cause response must be text")
    if len(text) > MAX_RESPONSE_CHARS:
        raise RootCauseContractError(
            f"root-cause response exceeds {MAX_RESPONSE_CHARS} characters"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise RootCauseContractError(
            "root-cause response is not valid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise RootCauseContractError("root-cause response must be a JSON object")
    _validate_fields(payload)

    expected = _bounded_text(
        expected_cluster_id,
        "expected_cluster_id",
        MAX_REFERENCE_ID_CHARS,
    )
    cluster_id = _bounded_text(
        payload["cluster_id"],
        "cluster_id",
        MAX_REFERENCE_ID_CHARS,
    )
    if cluster_id != expected:
        raise RootCauseContractError(
            "root-cause response 'cluster_id' does not match the requested cluster"
        )

    result_ids = _reference_ids(
        payload["result_ids"],
        "result_ids",
        _allowed_ids(allowed_result_ids, "allowed_result_ids"),
        required=True,
    )
    span_ids = _reference_ids(
        payload["span_ids"],
        "span_ids",
        _allowed_ids(allowed_span_ids, "allowed_span_ids"),
    )
    static_finding_ids = _reference_ids(
        payload["static_finding_ids"],
        "static_finding_ids",
        _allowed_ids(
            allowed_static_finding_ids,
            "allowed_static_finding_ids",
        ),
    )

    return ParsedRootCauseHypothesis(
        cluster_id=cluster_id,
        category=_bounded_text(
            payload["category"], "category", MAX_CATEGORY_CHARS
        ),
        title=_bounded_text(payload["title"], "title", MAX_TITLE_CHARS),
        explanation=_bounded_text(
            payload["explanation"],
            "explanation",
            MAX_EXPLANATION_CHARS,
        ),
        confidence=_confidence(payload["confidence"]),
        result_ids=result_ids,
        span_ids=span_ids,
        static_finding_ids=static_finding_ids,
    )


__all__ = [
    "ParsedRootCauseHypothesis",
    "RootCauseContractError",
    "parse_root_cause_response",
]
