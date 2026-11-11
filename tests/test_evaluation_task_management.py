from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from test_historical_comparison import report as historical_report

from agentgate.application.evaluation_task_management import EvaluationTaskManagement
from agentgate.domain import EvaluationRun
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.app import create_app
from agentgate.server.user_context import UserInfo, reset_user_info, set_user_info


class Dispatcher:
    def submit(self, run_id):
        pass


def client(path):
    return TestClient(create_app(path, dispatcher=Dispatcher()))


def launch(c, version="loan-agent-v1-risky"):
    response = c.post("/api/evaluations", json={
        "version": version, "dataset_id": "loan-risk-policy", "dataset_version": 1,
        "evaluator_ids": ["final-state"],
    })
    assert response.status_code == 202, response.text
    return response.json()["data"]["run_id"]


def test_single_task_survives_new_app_and_idempotent_save(tmp_path):
    path = tmp_path / "test.db"
    with client(path) as c:
        run_id = launch(c)
        body = {"kind": "single", "run_ids": [run_id]}
        first = c.get("/api/evaluation-tasks/" + run_id).json()["data"]
        assert c.put("/api/evaluation-tasks/" + run_id, json=body).json()["data"] == first
        assert c.put("/api/evaluation-tasks/other", json=body).status_code == 409
    with client(path) as c:
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"] == first
        assert len(c.get("/api/evaluation-tasks").json()["data"]) == 1


def test_unknown_and_wrong_report_rejected(tmp_path):
    with client(tmp_path / "test.db") as c:
        assert c.get("/api/evaluation-tasks/missing").status_code == 404
        assert c.put("/api/evaluation-tasks/x", json={"kind": "single", "run_ids": ["missing"]}).status_code == 404
        run_id = launch(c)
        response = c.put("/api/evaluation-tasks/" + run_id, json={
            "kind": "single", "run_ids": [run_id], "static_report_ids": ["missing"],
        })
        assert response.status_code == 404
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"]["static_report_ids"] == []


def test_ab_launch_and_reversed_association_conflict(tmp_path):
    with client(tmp_path / "test.db") as c:
        response = c.post("/api/run-comparisons", json={
            "baseline_version": "loan-agent-v1-risky", "candidate_version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluators": [{"id": "final-state", "version": "1"}],
        })
        assert response.status_code == 202, response.text
        pair = response.json()["data"]
        ids = [pair["baseline"]["run_id"], pair["candidate"]["run_id"]]
        task = c.get("/api/evaluation-tasks/" + ids[0]).json()["data"]
        assert task["kind"] == "ab"
        assert task["run_ids"] == ids
        assert c.put("/api/evaluation-tasks/" + ids[0], json={"kind": "ab", "run_ids": ids[::-1]}).status_code == 409


def test_same_version_ab_rejected(tmp_path):
    with client(tmp_path / "test.db") as c:
        a, b = launch(c), launch(c)
        response = c.put("/api/evaluation-tasks/" + a, json={"kind": "ab", "run_ids": [a, b]})
        assert response.status_code == 409
        assert "distinct" in response.text


def test_static_report_replacement_preserves_history_and_rejects_wrong_target(tmp_path):
    from agentgate.domain import SkillAnalysisReport
    with client(tmp_path / "test.db") as c:
        risky = launch(c)
        fixed = launch(c, "loan-agent-v2-fixed")
        repo = c.app.state.dependencies.repository
        reports = []
        for run_id in (risky, risky, fixed):
            target = repo.get_run(run_id).manifest.target
            report = SkillAnalysisReport(target_ref=target.ref, target_descriptor_sha256=target.descriptor_sha256,
                                         analyzer_version="test", status="completed")
            repo.save_skill_analysis_report(report)
            reports.append(report)
        for report in reports[:2]:
            response = c.put("/api/evaluation-tasks/"+risky, json={"kind":"single", "run_ids":[risky], "static_report_ids":[report.id]})
            assert response.status_code == 200, response.text
        assert c.get("/api/evaluation-tasks/"+risky).json()["data"]["static_report_ids"] == [reports[1].id]
        assert repo.get_skill_analysis_report(reports[0].id) == reports[0]
        assert c.put("/api/evaluation-tasks/"+risky, json={"kind":"single", "run_ids":[risky], "static_report_ids":[reports[2].id]}).status_code == 409


