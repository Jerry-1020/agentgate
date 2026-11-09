"""Read-only arithmetic differences of historical scores with condition evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from statistics import mean
from typing import Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from agentgate.domain import (
    DomainModel,
    EvaluationReport,
    EvaluationResult,
    EvaluatorKind,
    EvaluatorSpec,
    Outcome,
    ReleaseGateDecision,
    RunStatus,
)
from agentgate.domain.base import require_non_blank

ComparisonReason: TypeAlias = Literal[
    "target_changed",
    "dataset_changed",
    "case_scope_changed",
    "case_content_changed",
    "case_missing",
    "evaluator_changed",
    "evaluator_missing",
    "evaluator_snapshot_incomplete",
    "metric_plan_changed",
    "result_missing",
    "evaluation_error",
    "scored_scope_changed",
    "score_unavailable",
    "gate_changed",
]
ScoreLevel: TypeAlias = Literal["overall", "kind", "evaluator", "case"]
ScoreChange: TypeAlias = Literal["improvement", "regression", "unchanged", "changed"]
EvaluatorSignature: TypeAlias = tuple[tuple[str, str, str], ...]
ResultIndex: TypeAlias = Mapping[tuple[str, str], EvaluationResult]
_LLM_KINDS = {EvaluatorKind.LLM_JUDGE, EvaluatorKind.LLM_GROUP}


def _change(a: Outcome | None, b: Outcome | None, delta: float) -> ScoreChange:
    if a == b and delta == 0:
        return "unchanged"
    if a == Outcome.PASS and b != Outcome.PASS:
        return "regression"
    if a != Outcome.PASS and b == Outcome.PASS:
        return "improvement"
    if delta != 0:
        return "improvement" if delta > 0 else "regression"
    return "changed"


class HistoricalScoreComparison(DomainModel):
    """Original scores and B minus A, retaining condition differences separately."""

    level: ScoreLevel
    key: str
    case_id: str | None = None
    baseline_score: float | None = Field(default=None, ge=0, le=1)
    candidate_score: float | None = Field(default=None, ge=0, le=1)
    baseline_outcome: Outcome | None = None
    candidate_outcome: Outcome | None = None
    comparable: bool
    reasons: tuple[ComparisonReason, ...] = ()
    score_delta: float | None = Field(default=None, ge=-1, le=1)
    change: ScoreChange | None = None

    @field_validator("key", "case_id")
    @classmethod
    def validate_identity(cls, value: str | None) -> str | None:
        return require_non_blank(value, "comparison identity") if value is not None else value

    @model_validator(mode="after")
    def validate_comparison(self) -> HistoricalScoreComparison:
        if (self.level == "case") != (self.case_id is not None):
            raise ValueError("only case rows require a case_id")
        if self.level == "overall" and self.key != "overall":
            raise ValueError("overall row requires the overall key")
        if self.level == "kind" and self.key not in {"llm", "rule"}:
            raise ValueError("kind row requires llm or rule")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("comparison reasons must be unique")
        if self.comparable != (not self.reasons):
            raise ValueError("comparability must agree with reasons")
        has_scores = self.baseline_score is not None and self.candidate_score is not None
        if self.comparable and not has_scores:
            raise ValueError("comparable rows require both scores")
        if has_scores:
            if self.score_delta != self.candidate_score - self.baseline_score:
                raise ValueError("score delta must equal candidate minus baseline")
        elif self.score_delta is not None:
            raise ValueError("rows missing a score cannot contain a score delta")
        if self.level != "case" and (
            self.baseline_outcome is not None or self.candidate_outcome is not None
        ):
            raise ValueError("only case rows contain evaluator outcomes")
        if self.level == "case" and has_scores:
            if self.baseline_outcome not in {Outcome.PASS, Outcome.FAIL, Outcome.REVIEW} or (
                self.candidate_outcome not in {Outcome.PASS, Outcome.FAIL, Outcome.REVIEW}
            ):
                raise ValueError("case rows with both scores require scored outcomes")
            expected = _change(self.baseline_outcome, self.candidate_outcome, self.score_delta)
            if self.change != expected:
                raise ValueError("case change must agree with outcomes and scores")
        elif self.change is not None:
            raise ValueError("only case rows with both scores can classify change")
        return self


class HistoricalComparison(DomainModel):
    """Transient comparison output; source reports and storage models are unchanged."""

    baseline_run_id: str
    candidate_run_id: str
    baseline_gate: ReleaseGateDecision
    candidate_gate: ReleaseGateDecision
    gate_reasons: tuple[ComparisonReason, ...] = ()
    score_rows: tuple[HistoricalScoreComparison, ...]
    case_rows: tuple[HistoricalScoreComparison, ...]

    @field_validator("baseline_run_id", "candidate_run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return require_non_blank(value, "comparison run id")

    @model_validator(mode="after")
    def validate_rows(self) -> HistoricalComparison:
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("historical comparison requires distinct runs")
        if any(row.level == "case" for row in self.score_rows) or any(
            row.level != "case" for row in self.case_rows
        ):
            raise ValueError("score and case rows must be separate")
        identities = [(row.level, row.key, row.case_id) for row in self.score_rows + self.case_rows]
        if len(set(identities)) != len(identities):
            raise ValueError("comparison row identities must be unique")
        summaries = {(row.level, row.key) for row in self.score_rows if row.level != "evaluator"}
        if summaries != {("overall", "overall"), ("kind", "llm"), ("kind", "rule")}:
            raise ValueError("comparison requires overall, LLM and rule summaries")
        overall = next(row for row in self.score_rows if row.level == "overall")
        if (overall.baseline_score, overall.candidate_score) != (
            self.baseline_gate.score,
            self.candidate_gate.score,
        ):
            raise ValueError("overall scores must preserve the original gate scores")
        if len(set(self.gate_reasons)) != len(self.gate_reasons) or not set(
            overall.reasons
        ).issubset(self.gate_reasons):
            raise ValueError("gate comparability must include overall score limitations")
        if self.baseline_gate.minimum_score != self.candidate_gate.minimum_score and (
            "gate_changed" not in self.gate_reasons
        ):
            raise ValueError("different gate thresholds must be disclosed")
        return self


def _signature(specs: Mapping[str, EvaluatorSpec], evaluator_id: str) -> EvaluatorSignature | None:
    """Include transitive child snapshots, not just a composite's child references."""
    found: dict[str, tuple[str, str, str]] = {}
    visiting: set[str] = set()

    def visit(identity: str) -> bool:
        if identity in visiting or identity not in specs:
            return False
        if identity in found:
            return True
        spec = specs[identity]
        visiting.add(identity)
        for child in spec.children:
            if (
                child.evaluator_id not in specs
                or (specs[child.evaluator_id].version != child.evaluator_version)
                or not visit(child.evaluator_id)
            ):
                return False
        visiting.remove(identity)
        found[identity] = (identity, spec.version, spec.content_sha256)
        return True

    return tuple(sorted(found.values())) if visit(evaluator_id) else None


