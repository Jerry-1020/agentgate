"""Dedicated, bounded evaluation page queries; old routes remain available."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from agentgate.domain import RunStatus
from agentgate.domain.evaluation_task import EvaluationTaskKind
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.storage.evaluation_query_models import (
    EvaluationQuery,
    OverviewSummary,
    SummaryNotReady,
    TaskSummaryPage,
    TaskSummaryQuery,
)

router = APIRouter(prefix="/api", tags=["evaluation-queries"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


@router.get("/evaluation-overview/summary", response_model=OverviewSummary)
def overview_summary(
    dependencies: Dependencies, start_at: datetime | None = None, end_at: datetime | None = None
):
    try:
        return dependencies.evaluation_queries.overview(
            EvaluationQuery(start_at=start_at, end_at=end_at)
        )
    except ValidationError as exc:
        raise HTTPException(422, "invalid timezone-aware time range") from exc
    except SummaryNotReady as exc:
        raise HTTPException(503, "evaluation_summary_not_ready") from exc


@router.get("/evaluation-task-summaries", response_model=TaskSummaryPage)
def task_summaries(
    dependencies: Dependencies,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=256),
    status: RunStatus | None = None,
    kind: EvaluationTaskKind | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    try:
        query = TaskSummaryQuery(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
            kind=kind,
            start_at=start_at,
            end_at=end_at,
        )
        return dependencies.evaluation_queries.tasks(query)
    except ValidationError as exc:
        raise HTTPException(422, "invalid summary query") from exc
    except SummaryNotReady as exc:
        raise HTTPException(503, "evaluation_summary_not_ready") from exc
