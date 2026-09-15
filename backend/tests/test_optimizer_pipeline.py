import json
from datetime import UTC, datetime, timedelta

import pytest

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
    RunManifest,
    RunStatus,
    SkillAnalysisFinding,
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
from agentgate.optimizer import build_optimization_report


NOW = datetime(2026, 9, 11, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


class RecordingModelClient:
    provider_id = "provider-1"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[JudgeRequest] = []

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        reference_line = request.user_prompt.splitlines()[2]
        references = json.loads(reference_line)
        return JudgeResponse(
            text=json.dumps(
                {
                    "cluster_id": references["cluster_id"],
                    "category": "routing_confusion",
                    "title": "Ambiguous routing responsibilities",
                    "explanation": "The trace and evaluator evidence indicate overlap.",
                    "confidence": 0.8,
                    "result_ids": references["result_ids"],
                    "span_ids": references["span_ids"],
                    "static_finding_ids": references["static_finding_ids"],
                }
            ),
            resolved_model_id="resolved-model-1",
        )


def evaluation_case(case_id: str = "case-1") -> Case:
    return Case(
        id=case_id,
        name="Routing case",
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


def run(*, status: RunStatus = RunStatus.COMPLETED) -> EvaluationRun:
    dataset = DatasetVersion(
        id="dataset-version-1",
        dataset_id="dataset-1",
        dataset_name="Dataset",
        version=1,
        status=DatasetVersionStatus.PUBLISHED,
        cases=(evaluation_case(),),
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
    if status == RunStatus.PENDING:
        return EvaluationRun(id="run-1", manifest=manifest, created_at=NOW)
    return EvaluationRun(
        id="run-1",
        manifest=manifest,
        status=RunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )


def result(
    *,
    actual: str = "loan",
    failed: bool = False,
    run_id: str = "run-1",
    case_id: str = "case-1",
    trace_id: str = TRACE_ID,
) -> EvaluationResult:
    check = CheckResult(
        id="check-1",
        name="route",
        turn_id="turn-1",
        expectation_id="route-1",
        outcome=Outcome.FAIL if failed else Outcome.PASS,
        score=0 if failed else 1,
        reason="wrong route" if failed else "correct route",
        expected={"kind": "equals", "expected": "loan"},
        actual=actual,
        span_ids=(SPAN_ID,),
        failure_stage=FailureStage.ROUTING if failed else None,
        failure_sequence=1 if failed else None,
        failure_span_id=SPAN_ID if failed else None,
    )
    return EvaluationResult(
        id="result-1",
        run_id=run_id,
        case_id=case_id,
        trace_id=trace_id,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256="d" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.FAIL if failed else Outcome.PASS,
        score=0 if failed else 1,
        reason="failed" if failed else "passed",
        checks=(check,),
        primary_failure_stage=FailureStage.ROUTING if failed else None,
    )


def trace(
    *,
    run_id: str = "run-1",
    case_id: str = "case-1",
    trace_id: str = TRACE_ID,
) -> Trace:
    return Trace(
        trace_id=trace_id,
        run_id=run_id,
        case_id=case_id,
        spans=(
            TraceSpan(
                trace_id=trace_id,
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


def static_finding() -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id="finding-1",
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.8,
        skill_ids=("loan", "card"),
        reason="descriptions overlap",
        evidence=({"source": "test"},),
    )


def build(
    *,
    evaluation_run: EvaluationRun | None = None,
    results: tuple[EvaluationResult, ...] | None = None,
    traces: tuple[Trace, ...] | None = None,
    findings: tuple[SkillAnalysisFinding, ...] = (),
    client: RecordingModelClient | None = None,
    model_id: str | None = "model-1",
):
    configured_client = client or RecordingModelClient()
    report = build_optimization_report(
        evaluation_run or run(),
        results if results is not None else (result(actual="card", failed=True),),
        traces if traces is not None else (trace(),),
        findings,
        model_client=configured_client,
        model_id=model_id,
    )
    return report, configured_client


def test_composes_llm_report_with_manifest_provenance() -> None:
    completed = run()

    report, client = build(evaluation_run=completed)

    assert report.run_id == completed.id
    assert report.target_ref == completed.manifest.target.ref
    assert report.target_content_sha256 == completed.manifest.target.content_sha256
    assert report.dataset_id == completed.manifest.dataset.dataset_id
    assert report.dataset_version == 1
    assert report.dataset_content_sha256 == completed.manifest.dataset.content_sha256
    assert report.analyzer_version == "2"
    assert report.failed_result_count == 1
    assert len(report.clusters) == 1
    assert report.confusion_matrix.eligible_count == 1
    assert len(report.hypotheses) == 1
    assert len(report.suggestions) == 1
    assert len(client.requests) == 1
    assert TRACE_ID in client.requests[0].user_prompt


def test_static_findings_flow_into_hypotheses_and_suggestions() -> None:
    finding = static_finding()

    report, _ = build(findings=(finding,))

    assert report.hypotheses[0].static_finding_ids == (finding.id,)
    assert report.suggestions[0].target == "skill_routing"


def test_successful_run_needs_no_model_and_makes_no_model_call() -> None:
    client = RecordingModelClient()
    report = build_optimization_report(
        run(),
        (result(),),
        (trace(),),
        model_client=None,
        model_id=None,
    )

    assert report.failed_result_count == 0
    assert report.clusters == ()
    assert report.hypotheses == ()
    assert report.suggestions == ()
    assert report.confusion_matrix.eligible_count == 1
    assert client.requests == []


def test_failed_run_requires_complete_model_configuration() -> None:
    with pytest.raises(
        JudgeModelUnavailable,
        match="Root-cause model is not configured",
    ):
        build_optimization_report(
            run(),
            (result(failed=True),),
            (trace(),),
            model_client=None,
            model_id=None,
        )

    with pytest.raises(ValueError, match="configured together"):
        build_optimization_report(
            run(),
            (result(failed=True),),
            (trace(),),
            model_client=RecordingModelClient(),
            model_id=None,
        )


def test_requires_completed_run_and_owned_results_and_traces() -> None:
    with pytest.raises(ValueError, match="completed EvaluationRun"):
        build_optimization_report(
            run(status=RunStatus.PENDING),
            (),
            (),
            model_client=None,
            model_id=None,
        )
    with pytest.raises(ValueError, match="Results must belong"):
        build_optimization_report(
            run(),
            (result(run_id="another-run"),),
            (),
            model_client=None,
            model_id=None,
        )
    with pytest.raises(ValueError, match="Traces must belong"):
        build_optimization_report(
            run(),
            (),
            (trace(run_id="another-run"),),
            model_client=None,
            model_id=None,
        )


@pytest.mark.parametrize(
    ("results", "traces", "message"),
    [
        ((result(case_id="foreign-case"),), (), "Result references a Case outside"),
        ((), (trace(case_id="foreign-case"),), "Trace references a Case outside"),
        ((result(), result()), (), "Result identities must be unique"),
        ((), (trace(), trace()), "Trace identities must be unique"),
    ],
)
def test_rejects_foreign_cases_and_duplicate_evidence(
    results: tuple[EvaluationResult, ...],
    traces: tuple[Trace, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_optimization_report(
            run(),
            results,
            traces,
            model_client=None,
            model_id=None,
        )


def test_rejects_missing_or_mismatched_failed_trace_before_model_call() -> None:
    client = RecordingModelClient()
    with pytest.raises(ValueError, match="missing Trace evidence"):
        build_optimization_report(
            run(),
            (result(failed=True),),
            (),
            model_client=client,
            model_id="model-1",
        )
    assert client.requests == []

    mismatched = trace(trace_id=TRACE_ID).model_copy(update={"case_id": "other"})
    with pytest.raises(ValueError, match="Case outside"):
        build_optimization_report(
            run(),
            (result(failed=True),),
            (mismatched,),
            model_client=client,
            model_id="model-1",
        )
    assert client.requests == []


def test_provider_failure_prevents_report_creation() -> None:
    client = RecordingModelClient(JudgeModelTimeout("timed out"))

    with pytest.raises(JudgeModelTimeout, match="timed out"):
        build(
            client=client,
        )
    assert len(client.requests) == 1


def test_requires_valid_configuration_values() -> None:
    with pytest.raises(ValueError, match="analyzer_version"):
        build_optimization_report(
            run(),
            (result(),),
            (trace(),),
            model_client=None,
            model_id=None,
            analyzer_version=" ",
        )
    with pytest.raises(ValueError, match="model_id"):
        build_optimization_report(
            run(),
            (result(),),
            (trace(),),
            model_client=RecordingModelClient(),
            model_id=" ",
        )
    with pytest.raises(ValueError, match="timeout"):
        build_optimization_report(
            run(),
            (result(),),
            (trace(),),
            model_client=None,
            model_id=None,
            root_cause_timeout_seconds=0,
        )


def test_analytical_content_hash_is_deterministic() -> None:
    first, _ = build()
    second, _ = build()

    assert first.content_sha256 == second.content_sha256
    assert first.model_dump(mode="json", exclude={"created_at"}) == second.model_dump(
        mode="json",
        exclude={"created_at"},
    )
