"""A user-facing task associates existing executions and static reports."""

import re
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from .base import DomainModel, normalize_utc, require_non_blank, utcnow
from .run import EvaluationRun, RunStatus


class EvaluationTaskKind(StrEnum):
    SINGLE = "single"
    AB = "ab"
    STABILITY = "stability"


class EvaluationTask(DomainModel):
    """Immutable associations; execution state belongs to the referenced runs."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: EvaluationTaskKind
    name: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utcnow)
    run_ids: tuple[str, ...]
    previous_run_ids: tuple[str, ...] = ()
    static_report_ids: tuple[str, ...] = ()
    git_commit_refs: tuple[str, ...] = ()
    credential_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return require_non_blank(value, "task name").strip() if value is not None else None

    @field_validator("id", "credential_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        return require_non_blank(value, "identifier") if value is not None else value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return normalize_utc(value, "created_at")

    @field_validator("run_ids", "previous_run_ids", "static_report_ids")
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
        if set(self.run_ids).intersection(self.previous_run_ids):
            raise ValueError("current and previous runs must be distinct")
        if self.previous_run_ids and self.kind != EvaluationTaskKind.SINGLE:
            raise ValueError("only single tasks support execution history")
        if self.kind == EvaluationTaskKind.STABILITY:
            if not 2 <= len(self.run_ids) <= 20:
                raise ValueError("stability requires 2 to 20 runs")
            if len(self.static_report_ids) > 1:
                raise ValueError("stability uses one target snapshot")
            if self.git_commit_refs:
                raise ValueError("stability Git references are not supported")
            return self
        count = 1 if self.kind == EvaluationTaskKind.SINGLE else 2
        if len(self.run_ids) != count:
            raise ValueError(f"{self.kind} requires exactly {count} runs")
        if len(self.static_report_ids) > count:
            raise ValueError("too many static reports")
        if self.git_commit_refs and len(self.git_commit_refs) != count:
            raise ValueError("Git references must match the number of runs")
        return self


def task_with_rerun(
    task: EvaluationTask, source: EvaluationRun, rerun: EvaluationRun,
) -> EvaluationTask:
    """Validate one current-to-history switch without changing either execution."""
    if task.kind != EvaluationTaskKind.SINGLE:
        raise ValueError("only single tasks can be rerun")
    if task.run_ids != (source.id,):
        raise ValueError("task execution changed; refresh before rerunning")
    if source.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        raise ValueError("only a terminal task execution can be rerun")
    if rerun.status != RunStatus.PENDING or rerun.id in task.run_ids + task.previous_run_ids:
        raise ValueError("rerun must be a new pending execution")
    if rerun.manifest != source.manifest or any(
        getattr(rerun, field) != getattr(source, field)
        for field in ("user_team_id", "user_id", "user_name", "api_key")
    ):
        raise ValueError("rerun must preserve the source configuration and ownership")
    return EvaluationTask.model_validate({
        **task.model_dump(), "run_ids": (rerun.id,),
        "previous_run_ids": task.previous_run_ids + (source.id,),
    })
