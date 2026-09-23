"""HTTP boundary for exact-target platform evaluation submission."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.user_context import get_user_info

router = APIRouter(prefix="/api/agent-platform", tags=["agent-platform"])


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("identifier must not be blank")
    return value


Identifier = Annotated[str, Field(strict=True), AfterValidator(nonblank)]
TypeGroup = Literal["base/workflow", "abcclaw"]
ArrangeType = Literal["base", "workflow"]


class PlatformTargetInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    team_id: Identifier | None = None
    agent_id: Identifier
    type_group: TypeGroup
    agent_version: Identifier
    arrange_type: ArrangeType | None = None
    branch_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_branch(self) -> PlatformTargetInput:
        if self.type_group == "abcclaw":
            if self.branch_id is None:
                raise ValueError("abcclaw requires branch_id")
            if "arrange_type" in self.model_fields_set:
                raise ValueError("abcclaw must omit arrange_type")
        else:
            if self.arrange_type is None:
                raise ValueError("base/workflow requires arrange_type")
            if "branch_id" in self.model_fields_set:
                raise ValueError("base/workflow must omit branch_id")
        return self


class PlatformEvaluationInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target: PlatformTargetInput
    dataset_id: Identifier
    dataset_version: int = Field(strict=True, ge=1)
    evaluator_ids: list[Identifier] = Field(min_length=1, strict=True)
    case_ids: list[Identifier] | None = Field(default=None, min_length=1, strict=True)
    max_parallel_cases: int = Field(strict=True, ge=1, le=30)
    timeout_seconds: int = Field(strict=True, ge=1, le=3600)
    max_retries: int = Field(strict=True, ge=0, le=5)
    repetitions: int = Field(strict=True, ge=1, le=20)
    scheduled_for: datetime | None = None

    @field_validator("case_ids", mode="before")
    @classmethod
    def reject_null_cases(cls, value: object) -> object:
        if value is None:
            raise ValueError("omit case_ids for all cases")
        return value

    @field_validator("case_ids", "evaluator_ids")
    @classmethod
    def unique_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("identifiers must be unique")
        return value

    @field_validator("scheduled_for", mode="before")
    @classmethod
    def parse_schedule(cls, value: object) -> datetime:
        if not isinstance(value, str):
            # Pydantic validators use ValueError to report invalid input.
            raise ValueError("scheduled_for must be an ISO datetime string")  # noqa: TRY004
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("scheduled_for requires a timezone")
        return parsed.astimezone(UTC)

    @model_validator(mode="after")
    def validate_schedule(self) -> PlatformEvaluationInput:
        if self.scheduled_for is not None and (
            self.repetitions != 1 or self.scheduled_for <= datetime.now(UTC)
        ):
            raise ValueError("reservation requires one repetition and a future time")
        return self


class SubmitPlatformEvaluation(Protocol):
    def __call__(
        self,
        *,
        team_id: str,
        agent_id: str,
        type_group: TypeGroup,
        agent_version: str,
        arrange_type: ArrangeType | None,
        branch_id: str | None,
        dataset_id: str,
        dataset_version: int,
        case_ids: tuple[str, ...] | None,
        evaluator_ids: tuple[str, ...],
        max_parallel_cases: int,
        timeout_seconds: int,
        max_retries: int,
        repetitions: int,
        scheduled_for: datetime | None,
        token: str,
        user_team_id: str,
        user_id: str,
        user_name: str,
    ) -> EvaluationTask: ...


def read_platform_token(request: Request) -> str:
    values = request.headers.getlist("X-Agent-Platform-Token")
    if len(values) != 1:
        raise HTTPException(422, "Provide exactly one platform token header")
    token = values[0]
    if (
        not token
        or len(token) > 512
        or any(char.isspace() or unicodedata.category(char) == "Cc" for char in token)
        or re.match(r"Bearer\b", token, re.IGNORECASE)
    ):
        raise HTTPException(422, "Invalid platform token header")
    return token


async def read_platform_input(request: Request) -> PlatformEvaluationInput:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    try:
        return PlatformEvaluationInput.model_validate(await request.json())
    except (ValueError, UnicodeError):
        # Default validation details can contain input values, including misplaced secrets.
        raise HTTPException(422, "Invalid platform evaluation request") from None


def get_platform_submitter(request: Request) -> SubmitPlatformEvaluation:
    submitter = getattr(request.app.state, "submit_agent_platform_evaluation", None)
    if not callable(submitter):
        raise HTTPException(503, "Platform evaluation submission is unavailable")
    return cast(SubmitPlatformEvaluation, submitter)


def created_task_response(task: EvaluationTask, repetitions: int) -> JSONResponse:
    kind = "single" if repetitions == 1 else "stability"
    if (
        not isinstance(task, EvaluationTask)
        or not isinstance(task.id, str)
        or not task.id.strip()
        or task.kind != kind
        or not isinstance(task.run_ids, tuple)
        or len(task.run_ids) != repetitions
        or any(not isinstance(run_id, str) or not run_id.strip() for run_id in task.run_ids)
        or len(set(task.run_ids)) != len(task.run_ids)
    ):
        raise ValueError("Invalid created task")
    return JSONResponse({"id": task.id, "kind": kind, "run_ids": list(task.run_ids)}, 202)


@router.post("/evaluations", status_code=202)
async def launch_platform_evaluation(request: Request) -> JSONResponse:
    token = read_platform_token(request)
    inputs = await read_platform_input(request)
    submitter = get_platform_submitter(request)
    caller = get_user_info()
    try:
        task = await run_in_threadpool(
            submitter,
            team_id=inputs.target.team_id,
            agent_id=inputs.target.agent_id,
            type_group=inputs.target.type_group,
            agent_version=inputs.target.agent_version,
            arrange_type=inputs.target.arrange_type,
            branch_id=inputs.target.branch_id,
            dataset_id=inputs.dataset_id,
            dataset_version=inputs.dataset_version,
            case_ids=tuple(inputs.case_ids) if inputs.case_ids is not None else None,
            evaluator_ids=tuple(inputs.evaluator_ids),
            max_parallel_cases=inputs.max_parallel_cases,
            timeout_seconds=inputs.timeout_seconds,
            max_retries=inputs.max_retries,
            repetitions=inputs.repetitions,
            scheduled_for=inputs.scheduled_for,
            token=token,
            user_team_id=caller.user_team_id if caller else "",
            user_id=caller.user_id if caller else "anonymous",
            user_name=caller.user_name if caller else "匿名用户",
        )
    except PermissionError:
        raise HTTPException(403, "Platform target access was rejected") from None
    except LookupError:
        raise HTTPException(404, "Selected evaluation resource is unavailable") from None
    except ValueError:
        raise HTTPException(422, "Target or evaluation settings were rejected") from None
    except (TimeoutError, ConnectionError):
        raise HTTPException(
            503, "Submission outcome is uncertain; check tasks before retrying"
        ) from None
    except Exception:  # noqa: BLE001 -- Never expose or log an upstream credential-bearing error.
        raise HTTPException(
            500, "Submission outcome is uncertain; check tasks before retrying"
        ) from None
    try:
        return created_task_response(task, inputs.repetitions)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            500, "Submission outcome is uncertain; check tasks before retrying"
        ) from None
