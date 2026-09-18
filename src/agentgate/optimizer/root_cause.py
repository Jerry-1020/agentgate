"""LLM-backed, evidence-constrained root-cause hypotheses."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from agentgate.domain import (
    Case,
    EvaluationResult,
    FailureCluster,
    RootCauseHypothesis,
    RoutingConfusionMatrix,
    SkillAnalysisFinding,
    Trace,
    content_sha256,
    canonical_json,
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
    supported = {span_id for member in cluster.members for span_id in member.span_ids}
    return tuple(
        sorted(
            {
                span.span_id
                for trace in traces
                if trace.trace_id in trace_ids
                for span in trace.spans
                if span.span_id in supported
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
        for attempt in range(2):
            response = model_client.complete(request)
            try:
                parsed = parse_root_cause_response(
                    response.text,
                    expected_cluster_id=cluster.id,
                    allowed_result_ids={member.result_id for member in cluster.members},
                    allowed_span_ids=_allowed_span_ids(cluster, trace_items),
                    allowed_static_finding_ids=_allowed_finding_ids(cluster, routing_matrix, finding_items),
                )
                break
            except RootCauseContractError as error:
                if attempt:
                    raise JudgeModelInvalidResponse(
                        "Root-cause model returned invalid structured output"
                    ) from error
                request = replace(request, system_prompt=(request.system_prompt or "") + (
                    " This is the final contract-correction attempt. The previous output was invalid. "
                    "Copy identifiers exactly from reference_ids, never from Case or check IDs. "
                    "Use only 1 to 3 representative result_ids and at most 3 span_ids. "
                    "Confidence MUST be nonnegative certainty in your hypothesis (0.0 to 1.0). "
                    "A confident diagnosis of a bad Agent or bad test expectation uses positive "
                    "confidence such as 0.9, NEVER -0.9 or -1. Use 0.0 if uncertain. "
                    "Do not invent or shorten identifiers. Return all required fields and no extra fields."
                    " Allowed span_ids are exactly " + canonical_json(_allowed_span_ids(cluster, trace_items)) +
                    "; if empty, return span_ids: []. Other IDs visible inside Trace are NOT valid citations. "
                    "Do not output confidence=-1 as an unknown sentinel; use confidence=0.0 instead."
                ))

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
