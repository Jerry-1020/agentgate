"""Real MySQL contracts, executed only through the allowlisted test fixture."""

from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import text
from agentgate.domain import Dataset, DatasetVersion, RunStatus, transition_run, utcnow
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.storage.evaluation_query_models import (
    EvaluationQuery,
    TaskSummaryQuery,
    SummarySourceChanged,
)
from agentgate.result.summary import build_completed_run_summary
from agentgate.application.evaluation_summary_backfill import backfill
from agentgate.storage.evaluation_migration import inspect_or_upgrade_mysql
from test_evaluation_queries import seed
from test_run_engine import engine, StubTargetAdapter, pending_run


def test_mysql_summary_roundtrip(mysql_repository):
    repo = mysql_repository
    task, runs = seed(repo, "a", 2, "ab")
    seed(repo, "b")
    done = engine(repo).execute(runs[0], StubTargetAdapter())
    q = TaskSummaryQuery(keyword=task.id, page_size=1)
    page = repo.list_evaluation_task_summaries(q, user_team_id="a")
    assert page.total == 1 and page.items[0].status == "running"
    assert page.items[0].runs[0].overall_score == 1
    assert page.items[0].created_at.utcoffset() == timedelta(0)
    assert (
        repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="a").average_score == 1
    )
    assert not backfill(repo, apply=True)["failures"]
    assert not backfill(repo, apply=False)["failures"]
    assert repo.read_run_summary_source("missing") is None
    assert not repo.rebuild_task_query_fields("missing")
    assert not repo.rebuild_dataset_version_query_fields("missing")
    assert repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="none").total == 0
    summary = build_completed_run_summary(done, repo.list_results(done.id))
    repo.save_completed_run(done, summary)
    with pytest.raises(ValueError):
        repo.save_completed_run(done.model_copy(update={"id": "missing"}), summary)
    with pytest.raises(ValueError):
        repo.save_completed_run(runs[1], summary)
    with pytest.raises(ValueError):
        repo.save_completed_run(done.model_copy(update={"user_team_id": "changed"}), summary)
    with pytest.raises(ValueError):
        repo.save_completed_run(
            done.model_copy(update={"completed_at": done.completed_at + timedelta(seconds=1)}),
            summary,
        )
    with pytest.raises(SummarySourceChanged):
        repo.save_completed_run(done, summary.model_copy(update={"result_count": 999}))
    repo.delete_task_record(task.id, user_team_id="a")
    assert repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="a").total == 0


def test_mysql_migration_inspection_and_upgrade(mysql_repository):
    repo = mysql_repository
    assert inspect_or_upgrade_mysql(repo._engine) == []
    with repo._engine.begin() as db:
        db.execute(text("DROP TABLE agentgate_run_expected_evaluators"))
        db.execute(text("ALTER TABLE agentgate_dataset_versions DROP COLUMN sample_count"))
        db.execute(
            text("DROP INDEX ix_task_runs_current_position ON agentgate_evaluation_task_runs")
        )
    assert len(inspect_or_upgrade_mysql(repo._engine)) == 3
    assert len(inspect_or_upgrade_mysql(repo._engine, apply=True)) == 3
    assert inspect_or_upgrade_mysql(repo._engine) == []


def test_mysql_dataset_errors_preserve_original(mysql_repository):
    repo = mysql_repository
    dataset = Dataset(name="test")
    repo.save_dataset(dataset)
    version = DatasetVersion(dataset_id=dataset.id, cases=pending_run().manifest.dataset.cases)
    with pytest.raises(ValueError):
        repo.save_dataset_version(version.model_copy(update={"dataset_id": "unknown"}))
    repo.save_dataset_version(version)
    for changes in [
        {"dataset_id": "other"},
        {"created_at": version.created_at - timedelta(days=1)},
        {"updated_at": version.updated_at - timedelta(days=1)},
    ]:
        # Use a real second dataset to reach immutable identity validation.
        if changes.get("dataset_id") == "other":
            repo.save_dataset(Dataset(id="other", name="other"))
        with pytest.raises(ValueError):
            repo.save_dataset_version(version.model_copy(update=changes))
    with pytest.raises(ValueError):
        repo.save_dataset_version(version.model_copy(update={"status": "published"}))
    # Use validated domain publications for the persistence invariants.
    publication = DatasetVersion(
        dataset_id=dataset.id,
        cases=version.cases,
        version=1,
        status="published",
        created_at=version.created_at,
        updated_at=version.updated_at,
        published_at=version.updated_at,
    )
    with pytest.raises(ValueError):
        repo.replace_dataset_draft("missing", publication)
    with pytest.raises(ValueError):
        repo.replace_dataset_draft(version.id, version)
    with pytest.raises(ValueError):
        repo.replace_dataset_draft(
            version.id,
            publication.model_copy(
                update={"created_at": publication.created_at + timedelta(seconds=1)}
            ),
        )
    with pytest.raises(ValueError):
        repo.replace_dataset_draft(
            version.id,
            publication.model_copy(
                update={"updated_at": publication.updated_at - timedelta(seconds=1)}
            ),
        )
    repo.replace_dataset_draft(version.id, publication)
    with pytest.raises(ValueError):
        repo.save_dataset_version(publication.model_copy(update={"user_id": "changed"}))
    with pytest.raises(ValueError):
        repo.delete_dataset_version(dataset.id, 99, user_team_id="")
    with pytest.raises(ValueError):
        repo.delete_dataset_record("missing", user_team_id="")
    with pytest.raises(ValueError):
        repo.delete_task_record("missing", user_team_id="")