def test_delete_completed_task_removes_evidence_and_preserves_other_tasks(tmp_path):
    from agentgate.domain import OptimizationReport, RoutingConfusionMatrix

    with client(tmp_path / "delete.db") as c:
        other_id = launch(c)
        dependencies = c.app.state.dependencies
        run = dependencies.execute_demo_run("loan-agent-v1-risky")
        repo = dependencies.repository
        assert c.put("/api/evaluation-tasks/" + run.id, json={
            "kind": "single", "run_ids": [run.id],
        }).status_code == 200
        assert repo.list_traces(run.id)
        assert repo.list_results(run.id)
        report = OptimizationReport(
            run_id=run.id,
            target_ref=run.manifest.target.ref,
            target_content_sha256=run.manifest.target.descriptor_sha256,
            dataset_id=run.manifest.dataset.id,
            dataset_version=1,
            dataset_content_sha256="b" * 64,
            analyzer_version="1",
            failed_result_count=0,
            confusion_matrix=RoutingConfusionMatrix(eligible_count=0),
        )
        repo.save_optimization_report("delete-evidence", report)
        response = c.delete("/api/evaluation-tasks/" + run.id)
        assert response.status_code == 200, response.text
        assert c.get("/api/evaluation-tasks/" + run.id).status_code == 404
        assert repo.get_run(run.id) is None
        assert repo.list_traces(run.id) == []
        assert repo.list_results(run.id) == []
        assert repo.get_optimization_report("delete-evidence") is None
        assert c.get("/api/evaluation-tasks/" + other_id).status_code == 200
        assert repo.get_run(other_id) is not None
        assert c.delete("/api/evaluation-tasks/" + run.id).status_code == 404


def test_delete_ab_task_removes_both_runs(tmp_path):
    with client(tmp_path / "delete-ab.db") as c:
        response = c.post("/api/run-comparisons", json={
            "baseline_version": "loan-agent-v1-risky",
            "candidate_version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluators": [{"id": "final-state", "version": "1"}],
        })
        assert response.status_code == 202, response.text
        pair = response.json()["data"]
        ids = [pair["baseline"]["run_id"], pair["candidate"]["run_id"]]
        response = c.delete("/api/evaluation-tasks/" + ids[0])
        assert response.status_code == 200, response.text
        repo = c.app.state.dependencies.repository
        assert all(repo.get_run(run_id) is None for run_id in ids)
        assert c.get("/api/evaluation-tasks").json()["data"] == []


