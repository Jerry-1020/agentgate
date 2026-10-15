import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case,
    CaseCategory,
    CaseDifficulty,
    CaseTurn,
    Equals,
    SkillRouteExpectation,
    ToolCallExpectation,
)


def test_case_has_typed_single_and_multi_turn_forms():
    single = Case(name="single", turns=(CaseTurn(id="only", input={"message": "hi"}),))
    case = Case(
        name="multi",
        category=CaseCategory.BOUNDARY,
        difficulty=CaseDifficulty.HARD,
        turns=(
            CaseTurn(id="one", input={"message": "申请贷款"}),
            CaseTurn(id="two", input={"amount": 80000}),
        ),
    )

    assert not single.is_multi_turn
    assert case.is_multi_turn
    assert case.turns[1].input["amount"] == 80000


@pytest.mark.parametrize(
    ("field", "value"),
    (("id", " "), ("name", "")),
)
def test_case_rejects_blank_identity(field, value):
    data = {"name": "case", "turns": (CaseTurn(input={"message": "hello"}),)}
    data[field] = value

    with pytest.raises(ValidationError):
        Case(**data)


def test_case_rejects_duplicate_turn_ids_and_tags():
    with pytest.raises(ValidationError, match="CaseTurn ids must be unique"):
        Case(
            name="duplicate turns",
            turns=(
                CaseTurn(id="same", input={"message": "first"}),
                CaseTurn(id="same", input={"message": "second"}),
            ),
        )

    with pytest.raises(ValidationError, match="tags must not contain duplicates"):
        Case(
            name="duplicate tags",
            turns=(CaseTurn(input={"message": "hello"}),),
            tags=("regression", "regression"),
        )


def test_case_rejects_blank_turn_id_and_duplicate_expectation_ids():
    with pytest.raises(ValidationError):
        CaseTurn(id=" ", input={"message": "hello"})

    with pytest.raises(ValidationError, match="Expectation ids must be unique"):
        Case(
            name="duplicate expectations",
            turns=(
                CaseTurn(
                    id="first",
                    input={"message": "hello"},
                    expectations=(
                        SkillRouteExpectation(
                            id="same", condition=Equals(expected="loan")
                        ),
                    ),
                ),
                CaseTurn(
                    id="second",
                    input={"message": "continue"},
                    expectations=(ToolCallExpectation(id="same", tool="credit"),),
                ),
            ),
        )


def test_case_turn_rejects_empty_input():
    with pytest.raises(ValidationError, match="CaseTurn input must not be empty"):
        CaseTurn(input={})


def test_turn_extensions_roundtrip_and_are_immutable():
    data = {
        "id": "turn",
        "input": {"txt": "输入"},
        "expectations": [],
        "notes": "",
        "extensions": [{"key": "background", "value": "背景说明"}],
    }
    turn = CaseTurn.model_validate(data)
    assert turn.model_dump(mode="json") == data
    assert CaseTurn.model_validate_json(turn.model_dump_json()) == turn
    with pytest.raises(ValidationError, match="frozen"):
        turn.extensions[0].value = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        turn.extensions = ()


@pytest.mark.parametrize("value", [1, True, None, [], {}, b"text"])
@pytest.mark.parametrize("field", ["key", "value"])
def test_turn_extensions_reject_non_string_fields(field, value):
    extension = {"key": "background", "value": "text", field: value}
    with pytest.raises(ValidationError):
        CaseTurn(input={"txt": "input"}, extensions=[extension])


@pytest.mark.parametrize("key", ["", " ", "\n"])
def test_turn_extensions_reject_blank_keys(key):
    with pytest.raises(ValidationError, match="must not be blank"):
        CaseTurn(input={"txt": "input"}, extensions=[{"key": key, "value": ""}])


def test_turn_extensions_reject_duplicate_keys():
    with pytest.raises(ValidationError, match="extension keys must not contain duplicates"):
        CaseTurn(
            input={"txt": "input"},
            extensions=[
                {"key": "background", "value": "first"},
                {"key": "background", "value": "second"},
            ],
        )


def test_turn_extensions_allow_empty_values_and_omit_empty_collections():
    turn = CaseTurn(input={"txt": "input"})
    assert turn.extensions == ()
    assert "extensions" not in turn.model_dump(mode="json")
    assert "extensions" not in CaseTurn(input={"txt": "input"}, extensions=[]).model_dump()
    with_value = CaseTurn(
        input={"txt": "input"}, extensions=[{"key": "background", "value": ""}]
    )
    assert with_value.model_dump(mode="json")["extensions"] == [
        {"key": "background", "value": ""}
    ]


def test_extensions_are_independent_per_turn_and_do_not_change_inputs_or_expectations():
    case = Case(
        name="multi",
        turns=[
            CaseTurn(
                input={"txt": "input"},
                expectations=[SkillRouteExpectation(condition=Equals(expected="loan"))],
                extensions=[{"key": "background", "value": background}],
            )
            for background in ("first", "second")
        ],
    )
    restored = Case.model_validate_json(case.model_dump_json())
    assert [turn.extensions[0].value for turn in restored.turns] == ["first", "second"]
    for before, after in zip(case.turns, restored.turns):
        assert after.input == before.input
        assert after.expectations == before.expectations