def test_mysql_run_creation_guards(mysql_repository):
    repo = mysql_repository
    run = pending_run()
    repo.save_run(run)
    for changes in [
        {"created_at": run.created_at + timedelta(seconds=1)},
        {"scheduled_for": utcnow()},
    ]:
        with pytest.raises(ValueError):
            repo.save_run(run.model_copy(update=changes))
    task = EvaluationTask(kind="single", run_ids=(run.id,))
    with pytest.raises(ValueError):
        repo.save_task_runs(task, [])
    with pytest.raises(ValueError):
        repo.save_task_runs(task.model_copy(update={"previous_run_ids": ("history",)}), [run])
    with pytest.raises(ValueError):
        repo.save_task_runs(task, [run.model_copy(update={"status": RunStatus.RUNNING})])
    with pytest.raises(ValueError):
        repo.save_evaluation_task(task.model_copy(update={"run_ids": ("missing",)}))
    repo.save_evaluation_task(task)
    with pytest.raises(ValueError):
        repo.save_evaluation_task(task.model_copy(update={"kind": "ab"}))
    with pytest.raises(ValueError):
        repo.save_evaluation_task(task.model_copy(update={"previous_run_ids": ("history",)}))
    running = repo.claim_pending_run(run.id, utcnow())
    with pytest.raises(ValueError):
        repo.save_run(
            running.model_copy(update={"started_at": running.started_at + timedelta(seconds=1)})
        )
    failed = transition_run(running, RunStatus.FAILED, error="test")
    repo.save_run(failed)
    with pytest.raises(ValueError):
        repo.save_run(failed.model_copy(update={"error": "different"}))


def test_mysql_tools(mysql_repository, mysql_config, tmp_path, monkeypatch):
    import sys
    from test_evaluation_summary_tools import module

    report = tmp_path / "report.json"
    for name, args in [
        ("migrate_evaluation_summaries", ["--check"]),
        ("migrate_evaluation_summaries", ["--apply"]),
        ("backfill_evaluation_summaries", ["--apply", "--report", str(report)]),
    ]:
        tool = module(name)
        monkeypatch.setattr(tool, "load_database_config", lambda *a, **kw: mysql_config)
        monkeypatch.setattr(sys, "argv", [name, *args])
        assert tool.main() == 0


def test_mysql_preserves_fractional_report_score(mysql_repository):
    from agentgate.run.engine import RunEngine
    from agentgate.result.report import build_evaluation_report
    from test_run_engine import evaluate_case, resolve_trace

    repo = mysql_repository
    task, runs = seed(repo, "precision")
    value = 0.12345678912345

    def fractional(case, trace, specs):
        item = evaluate_case(case, trace, specs)[0]
        return (
            item.model_copy(
                update={
                    "score": value,
                    "checks": tuple(c.model_copy(update={"score": value}) for c in item.checks),
                }
            ),
        )

    done = RunEngine(repo, fractional, resolve_trace).execute(runs[0], StubTargetAdapter())
    expected = next(
        m.score
        for m in build_evaluation_report(done, repo.list_results(done.id)).metrics
        if m.level == "overall"
    )
    actual = repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="precision")
    assert actual.items[0].runs[0].overall_score == expected == value


def test_mysql_historical_summary_count(mysql_repository):
    from test_evaluation_queries import assert_history_counts
    assert_history_counts(mysql_repository)
