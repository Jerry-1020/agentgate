"""Case-level composition of cached, version-pinned child results."""

import math

from agentgate.domain import EvaluatorKind, Outcome, FailureStage
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate


class CompositeEvaluator:
    kind = EvaluatorKind.HYBRID
    implementation_id = "composite"
    implementation_version = "1"

    def validate_spec(self, spec):
        if set(spec.config) - {"pass_threshold"}:
            raise ValueError("unsupported composite configuration")
        threshold = spec.config.get("pass_threshold", 0.8)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("pass_threshold must be between 0 and 1")
        if spec.combination == "weighted_score" and not math.isclose(sum(c.weight for c in spec.children), 1.0):
            raise ValueError("composite weights must sum to 1")

    def evaluate_case(self, spec, case, trace, resolve):
        self.validate_spec(spec)
        children = [(ref, resolve(ref.evaluator_id)) for ref in spec.children]
        if any(result.outcome == Outcome.ERROR for _, result in children):
            raise ValueError("composite child evaluation failed")
        applicable = [(ref, r) for ref, r in children if r.outcome != Outcome.NOT_APPLICABLE]
        score = None
        outcome = Outcome.NOT_APPLICABLE
        if applicable:
            if any(r.score is None for _, r in applicable):
                raise ValueError("composite child score missing")
            score = sum(r.score for _, r in applicable) / len(applicable)
            if spec.combination == "weighted_score":
                score = sum(ref.weight * r.score for ref, r in applicable) / sum(ref.weight for ref, _ in applicable)
                passed = score >= spec.config.get("pass_threshold", 0.8)
            elif spec.combination == "all":
                passed = all(r.outcome == Outcome.PASS for _, r in applicable)
            else:
                passed = any(r.outcome == Outcome.PASS for _, r in applicable)
            if any(r.severity == "blocking" and r.outcome == Outcome.FAIL for _, r in applicable):
                outcome = Outcome.FAIL
            elif any(r.outcome == Outcome.REVIEW for _, r in applicable):
                outcome = Outcome.REVIEW
            else:
                outcome = Outcome.PASS if passed else Outcome.FAIL
        return Evaluation(checks=(CheckDraft(
            name="复合评估", outcome=outcome, score=score,
            reason="按已发布子评估器结果聚合；不适用子项排除后权重重新归一化，待复核项保留人工复核。",
            expected={"combination": spec.combination, "pass_threshold": spec.config.get("pass_threshold", 0.8)},
            actual=[{"result_id": r.id, "evaluator_id": r.evaluator_id, "version": r.evaluator_version,
                     "outcome": r.outcome, "score": r.score} for _, r in children],
            failure=FailureCandidate(stage=FailureStage.RESULT_INTERPRETATION, at_trace_completion=True) if outcome == Outcome.FAIL else None,
        ),))