def _evaluator_reasons(
    a: Mapping[str, EvaluatorSignature | None],
    b: Mapping[str, EvaluatorSignature | None],
    a_ids: Sequence[str],
    b_ids: Sequence[str],
) -> list[ComparisonReason]:
    reasons: list[ComparisonReason] = []
    if not a_ids or not b_ids:
        reasons.append("evaluator_missing")
    if tuple(a_ids) != tuple(b_ids):
        reasons.append("evaluator_changed")
    if any(a[identity] is None for identity in a_ids) or any(
        b[identity] is None for identity in b_ids
    ):
        reasons.append("evaluator_snapshot_incomplete")
    if any(a[identity] != b[identity] for identity in set(a_ids).intersection(b_ids)):
        reasons.append("evaluator_changed")
    return reasons


def _case_mean(results: Iterable[EvaluationResult]) -> float | None:
    scores: dict[str, list[float]] = defaultdict(list)
    for result in results:
        if result.score is not None:
            scores[result.case_id].append(result.score)
    return mean(mean(values) for values in scores.values()) if scores else None


def _score(report: EvaluationReport, level: ScoreLevel, key: str) -> float | None:
    if level == "evaluator":
        if key not in report.run.manifest.primary_evaluator_ids:
            return None
        return _case_mean(result for result in report.results if result.evaluator_id == key)
    if key != "llm":
        return next(
            (
                metric.score
                for metric in report.metrics
                if metric.level == level and metric.key == key
            ),
            None,
        )
    summaries = [
        metric for metric in report.metrics if metric.level == "kind" and metric.key in _LLM_KINDS
    ]
    if len(summaries) == 1:
        return summaries[0].score
    # Match the existing UI: average metrics after averaging their per-case LLM scores.
    by_metric: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in report.results:
        if (
            result.evaluator_id in report.run.manifest.primary_evaluator_ids
            and result.evaluator_kind in _LLM_KINDS
        ):
            by_metric[result.metric].append(result)
    scores = [_case_mean(results) for results in by_metric.values()]
    numeric = [score for score in scores if score is not None]
    return mean(numeric) if numeric else None


