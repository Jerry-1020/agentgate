from datetime import UTC, datetime

import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    EvaluationResult,
    EvaluatorKind,
    EvaluatorSeverity,
    FailedResultEvidence,
    FailureCluster,
    FailureStage,
    FindingSeverity,
    ObservedRoute,
    ObservedRouteKind,
    Outcome,
    RoutingConfusionCell,
    RoutingConfusionMatrix,
    RoutingObservation,
    SkillAnalysisFinding,
    Trace,
    TraceSpan,
)
from agentgate.optimizer.root_cause_prompt import build_root_cause_request


NOW = datetime(2026, 9, 10, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def case(case_id: str = "case-1") -> Case:
    return Case(
        id=case_id,
        name="Routing case",
        turns=(CaseTurn(id="turn-1", input={"message": "secret request"}),),
    )


def result(**changes: object) -> EvaluationResult:
    item = EvaluationResult(
        id="result-1",
        run_id="run-1",
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256="c" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.FAIL,
        score=0,
        reason="wrong route",
        checks=(
            CheckResult(
                id="check-1",
                name="route",
                outcome=Outcome.FAIL,
                score=0,
                reason="wrong route",
                failure_stage=FailureStage.ROUTING,
                failure_sequence=1,
                failure_span_id=SPAN_ID,
                span_ids=(SPAN_ID,),
            ),
        ),
        primary_failure_stage=FailureStage.ROUTING,
    )
    return item.model_copy(update=changes)


def trace(**changes: object) -> Trace:
    item = Trace(
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
                attributes={"selected": "card"},
            ),
        ),
        final_output={"message": "declined"},
    )
    return item.model_copy(update=changes)


def cluster() -> FailureCluster:
    member = FailedResultEvidence(
        run_id="run-1",
        case_id="case-1",
        result_id="result-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        failure_stage=FailureStage.ROUTING,
        reason="wrong route",
        span_ids=(SPAN_ID,),
    )
    return FailureCluster(
        id="cluster-1",
        category="routing",
        label="Routing failures",
        failure_stage=FailureStage.ROUTING,
        evaluator_id="routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        members=(member,),
        representative_result_ids=(member.result_id,),
        failure_count=1,
        case_count=1,
        share=1,
    )


def observation() -> RoutingObservation:
    return RoutingObservation(
        case_id="case-1",
        turn_id="turn-1",
        expectation_id="expectation-1",
        result_id="result-1",
        trace_id=TRACE_ID,
        expected_skill_id="loan",
        actual_route=ObservedRoute(
            kind=ObservedRouteKind.SKILL,
            skill_id="card",
        ),
        span_ids=(SPAN_ID,),
    )


def matrix() -> RoutingConfusionMatrix:
    item = observation()
    return RoutingConfusionMatrix(
        cells=(
            RoutingConfusionCell(
                expected_skill_id=item.expected_skill_id,
                actual_route=item.actual_route,
                observations=(item,),
                count=1,
            ),
        ),
        eligible_count=1,
    )


def finding(finding_id: str = "finding-1") -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id=finding_id,
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.8,
        skill_ids=("loan", "card"),
        reason="descriptions overlap",
        evidence=({"source": "test"},),
    )


def request(**overrides: object):
    arguments = {
        "model_id": "model-1",
        "cluster": cluster(),
        "cases": (case(),),
        "results": (result(),),
        "traces": (trace(),),
        "routing_matrix": matrix(),
        "static_findings": (finding(),),
        "temperature": 0.1,
        "seed": 7,
        "max_output_tokens": 900,
        "timeout_seconds": 12,
        "max_input_chars": 20_000,
        "redact": lambda value: value,
    }
    arguments.update(overrides)
    return build_root_cause_request(**arguments)


def test_builds_deterministic_request_with_explicit_model_settings() -> None:
    first = request()
    second = request()

    assert first == second
    assert first.model_id == "model-1"
    assert first.temperature == 0.1
    assert first.seed == 7
    assert first.max_output_tokens == 900
    assert first.timeout_seconds == 12
    assert first.response_format == "json_object"
    assert "requires human review" in first.system_prompt
    assert '"cluster_id":"cluster-1"' in first.user_prompt
    assert '"result_ids":["result-1"]' in first.user_prompt
    assert SPAN_ID in first.user_prompt
    assert '"static_finding_ids":["finding-1"]' in first.user_prompt


def test_redacts_evidence_but_preserves_reference_allowlists() -> None:
    built = request(redact=lambda _value: {"protected": True})

    assert "secret request" not in built.user_prompt
    assert '"protected":true' in built.user_prompt
    assert '"result_ids":["result-1"]' in built.user_prompt


def test_bounds_detailed_evidence_without_truncating_reference_ids() -> None:
    built = request(max_input_chars=160)

    assert '"truncated":true' in built.user_prompt
    assert '"cluster_id":"cluster-1"' in built.user_prompt
    assert '"result_ids":["result-1"]' in built.user_prompt


def test_excludes_unrelated_cases_results_traces_and_findings() -> None:
    unrelated_result = result(
        id="result-other",
        case_id="case-other",
        trace_id="d" * 32,
    )
    unrelated_trace = trace(
        trace_id="d" * 32,
        case_id="case-other",
        spans=(),
    )
    built = request(
        cases=(case(), case("case-other")),
        results=(result(), unrelated_result),
        traces=(trace(), unrelated_trace),
        static_findings=(finding(), finding("finding-other").model_copy(
            update={"skill_ids": ("payments",)}
        )),
    )

    assert "case-other" not in built.user_prompt
    assert "result-other" not in built.user_prompt
    assert "finding-other" not in built.user_prompt


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cases": ()}, "missing Case evidence"),
        ({"results": ()}, "missing EvaluationResult evidence"),
        ({"traces": ()}, "missing Trace evidence"),
        (
            {"results": (result(run_id="other-run"),)},
            "EvaluationResult evidence does not match",
        ),
        (
            {"traces": (trace(run_id="other-run"),)},
            "Trace evidence does not match",
        ),
    ],
)
def test_rejects_missing_or_mismatched_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        request(**overrides)


@pytest.mark.parametrize(
    ("field", "items", "message"),
    [
        ("cases", (case(), case()), "Case identities must be unique"),
        (
            "results",
            (result(), result()),
            "EvaluationResult identities must be unique",
        ),
        ("traces", (trace(), trace()), "Trace identities must be unique"),
        (
            "static_findings",
            (finding(), finding()),
            "SkillAnalysisFinding identities must be unique",
        ),
    ],
)
def test_rejects_duplicate_evidence_identities(
    field: str,
    items: tuple[object, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        request(**{field: items})


def test_rejects_missing_redaction_callable() -> None:
    with pytest.raises(TypeError, match="redaction callable"):
        request(redact=None)