def test_task_name_persists_and_old_tasks_are_named_once(tmp_path):
    from datetime import UTC, datetime

    from agentgate.domain.evaluation_task import EvaluationTask

    path = tmp_path / "names.db"
    with client(path) as c:
        run_id = launch(c)
        repo = c.app.state.dependencies.repository
        # Model and repository retain explicit user names through metadata updates.
        body = {"kind": "single", "run_ids": [run_id], "name": "  自定义回归任务  "}
        response = c.put("/api/evaluation-tasks/" + run_id, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["name"] == "自定义回归任务"
        c.put("/api/evaluation-tasks/" + run_id, json={"kind": "single", "run_ids": [run_id]})
        assert repo.get_evaluation_task(run_id).name == "自定义回归任务"
        old_id = "historical-name-test"
        old_run = repo.get_run(run_id).model_copy(update={"id": old_id})
        old = EvaluationTask(id=old_id, kind="single", run_ids=(old_id,),
                             created_at=datetime(2026, 9, 24, tzinfo=UTC))
        repo.save_task_runs(old, [old_run])
        response = c.get("/api/evaluation-tasks").json()["data"]
        assert next(t for t in response if t["id"] == old_id)["name"] == "贷款智能体924"
        assert repo.get_evaluation_task(old_id).name == "贷款智能体924"
    with client(path) as c:
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"]["name"] == "自定义回归任务"
        assert c.get("/api/evaluation-tasks/" + old_id).json()["data"]["name"] == "贷款智能体924"


def test_blank_or_overlong_task_name_is_rejected(tmp_path):
    with client(tmp_path / "invalid-name.db") as c:
        run_id = launch(c)
        for name in ("   ", "a" * 129):
            response = c.put("/api/evaluation-tasks/" + run_id, json={
                "kind": "single", "run_ids": [run_id], "name": name,
            })
            assert response.status_code == 409


class HistoryComparisonRepository:
    """Application boundary double; transaction and SQL guarantees need adapter tests."""

    def __init__(self, *, team_id="", candidate=None):
        reports = (
            historical_report("baseline-run", default_score=0.4),
            candidate or historical_report("candidate-run", default_score=0.8),
        )
        self.runs = {
            report.run.id: report.run.model_copy(update={"user_team_id": team_id})
            for report in reports
        }
        self.results = {report.run.id: report.results for report in reports}
        self.tasks = {
            "baseline-task": EvaluationTask(
                id="baseline-task",
                kind="single",
                name="历史单任务 A",
                run_ids=("baseline-run",),
            ),
            "candidate-task": EvaluationTask(
                id="candidate-task",
                kind="single",
                name="当前单任务 B",
                run_ids=("candidate-run",),
            ),
        }
        self.reference_sources = {}
        self.save_calls = []
        self.result_reads = []

    def get_evaluation_task(self, task_id):
        return self.tasks.get(task_id)

    def list_evaluation_tasks(self):
        return list(self.tasks.values())

    def get_run(self, run_id, *, user_team_id):
        run = self.runs.get(run_id)
        return run if run is not None and run.user_team_id == user_team_id else None

    def list_results(self, run_id):
        self.result_reads.append(run_id)
        return self.results[run_id]

    def save_evaluation_task(self, task):
        raise AssertionError("historical comparisons must not use ordinary task saves")

    def save_historical_comparison(
        self,
        task,
        *,
        baseline_task_id,
        candidate_task_id,
        user_team_id,
    ):
        self.save_calls.append((task, baseline_task_id, candidate_task_id, user_team_id))
        existing = self.tasks.get(task.id)
        source_ids = (baseline_task_id, candidate_task_id)
        if existing is not None:
            if (
                existing.kind != "ab"
                or existing.run_ids != task.run_ids
                or self.reference_sources.get(task.id) != source_ids
            ):
                raise ValueError("comparison identity already has different references")
            return existing
        self.tasks[task.id] = task
        self.reference_sources[task.id] = source_ids
        return task


@contextmanager
def history_user(team_id):
    token = set_user_info(UserInfo(team_id, "test-user", "Test User"))
    try:
        yield
    finally:
        reset_user_info(token)


def create_history(repository, **overrides):
    return EvaluationTaskManagement(repository).create_history_comparison(
        **{
            "comparison_id": "history-ab",
            "baseline_task_id": "baseline-task",
            "baseline_run_id": "baseline-run",
            "candidate_task_id": "candidate-task",
            "candidate_run_id": "candidate-run",
            **overrides,
        }
    )


def replace_source_run(repository, task_id, run_id, status="running"):
    task = repository.tasks[task_id]
    original = repository.runs[task.run_ids[0]]
    data = original.model_dump()
    data.update(id=run_id, status=status, completed_at=None)
    repository.runs[run_id] = EvaluationRun.model_validate(data)
    repository.results[run_id] = ()
    repository.tasks[task_id] = task.model_copy(
        update={
            "run_ids": (run_id,),
            "previous_run_ids": task.previous_run_ids + task.run_ids,
        }
    )


@pytest.mark.parametrize("team_id", ["", "bank-team", "integrated-team"])
def test_history_create_and_read_use_current_team_without_changing_source_records(team_id):
    repository = HistoryComparisonRepository(team_id=team_id)
    original_tasks = dict(repository.tasks)
    original_runs = dict(repository.runs)
    original_results = dict(repository.results)
    with history_user(team_id):
        task = create_history(repository, name="  我的历史对比  ")
        comparison = EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert task.kind == "ab" and task.name == "我的历史对比"
    assert task.run_ids == ("baseline-run", "candidate-run")
    assert task.previous_run_ids == task.static_report_ids == task.git_commit_refs == ()
    assert task.credential_id is None
    assert set(task.model_dump()) == set(original_tasks["baseline-task"].model_dump())
    assert repository.save_calls == [(task, "baseline-task", "candidate-task", team_id)]
    assert repository.runs == original_runs and repository.results == original_results
    assert all(repository.tasks[key] == value for key, value in original_tasks.items())
    overall = comparison.score_rows[0]
    assert (overall.baseline_score, overall.candidate_score) == (0.4, 0.8)
    assert overall.comparable and overall.score_delta == pytest.approx(0.4)


def test_history_same_version_and_different_conditions_are_saved_with_limitations():
    repository = HistoryComparisonRepository(
        candidate=historical_report(
            "candidate-run",
            dataset_id="different-dataset",
            default_score=0.9,
        )
    )
    task = create_history(repository)
    comparison = EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert comparison.score_rows[0].candidate_score == 0.9
    assert "dataset_changed" in comparison.score_rows[0].reasons
    assert comparison.score_rows[0].score_delta == pytest.approx(0.5)


def test_history_sources_can_be_nameless_without_triggering_name_writeback():
    repository = HistoryComparisonRepository()
    for key, task in repository.tasks.items():
        repository.tasks[key] = task.model_copy(update={"name": None})
    created = create_history(repository)
    assert created.name and len(created.name) <= 128
    assert repository.tasks["baseline-task"].name is None
    assert repository.tasks["candidate-task"].name is None
    assert len(repository.save_calls) == 1


def test_history_default_name_keeps_both_source_names_within_existing_length_limit():
    repository = HistoryComparisonRepository()
    repository.tasks["baseline-task"] = repository.tasks["baseline-task"].model_copy(
        update={"name": "A" * 128},
    )
    repository.tasks["candidate-task"] = repository.tasks["candidate-task"].model_copy(
        update={"name": "B" * 128},
    )
    created = create_history(repository)
    assert "A" * 48 in created.name and "B" * 48 in created.name
    assert len(created.name) <= 128


def test_history_duplicate_submission_keeps_original_identity_name_and_creation_time():
    repository = HistoryComparisonRepository()
    first = create_history(repository, name="Original")
    retry = create_history(repository, name="Do not rename an existing comparison")
    assert retry == first
    assert len(repository.tasks) == 3 and len(repository.runs) == 2
    assert all(call[0].run_ids == first.run_ids for call in repository.save_calls)


def test_history_same_identity_cannot_reverse_the_saved_pair():
    repository = HistoryComparisonRepository()
    first = create_history(repository)
    with pytest.raises(ValueError, match="different references"):
        create_history(
            repository,
            baseline_task_id="candidate-task",
            baseline_run_id="candidate-run",
            candidate_task_id="baseline-task",
            candidate_run_id="baseline-run",
        )
    assert repository.tasks[first.id] == first and len(repository.tasks) == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"baseline_task_id": "candidate-task"},
        {"baseline_run_id": "candidate-run"},
        {"comparison_id": "baseline-task"},
        {"comparison_id": "candidate-task"},
    ],
)
def test_history_rejects_self_comparison_and_source_identity_reuse(overrides):
    repository = HistoryComparisonRepository()
    with pytest.raises(ValueError):
        create_history(repository, **overrides)
    assert repository.save_calls == [] and len(repository.tasks) == 2


