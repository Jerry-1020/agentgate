"""Durable task associations for the evaluation workspace."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentgate.application.evaluation_task_management import EvaluationTaskManagement
from agentgate.domain.evaluation_task import EvaluationTask, EvaluationTaskKind
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.user_context import get_user_info

router = APIRouter(prefix="/api/evaluation-tasks", tags=["evaluation-tasks"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class TaskAssociationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: EvaluationTaskKind
    name: str | None = None
    run_ids: tuple[str, ...]
    static_report_ids: tuple[str, ...] = ()


class TaskRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str = Field(strict=True, min_length=1)

    @field_validator("source_run_id")
    @classmethod
    def nonblank_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_run_id must not be blank")
        return value


@router.post("/{task_id}/rerun", status_code=202)
def rerun_task(task_id: str, body: TaskRerunRequest, dependencies: Dependencies):
    try:
        return EvaluationTaskManagement(dependencies.repository).rerun(
            task_id, body.source_run_id, dependencies.runs, dependencies.dispatcher,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("")
def list_tasks(dependencies: Dependencies):
    return EvaluationTaskManagement(dependencies.repository).list()


@router.get("/{task_id}")
def get_task(task_id: str, dependencies: Dependencies):
    try:
        return EvaluationTaskManagement(dependencies.repository).get(task_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{task_id}")
def save_task(task_id: str, body: TaskAssociationRequest, dependencies: Dependencies):
    try:
        task = EvaluationTask(id=task_id, **body.model_dump())
        return EvaluationTaskManagement(dependencies.repository).save(task)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/{task_id}")
def delete_task(task_id: str, dependencies: Dependencies):
    try:
        info = get_user_info()
        dependencies.repository.delete_task_record(task_id, user_team_id=info.user_team_id if info else "")
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": task_id}
