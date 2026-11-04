"""Persisted timing and diagnostic information for one execution operation."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from .base import DomainModel, normalize_utc, utcnow


class RunEvent(DomainModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str | None = None
    run_id: str | None = None
    user_team_id: str = ""
    stage: str
    name: str
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"] = "running"
    case_id: str | None = None
    turn_id: str | None = None
    evaluator_id: str | None = None
    bjs_job_id: str | None = None
    bjs_batch_number: str | None = None
    agent_id: str | None = None
    pod_task_id: str | None = None
    pod_name: str | None = None
    attempt: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    message: str = ""

    @field_validator("started_at", "ended_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value, "execution timestamp") if value else None

    @model_validator(mode="after")
    def validate_timing(self) -> "RunEvent":
        normalize_utc(self.started_at, "started_at")
        if self.ended_at is not None:
            normalize_utc(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("event end must not precede start")
        if (self.status == "running") != (self.ended_at is None):
            raise ValueError("only a running event may have no end time")
        return self
