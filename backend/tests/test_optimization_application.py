from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from agentgate.application import (
    OptimizationAnalysis,
    OptimizationRunNotCompleted,
    OptimizationRunNotFound,
    OptimizationSkillAnalysisMismatch,
    OptimizationSkillAnalysisNotUsable,
    OptimizationSkillAnalysisReportNotFound,
)
from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    DatasetVersion,
    DatasetVersionStatus,
    Equals,
    EvaluationResult,
    EvaluationRun,
    EvaluatorKind,
    EvaluatorSeverity,
    EvaluatorSpec,
    FailureStage,
    FindingSeverity,
    MetricPlan,
    Outcome,
    ReleaseGateSpec,
    ReviewDecision,
    RunManifest,
    RunStatus,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisReview,
    SkillAnalysisStatus,
    SkillRouteExpectation,
    TargetRef,
    TargetSnapshot,
    TargetType,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.judge import (
    JudgeModelTimeout,
    JudgeModelUnavailable,
    JudgeRequest,
    JudgeResponse,
)


NOW = datetime(2026, 9, 8, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def completed_run() -> EvaluationRun:
    case = Case(
        id="case-1",
        name="Route",
        turns=(
            CaseTurn(
                id="turn-1",
                input={"message": "apply"},
                expectations=(
                    SkillRouteExpectation(
                        id="route-1",
                        condition=Equals(expected="loan"),
                    ),
                ),
            ),
        ),
    )
    dataset = DatasetVersion(
        id="dataset-version-1",
        dataset_id="dataset-1",
        version=1,
        status=DatasetVersionStatus.PUBLISHED,
        cases=(case,),
        created_at=NOW,
        updated_at=NOW,
        published_at=NOW,
    )
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        display_name="Loan Agent",
        adapter_type="python_function",
        adapter_version="1",
        descriptor_sha256="c" * 64,
        captured_at=NOW,
    )
    evaluator = EvaluatorSpec(
        id="routing",
        name="Routing",
        dimension="routing",
        metric="skill_route",
        implementation_id="skill_routing",
    )
    manifest = RunManifest(
        dataset=dataset,
        target=target,
        evaluator_specs=(evaluator,),
        primary_evaluator_ids=(evaluator.id,),
        metric_plan=MetricPlan(),
        gate_spec=ReleaseGateSpec(),
        created_at=NOW,
    )
    return EvaluationRun(
        id="run-1",
        manifest=manifest,
        status=RunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )


def failed_result() -> EvaluationResult:
    check = CheckResult(
        id="check-1",
        name="route",
        turn_id="turn-1",
        expectation_id="route-1",
        outcome=Outcome.FAIL,
        score=0,
        reason="wrong route",
        expected={"kind": "equals", "expected": "loan"},
        actual="card",
        span_ids=(SPAN_ID,),
        failure_stage=FailureStage.ROUTING,
        failure_sequence=1,
        failure_span_id=SPAN_ID,
    )
    return EvaluationResult(
        id="result-1",
        run_id="run-1",
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256="d" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.FAIL,
        score=0,
        reason="failed",
        checks=(check,),
        primary_failure_stage=FailureStage.ROUTING,
    )


def passed_result() -> EvaluationResult:
    check = CheckResult(
        id="check-1",
        name="route",
        turn_id="turn-1",
        expectation_id="route-1",
        outcome=Outcome.PASS,
        score=1,
        reason="correct route",
        expected={"kind": "equals", "expected": "loan"},
        actual="loan",
        span_ids=(SPAN_ID,),
    )
    return EvaluationResult(
        id="result-1",
        run_id="run-1",
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256="d" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.PASS,
        score=1,
        reason="passed",
        checks=(check,),
    )


def execution_trace() -> Trace:
    return Trace(
        trace_id=TRACE_ID,
        run_id="run-1",
        case_id="case-1",
        spans=(
            TraceSpan(
                trace_id=TRACE_ID,
                span_id=SPAN_ID,
                name="route",
                operation_type="routing",
                sequence=1,
                started_at=NOW,
                ended_at=NOW,
                attributes={"agentgate.skill.id": "card"},
            ),
        ),
    )


