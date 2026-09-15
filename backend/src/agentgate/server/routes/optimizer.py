"""Read-only optimization analysis endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agentgate.application import (
    OptimizationRunNotCompleted,
    OptimizationRunNotFound,
    OptimizationSkillAnalysisMismatch,
    OptimizationSkillAnalysisNotUsable,
    OptimizationSkillAnalysisReportNotFound,
)
from agentgate.domain import OptimizationReport
from agentgate.evaluator.judge import (
    CredentialUnavailable,
    JudgeModelError,
    JudgeModelInvalidResponse,
    JudgeModelTimeout,
    JudgeModelUnavailable,
)
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import (
    raise_conflict,
    raise_not_found,
    raise_unprocessable,
)


router = APIRouter(prefix="/api", tags=["optimizer"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


@router.get(
    "/runs/{run_id}/optimization",
    response_model=OptimizationReport,
)
def optimization_report(
    run_id: str,
    dependencies: Dependencies,
    skill_analysis_report_id: Annotated[
        str | None,
        Query(min_length=1),
    ] = None,
) -> OptimizationReport:
    try:
        return dependencies.optimization.analyze_run(
            run_id,
            skill_analysis_report_id,
        )
    except (
        OptimizationRunNotFound,
        OptimizationSkillAnalysisReportNotFound,
    ) as error:
        raise_not_found(error)
    except OptimizationRunNotCompleted as error:
        raise_conflict(error)
    except JudgeModelTimeout as error:
        raise HTTPException(
            status_code=504,
            detail="Root-cause model timed out",
        ) from error
    except (CredentialUnavailable, JudgeModelUnavailable) as error:
        raise HTTPException(
            status_code=503,
            detail="Root-cause model is unavailable",
        ) from error
    except JudgeModelInvalidResponse as error:
        raise HTTPException(
            status_code=502,
            detail="Root-cause model returned an invalid response",
        ) from error
    except JudgeModelError as error:
        raise HTTPException(
            status_code=502,
            detail="Root-cause model request failed",
        ) from error
    except (
        OptimizationSkillAnalysisMismatch,
        OptimizationSkillAnalysisNotUsable,
        ValueError,
    ) as error:
        raise_unprocessable(error)