def _result_reasons(
    a: ResultIndex,
    b: ResultIndex,
    a_keys: set[tuple[str, str]],
    b_keys: set[tuple[str, str]],
) -> list[ComparisonReason]:
    reasons: list[ComparisonReason] = []
    a_present = {key for key in a_keys if key in a}
    b_present = {key for key in b_keys if key in b}
    if a_present != a_keys or b_present != b_keys:
        reasons.append("result_missing")
    if any(a[key].outcome == Outcome.ERROR for key in a_present) or any(
        b[key].outcome == Outcome.ERROR for key in b_present
    ):
        reasons.append("evaluation_error")
    a_scored = {key for key in a_present if a[key].score is not None}
    b_scored = {key for key in b_present if b[key].score is not None}
    if a_scored != b_scored:
        reasons.append("scored_scope_changed")
    return reasons


def _row(
    level: ScoreLevel,
    key: str,
    a: float | None,
    b: float | None,
    reasons: Sequence[ComparisonReason],
    *,
    case_id: str | None = None,
    before: Outcome | None = None,
    after: Outcome | None = None,
) -> HistoricalScoreComparison:
    limitations = list(reasons)
    if a is None or b is None:
        limitations.append("score_unavailable")
    delta = b - a if a is not None and b is not None else None
    return HistoricalScoreComparison(
        level=level,
        key=key,
        case_id=case_id,
        baseline_score=a,
        candidate_score=b,
        baseline_outcome=before,
        candidate_outcome=after,
        comparable=not limitations,
        reasons=tuple(dict.fromkeys(limitations)),
        score_delta=delta,
        change=_change(before, after, delta) if level == "case" and delta is not None else None,
    )


