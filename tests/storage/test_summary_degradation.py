"""Missing or malformed read projections never hide an existing task."""

import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from test_evaluation_queries import seed
from test_run_engine import StubTargetAdapter, evaluate_case, resolve_trace

from agentgate.run.engine import RunEngine
from agentgate.storage.evaluation_query_models import EvaluationQuery, TaskSummaryQuery
from agentgate.storage.sqlite import SQLiteRepository


def engine(repo):
    def evaluate(*args, **kwargs):
        return tuple(
            result.model_copy(update={"id": result.run_id + result.id})
            for result in evaluate_case(*args, **kwargs)
        )

    return RunEngine(repo, evaluate, resolve_trace)


@contextmanager
def sql(repo):
    if isinstance(repo, SQLiteRepository):
        with repo._connect() as db:
            yield lambda query, params: db.execute(query, params)
    else:
        with repo._engine.begin() as db:
            yield lambda query, params: db.execute(text(query), params)


def damage(repo, run_id, fault):
    column = "run_id"
    statement = {
        "missing": f"DELETE FROM agentgate_run_summaries WHERE {column}=:id",
        "version": f"UPDATE agentgate_run_summaries SET summary_version=99 WHERE {column}=:id",
        "json": f"UPDATE agentgate_run_summaries SET display_payload='broken' WHERE {column}=:id",
        "fields": f"UPDATE agentgate_run_summaries SET display_payload='{{}}' WHERE {column}=:id",
        "score": f"UPDATE agentgate_run_summaries SET overall_score=9 WHERE {column}=:id",
    }[fault]
    with sql(repo) as execute:
        execute(statement, {"id": run_id})


@pytest.mark.parametrize("fault", ["missing", "version", "json", "fields", "score"])
def test_bad_summary_preserves_pagination_and_excludes_statistics(repository, fault, caplog):
    repo = repository
    good_task, good = seed(repo, "owner")
    bad_task, bad = seed(repo, "owner")
    seed(repo, "other")
    engine(repo).execute(good[0], StubTargetAdapter())
    engine(repo).execute(bad[0], StubTargetAdapter())
    damage(repo, bad[0].id, fault)
    with caplog.at_level(logging.WARNING):
        page = repo.list_evaluation_task_summaries(
            TaskSummaryQuery(keyword=bad_task.id), user_team_id="owner"
        )
    assert page.total == 1 and page.items[0].id == bad_task.id
    item = page.items[0]
    assert item.status == "completed" and item.summary_pending
    assert item.total_cases is None and item.completed_cases is None
    assert item.runs[0].run_id == bad[0].id
    assert item.runs[0].overall_score is None and item.runs[0].target_name is None
    assert bad_task.id in caplog.text and "missing_or_invalid_summary" in caplog.text
    pages = [
        repo.list_evaluation_task_summaries(
            TaskSummaryQuery(page=p, page_size=1), user_team_id="owner"
        )
        for p in (1, 2)
    ]
    assert all(p.total == 2 and len(p.items) == 1 for p in pages)
    assert {p.items[0].id for p in pages} == {good_task.id, bad_task.id}
    overview = repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="owner")
    assert overview.task_count == 2 and overview.pending_summary_task_count == 1
    assert overview.average_score == 1 and overview.scored_run_count == 1
    assert overview.completed_sample_count == 1
    assert (
        repo.list_evaluation_task_summaries(
            TaskSummaryQuery(keyword=bad_task.id), user_team_id="other"
        ).total
        == 0
    )
    assert (
        repo.get_evaluation_overview_summary(
            EvaluationQuery(start_at=bad[0].created_at), user_team_id="owner"
        ).pending_summary_task_count
        == 1
    )
    # Restoring the compact summary makes the task eligible without changing its identity.
    with sql(repo) as execute:
        execute("DELETE FROM agentgate_run_summaries WHERE run_id=:id", {"id": bad[0].id})
    from agentgate.application.evaluation_summary_backfill import backfill

    assert not backfill(repo, apply=True)["failures"]
    assert (
        repo.get_evaluation_overview_summary(
            EvaluationQuery(), user_team_id="owner"
        ).pending_summary_task_count
        == 0
    )


@pytest.mark.parametrize("kind", ["ab", "stability"])
def test_partial_group_remains_visible_but_not_scored(repository, kind):
    task, runs = seed(repository, "owner", 2, kind)
    for run in runs:
        engine(repository).execute(run, StubTargetAdapter())
    damage(repository, runs[1].id, "missing")
    page = repository.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="owner")
    assert page.total == 1 and page.items[0].id == task.id
    assert len(page.items[0].runs) == 2 and page.items[0].summary_pending
    assert page.items[0].status == "completed"
    overview = repository.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="owner")
    assert overview.task_count == 1 and overview.pending_summary_task_count == 1
    assert overview.average_score is None and overview.completed_sample_count == 0


def test_independent_missing_summary_keeps_identity_and_pending_status(repository):
    from test_run_engine import pending_run

    run = pending_run().model_copy(update={"user_team_id": "owner"})
    repository.save_run(run)
    damage(repository, run.id, "missing")
    item = repository.list_evaluation_task_summaries(
        TaskSummaryQuery(), user_team_id="owner"
    ).items[0]
    assert item.id == run.id and item.name == run.id
    assert item.status == "pending" and item.summary_pending
    assert item.runs[0].run_id == run.id


def test_missing_dataset_sample_count_does_not_block_task_metrics(repository):
    from test_run_engine import pending_run

    from agentgate.domain import Dataset, DatasetVersion, utcnow

    repo = repository
    dataset = Dataset(name="Published", user_team_id="owner")
    repo.save_dataset(dataset)
    now = utcnow()
    version = DatasetVersion(
        dataset_id=dataset.id,
        user_team_id="owner",
        created_at=now,
        updated_at=now,
        version=1,
        status="published",
        published_at=now,
        cases=pending_run().manifest.dataset.cases,
    )
    repo.save_dataset_version(version)
    with sql(repo) as execute:
        execute(
            "UPDATE agentgate_dataset_versions SET sample_count=NULL WHERE id=:id",
            {"id": version.id},
        )
    overview = repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="owner")
    assert overview.task_count == 0 and overview.pending_dataset_count == 1
    assert overview.dataset_count == 0 and overview.dataset_sample_count == 0
    assert (
        repo.get_evaluation_overview_summary(
            EvaluationQuery(), user_team_id="other"
        ).pending_dataset_count
        == 0
    )


def test_missing_table_is_not_disguised_as_empty_data(repository):
    import sqlite3

    from sqlalchemy.exc import DBAPIError

    seed(repository, "owner")
    with sql(repository) as execute:
        execute("DROP TABLE agentgate_run_summaries", {})
    with pytest.raises((sqlite3.DatabaseError, DBAPIError, RuntimeError)):
        repository.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="owner")
    # Recreate only the test structure so the shared fixture can clean up afterwards.
    if not isinstance(repository, SQLiteRepository):
        from agentgate.storage.mysql_schema import metadata

        metadata.create_all(repository._engine)
