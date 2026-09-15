"""Composition of optimization analysis for one completed Run."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    EvaluationResult,
    EvaluationRun,
    OptimizationReport,
    Outcome,
    RunStatus,
    SkillAnalysisFinding,
    Trace,
)
from agentgate.domain.base import require_non_blank
from agentgate.evaluator.judge.model_protocol import (
    JudgeModelClient,
    JudgeModelUnavailable,
)

from .clustering import cluster_failed_results
from .confusion_matrix import build_routing_confusion_matrix
from .root_cause import infer_root_causes
from .suggestions import build_optimization_suggestions


ANALYZER_VERSION = "2"


def build_optimization_report(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
    traces: Sequence[Trace],
    static_findings: Sequence[SkillAnalysisFinding] = (),
    *,
    model_client: JudgeModelClient | None,
    model_id: str | None,
    root_cause_timeout_seconds: float = 60,
    analyzer_version: str = ANALYZER_VERSION,
) -> OptimizationReport:
    """Compose optimizer outputs, including evidence-constrained LLM analysis."""

    if run.status != RunStatus.COMPLETED:
        raise ValueError("optimization requires a completed EvaluationRun")
    analyzer_version = require_non_blank(
        analyzer_version,
        "optimizer analyzer_version",
    )

    result_items = tuple(results)
    if any(result.run_id != run.id for result in result_items):
        raise ValueError("optimization Results must belong to the requested Run")
    result_ids = tuple(result.id for result in result_items)
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("optimization Result identities must be unique")

    trace_items = tuple(traces)
    if any(trace.run_id != run.id for trace in trace_items):
        raise ValueError("optimization Traces must belong to the requested Run")
    trace_ids = tuple(trace.trace_id for trace in trace_items)
    if len(set(trace_ids)) != len(trace_ids):
        raise ValueError("optimization Trace identities must be unique")

    cases = run.manifest.execution_cases
    case_ids = {case.id for case in cases}
    if any(result.case_id not in case_ids for result in result_items):
        raise ValueError("optimization Result references a Case outside the Run")
    if any(trace.case_id not in case_ids for trace in trace_items):
        raise ValueError("optimization Trace references a Case outside the Run")

    if (model_client is None) != (model_id is None):
        raise ValueError("root-cause model client and model id must be configured together")
    if model_id is not None:
        model_id = require_non_blank(model_id, "root-cause model_id")
    if (
        isinstance(root_cause_timeout_seconds, bool)
        or not isinstance(root_cause_timeout_seconds, (int, float))
        or root_cause_timeout_seconds <= 0
    ):
        raise ValueError("root_cause_timeout_seconds must be positive")

    finding_items = tuple(static_findings)
    dataset = run.manifest.dataset
    if dataset.version is None:
        raise ValueError("optimization requires a published Dataset version")

    failed_results = tuple(
        result for result in result_items if result.outcome == Outcome.FAIL
    )
    clusters = cluster_failed_results(failed_results)
    confusion_matrix = build_routing_confusion_matrix(
        cases,
        result_items,
    )
    hypotheses = ()
    if clusters:
        if model_client is None or model_id is None:
            raise JudgeModelUnavailable(
                "Root-cause model is not configured"
            )
        traces_by_id = {trace.trace_id: trace for trace in trace_items}
        for result in failed_results:
            trace = traces_by_id.get(result.trace_id)
            if trace is None:
                raise ValueError(
                    f"missing Trace evidence for failed Result: {result.id}"
                )
            if trace.case_id != result.case_id:
                raise ValueError(
                    f"Trace evidence does not match failed Result: {result.id}"
                )
        hypotheses = infer_root_causes(
            clusters,
            cases,
            result_items,
            trace_items,
            confusion_matrix,
            finding_items,
            model_client=model_client,
            model_id=model_id,
            timeout_seconds=float(root_cause_timeout_seconds),
        )
    suggestions = build_optimization_suggestions(
        hypotheses,
        clusters,
        finding_items,
    )
    return OptimizationReport(
        run_id=run.id,
        target_ref=run.manifest.target.ref,
        target_content_sha256=run.manifest.target.content_sha256,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_content_sha256=dataset.content_sha256,
        analyzer_version=analyzer_version,
        failed_result_count=len(failed_results),
        clusters=clusters,
        confusion_matrix=confusion_matrix,
        hypotheses=hypotheses,
        suggestions=suggestions,
    )
