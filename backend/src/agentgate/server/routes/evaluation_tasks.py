"""Durable task associations for the evaluation workspace."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from agentgate.application.evaluation_task_management import EvaluationTaskManagement
from agentgate.domain.evaluation_task import EvaluationTask, EvaluationTaskKind
from agentgate.server.dependencies import ServerDependencies, get_dependencies

router = APIRouter(prefix="/api/evaluation-tasks", tags=["evaluation-tasks"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class TaskAssociationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: EvaluationTaskKind
    run_ids: tuple[str, ...]
    static_report_ids: tuple[str, ...] = ()


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
