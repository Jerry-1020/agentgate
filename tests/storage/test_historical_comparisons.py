"""Historical comparisons preserve ownership, access and existing storage contracts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_historical_comparison import report

from agentgate.domain import RunStatus, Trace
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.result.summary import build_completed_run_summary
from agentgate.server.app import create_app
from agentgate.storage.evaluation_query_models import EvaluationQuery, TaskSummaryQuery
from agentgate.storage.historical_comparisons import TaskReferencedError
from agentgate.storage.sqlite import SQLiteRepository


def seed(repo, identity, team="", **kwargs):
    evidence = report(identity + "-run", **kwargs)
    run = evidence.run.model_copy(update={"user_team_id": team})
    repo.save_run(run)
    trace_ids = {case.id: uuid4().hex for case in run.manifest.execution_cases}
    for case_id, trace_id in trace_ids.items():
        repo.save_trace(Trace(trace_id=trace_id, run_id=run.id, case_id=case_id, spans=()))
    results = tuple(
        result.model_copy(update={"trace_id": trace_ids[result.case_id]})
        for result in evidence.results
    )
    repo.save_results(results)
    repo.save_completed_run(run, build_completed_run_summary(run, results))
    task = EvaluationTask(id=identity, name=identity, kind="single", run_ids=(run.id,))
    repo.save_evaluation_task(task)
    return task


def compare(repo, a, b, identity="comparison", team=""):
    return repo.save_historical_comparison(
        EvaluationTask(
            id=identity, name="历史对比", kind="ab", run_ids=(a.run_ids[0], b.run_ids[0])
        ),
        baseline_task_id=a.id,
        candidate_task_id=b.id,
        user_team_id=team,
    )


def test_reference_listing_scores_and_delete(repository):
    repo = repository
    a, b = seed(repo, "A", default_score=0), seed(repo, "B", default_score=1)
    before = repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="")
    task = compare(repo, a, b)
    assert repo.is_historical_comparison(task.id, user_team_id="")
    assert not repo.is_historical_comparison(a.id, user_team_id="")
    assert repo.get_evaluation_task(a.id) == a
    assert repo.get_evaluation_task(b.id) == b
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(kind="ab"), user_team_id="")
    assert page.total == 1
    assert page.items[0].historical_comparison
    assert [r.run_id for r in page.items[0].runs] == list(task.run_ids)
    assert [r.overall_score for r in page.items[0].runs] == [0, 1]
    assert page.items[0].status == "completed"
    assert (
        repo.list_evaluation_task_summaries(TaskSummaryQuery(kind="single"), user_team_id="").total
        == 2
    )
    after = repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="")
    assert after.task_count == before.task_count + 1
    assert after.scored_run_count == before.scored_run_count
    assert after.completed_sample_count == before.completed_sample_count
    assert after.average_score == before.average_score
    with pytest.raises(TaskReferencedError):
        repo.delete_task_record(a.id, user_team_id="")
    repo.delete_task_record(task.id, user_team_id="")
    assert repo.get_run(a.run_ids[0]) is not None
    assert len(repo.list_results(a.run_ids[0])) == 4
    repo.delete_task_record(a.id, user_team_id="")
    assert repo.get_run(a.run_ids[0]) is None
    assert repo.get_run(b.run_ids[0]) is not None


def test_retry_identity_access_and_multiple_references(repository):
    repo = repository
    a, b, c = (seed(repo, name, team="bank") for name in ("A", "B", "C"))
    task = compare(repo, a, b, team="bank")
    assert compare(repo, a, b, team="bank") == task
    with pytest.raises(ValueError):
        compare(repo, a, c, team="bank")
    with pytest.raises((ValueError, LookupError)):
        compare(repo, a, b, identity=a.id, team="bank")
    with pytest.raises(LookupError):
        compare(repo, a, b, identity="foreign", team="external")
    with pytest.raises(LookupError):
        repo.is_historical_comparison(task.id, user_team_id="external")
    assert (
        repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="external").total == 0
    )
    with pytest.raises(ValueError):
        repo.delete_task_record(task.id, user_team_id="external")
    second = compare(repo, a, c, identity="second", team="bank")
    repo.delete_task_record(task.id, user_team_id="bank")
    with pytest.raises(TaskReferencedError):
        repo.delete_task_record(a.id, user_team_id="bank")
    repo.delete_task_record(second.id, user_team_id="bank")
    repo.delete_task_record(a.id, user_team_id="bank")


def test_fixed_reference_survives_rerun(repository):
    repo = repository
    a, b = seed(repo, "A"), seed(repo, "B")
    task = compare(repo, a, b)
    old = repo.get_run(a.run_ids[0])
    new = old.model_copy(
        update={
            "id": "A-new",
            "status": RunStatus.PENDING,
            "started_at": None,
            "completed_at": None,
        }
    )
    repo.save_task_rerun(a.id, old.id, new, user_team_id="")
    assert repo.get_evaluation_task(task.id).run_ids == (old.id, b.run_ids[0])
    assert compare(repo, a, b) == task
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(kind="ab"), user_team_id="")
    assert page.items[0].status == "completed"
    assert page.items[0].runs[0].run_id == old.id
    with pytest.raises(TaskReferencedError):
        repo.delete_task_record(a.id, user_team_id="")


def test_unicode_ids_persist_and_paginate_without_schema_changes(tmp_path):
    path = tmp_path / "history.db"
    repo = SQLiteRepository(path)
    a, b = seed(repo, 'A"中文'), seed(repo, "B\\中文")
    with repo._connect() as db:
        schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    task = compare(repo, a, b)
    reopened = SQLiteRepository(path)
    assert reopened.get_evaluation_task(task.id) == task
    with reopened._connect() as db:
        assert db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == schema
        assert (
            db.execute(
                "SELECT COUNT(*) FROM agentgate_evaluation_task_runs WHERE task_id=?", (task.id,)
            ).fetchone()[0]
            == 0
        )
    all_ids = [
        repo.list_evaluation_task_summaries(TaskSummaryQuery(page=n, page_size=1), user_team_id="")
        .items[0]
        .id
        for n in range(1, 4)
    ]
    assert set(all_ids) == {a.id, b.id, task.id}


def test_concurrent_retries_create_one_task(tmp_path):
    repo = SQLiteRepository(tmp_path / "history.db")
    a, b = seed(repo, "A"), seed(repo, "B")
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(lambda _: compare(repo, a, b), range(8)))
    assert all(task == saved[0] for task in saved)
    assert len(repo.list_evaluation_tasks()) == 3


def test_delete_racing_creation_never_leaves_a_broken_comparison(tmp_path):
    repo = SQLiteRepository(tmp_path / "race.db")
    a, b = seed(repo, "A"), seed(repo, "B")
    barrier = Barrier(2)

    def create():
        barrier.wait()
        try:
            return compare(repo, a, b)
        except LookupError:
            return None

    def delete():
        barrier.wait()
        try:
            repo.delete_task_record(a.id, user_team_id="")
        except TaskReferencedError:
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        created, deleted = pool.submit(create), pool.submit(delete)
        saved = created.result()
        deleted.result()
    assert (repo.get_run(a.run_ids[0]) is not None) == (saved is not None)
    assert (repo.get_evaluation_task("comparison") is not None) == (saved is not None)


def test_missing_reference_is_not_partially_visible(tmp_path):
    repo = SQLiteRepository(tmp_path / "missing.db")
    a, b = seed(repo, "A"), seed(repo, "B")
    compare(repo, a, b)
    with repo._connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DELETE FROM agentgate_runs WHERE id=?", (b.run_ids[0],))
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(kind="ab"), user_team_id="")
    assert page.total == 0
    with pytest.raises(LookupError):
        repo.is_historical_comparison("comparison", user_team_id="")


def test_api_creates_reads_and_deletes_without_dispatch(tmp_path):
    class Dispatcher:
        def submit(self, run_id):
            pytest.fail("historical comparison must never dispatch a run")

    with TestClient(create_app(tmp_path / "api.db", dispatcher=Dispatcher())) as client:
        repo = client.app.state.dependencies.repository
        a, b = seed(repo, "A"), seed(repo, "B", dataset_id="different", default_score=1)
        body = {
            "comparison_id": "history",
            "baseline_task_id": a.id,
            "baseline_run_id": a.run_ids[0],
            "candidate_task_id": b.id,
            "candidate_run_id": b.run_ids[0],
        }
        first = client.post("/api/evaluation-tasks/history-comparisons", json=body)
        assert first.status_code == 201, first.text
        assert (
            client.post("/api/evaluation-tasks/history-comparisons", json=body).json()
            == first.json()
        )
        detail = client.get("/api/evaluation-tasks/history").json()["data"]
        assert detail["historical_comparison"]
        result = client.get("/api/evaluation-tasks/history/comparison").json()["data"]
        overall = result["score_rows"][0]
        assert overall["baseline_score"] == 0.5 and overall["candidate_score"] == 1
        assert not overall["comparable"] and overall["score_delta"] == 0.5
        assert "dataset_changed" in overall["reasons"]
        assert client.delete("/api/evaluation-tasks/A").status_code == 409
        assert (
            client.post(
                "/api/evaluation-tasks/history/rerun", json={"source_run_id": a.run_ids[0]}
            ).status_code
            == 409
        )
        assert client.delete("/api/evaluation-tasks/history").status_code == 200
        assert client.get("/api/evaluation-tasks/A").status_code == 200
        assert client.delete("/api/evaluation-tasks/A").status_code == 200
