from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from agentgate.domain import EvaluationRun, RunStatus
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.app import create_app
from agentgate.storage.sqlite import SQLiteRepository
from agentgate.storage.evaluation_query_models import (
    EvaluationQuery,
    TaskSummaryQuery,
)
from agentgate.application.evaluation_summary_backfill import backfill
from test_run_engine import pending_run, engine, StubTargetAdapter


def seed(repo, team, count=1, kind="single"):
    runs = []
    for i in range(count):
        run = pending_run().model_copy(update={"id": str(uuid4()), "user_team_id": team})
        repo.save_run(run)
        runs.append(run)
    task = EvaluationTask(kind=kind, name="Task " + team, run_ids=tuple(r.id for r in runs))
    repo.save_evaluation_task(task)
    return task, runs


def test_team_scope_and_ab_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "q.db")
    a, ar = seed(repo, "a", 2, "ab")
    b, br = seed(repo, "b")
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="a")
    assert page.total == 1
    assert page.items[0].id == a.id
    assert [r.run_id for r in page.items[0].runs] == list(a.run_ids)
    assert page.items[0].total_cases == 2
    assert repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="none").total == 0
    assert repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="a").task_count == 1


def test_completed_score_progress_and_backfill(tmp_path):
    repo = SQLiteRepository(tmp_path / "q.db")
    task, runs = seed(repo, "a")
    completed = engine(repo).execute(runs[0], StubTargetAdapter())
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="a")
    assert page.items[0].status == RunStatus.COMPLETED
    assert page.items[0].completed_cases == 1
    assert page.items[0].runs[0].overall_score == 1
    summary = repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="a")
    assert summary.average_score == 1 and summary.completed_sample_count == 1
    assert backfill(repo, apply=True)["failures"] == []
    assert backfill(repo, apply=True)["failures"] == []
    assert repo.get_evaluation_overview_summary(EvaluationQuery(), user_team_id="a") == summary


def test_pagination_filter_and_unknown_summary(tmp_path):
    repo = SQLiteRepository(tmp_path / "q.db")
    for _ in range(3):
        seed(repo, "a")
    q = TaskSummaryQuery(page=2, page_size=2, status="pending", keyword="Task a", kind="single")
    page = repo.list_evaluation_task_summaries(q, user_team_id="a")
    assert page.total == 3 and len(page.items) == 1
    assert (
        repo.list_evaluation_task_summaries(TaskSummaryQuery(keyword="%"), user_team_id="a").total
        == 0
    )
    with repo._connect() as db:
        db.execute("DELETE FROM agentgate_run_summaries")
    degraded = repo.list_evaluation_task_summaries(q, user_team_id="a")
    assert degraded.total == 3 and degraded.items[0].summary_pending
    assert backfill(repo, apply=True)["failures"] == []
    assert repo.list_evaluation_task_summaries(q, user_team_id="a").total == 3


@pytest.mark.parametrize(
    "values",
    [
        {"page": 0},
        {"page_size": 101},
        {"keyword": "a" * 257},
        {"start_at": datetime.now()},
        {
            "start_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "end_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ],
)
def test_query_validation(values):
    with pytest.raises(ValueError):
        TaskSummaryQuery(**values)


def test_http_contract(tmp_path):
    class Dispatcher:
        def submit(self, run_id):
            pass

    with TestClient(create_app(tmp_path / "api.db", dispatcher=Dispatcher())) as client:
        repo = client.app.state.dependencies.repository
        task, _ = seed(repo, "team-a")
        a = client.get("/api/evaluation-task-summaries", headers={"X-Team-Id": "team-a"})
        assert a.status_code == 200, a.text
        assert a.json()["data"]["items"][0]["id"] == task.id
        assert (
            client.get("/api/evaluation-task-summaries", headers={"X-Team-Id": "team-b"}).json()[
                "data"
            ]["total"]
            == 0
        )
        overview = client.get(
            "/api/evaluation-overview/summary", headers={"X-Team-Id": "team-a"}
        )
        assert overview.status_code == 200, overview.text
        assert overview.json()["data"]["task_count"] == 1
        assert client.get("/api/evaluation-task-summaries?page=0").status_code == 422
        assert client.get("/api/evaluation-overview/summary?start_at=2026-01-01").status_code == 422


def assert_history_counts(repo):
    from agentgate.domain import transition_run
    task, old = seed(repo, "history")
    current = old[0]
    for _ in range(2):
        repo.save_run(transition_run(current, RunStatus.CANCELLED))
        replacement = current.model_copy(update={"id": str(uuid4())})
        repo.save_task_rerun(task.id, current.id, replacement, user_team_id="history")
        current = replacement
    independent = pending_run().model_copy(update={"id": str(uuid4()), "user_team_id": "history"})
    repo.save_run(independent)
    page = repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="history")
    by_id = {r.id: r for r in page.items}
    assert by_id[task.id].previous_run_count == 2
    assert by_id[independent.id].previous_run_count == 0
    assert page.total == 2
    assert repo.list_evaluation_task_summaries(TaskSummaryQuery(keyword=task.id), user_team_id="history").items[0].previous_run_count == 2
    assert not repo.list_evaluation_task_summaries(TaskSummaryQuery(), user_team_id="other").items


def test_historical_summary_count(tmp_path):
    assert_history_counts(SQLiteRepository(tmp_path / "history.db"))