@pytest.mark.parametrize(
    "field",
    [
        "comparison_id",
        "baseline_task_id",
        "baseline_run_id",
        "candidate_task_id",
        "candidate_run_id",
    ],
)
def test_history_rejects_blank_identifiers_before_reading_or_saving(field):
    repository = HistoryComparisonRepository()
    with pytest.raises(ValueError, match="blank"):
        create_history(repository, **{field: " "})
    assert repository.result_reads == repository.save_calls == []


@pytest.mark.parametrize("name", ["", " ", "x" * 129])
def test_history_rejects_invalid_names_without_saving(name):
    repository = HistoryComparisonRepository()
    with pytest.raises(ValueError):
        create_history(repository, name=name)
    assert repository.save_calls == [] and "history-ab" not in repository.tasks


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("kind", ["ab", "stability"])
def test_history_only_single_tasks_can_be_sources(side, kind):
    repository = HistoryComparisonRepository()
    identity = side + "-task"
    repository.tasks[identity] = EvaluationTask(
        id=identity,
        kind=kind,
        run_ids=("baseline-run", "candidate-run"),
    )
    with pytest.raises(ValueError, match="single tasks"):
        create_history(repository)
    assert repository.save_calls == []


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_history_rejects_an_unrelated_run_even_if_the_user_can_read_it(side):
    repository = HistoryComparisonRepository()
    repository.runs["unrelated"] = repository.runs[side + "-run"].model_copy(
        update={"id": "unrelated"},
    )
    with pytest.raises(ValueError, match="does not belong"):
        create_history(repository, **{side + "_run_id": "unrelated"})
    assert repository.save_calls == []


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("missing", ["task", "run"])
def test_history_deleted_sources_do_not_leave_a_comparison_task(side, missing):
    repository = HistoryComparisonRepository()
    (repository.tasks if missing == "task" else repository.runs).pop(side + "-" + missing)
    with pytest.raises(LookupError):
        create_history(repository)
    assert repository.save_calls == [] and "history-ab" not in repository.tasks


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("status", ["pending", "waiting", "running", "failed", "cancelled"])
def test_history_requires_both_selected_runs_to_be_completed(side, status):
    repository = HistoryComparisonRepository()
    key = side + "-run"
    data = repository.runs[key].model_dump()
    data["status"] = status
    if status in {"pending", "waiting", "running"}:
        data["completed_at"] = None
    if status in {"pending", "waiting"}:
        data["started_at"] = None
    if status == "failed":
        data["error"] = "Recorded failure"
    repository.runs[key] = EvaluationRun.model_validate(data)
    with pytest.raises(ValueError, match="completed"):
        create_history(repository)
    assert repository.save_calls == []


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_history_foreign_team_sources_are_not_found(side):
    repository = HistoryComparisonRepository(team_id="owner")
    key = side + "-run"
    repository.runs[key] = repository.runs[key].model_copy(update={"user_team_id": "other"})
    with history_user("owner"), pytest.raises(LookupError, match="unknown"):
        create_history(repository)
    assert repository.save_calls == [] and key not in repository.result_reads


