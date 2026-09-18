"""Launch and inspect repeated runs against one immutable manifest."""

from statistics import mean, variance, stdev
from fastapi import APIRouter, HTTPException
from pydantic import Field, ConfigDict
from agentgate.server.routes.runs import LaunchRequest, Dependencies
from agentgate.application.evaluation_task_management import EvaluationTaskManagement

router = APIRouter(prefix="/api/stability-experiments", tags=["stability"])


class StabilityRequest(LaunchRequest):
    model_config = ConfigDict(extra="forbid")
    repetitions: int = Field(ge=2, le=20, strict=True)


@router.post("", status_code=202)
def launch(body: StabilityRequest, dependencies: Dependencies):
    if body.scheduled_for is not None:
        raise HTTPException(422, "stability does not support scheduling")
    try:
        return dependencies.submit_stability_runs(**body.model_dump())
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def list_experiments(dependencies: Dependencies):
    return [t for t in EvaluationTaskManagement(dependencies.repository).list() if t.kind == "stability"]


@router.get("/{task_id}")
def summary(task_id: str, dependencies: Dependencies):
    try:
        task = EvaluationTaskManagement(dependencies.repository).get(task_id)
    except LookupError:
        raise HTTPException(404, "unknown stability experiment") from None
    if task is None or task.kind != "stability":
        raise HTTPException(404, "unknown stability experiment")
    rows, scores = [], []
    for run_id in task.run_ids:
        progress = dependencies.results.get_run_progress(run_id)
        score, outcome = None, None
        if progress.status == "completed":
            report = dependencies.results.get_report(run_id)
            overall = next((m for m in report.metrics if m.level == "overall"), None)
            # Incomplete/error measurements do not masquerade as stable zero scores.
            if overall is not None and not overall.errors:
                score = overall.score
            outcome = report.release_gate.outcome
            if score is not None:
                scores.append(score)
        rows.append({"progress": progress, "score": score, "outcome": outcome})
    return {
        "experiment": task, "runs": rows, "measured_runs": len(scores),
        "mean": mean(scores) if scores else None,
        "sample_variance": variance(scores) if len(scores) > 1 else None,
        "sample_stddev": stdev(scores) if len(scores) > 1 else None,
        "min": min(scores) if scores else None, "max": max(scores) if scores else None,
        "complete": all(r["progress"].status in {"completed", "failed", "cancelled"} for r in rows),
    }
