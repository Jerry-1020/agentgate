"""LLM-backed, evidence-constrained root-cause hypotheses."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    Case,
    EvaluationResult,
    FailureCluster,
    RootCauseHypothesis,
    RoutingConfusionMatrix,
    SkillAnalysisFinding,
    Trace,
    content_sha256,
)
from agentgate.evaluator.judge.model_protocol import (
    JudgeModelClient,
    JudgeModelInvalidResponse,
    request_fingerprint,
)
from agentgate.trace.redaction import redact_value

from .root_cause_contract import (
    ParsedRootCauseHypothesis,
    RootCauseContractError,
    parse_root_cause_response,
)
from .root_cause_prompt import build_root_cause_request


MODEL_TEMPERATURE = 0.0
MODEL_SEED = 0
MAX_OUTPUT_TOKENS = 1_200
MAX_INPUT_CHARS = 24_000


def _validate_cluster_ids(clusters: tuple[FailureCluster, ...]) -> None:
    cluster_ids = tuple(item.id for item in clusters)
    if len(set(cluster_ids)) != len(cluster_ids):
        raise ValueError("root-cause cluster IDs must be unique")


def _allowed_span_ids(
    cluster: FailureCluster,
    traces: tuple[Trace, ...],
) -> tuple[str, ...]:
    trace_ids = {member.trace_id for member in cluster.members}
    return tuple(
        sorted(
            {
                span.span_id
                for trace in traces
                if trace.trace_id in trace_ids
                for span in trace.spans
            }
        )
    )


def _allowed_finding_ids(
    cluster: FailureCluster,
    routing_matrix: RoutingConfusionMatrix,
    static_findings: tuple[SkillAnalysisFinding, ...],
) -> tuple[str, ...]:
    result_ids = {member.result_id for member in cluster.members}
    observations = tuple(
        observation
        for cell in routing_matrix.cells
        for observation in cell.observations
        if observation.result_id in result_ids
    )
    skill_ids = {item.expected_skill_id for item in observations}
    skill_ids.update(
        item.actual_route.skill_id
        for item in observations
        if item.actual_route.skill_id is not None
    )
    return tuple(
        sorted(
            finding.id
            for finding in static_findings
            if skill_ids.intersection(finding.skill_ids)
        )
    )


def _hypothesis_id(
    cluster: FailureCluster,
    parsed: ParsedRootCauseHypothesis,
    *,
    request_sha256: str,
    provider_id: str,
    resolved_model_id: str,
) -> str:
    digest = content_sha256(
        {
            "cluster_id": cluster.id,
            "request_sha256": request_sha256,
            "provider_id": provider_id,
            "resolved_model_id": resolved_model_id,
            "category": parsed.category,
            "title": parsed.title,
            "explanation": parsed.explanation,
            "confidence": parsed.confidence,
            "result_ids": parsed.result_ids,
            "span_ids": parsed.span_ids,
            "static_finding_ids": parsed.static_finding_ids,
        }
    )
    return f"root-cause-{digest[:24]}"


def infer_root_causes(
    clusters: Sequence[FailureCluster],
    cases: Sequence[Case],
    results: Sequence[EvaluationResult],
    traces: Sequence[Trace],
    routing_matrix: RoutingConfusionMatrix,
    static_findings: Sequence[SkillAnalysisFinding] = (),
    *,
    model_client: JudgeModelClient,
    model_id: str,
    timeout_seconds: float = 60,
) -> tuple[RootCauseHypothesis, ...]:
    """Generate one validated LLM hypothesis for each failure cluster."""

    cluster_items = tuple(clusters)
    _validate_cluster_ids(cluster_items)
    if not cluster_items:
        return ()

    case_items = tuple(cases)
    result_items = tuple(results)
    trace_items = tuple(traces)
    finding_items = tuple(static_findings)
    hypotheses: list[RootCauseHypothesis] = []
    for cluster in sorted(cluster_items, key=lambda item: item.id):
        request = build_root_cause_request(
            model_id=model_id,
            cluster=cluster,
            cases=case_items,
            results=result_items,
            traces=trace_items,
            routing_matrix=routing_matrix,
            static_findings=finding_items,
            temperature=MODEL_TEMPERATURE,
            seed=MODEL_SEED,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout_seconds=timeout_seconds,
            max_input_chars=MAX_INPUT_CHARS,
            redact=redact_value,
        )
        response = model_client.complete(request)
        try:
            parsed = parse_root_cause_response(
                response.text,
                expected_cluster_id=cluster.id,
                allowed_result_ids={member.result_id for member in cluster.members},
                allowed_span_ids=_allowed_span_ids(cluster, trace_items),
                allowed_static_finding_ids=_allowed_finding_ids(
                    cluster,
                    routing_matrix,
                    finding_items,
                ),
            )
        except RootCauseContractError as error:
            raise JudgeModelInvalidResponse(
                "Root-cause model returned invalid structured output"
            ) from error

        hypotheses.append(
            RootCauseHypothesis(
                id=_hypothesis_id(
                    cluster,
                    parsed,
                    request_sha256=request_fingerprint(request),
                    provider_id=model_client.provider_id,
                    resolved_model_id=response.resolved_model_id,
                ),
                category=parsed.category,
                title=parsed.title,
                explanation=parsed.explanation,
                confidence=parsed.confidence,
                cluster_ids=(cluster.id,),
                result_ids=parsed.result_ids,
                span_ids=parsed.span_ids,
                static_finding_ids=parsed.static_finding_ids,
            )
        )
    return tuple(
        sorted(
            hypotheses,
            key=lambda item: (-item.confidence, item.id),
        )
    )


__all__ = ["infer_root_causes"]