class RecordingModelClient:
    provider_id = "provider-1"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[JudgeRequest] = []

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        references = json.loads(request.user_prompt.splitlines()[2])
        return JudgeResponse(
            text=json.dumps(
                {
                    "cluster_id": references["cluster_id"],
                    "category": "routing_confusion",
                    "title": "Ambiguous routing responsibilities",
                    "explanation": "The trace evidence indicates Skill overlap.",
                    "confidence": 0.8,
                    "result_ids": references["result_ids"],
                    "span_ids": references["span_ids"],
                    "static_finding_ids": references["static_finding_ids"],
                }
            ),
            resolved_model_id="resolved-model-1",
        )


def skill_report(
    run: EvaluationRun,
    *,
    status: SkillAnalysisStatus = SkillAnalysisStatus.COMPLETED,
) -> SkillAnalysisReport:
    finding = SkillAnalysisFinding(
        id="finding-1",
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.8,
        skill_ids=("loan", "card"),
        reason="descriptions overlap",
        evidence=({"source": "test"},),
    )
    return SkillAnalysisReport(
        id="skill-report-1",
        target_ref=run.manifest.target.ref,
        target_descriptor_sha256=run.manifest.target.descriptor_sha256,
        analyzer_version="1",
        status=status,
        findings=() if status == SkillAnalysisStatus.FAILED else (finding,),
        errors=(
            ({"category": "unavailable", "message": "analysis failed"},)
            if status == SkillAnalysisStatus.FAILED
            else ()
        ),
        created_at=NOW,
    )


class RepositoryStub:
    def __init__(
        self,
        run: EvaluationRun | None,
        results: tuple[EvaluationResult, ...] = (),
        report: SkillAnalysisReport | None = None,
        reviews: tuple[SkillAnalysisReview, ...] = (),
        traces: tuple[Trace, ...] = (),
    ) -> None:
        self.run = run
        self.results = results
        self.report = report
        self.reviews = reviews
        self.traces = traces
        self.result_loads = 0
        self.trace_loads = 0

    def get_run(self, run_id: str) -> EvaluationRun | None:
        return self.run if self.run is not None and self.run.id == run_id else None

    def list_results(self, run_id: str) -> list[EvaluationResult]:
        self.result_loads += 1
        return [result for result in self.results if result.run_id == run_id]

    def list_traces(self, run_id: str) -> list[Trace]:
        self.trace_loads += 1
        return [trace for trace in self.traces if trace.run_id == run_id]

    def get_skill_analysis_report(
        self,
        report_id: str,
    ) -> SkillAnalysisReport | None:
        if self.report is not None and self.report.id == report_id:
            return self.report
        return None

    def list_skill_analysis_reviews(
        self,
        report_id: str,
    ) -> list[SkillAnalysisReview]:
        return list(self.reviews) if self.report and self.report.id == report_id else []


def test_analyzes_persisted_run_results_without_static_report() -> None:
    run = completed_run()
    repository = RepositoryStub(
        run,
        (failed_result(),),
        traces=(execution_trace(),),
    )
    client = RecordingModelClient()
    report = OptimizationAnalysis(
        repository,
        root_cause_model_client=client,
        root_cause_model_id="model-1",
    ).analyze_run(run.id)

    assert report.run_id == run.id
    assert report.failed_result_count == 1
    assert report.hypotheses[0].static_finding_ids == ()
    assert report.suggestions[0].target == "agent_routing"
    assert len(client.requests) == 1
    assert repository.result_loads == 1
    assert repository.trace_loads == 1


def test_uses_explicit_matching_static_report() -> None:
    run = completed_run()
    static = skill_report(run)
    report = OptimizationAnalysis(
        RepositoryStub(
            run,
            (failed_result(),),
            static,
            traces=(execution_trace(),),
        ),
        root_cause_model_client=RecordingModelClient(),
        root_cause_model_id="model-1",
    ).analyze_run(run.id, static.id)

    assert report.hypotheses[0].static_finding_ids == ("finding-1",)
    assert report.suggestions[0].target == "skill_routing"


