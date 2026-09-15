import json
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
from agentgate.evaluator.judge import (
    JudgeModelInvalidResponse,
    JudgeModelTimeout,
    JudgeRequest,
    JudgeResponse,
)
from agentgate.optimizer.root_cause import infer_root_causes


NOW = datetime(2026, 9, 11, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


class RecordingModelClient:
    provider_id = "provider-1"

    def __init__(self, responses: dict[str, str | Exception]) -> None:
        self.responses = responses
        self.requests: list[JudgeRequest] = []

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        cluster_id = next(
            item for item in self.responses if item in request.user_prompt
        )
        response = self.responses[cluster_id]
        if isinstance(response, Exception):
            raise response
        return JudgeResponse(
            text=response,
            resolved_model_id="resolved-model-1",
        )


def case(case_id: str) -> Case:
    return Case(
        id=case_id,
        name=f"Case {case_id}",
        turns=(CaseTurn(id=f"turn-{case_id}", input={"message": "apply"}),),
    )


def result(
    result_id: str,
    case_id: str,
    trace_id: str,
    span_id: str,
) -> EvaluationResult:
    return EvaluationResult(
        id=result_id,
        run_id="run-1",
        case_id=case_id,
        trace_id=trace_id,
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
                id=f"check-{result_id}",
                name="route",
                outcome=Outcome.FAIL,
                score=0,
                reason="wrong route",
                failure_stage=FailureStage.ROUTING,
                failure_sequence=1,
                failure_span_id=span_id,
                span_ids=(span_id,),
            ),
        ),
        primary_failure_stage=FailureStage.ROUTING,
    )


def trace(case_id: str, trace_id: str, span_id: str) -> Trace:
    return Trace(
        trace_id=trace_id,
        run_id="run-1",
        case_id=case_id,
        spans=(
            TraceSpan(
                trace_id=trace_id,
                span_id=span_id,
                name="route",
                operation_type="routing",
                sequence=1,
                started_at=NOW,
                ended_at=NOW,
            ),
        ),
    )


def cluster(
    cluster_id: str,
    result_id: str,
    case_id: str,
    trace_id: str,
    span_id: str,
) -> FailureCluster:
    member = FailedResultEvidence(
        run_id="run-1",
        case_id=case_id,
        result_id=result_id,
        trace_id=trace_id,
        evaluator_id="routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        failure_stage=FailureStage.ROUTING,
        reason="wrong route",
        span_ids=(span_id,),
    )
    return FailureCluster(
        id=cluster_id,
        category="routing",
        label="Routing failures",
        failure_stage=FailureStage.ROUTING,
        evaluator_id="routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        members=(member,),
        representative_result_ids=(result_id,),
        failure_count=1,
        case_count=1,
        share=1,
    )


def observation(
    result_id: str,
    case_id: str,
    trace_id: str,
    span_id: str,
) -> RoutingObservation:
    return RoutingObservation(
        case_id=case_id,
        turn_id=f"turn-{case_id}",
        expectation_id=f"expectation-{case_id}",
        result_id=result_id,
        trace_id=trace_id,
        expected_skill_id="loan",
        actual_route=ObservedRoute(
            kind=ObservedRouteKind.SKILL,
            skill_id="card",
        ),
        span_ids=(span_id,),
    )


def matrix(*items: RoutingObservation) -> RoutingConfusionMatrix:
    return RoutingConfusionMatrix(
        cells=(
            RoutingConfusionCell(
                expected_skill_id=items[0].expected_skill_id,
                actual_route=items[0].actual_route,
                observations=items,
                count=len(items),
            ),
        )
        if items
        else (),
        eligible_count=len(items),
    )


def finding() -> SkillAnalysisFinding:
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


