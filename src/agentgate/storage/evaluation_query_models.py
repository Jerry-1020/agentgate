"""Typed read contracts for the evaluation workspace."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgate.domain import RunStatus
from agentgate.domain.evaluation_task import EvaluationTaskKind

SUMMARY_VERSION = 1


class SummaryNotReady(RuntimeError):
    """A read projection is missing or stale; never substitute an incorrect zero."""


class SummarySourceChanged(RuntimeError):
    """The source changed while a projection was being calculated."""


class EvaluationQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self):
        for value in (self.start_at, self.end_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("time bounds must include a timezone")
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValueError("start_at must precede end_at")
        return self


class TaskSummaryQuery(EvaluationQuery):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str = Field(default="", max_length=256)
    status: RunStatus | None = None
    kind: EvaluationTaskKind | None = None


class OverviewSummary(BaseModel):
    task_count: int = Field(ge=0)
    average_score: float | None = Field(default=None, ge=0, le=1)
    scored_run_count: int = Field(ge=0)
    completed_sample_count: int = Field(ge=0)
    dataset_count: int = Field(ge=0)
    dataset_sample_count: int = Field(ge=0)


class RunListSummary(BaseModel):
    run_id: str
    status: RunStatus
    target_name: str
    target_version: str
    dataset_name: str
    dataset_version: int | None
    evaluator_kinds: tuple[str, ...]
    scoring_mode: str
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    overall_score: float | None = Field(default=None, ge=0, le=1)
    gate_reason: str | None = None


class TaskListSummary(BaseModel):
    id: str
    task_id: str | None = None
    name: str
    kind: EvaluationTaskKind
    created_at: datetime
    status: RunStatus
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    previous_run_count: int = Field(default=0, ge=0)
    runs: tuple[RunListSummary, ...]


class TaskSummaryPage(BaseModel):
    items: tuple[TaskListSummary, ...]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class CompletedRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_results_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_count: int = Field(ge=0)
    summary_version: Literal[1] = SUMMARY_VERSION
    overall_score: float | None = Field(default=None, ge=0, le=1)
    gate_reason: str


from agentgate.domain import EvaluationResult, EvaluationRun


class RunSummarySource(BaseModel):
    run: EvaluationRun
    results: tuple[EvaluationResult, ...]
