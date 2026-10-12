"""Read evaluator snapshots and evidence for human annotation; never execute a model."""

import inspect
import json

from agentgate.domain import Case, EvaluationResult, EvaluatorSpec, Trace, canonical_json
from agentgate.evaluator.judge.answer_quality import build_answer_quality_request
from agentgate.evaluator.judge.dimension_quality import build_dimension_quality_request
from agentgate.evaluator.judge.model_protocol import request_fingerprint
from agentgate.evaluator.rule.operators import resolve_operator
from agentgate.evaluator.rule.output import FinalOutputEvaluator
from agentgate.evaluator.rule.policy import PolicyComplianceEvaluator
from agentgate.evaluator.rule.routing import SkillRoutingEvaluator
from agentgate.evaluator.rule.state import FinalStateEvaluator
from agentgate.evaluator.rule.tool_use import (
    ForbiddenToolEvaluator,
    RequiredToolEvaluator,
    ToolArgumentsEvaluator,
)
from agentgate.trace.redaction import redact_trace, redact_value


def evaluator_annotation_evidence(
    spec: EvaluatorSpec, case: Case, trace: Trace, result: EvaluationResult | None
) -> dict:
    """Expose persisted results and label reconstructed requests explicitly."""
    evidence = {"case": case.model_dump(mode="json"), "trace": trace.model_dump(mode="json")}
    payload = {
        "spec": spec.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result else None,
        "evidence": evidence,
        "code": [],
        "system_prompt": None,
        "user_prompt": None,
        "prompt_source": "unavailable",
        "request_hash_matches": None,
    }
    if spec.kind == "rule":
        implementation = next(
            (
                cls
                for cls in (
                    FinalOutputEvaluator,
                    FinalStateEvaluator,
                    SkillRoutingEvaluator,
                    PolicyComplianceEvaluator,
                    RequiredToolEvaluator,
                    ForbiddenToolEvaluator,
                    ToolArgumentsEvaluator,
                )
                if cls.implementation_id == spec.implementation_id
                and cls.implementation_version == spec.implementation_version
            ),
            None,
        )
        if implementation:
            payload["code"].append(
                {"name": spec.implementation_id, "source": inspect.getsource(implementation)}
            )
        seen = set()
        for check in result.checks if result else ():
            for method in check.methods:
                key = (method.implementation_id, method.implementation_version)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    payload["code"].append(
                        {"name": "@".join(key), "source": inspect.getsource(resolve_operator(*key))}
                    )
                except (ValueError, OSError, TypeError):
                    pass
    elif spec.kind == "llm_judge":
        record = result.judge_record if result else None
        if (
            record
            and record.request_system_prompt is not None
            and record.request_user_prompt is not None
        ):
            payload.update(
                system_prompt=record.request_system_prompt,
                user_prompt=record.request_user_prompt,
                prompt_source="recorded",
            )
        elif spec.implementation_id == "answer_quality" and spec.implementation_version in {"1", "2"}:
            try:
                build_request = (
                    build_answer_quality_request if spec.implementation_version == "1"
                    else build_dimension_quality_request
                )
                request = build_request(spec, case, trace)
                payload.update(
                    system_prompt=request.system_prompt,
                    user_prompt=request.user_prompt,
                    prompt_source="reconstructed",
                    request_hash_matches=request_fingerprint(request) == record.request_sha256
                    if record
                    else None,
                )
            except (ValueError, TypeError, KeyError):
                pass
    protected = json.loads(canonical_json(redact_value(payload)))
    # Redact evidence values without corrupting the identifiers used to save annotations.
    protected["spec"].update(id=spec.id, version=spec.version, content_sha256=spec.content_sha256)
    protected["code"] = payload["code"]
    protected["evidence"]["case"]["id"] = case.id
    for safe_turn, turn in zip(protected["evidence"]["case"]["turns"], case.turns, strict=True):
        safe_turn["id"] = turn.id
        for safe_expectation, expectation in zip(
            safe_turn["expectations"], turn.expectations, strict=True
        ):
            safe_expectation["id"] = expectation.id
    protected["evidence"]["trace"] = redact_trace(trace).model_dump(mode="json")
    if result:
        original = result.model_dump(mode="json")
        for key in (
            "id",
            "run_id",
            "trace_id",
            "case_id",
            "evaluator_id",
            "evaluator_version",
            "evaluator_content_sha256",
        ):
            protected["result"][key] = original[key]
        for safe_check, check in zip(
            protected["result"]["checks"], original["checks"], strict=True
        ):
            for key in ("id", "turn_id", "expectation_id", "span_ids", "failure_span_id"):
                safe_check[key] = check[key]
    return protected