def completion(
    cluster_id: str,
    result_id: str,
    span_id: str,
    *,
    confidence: float = 0.8,
    **overrides: object,
) -> str:
    payload: dict[str, object] = {
        "cluster_id": cluster_id,
        "category": "routing_confusion",
        "title": "Overlapping Skill descriptions",
        "explanation": "The routing evidence suggests ambiguous responsibilities.",
        "confidence": confidence,
        "result_ids": [result_id],
        "span_ids": [span_id],
        "static_finding_ids": ["finding-1"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def inputs():
    first = {
        "cluster": cluster("cluster-1", "result-1", "case-1", TRACE_ID, SPAN_ID),
        "case": case("case-1"),
        "result": result("result-1", "case-1", TRACE_ID, SPAN_ID),
        "trace": trace("case-1", TRACE_ID, SPAN_ID),
        "observation": observation("result-1", "case-1", TRACE_ID, SPAN_ID),
    }
    second_trace_id = "d" * 32
    second_span_id = "e" * 16
    second = {
        "cluster": cluster(
            "cluster-2",
            "result-2",
            "case-2",
            second_trace_id,
            second_span_id,
        ),
        "case": case("case-2"),
        "result": result("result-2", "case-2", second_trace_id, second_span_id),
        "trace": trace("case-2", second_trace_id, second_span_id),
        "observation": observation(
            "result-2", "case-2", second_trace_id, second_span_id
        ),
    }
    return first, second


def infer(client: RecordingModelClient, *, reverse: bool = False):
    first, second = inputs()
    ordered = (second, first) if reverse else (first, second)
    return infer_root_causes(
        tuple(item["cluster"] for item in ordered),
        tuple(item["case"] for item in ordered),
        tuple(item["result"] for item in ordered),
        tuple(item["trace"] for item in ordered),
        matrix(*(item["observation"] for item in ordered)),
        (finding(),),
        model_client=client,
        model_id="model-1",
        timeout_seconds=12,
    )


def valid_responses() -> dict[str, str]:
    return {
        "cluster-1": completion("cluster-1", "result-1", SPAN_ID),
        "cluster-2": completion(
            "cluster-2",
            "result-2",
            "e" * 16,
            confidence=0.6,
        ),
    }


def test_calls_model_once_per_cluster_and_builds_validated_hypotheses() -> None:
    client = RecordingModelClient(valid_responses())

    hypotheses = infer(client, reverse=True)

    assert len(client.requests) == 2
    assert "cluster-1" in client.requests[0].user_prompt
    assert "cluster-2" in client.requests[1].user_prompt
    assert [item.cluster_ids for item in hypotheses] == [
        ("cluster-1",),
        ("cluster-2",),
    ]
    assert hypotheses[0].title == "Overlapping Skill descriptions"
    assert hypotheses[0].result_ids == ("result-1",)
    assert hypotheses[0].span_ids == (SPAN_ID,)
    assert hypotheses[0].static_finding_ids == ("finding-1",)
    assert hypotheses[0].id.startswith("root-cause-")
    request = client.requests[0]
    assert request.temperature == 0
    assert request.seed == 0
    assert request.max_output_tokens == 1_200
    assert request.timeout_seconds == 12


def test_hypothesis_ids_and_output_order_are_deterministic() -> None:
    forward = infer(RecordingModelClient(valid_responses()))
    reverse = infer(RecordingModelClient(valid_responses()), reverse=True)

    assert forward == reverse


def test_empty_clusters_make_no_model_calls() -> None:
    client = RecordingModelClient({})

    assert infer_root_causes(
        (),
        (),
        (),
        (),
        matrix(),
        model_client=client,
        model_id="model-1",
    ) == ()
    assert client.requests == []


@pytest.mark.parametrize(
    "error",
    [
        JudgeModelTimeout("timed out"),
        ConnectionError("provider unavailable"),
    ],
)
def test_propagates_model_failures_without_rule_fallback(error: Exception) -> None:
    responses: dict[str, str | Exception] = valid_responses()
    responses["cluster-1"] = error
    client = RecordingModelClient(responses)

    with pytest.raises(type(error), match=str(error)):
        infer(client)


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        completion(
            "cluster-1",
            "invented-result",
            SPAN_ID,
        ),
        completion(
            "cluster-1",
            "result-1",
            "f" * 16,
        ),
        completion(
            "cluster-1",
            "result-1",
            SPAN_ID,
            static_finding_ids=["invented-finding"],
        ),
    ],
)
def test_normalizes_invalid_or_invented_model_output(response: str) -> None:
    responses = valid_responses()
    responses["cluster-1"] = response

    with pytest.raises(
        JudgeModelInvalidResponse,
        match="invalid structured output",
    ):
        infer(RecordingModelClient(responses))


def test_cluster_failure_returns_no_partial_hypothesis_tuple() -> None:
    responses: dict[str, str | Exception] = valid_responses()
    responses["cluster-2"] = JudgeModelTimeout("second cluster failed")
    client = RecordingModelClient(responses)

    with pytest.raises(JudgeModelTimeout, match="second cluster failed"):
        infer(client)
    assert len(client.requests) == 2


def test_rejects_duplicate_cluster_ids_before_calling_model() -> None:
    first, _ = inputs()
    client = RecordingModelClient(valid_responses())

    with pytest.raises(ValueError, match="cluster IDs must be unique"):
        infer_root_causes(
            (first["cluster"], first["cluster"]),
            (first["case"],),
            (first["result"],),
            (first["trace"],),
            matrix(first["observation"]),
            (finding(),),
            model_client=client,
            model_id="model-1",
        )
    assert client.requests == []