def test_excludes_dismissed_static_findings() -> None:
    run = completed_run()
    static = skill_report(run)
    dismissed = SkillAnalysisReview(
        finding_id="finding-1",
        decision=ReviewDecision.DISMISSED,
        reviewer_id="reviewer-1",
        reviewed_at=NOW,
    )
    report = OptimizationAnalysis(
        RepositoryStub(
            run,
            (failed_result(),),
            static,
            (dismissed,),
            (execution_trace(),),
        ),
        root_cause_model_client=RecordingModelClient(),
        root_cause_model_id="model-1",
    ).analyze_run(run.id, static.id)

    assert report.hypotheses[0].static_finding_ids == ()
    assert report.suggestions[0].target == "agent_routing"


def test_rejects_missing_and_incomplete_runs() -> None:
    with pytest.raises(OptimizationRunNotFound):
        OptimizationAnalysis(RepositoryStub(None)).analyze_run("missing")

    completed = completed_run()
    pending = EvaluationRun(
        id=completed.id,
        manifest=completed.manifest,
        created_at=NOW,
    )
    with pytest.raises(OptimizationRunNotCompleted):
        OptimizationAnalysis(RepositoryStub(pending)).analyze_run(pending.id)


def test_rejects_missing_failed_and_mismatched_static_reports() -> None:
    run = completed_run()
    application = OptimizationAnalysis(
        RepositoryStub(run, (failed_result(),))
    )
    with pytest.raises(OptimizationSkillAnalysisReportNotFound):
        application.analyze_run(run.id, "missing")

    failed = skill_report(run, status=SkillAnalysisStatus.FAILED)
    with pytest.raises(OptimizationSkillAnalysisNotUsable):
        OptimizationAnalysis(
            RepositoryStub(run, (failed_result(),), failed)
        ).analyze_run(run.id, failed.id)

    matching = skill_report(run)
    mismatched = matching.model_copy(
        update={"target_descriptor_sha256": "e" * 64}
    )
    with pytest.raises(OptimizationSkillAnalysisMismatch):
        OptimizationAnalysis(
            RepositoryStub(run, (failed_result(),), mismatched)
        ).analyze_run(run.id, mismatched.id)


def test_requires_nonblank_run_and_static_report_ids() -> None:
    run = completed_run()
    application = OptimizationAnalysis(
        RepositoryStub(run, (failed_result(),))
    )
    with pytest.raises(ValueError, match="EvaluationRun id"):
        application.analyze_run(" ")
    with pytest.raises(ValueError, match="SkillAnalysisReport id"):
        application.analyze_run(run.id, " ")


def test_all_pass_run_works_without_model_configuration() -> None:
    run = completed_run()
    report = OptimizationAnalysis(
        RepositoryStub(
            run,
            (passed_result(),),
            traces=(execution_trace(),),
        )
    ).analyze_run(run.id)

    assert report.failed_result_count == 0
    assert report.hypotheses == ()


def test_failed_run_without_model_fails_explicitly() -> None:
    run = completed_run()
    with pytest.raises(JudgeModelUnavailable, match="not configured"):
        OptimizationAnalysis(
            RepositoryStub(
                run,
                (failed_result(),),
                traces=(execution_trace(),),
            )
        ).analyze_run(run.id)


@pytest.mark.parametrize(
    "arguments",
    [
        {"root_cause_model_client": RecordingModelClient()},
        {"root_cause_model_id": "model-1"},
    ],
)
def test_constructor_requires_model_client_and_id_together(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="configured together"):
        OptimizationAnalysis(RepositoryStub(None), **arguments)


def test_constructor_validates_model_id_and_timeout() -> None:
    with pytest.raises(ValueError, match="model_id"):
        OptimizationAnalysis(
            RepositoryStub(None),
            root_cause_model_client=RecordingModelClient(),
            root_cause_model_id=" ",
        )
    with pytest.raises(ValueError, match="timeout"):
        OptimizationAnalysis(
            RepositoryStub(None),
            root_cause_timeout_seconds=0,
        )


def test_provider_failure_propagates_unchanged() -> None:
    run = completed_run()
    client = RecordingModelClient(JudgeModelTimeout("timed out"))
    application = OptimizationAnalysis(
        RepositoryStub(
            run,
            (failed_result(),),
            traces=(execution_trace(),),
        ),
        root_cause_model_client=client,
        root_cause_model_id="model-1",
    )

    with pytest.raises(JudgeModelTimeout, match="timed out"):
        application.analyze_run(run.id)
