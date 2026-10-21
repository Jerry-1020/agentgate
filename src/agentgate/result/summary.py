"""Calculate immutable completion projections with the original scoring rules."""

from collections.abc import Sequence

from agentgate.domain import EvaluationResult, EvaluationRun, RunStatus, content_sha256
from agentgate.storage.evaluation_query_models import CompletedRunSummary

from .report import build_evaluation_report


def result_source_digest(results: Sequence[EvaluationResult]) -> str:
    ordered = sorted(results, key=lambda r: (r.case_id, r.evaluator_id, r.id))
    return content_sha256([r.model_dump(mode="json") for r in ordered])


def build_completed_run_summary(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
) -> CompletedRunSummary:
    if run.status is not RunStatus.COMPLETED:
        raise ValueError("completed run required")
    if any(result.run_id != run.id for result in results):
        raise ValueError("results must belong to the completed run")
    report = build_evaluation_report(run, results)
    overall = next((m for m in report.metrics if m.level == "overall"), None)
    return CompletedRunSummary(
        run_id=run.id,
        manifest_sha256=content_sha256(run.manifest),
        source_results_sha256=result_source_digest(results),
        result_count=len(results),
        overall_score=None if overall is None else overall.score,
        gate_reason=report.release_gate.reason_code,
    )