def test_history_foreign_task_kind_is_not_disclosed():
    repository = HistoryComparisonRepository(team_id="other")
    repository.tasks["baseline-task"] = EvaluationTask(
        id="baseline-task",
        kind="ab",
        run_ids=("baseline-run", "candidate-run"),
    )
    with history_user("owner"), pytest.raises(LookupError, match="unknown"):
        create_history(repository)
    assert repository.result_reads == repository.save_calls == []


def test_history_access_is_checked_again_for_selected_previous_runs():
    repository = HistoryComparisonRepository(team_id="owner")
    replace_source_run(repository, "baseline-task", "new-baseline")
    repository.runs["baseline-run"] = repository.runs["baseline-run"].model_copy(
        update={"user_team_id": "other"},
    )
    with history_user("owner"), pytest.raises(LookupError):
        create_history(repository)
    assert repository.save_calls == [] and "baseline-run" not in repository.result_reads


def test_history_pins_selected_runs_across_reruns_before_and_after_creation():
    repository = HistoryComparisonRepository()
    replace_source_run(repository, "baseline-task", "new-baseline")
    task = create_history(repository)
    replace_source_run(repository, "candidate-task", "new-candidate")
    comparison = EvaluationTaskManagement(repository).compare_task_results(task.id)
    retry = create_history(repository)
    assert task == retry
    assert (comparison.baseline_run_id, comparison.candidate_run_id) == (
        "baseline-run",
        "candidate-run",
    )
    assert comparison.score_rows[0].score_delta == pytest.approx(0.4)
    assert not {"new-baseline", "new-candidate"}.intersection(repository.result_reads)


