"""Historical comparisons subtract available scores while retaining difference evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    DatasetVersion,
    EvaluationReport,
    EvaluationResult,
    EvaluationRun,
    EvaluatorSpec,
    MetricPlan,
    ReleaseGateSpec,
    RunManifest,
    TargetRef,
    TargetSnapshot,
)
from agentgate.domain.result import EvaluatorErrorDetail, JudgeRecord
from agentgate.result.historical_comparison import HistoricalComparison, compare_historical_reports
from agentgate.result.report import build_evaluation_report

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def rule(identity="rule", **changes):
    return EvaluatorSpec(
        **{
            "id": identity,
            "name": identity,
            "dimension": "quality",
            "metric": "correctness",
            "implementation_id": "final_state",
            **changes,
        }
    )


def judge(identity="judge", **changes):
    return rule(
        identity,
        **{
            "kind": "llm_judge",
            "metric": "answer_quality",
            "implementation_id": "llm_judge",
            "config": {"model": {"provider_id": "test", "model_id": "test-model"}},
            **changes,
        },
    )


def group(child="judge", **changes):
    return rule(
        "group",
        **{
            "kind": "llm_group",
            "metric": "group_quality",
            "implementation_id": "llm_group",
            "children": ({"evaluator_id": child, "evaluator_version": "1", "weight": 1},),
            "combination": "weighted_score",
            **changes,
        },
    )


def case(identity="case-1", **changes):
    return Case(
        **{
            "id": identity,
            "name": identity,
            "turns": (CaseTurn(id="turn-1", input={"message": identity}),),
            **changes,
        }
    )


def result(run_id, sample, evaluator, score, outcome):
    failed = outcome == "fail"
    return EvaluationResult(
        run_id=run_id,
        case_id=sample.id,
        trace_id="a" * 32,
        evaluator_id=evaluator.id,
        evaluator_name=evaluator.name,
        evaluator_version=evaluator.version,
        evaluator_content_sha256=evaluator.content_sha256,
        evaluator_kind=evaluator.kind,
        dimension=evaluator.dimension,
        metric=evaluator.metric,
        severity=evaluator.severity,
        outcome=outcome,
        score=score,
        reason="Recorded evaluation",
        checks=()
        if outcome == "error"
        else (
            CheckResult(
                name="Recorded check",
                outcome=outcome,
                score=score,
                reason="Recorded check result",
                failure_stage="final_state" if failed else None,
                failure_sequence=1 if failed else None,
            ),
        ),
        primary_failure_stage="final_state" if failed else None,
        error_detail=EvaluatorErrorDetail(
            category="timeout",
            exception_type="TimeoutError",
            message="Evaluation timed out",
        )
        if outcome == "error"
        else None,
        judge_record=JudgeRecord(
            provider_id="test",
            requested_model="test-model",
            request_sha256="b" * 64,
            raw_response="Recorded response",
        )
        if evaluator.kind == "llm_judge" and score is not None
        else None,
    )


def report(
    run_id="baseline",
    *,
    specs=None,
    cases=None,
    primary=None,
    selection=None,
    dataset_id="dataset",
    version="agent-v1",
    source="demo",
    target_id="loan",
    default_score=0.5,
    scores=None,
    outcomes=None,
    missing=(),
    minimum=0.5,
):
    specs = specs if specs is not None else (rule(), judge())
    cases = cases if cases is not None else (case(), case("case-2"))
    manifest = RunManifest(
        dataset=DatasetVersion(
            id="dataset-version",
            dataset_id=dataset_id,
            dataset_name="History",
            version=1,
            status="published",
            cases=cases,
            created_at=NOW,
            updated_at=NOW,
            published_at=NOW,
        ),
        selected_case_ids=selection,
        target=TargetSnapshot(
            ref=TargetRef(
                source_id=source,
                target_type="agent",
                external_target_id=target_id,
                external_version_id=version,
            ),
            display_name="Loan",
            adapter_type="demo",
            adapter_version="1",
            descriptor_sha256="c" * 64,
            captured_at=NOW,
        ),
        evaluator_specs=specs,
        primary_evaluator_ids=primary if primary is not None else tuple(spec.id for spec in specs),
        metric_plan=MetricPlan(),
        gate_spec=ReleaseGateSpec(minimum_score=minimum),
        created_at=NOW,
    )
    run = EvaluationRun(
        id=run_id,
        manifest=manifest,
        status="completed",
        created_at=NOW,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    results = []
    for sample in manifest.execution_cases:
        for spec in specs:
            key = (sample.id, spec.id)
            if key in missing:
                continue
            value = (scores or {}).get(key, default_score)
            outcome = (outcomes or {}).get(
                key,
                "not_applicable" if value is None else "pass" if value >= 0.5 else "fail",
            )
            results.append(result(run.id, sample, spec, value, outcome))
    return build_evaluation_report(run, results)


def score_row(comparison, key, level=None):
    return next(
        row
        for row in comparison.score_rows
        if row.key == key and (level is None or row.level == level)
    )


def case_row(comparison, sample="case-1", evaluator="rule"):
    return next(
        row for row in comparison.case_rows if row.case_id == sample and row.key == evaluator
    )


@pytest.mark.parametrize("version", ["agent-v1", "agent-v2"])
@pytest.mark.parametrize("source", ["local", "in-bank"])
def test_same_and_different_agent_versions_compare_original_scores(version, source):
    a = report(default_score=0, source=source)
    b = report("candidate", default_score=0.75, source=source, version=version)
    compared = compare_historical_reports(a, b)
    for row in compared.score_rows:
        assert row.comparable and row.reasons == ()
        assert (row.baseline_score, row.candidate_score, row.score_delta) == (0, 0.75, 0.75)
    assert all(row.change == "improvement" for row in compared.case_rows)
    reverse = compare_historical_reports(b, a)
    assert score_row(reverse, "overall").score_delta == -0.75
    assert all(row.change == "regression" for row in reverse.case_rows)


def test_zero_scores_are_real_values_and_unchanged():
    compared = compare_historical_reports(
        report(default_score=0), report("candidate", default_score=0)
    )
    assert all(row.score_delta == 0 for row in compared.score_rows + compared.case_rows)
    assert all(row.change == "unchanged" for row in compared.case_rows)


@pytest.mark.parametrize(
    "changed",
    [
        {"version": "2"},
        {"config": {"model": {"provider_id": "test", "model_id": "another-model"}}},
    ],
)
def test_changed_llm_does_not_hide_unchanged_rule_scores(changed):
    compared = compare_historical_reports(
        report(),
        report("candidate", specs=(rule(), judge(**changed)), default_score=0.8),
    )
    for key in ("overall", "llm", "judge"):
        row = score_row(compared, key)
        assert not row.comparable and row.score_delta == pytest.approx(0.3)
        assert "evaluator_changed" in row.reasons
        assert row.candidate_score == 0.8
    assert score_row(compared, "rule", "kind").score_delta == pytest.approx(0.3)
    assert case_row(compared).comparable
    assert not case_row(compared, evaluator="judge").comparable
    assert case_row(compared, evaluator="judge").change == "improvement"
    assert case_row(compared, evaluator="judge").score_delta == pytest.approx(0.3)


def test_transitive_child_definition_change_is_detected_when_parent_hash_is_unchanged():
    a = report(specs=(rule(), judge(), group()), primary=("rule", "group"))
    b = report(
        "candidate",
        specs=(
            rule(),
            judge(
                config={
                    "model": {"provider_id": "test", "model_id": "new-model"},
                }
            ),
            group(),
        ),
        primary=("rule", "group"),
    )
    assert a.run.manifest.evaluator_specs[-1] == b.run.manifest.evaluator_specs[-1]
    compared = compare_historical_reports(a, b)
    assert "evaluator_changed" in score_row(compared, "group").reasons
    assert "evaluator_changed" in case_row(compared, evaluator="group").reasons
    assert score_row(compared, "rule", "kind").comparable


@pytest.mark.parametrize("child_specs", [(), (judge(version="2"),)])
def test_missing_or_wrong_version_child_snapshot_is_not_assumed_comparable(child_specs):
    specs = (rule(), group(), *child_specs)
    compared = compare_historical_reports(
        report(specs=specs, primary=("rule", "group")),
        report("candidate", specs=specs, primary=("rule", "group")),
    )
    assert "evaluator_snapshot_incomplete" in score_row(compared, "group").reasons
    assert score_row(compared, "rule", "kind").comparable


def test_composite_cycle_is_incomparable_without_recursing_forever():
    specs = (rule(), group(child="group"))
    compared = compare_historical_reports(report(specs=specs), report("candidate", specs=specs))
    assert "evaluator_snapshot_incomplete" in score_row(compared, "group").reasons


def test_mixed_llm_categories_use_existing_metric_then_case_average():
    specs = (rule(), judge(), judge("second"), judge("third"), group())
    a = report(
        specs=specs,
        scores={
            (sample, identity): value
            for sample in ("case-1", "case-2")
            for identity, value in (("judge", 0), ("second", 0), ("third", 0), ("group", 1))
        },
    )
    b = report("candidate", specs=specs, default_score=1)
    row = score_row(compare_historical_reports(a, b), "llm")
    # The three judges share one metric; the group uses another. This is not 1/4.
    assert (row.baseline_score, row.candidate_score, row.score_delta) == (0.5, 1, 0.5)


def test_different_datasets_preserve_raw_summaries_and_compare_unchanged_sample_content():
    compared = compare_historical_reports(report(), report("candidate", dataset_id="other"))
    assert all("dataset_changed" in row.reasons for row in compared.score_rows)
    assert all(row.baseline_score == row.candidate_score == 0.5 for row in compared.score_rows)
    assert all(row.score_delta == 0 for row in compared.score_rows)
    assert all(row.comparable for row in compared.case_rows)


def test_selected_case_scope_changes_do_not_recalculate_raw_scores_over_the_intersection():
    a = report(scores={("case-1", "rule"): 0, ("case-2", "rule"): 1}, specs=(rule(),))
    b = report("candidate", selection=("case-1",), default_score=0.75, specs=(rule(),))
    compared = compare_historical_reports(a, b)
    row = score_row(compared, "overall")
    assert (row.baseline_score, row.candidate_score, row.score_delta) == (0.5, 0.75, 0.25)
    assert "case_scope_changed" in row.reasons
    assert case_row(compared).score_delta == 0.75
    missing = case_row(compared, sample="case-2")
    assert missing.baseline_score == 1 and missing.candidate_score is None
    assert "case_missing" in missing.reasons and missing.change is None


def test_matching_names_are_not_used_to_join_different_sample_ids():
    a = report(cases=(case("old", name="same name"),))
    b = report("candidate", cases=(case("new", name="same name"),))
    compared = compare_historical_reports(a, b)
    assert len(compared.case_rows) == 4
    assert all(
        "case_missing" in row.reasons and row.score_delta is None for row in compared.case_rows
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"turns": (CaseTurn(id="turn-1", input={"message": "changed"}),)},
        {"initial_state": {"customer": "changed"}},
        {
            "turns": (
                CaseTurn(id="turn-1", input={"message": "case-1"}),
                CaseTurn(id="turn-2", input={"message": "followup"}),
            )
        },
    ],
)
def test_same_case_id_requires_identical_content_including_all_turns(changes):
    compared = compare_historical_reports(
        report(),
        report("candidate", cases=(case(**changes), case("case-2"))),
    )
    assert "case_content_changed" in case_row(compared).reasons
    assert case_row(compared).score_delta == 0
    assert case_row(compared).change == "unchanged"
    assert case_row(compared, sample="case-2").comparable
    assert not score_row(compared, "overall").comparable


def test_added_and_removed_evaluators_are_visible_with_missing_side_not_zero():
    compared = compare_historical_reports(
        report(specs=(rule(), judge("old"))),
        report("candidate", specs=(rule(), judge("new"))),
    )
    assert (
        score_row(compared, "old").baseline_score,
        score_row(compared, "old").candidate_score,
    ) == (0.5, None)
    assert (
        score_row(compared, "new").baseline_score,
        score_row(compared, "new").candidate_score,
    ) == (None, 0.5)
    assert score_row(compared, "rule", "kind").comparable
    assert not score_row(compared, "llm").comparable


def test_non_primary_results_do_not_fill_a_missing_evaluator_side():
    compared = compare_historical_reports(report(), report("candidate", primary=("rule",)))
    assert score_row(compared, "judge").candidate_score is None
    assert case_row(compared, evaluator="judge").candidate_score is None
    assert case_row(compared, evaluator="judge").candidate_outcome is None
    assert score_row(compared, "rule", "kind").comparable


@pytest.mark.parametrize("both", [False, True])
def test_missing_results_retain_aggregate_deltas_but_not_missing_sample_deltas(both):
    missing = (("case-2", "judge"),)
    compared = compare_historical_reports(
        report(missing=missing if both else ()),
        report("candidate", missing=missing),
    )
    row = score_row(compared, "llm")
    assert row.baseline_score == row.candidate_score == 0.5
    assert "result_missing" in row.reasons and row.score_delta == 0
    missing = case_row(compared, sample="case-2", evaluator="judge")
    assert missing.candidate_score is None and missing.score_delta is None
    assert missing.change is None
    assert score_row(compared, "rule", "kind").comparable


def test_evaluator_error_is_not_a_zero_and_does_not_affect_other_evaluators():
    key = ("case-1", "judge")
    compared = compare_historical_reports(
        report(),
        report("candidate", scores={key: None}, outcomes={key: "error"}),
    )
    assert "evaluation_error" in score_row(compared, "llm").reasons
    assert score_row(compared, "llm").candidate_score == 0.5
    assert score_row(compared, "llm").score_delta == 0
    assert case_row(compared, evaluator="judge").candidate_score is None
    assert case_row(compared, evaluator="judge").score_delta is None
    assert case_row(compared, evaluator="judge").change is None
    assert case_row(compared, evaluator="judge").candidate_outcome == "error"
    assert score_row(compared, "rule", "kind").comparable


def test_not_applicable_changes_actual_scoring_population():
    key = ("case-1", "judge")
    a, b = report(), report("candidate", scores={key: None})
    row = score_row(compare_historical_reports(a, b), "llm")
    assert row.baseline_score == row.candidate_score == 0.5
    assert "scored_scope_changed" in row.reasons and not row.comparable
    assert row.score_delta == 0
    same_population = compare_historical_reports(report(scores={key: None}), b)
    assert score_row(same_population, "llm").score_delta == 0
    assert not case_row(same_population, evaluator="judge").comparable


def test_absent_category_and_unscored_results_remain_null():
    compared = compare_historical_reports(
        report(specs=(rule(),), default_score=None),
        report("candidate", specs=(rule(),), default_score=None),
    )
    assert all(
        row.baseline_score is None and row.candidate_score is None for row in compared.score_rows
    )
    assert all(row.score_delta is None for row in compared.score_rows + compared.case_rows)
    assert "evaluator_missing" in score_row(compared, "llm").reasons


def test_different_gate_thresholds_preserve_both_conclusions_without_a_gate_verdict():
    a, b = report(minimum=0.4), report("candidate", minimum=0.9)
    compared = compare_historical_reports(a, b)
    assert compared.baseline_gate == a.release_gate and compared.baseline_gate.outcome == "pass"
    assert compared.candidate_gate == b.release_gate and compared.candidate_gate.outcome == "fail"
    assert compared.gate_reasons == ("gate_changed",)
    assert score_row(compared, "overall").score_delta == 0
    assert score_row(compared, "overall").change is None


@pytest.mark.parametrize("change", [{"target_id": "other-agent"}, {"source": "other-source"}])
def test_different_target_identity_retains_arithmetic_deltas_and_changes(change):
    compared = compare_historical_reports(
        report(), report("candidate", default_score=0.25, **change)
    )
    assert all("target_changed" in row.reasons for row in compared.score_rows + compared.case_rows)
    assert score_row(compared, "overall").candidate_score == 0.25
    assert all(row.score_delta == -0.25 for row in compared.score_rows + compared.case_rows)
    assert all(row.change == "regression" for row in compared.case_rows)


def test_changed_metric_plan_is_disclosed_alongside_aggregate_and_sample_deltas():
    a, b = report(), report("candidate")
    data = b.model_dump(mode="json")
    data["run"]["manifest"]["metric_plan"]["version"] = "2"
    data["run"]["manifest"]["manifest_sha256"] = ""
    b = EvaluationReport.model_validate(data)
    compared = compare_historical_reports(a, b)
    assert all("metric_plan_changed" in row.reasons for row in compared.score_rows)
    assert all(row.score_delta == 0 for row in compared.score_rows + compared.case_rows)


def test_comparison_is_deterministic_serializable_and_leaves_both_reports_unchanged():
    a, b = report(), report("candidate", specs=(judge("new"), rule()))
    originals = (a.model_dump_json(), b.model_dump_json())
    first = compare_historical_reports(a, b)
    assert first == compare_historical_reports(a, b)
    assert first == HistoricalComparison.model_validate_json(first.model_dump_json())
    assert (a.model_dump_json(), b.model_dump_json()) == originals
    assert [(row.level, row.key) for row in first.score_rows] == [
        ("overall", "overall"),
        ("kind", "llm"),
        ("kind", "rule"),
        ("evaluator", "rule"),
        ("evaluator", "judge"),
        ("evaluator", "new"),
    ]
    with pytest.raises(ValidationError, match="frozen"):
        first.baseline_run_id = "changed"


def test_same_execution_is_rejected():
    a = report()
    with pytest.raises(ValueError, match="distinct"):
        compare_historical_reports(a, a)


@pytest.mark.parametrize("status", ["pending", "waiting", "running", "failed", "cancelled"])
def test_non_completed_reports_cannot_bypass_the_entrypoint_guard(status):
    a, b = report(), report("candidate")
    b = b.model_copy(update={"run": b.run.model_copy(update={"status": status})})
    with pytest.raises(ValueError, match="completed"):
        compare_historical_reports(a, b)


@pytest.mark.parametrize(
    "invalid",
    [
        {"score_delta": 0.2},
        {"comparable": False},
        {"reasons": ["dataset_changed"]},
        {"candidate_score": None},
        {"change": "improvement"},
    ],
)
def test_serialization_boundary_rejects_inconsistent_summary_rows(invalid):
    compared = compare_historical_reports(report(), report("candidate"))
    data = compared.model_dump(mode="json")
    data["score_rows"][0].update(invalid)
    with pytest.raises(ValidationError):
        HistoricalComparison.model_validate(data)


def test_rows_with_condition_differences_require_correct_deltas_and_change_labels():
    compared = compare_historical_reports(report(), report("candidate", target_id="other"))
    assert HistoricalComparison.model_validate_json(compared.model_dump_json()) == compared
    for section, field, value in (
        ("score_rows", "score_delta", None),
        ("score_rows", "score_delta", 0.2),
        ("case_rows", "change", None),
        ("case_rows", "change", "improvement"),
    ):
        data = compared.model_dump(mode="json")
        data[section][0][field] = value
        with pytest.raises(ValidationError):
            HistoricalComparison.model_validate(data)


@pytest.mark.parametrize("field,value", [("score_delta", 0), ("change", "unchanged")])
def test_missing_scores_cannot_be_serialized_with_deltas_or_change_labels(field, value):
    compared = compare_historical_reports(
        report(), report("candidate", missing=(("case-1", "rule"),))
    )
    data = compared.model_dump(mode="json")
    data["case_rows"][0][field] = value
    with pytest.raises(ValidationError):
        HistoricalComparison.model_validate(data)


def test_duplicate_rows_and_missing_gate_limitations_are_rejected():
    compared = compare_historical_reports(report(), report("candidate", dataset_id="other"))
    for defect in ("duplicate", "gate"):
        data = compared.model_dump(mode="json")
        if defect == "duplicate":
            data["case_rows"].append(data["case_rows"][0])
        else:
            data["gate_reasons"] = []
        with pytest.raises(ValidationError):
            HistoricalComparison.model_validate(data)
