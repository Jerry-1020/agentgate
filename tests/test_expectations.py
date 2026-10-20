import pytest
from pydantic import TypeAdapter, ValidationError

from agentgate.domain import (
    Equals,
    Expectation,
    MatchesPattern,
    OneOf,
    PolicyExpectation,
    SkillRouteExpectation,
    ToolArgumentExpectation,
    ToolCallExpectation,
    WithinRange,
    WithinTolerance,
)
from agentgate.domain.base import FrozenJsonObject


def test_condition_values_are_recursively_immutable():
    source = {"nested": [{"value": 1}]}
    condition = Equals(expected=source)
    source["nested"][0]["value"] = 2
    assert condition.expected["nested"][0]["value"] == 1
    with pytest.raises(TypeError):
        condition.expected["nested"][0]["value"] = 3


@pytest.mark.parametrize("condition_type, field", [(Equals, "expected"), (OneOf, "allowed")])
@pytest.mark.parametrize(
    "value",
    [
        {"nested": [{"enabled": True, "score": 1, "value": None}]},
        [{"items": [False, 2, None, "text"]}],
    ],
)
def test_json_conditions_round_trip_nested_objects_without_thawing_model(
    condition_type, field, value
):
    original = value if field == "expected" else [value]
    condition = condition_type(**{field: original})

    assert condition.model_dump(mode="json")[field] == original
    restored = condition_type.model_validate_json(condition.model_dump_json())
    assert restored == condition

    frozen = getattr(restored, field)
    if field == "allowed":
        frozen = frozen[0]
    if isinstance(frozen, tuple):
        frozen = frozen[0]
    assert isinstance(frozen, FrozenJsonObject)
    with pytest.raises(TypeError):
        frozen["changed"] = True

    serialized = restored.model_dump(mode="json")[field]
    if field == "allowed":
        serialized = serialized[0]
    if isinstance(serialized, list):
        serialized = serialized[0]
    serialized["changed"] = True
    assert "changed" not in frozen


def test_condition_construction_rejects_invalid_rules():
    with pytest.raises(ValidationError):
        MatchesPattern(pattern="[")
    with pytest.raises(ValidationError):
        WithinRange()
    with pytest.raises(ValidationError):
        WithinTolerance(expected=float("inf"))
    with pytest.raises(ValidationError):
        OneOf(allowed=())
    with pytest.raises(ValidationError, match="must be unique"):
        OneOf(allowed=({"value": 1}, {"value": 1}))

    assert OneOf(allowed=({"value": 1},)).allowed[0]["value"] == 1


def test_expectation_union_parses_each_observation_subject():
    adapter = TypeAdapter(Expectation)

    route = adapter.validate_python(
        {
            "kind": "skill_route",
            "id": "route",
            "condition": {"kind": "equals", "expected": "loan"},
        }
    )
    tool = adapter.validate_python(
        {"kind": "tool_call", "id": "tool", "tool": "credit", "mode": "forbidden"}
    )
    policy = adapter.validate_python(
        {"kind": "policy", "id": "policy", "policy_id": "P1"}
    )

    assert isinstance(route, SkillRouteExpectation)
    assert isinstance(tool, ToolCallExpectation)
    assert isinstance(policy, PolicyExpectation)


def test_expectation_references_cannot_be_blank():
    with pytest.raises(ValidationError):
        ToolCallExpectation(tool=" ")
    with pytest.raises(ValidationError):
        ToolArgumentExpectation(
            tool="credit", path=" ", condition=Equals(expected=1)
        )
    with pytest.raises(ValidationError):
        PolicyExpectation(policy_id=" ")
