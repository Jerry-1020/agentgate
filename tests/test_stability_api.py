import pytest
from fastapi.testclient import TestClient
from agentgate.server.app import create_app
from agentgate.server.dependencies import DemoLoanTargetAdapter, InMemoryTraceCapture


class Dispatcher:
    def __init__(self, fail=False):
        self.ids = []
        self.fail = fail

    def submit(self, run_id):
        self.ids.append(run_id)
        if self.fail:
            raise RuntimeError("queue unavailable")


def body(count=3):
    return {"version": "loan-agent-v2-fixed", "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluator_ids": ["final-state"], "repetitions": count}


def test_repeated_runs_share_snapshot_and_persist_summary(tmp_path):
    path = tmp_path / "runs.db"
    dispatcher = Dispatcher()
    app = create_app(path, dispatcher=dispatcher)
    with TestClient(app) as client:
        response = client.post("/api/stability-experiments", json=body())
        assert response.status_code == 202, response.text
        task = response.json()["data"]
        assert task["run_ids"] == dispatcher.ids
        deps = app.state.dependencies
        runs = [deps.repository.get_run(id) for id in task["run_ids"]]
        assert len(runs) == 3
        assert all(r.manifest == runs[0].manifest for r in runs)
        pending = client.get("/api/stability-experiments/" + task["id"]).json()["data"]
        assert pending["mean"] is None and not pending["complete"]
        for run in runs:
            capture = InMemoryTraceCapture()
            try:
                deps.runs.execute_run(run.id, DemoLoanTargetAdapter(capture, state_store=deps.demo_state), capture.resolve)
            finally:
                capture.shutdown()
        summary = client.get("/api/stability-experiments/" + task["id"]).json()["data"]
        assert summary["complete"]
        assert summary["measured_runs"] == 3
        assert summary["sample_variance"] == 0
        assert summary["mean"] == 1
    with TestClient(create_app(path, dispatcher=Dispatcher())) as client:
        assert client.get("/api/stability-experiments/" + task["id"]).json()["data"] == summary


@pytest.mark.parametrize("count", [0, 1, 21, 2.5, True])
def test_invalid_repetitions_create_nothing(tmp_path, count):
    app = create_app(tmp_path / "runs.db", dispatcher=Dispatcher())
    with TestClient(app) as client:
        assert client.post("/api/stability-experiments", json=body(count)).status_code == 422
        assert app.state.dependencies.repository.list_runs(user_team_id="") == []


def test_dispatch_failure_retains_group_without_zero_scores(tmp_path):
    app = create_app(tmp_path / "runs.db", dispatcher=Dispatcher(fail=True))
    with TestClient(app) as client:
        task = client.post("/api/stability-experiments", json=body(2)).json()["data"]
        response = client.get("/api/stability-experiments/" + task["id"])
        assert response.status_code == 200, response.text
        summary = response.json()["data"]
        assert summary["complete"] and summary["mean"] is None
        assert summary["measured_runs"] == 0
        assert all(row["progress"]["status"] == "failed" for row in summary["runs"])


def test_group_transaction_rolls_back_new_runs_on_task_conflict(tmp_path):
    import sqlite3
    from agentgate.domain import EvaluationRun
    from agentgate.domain.evaluation_task import EvaluationTask
    app = create_app(tmp_path / "runs.db", dispatcher=Dispatcher())
    with TestClient(app) as client:
        task = client.post("/api/stability-experiments", json=body(2)).json()["data"]
        repo = app.state.dependencies.repository
        template = repo.get_run(task["run_ids"][0])
        runs = [EvaluationRun(manifest=template.manifest) for _ in range(2)]
        duplicate = EvaluationTask(id=task["id"], kind="stability", run_ids=tuple(r.id for r in runs))
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_task_runs(duplicate, runs)
        assert all(repo.get_run(r.id) is None for r in runs)
        assert len(repo.list_runs(user_team_id="")) == 2
