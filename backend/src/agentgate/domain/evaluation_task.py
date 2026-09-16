"""A user-facing task associates existing executions and static reports."""

from datetime import datetime
from enum import StrEnum
import re
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from .base import DomainModel, normalize_utc, require_non_blank, utcnow


class EvaluationTaskKind(StrEnum):
    SINGLE = "single"
    AB = "ab"


class EvaluationTask(DomainModel):
    """Immutable associations; execution state belongs to the referenced runs."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: EvaluationTaskKind
    created_at: datetime = Field(default_factory=utcnow)
    run_ids: tuple[str, ...]
    static_report_ids: tuple[str, ...] = ()
    git_commit_refs: tuple[str, ...] = ()
    credential_id: str | None = None

    @field_validator("id", "credential_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        return require_non_blank(value, "identifier") if value is not None else value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return normalize_utc(value, "created_at")

    @field_validator("run_ids", "static_report_ids")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("references must not be blank")
        if len(set(value)) != len(value):
            raise ValueError("references must be unique")
        return value

    @field_validator("git_commit_refs")
    @classmethod
    def validate_commits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", item) for item in value):
            raise ValueError("Git references must be full commit hashes")
        return value

    @model_validator(mode="after")
    def validate_cardinality(self) -> "EvaluationTask":
        count = 1 if self.kind == EvaluationTaskKind.SINGLE else 2
        if len(self.run_ids) != count:
            raise ValueError(f"{self.kind} requires exactly {count} runs")
        if len(self.static_report_ids) > count:
            raise ValueError("too many static reports")
        if self.git_commit_refs and len(self.git_commit_refs) != count:
            raise ValueError("Git references must match the number of runs")
        return self