def test_history_missing_sample_results_remain_disclosed_without_rerunning():
    repository = HistoryComparisonRepository(
        candidate=historical_report(
            "candidate-run",
            missing=(("case-1", "judge"),),
        )
    )
    task = create_history(repository)
    comparison = EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert "result_missing" in comparison.score_rows[0].reasons
    assert comparison.score_rows[0].score_delta == pytest.approx(0.1)
    assert len(repository.runs) == 2


def test_history_unreadable_results_fail_before_saving(monkeypatch):
    repository = HistoryComparisonRepository()

    def unavailable(_):
        raise RuntimeError("result storage unavailable")

    monkeypatch.setattr(repository, "list_results", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        create_history(repository)
    assert repository.save_calls == [] and "history-ab" not in repository.tasks


@pytest.mark.parametrize("error", [LookupError("source disappeared"), RuntimeError("save failed")])
def test_history_storage_failure_propagates_without_fallback_writes(monkeypatch, error):
    repository = HistoryComparisonRepository()
    original = dict(repository.tasks)

    def reject(*args, **kwargs):
        raise error

    monkeypatch.setattr(repository, "save_historical_comparison", reject)
    with pytest.raises(type(error), match=str(error)):
        create_history(repository)
    assert repository.tasks == original and len(repository.runs) == 2


@pytest.mark.parametrize("kind", ["single", "stability"])
def test_history_result_read_requires_an_ab_task(kind):
    repository = HistoryComparisonRepository()
    repository.tasks["not-ab"] = EvaluationTask(
        id="not-ab",
        kind=kind,
        run_ids=("baseline-run",) if kind == "single" else ("baseline-run", "candidate-run"),
    )
    with pytest.raises(ValueError, match="A/B task"):
        EvaluationTaskManagement(repository).compare_task_results("not-ab")
    assert repository.result_reads == repository.save_calls == []


def test_history_result_read_does_not_backfill_task_names_or_write_storage():
    repository = HistoryComparisonRepository()
    task = create_history(repository)
    repository.tasks[task.id] = task.model_copy(update={"name": None})
    calls = len(repository.save_calls)
    comparison = EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert comparison.baseline_run_id == "baseline-run"
    assert repository.tasks[task.id].name is None and len(repository.save_calls) == calls


def test_history_result_read_rechecks_current_user_access():
    repository = HistoryComparisonRepository(team_id="owner")
    with history_user("owner"):
        task = create_history(repository)
    repository.result_reads.clear()
    with history_user("other"), pytest.raises(LookupError):
        EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert repository.result_reads == []


def test_history_result_read_reports_missing_records_instead_of_following_latest():
    repository = HistoryComparisonRepository()
    task = create_history(repository)
    replace_source_run(repository, "baseline-task", "new-baseline")
    repository.runs.pop("baseline-run")
    with pytest.raises(LookupError):
        EvaluationTaskManagement(repository).compare_task_results(task.id)
    assert "new-baseline" not in repository.result_reads


def test_history_rejects_duplicate_names_but_allows_idempotent_resubmission():
    repository = HistoryComparisonRepository()
    with history_user(""):
        task = create_history(repository, name="重复对比名称")
        resubmitted = create_history(repository, name="重复对比名称")
        assert resubmitted == task
        with pytest.raises(ValueError, match="任务名称已存在"):
            create_history(
                repository,
                comparison_id="history-ab-2",
                name="重复对比名称",
            )
        renamed = create_history(
            repository,
            comparison_id="history-ab-2",
            name="重复对比名称 2",
        )
        assert renamed.id == "history-ab-2"
