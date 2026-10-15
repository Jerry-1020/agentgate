"""Evaluation Case and multi-turn conversation domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

from .base import DomainModel, FrozenJsonObject, require_non_blank
from .expectation import Expectation


def _require_unique_non_blank(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank values")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class CaseCategory(StrEnum):
    """Business scenario category assigned to an evaluation Case."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"


class CaseDifficulty(StrEnum):
    """Human-maintained difficulty classification for an evaluation Case."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class TurnExtension(DomainModel):
    """One immutable string-valued annotation on a conversation turn."""

    key: StrictStr
    value: StrictStr

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return require_non_blank(value, "TurnExtension key")


class CaseTurn(DomainModel):
    """One user input and its expected outcomes within an evaluation Case."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    input: FrozenJsonObject
    expectations: tuple[Expectation, ...] = ()
    notes: str = ""
    extensions: tuple[TurnExtension, ...] = ()

    @field_validator("extensions")
    @classmethod
    def validate_extensions(
        cls, value: tuple[TurnExtension, ...]
    ) -> tuple[TurnExtension, ...]:
        _require_unique_non_blank(tuple(item.key for item in value), "extension keys")
        return value

    @model_serializer(mode="wrap")
    def serialize_turn(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        # Empty annotations must not change existing dataset and run hashes.
        if not self.extensions:
            data.pop("extensions", None)
        return data

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return require_non_blank(value, "CaseTurn id")

    @field_validator("input")
    @classmethod
    def validate_input(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        if not value:
            raise ValueError("CaseTurn input must not be empty")
        return value


class Case(DomainModel):
    """An immutable single-turn or multi-turn evaluation scenario."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    turns: tuple[CaseTurn, ...] = Field(min_length=1)
    initial_state: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    category: CaseCategory = CaseCategory.POSITIVE
    difficulty: CaseDifficulty = CaseDifficulty.MEDIUM
    tags: tuple[str, ...] = ()
    notes: str = ""

    @field_validator("id", "name")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"Case {info.field_name}")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_non_blank(value, "tags")

    @model_validator(mode="after")
    def validate_child_ids(self) -> "Case":
        turn_ids = tuple(turn.id for turn in self.turns)
        if len(set(turn_ids)) != len(turn_ids):
            raise ValueError("CaseTurn ids must be unique within a Case")

        expectation_ids = tuple(
            expectation.id
            for turn in self.turns
            for expectation in turn.expectations
        )
        if len(set(expectation_ids)) != len(expectation_ids):
            raise ValueError("Expectation ids must be unique within a Case")
        return self

    @property
    def is_multi_turn(self) -> bool:
        """Return whether execution requires more than one conversation turn."""

        return len(self.turns) > 1