def compare_historical_reports(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> HistoricalComparison:
    """Compare original scores without executing, normalizing or persisting either run."""
    if baseline.run.id == candidate.run.id:
        raise ValueError("historical comparison requires distinct runs")
    if any(report.run.status != RunStatus.COMPLETED for report in (baseline, candidate)):
        raise ValueError("historical comparison requires completed reports")
    a, b = baseline.run.manifest, candidate.run.manifest
    a_specs = {spec.id: spec for spec in a.evaluator_specs}
    b_specs = {spec.id: spec for spec in b.evaluator_specs}
    a_signatures = {identity: _signature(a_specs, identity) for identity in a.primary_evaluator_ids}
    b_signatures = {identity: _signature(b_specs, identity) for identity in b.primary_evaluator_ids}
    a_cases = {case.id: case for case in a.execution_cases}
    b_cases = {case.id: case for case in b.execution_cases}
    a_results = {(result.case_id, result.evaluator_id): result for result in baseline.results}
    b_results = {(result.case_id, result.evaluator_id): result for result in candidate.results}
    target_reasons: list[ComparisonReason] = []
    ar, br = a.target.ref, b.target.ref
    if (ar.source_id, ar.target_type, ar.external_target_id) != (
        br.source_id,
        br.target_type,
        br.external_target_id,
    ):
        target_reasons.append("target_changed")
    summary_reasons = list(target_reasons)
    if (a.dataset.dataset_id, a.dataset.content_sha256) != (
        b.dataset.dataset_id,
        b.dataset.content_sha256,
    ):
        summary_reasons.append("dataset_changed")
    if tuple(a_cases) != tuple(b_cases):
        summary_reasons.append("case_scope_changed")
    if any(a_cases[identity] != b_cases[identity] for identity in a_cases.keys() & b_cases.keys()):
        summary_reasons.append("case_content_changed")
    if a.metric_plan != b.metric_plan:
        summary_reasons.append("metric_plan_changed")

    groups: list[tuple[ScoreLevel, str, tuple[str, ...], tuple[str, ...]]] = [
        ("overall", "overall", a.primary_evaluator_ids, b.primary_evaluator_ids),
    ]
    for key, kinds in (("llm", _LLM_KINDS), ("rule", {EvaluatorKind.RULE})):
        groups.append(
            (
                "kind",
                key,
                tuple(
                    identity
                    for identity in a.primary_evaluator_ids
                    if a_specs[identity].kind in kinds
                ),
                tuple(
                    identity
                    for identity in b.primary_evaluator_ids
                    if b_specs[identity].kind in kinds
                ),
            )
        )
    for identity in dict.fromkeys(a.primary_evaluator_ids + b.primary_evaluator_ids):
        groups.append(
            (
                "evaluator",
                identity,
                (identity,) if identity in a_signatures else (),
                (identity,) if identity in b_signatures else (),
            )
        )

    score_rows = []
    for level, key, a_ids, b_ids in groups:
        reasons = summary_reasons + _evaluator_reasons(a_signatures, b_signatures, a_ids, b_ids)
        reasons += _result_reasons(
            a_results,
            b_results,
            {(case, evaluator) for case in a_cases for evaluator in a_ids},
            {(case, evaluator) for case in b_cases for evaluator in b_ids},
        )
        score_rows.append(
            _row(level, key, _score(baseline, level, key), _score(candidate, level, key), reasons)
        )

    a_keys = {(case, evaluator) for case in a_cases for evaluator in a.primary_evaluator_ids}
    b_keys = {(case, evaluator) for case in b_cases for evaluator in b.primary_evaluator_ids}
    ordered_keys = dict.fromkeys(
        [(case, evaluator) for case in a_cases for evaluator in a.primary_evaluator_ids]
        + [(case, evaluator) for case in b_cases for evaluator in b.primary_evaluator_ids]
    )
    case_rows = []
    for case_id, evaluator_id in ordered_keys:
        identity = (case_id, evaluator_id)
        before = a_results.get(identity) if identity in a_keys else None
        after = b_results.get(identity) if identity in b_keys else None
        reasons = target_reasons + _evaluator_reasons(
            a_signatures,
            b_signatures,
            (evaluator_id,) if evaluator_id in a_signatures else (),
            (evaluator_id,) if evaluator_id in b_signatures else (),
        )
        if case_id not in a_cases or case_id not in b_cases:
            reasons.append("case_missing")
        elif a_cases[case_id] != b_cases[case_id]:
            reasons.append("case_content_changed")
        reasons += _result_reasons(
            a_results,
            b_results,
            {identity} if identity in a_keys else set(),
            {identity} if identity in b_keys else set(),
        )
        case_rows.append(
            _row(
                "case",
                evaluator_id,
                before.score if before else None,
                after.score if after else None,
                reasons,
                case_id=case_id,
                before=before.outcome if before else None,
                after=after.outcome if after else None,
            )
        )
    gate_reasons = list(score_rows[0].reasons)
    if a.gate_spec != b.gate_spec:
        gate_reasons.append("gate_changed")
    return HistoricalComparison(
        baseline_run_id=baseline.run.id,
        candidate_run_id=candidate.run.id,
        baseline_gate=baseline.release_gate,
        candidate_gate=candidate.release_gate,
        gate_reasons=tuple(dict.fromkeys(gate_reasons)),
        score_rows=tuple(score_rows),
        case_rows=tuple(case_rows),
    )
