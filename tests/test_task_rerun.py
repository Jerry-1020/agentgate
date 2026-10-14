"""Task identity remains stable while executions and evidence stay immutable."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from agentgate.domain import EvaluationRun, RunStatus, utcnow
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.server.app import create_app


class Dispatcher:
    def __init__(self):
        self.ids = []
        self.fail = False

    def submit(self, run_id):
        self.ids.append(run_id)
        if self.fail:
            raise RuntimeError("dispatch unavailable")

    def cancel(self, run_id):
        pass


def completed_task(client):
    deps = client.app.state.dependencies
    source = deps.execute_demo_run("loan-agent-v1-risky")
    task = EvaluationTask(id="stable-task-id", name="原测评任务", kind="single", run_ids=(source.id,))
    deps.repository.save_evaluation_task(task)
    return task, source


def rerun(client, task_id, run_id):
    return client.post(f"/api/evaluation-tasks/{task_id}/rerun", json={"source_run_id": run_id})


def execute(client, run_id):
    capture = InMemoryTraceCapture()
    try:
        return client.app.state.dependencies.runs.execute_run(
            run_id, DemoLoanTargetAdapter(capture), capture.resolve,
        )
    finally:
        capture.shutdown()


def test_rerun_preserves_task_snapshot_and_old_evidence_across_restart(tmp_path):
    path = tmp_path / "rerun.db"
    dispatcher = Dispatcher()
    with TestClient(create_app(path, dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        repo = client.app.state.dependencies.repository
        before = source.model_dump_json()
        traces, results = repo.list_traces(source.id), repo.list_results(source.id)
        assert traces and results
        response = rerun(client, task.id, source.id)
        assert response.status_code == 202, response.text
        updated = response.json()["data"]
        assert updated["id"] == task.id
        assert updated["name"] == task.name
        assert updated["created_at"] == task.model_dump(mode="json")["created_at"]
        assert updated["previous_run_ids"] == [source.id]
        next_id = updated["run_ids"][0]
        assert next_id != source.id
        next_run = repo.get_run(next_id)
        assert next_run.status == RunStatus.PENDING
        assert next_run.manifest == source.manifest
        assert next_run.manifest.target.credential_ref == source.manifest.target.credential_ref
        assert next_run.api_key == source.api_key
        assert next_run.started_at is next_run.completed_at is next_run.error is None
        assert repo.list_traces(next_id) == repo.list_results(next_id) == []
        assert repo.get_run(source.id).model_dump_json() == before
        assert repo.list_traces(source.id) == traces
        assert repo.list_results(source.id) == results
        assert dispatcher.ids == [next_id]
        assert len(client.get("/api/evaluation-tasks").json()["data"]) == 1

    with TestClient(create_app(path, dispatcher=Dispatcher())) as client:
        updated = client.get(f"/api/evaluation-tasks/{task.id}").json()["data"]
        assert updated["run_ids"] == [next_id]
        assert updated["previous_run_ids"] == [source.id]
        assert client.get(f"/api/runs/{source.id}/samples").status_code == 200


def test_repeated_reruns_preserve_history_and_metadata_then_delete_all_runs(tmp_path):
    with TestClient(create_app(tmp_path / "repeat.db", dispatcher=Dispatcher())) as client:
        task, source = completed_task(client)
        repo = client.app.state.dependencies.repository
        first = rerun(client, task.id, source.id)
        assert first.status_code == 202, first.text
        first_id = first.json()["data"]["run_ids"][0]
        assert execute(client, first_id).status == RunStatus.COMPLETED
        second = rerun(client, task.id, first_id)
        assert second.status_code == 202, second.text
        second_id = second.json()["data"]["run_ids"][0]
        assert second.json()["data"]["previous_run_ids"] == [source.id, first_id]
        saved = client.put(f"/api/evaluation-tasks/{task.id}", json={
            "kind": "single", "run_ids": [second_id], "name": "重命名",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["previous_run_ids"] == [source.id, first_id]
        assert saved.json()["data"]["name"] == "重命名"
        assert client.delete(f"/api/evaluation-tasks/{task.id}").status_code == 200
        for run_id in (source.id, first_id, second_id):
            assert repo.get_run(run_id) is None
            assert repo.list_traces(run_id) == repo.list_results(run_id) == []


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_single_task_can_rerun(tmp_path, status):
    with TestClient(create_app(tmp_path / "terminal.db", dispatcher=Dispatcher())) as client:
        task, source = completed_task(client)
        if status != "completed":
            run = EvaluationRun(
                manifest=source.manifest, status=status, completed_at=utcnow(),
                created_at=source.created_at, error="failure" if status == "failed" else None,
            )
            repo = client.app.state.dependencies.repository
            repo.save_run(run)
            task = EvaluationTask(kind="single", run_ids=(run.id,))
            repo.save_evaluation_task(task)
            source = run
        response = rerun(client, task.id, source.id)
        assert response.status_code == 202, response.text


@pytest.mark.parametrize("status", ["pending", "waiting", "running", "scheduled"])
def test_active_task_cannot_rerun(tmp_path, status):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "active.db", dispatcher=dispatcher)) as client:
        _, source = completed_task(client)
        values = {"manifest": source.manifest, "created_at": source.created_at, "status": status}
        if status == "running":
            values["started_at"] = utcnow()
        if status == "scheduled":
            values["scheduled_for"] = utcnow() + timedelta(hours=1)
        active = EvaluationRun(**values)
        repo = client.app.state.dependencies.repository
        repo.save_run(active)
        task = EvaluationTask(kind="single", run_ids=(active.id,))
        repo.save_evaluation_task(task)
        response = rerun(client, task.id, active.id)
        assert response.status_code == 409, response.text
        assert repo.get_evaluation_task(task.id).run_ids == (active.id,)
        assert dispatcher.ids == []


def test_stale_and_concurrent_requests_do_not_create_extra_runs(tmp_path):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "race.db", dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: rerun(client, task.id, source.id), range(2)))
        assert sorted(r.status_code for r in responses) == [202, 409]
        assert len(dispatcher.ids) == 1
        repo = client.app.state.dependencies.repository
        assert len(repo.list_runs(user_team_id="")) == 2
        assert rerun(client, task.id, source.id).status_code == 409
        assert len(repo.list_runs(user_team_id="")) == 2


@pytest.mark.parametrize("kind", ["ab", "stability"])
def test_group_task_cannot_rerun_as_single(tmp_path, kind):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "group.db", dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        repo = client.app.state.dependencies.repository
        other = EvaluationRun.model_validate({**source.model_dump(), "id": "second-run"})
        repo.save_run(other)
        group = EvaluationTask(kind=kind, run_ids=(source.id, other.id))
        # Source is already assigned to a single task; use another independent run.
        first = EvaluationRun.model_validate({**source.model_dump(), "id": "first-run"})
        repo.save_run(first)
        group = group.model_copy(update={"run_ids": (first.id, other.id)})
        repo.save_evaluation_task(group)
        assert rerun(client, group.id, first.id).status_code == 409
        assert dispatcher.ids == []
        assert repo.get_evaluation_task(task.id).run_ids == (source.id,)


def test_missing_and_other_team_tasks_are_inaccessible(tmp_path):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "scope.db", dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        assert rerun(client, "missing", source.id).status_code == 404
        response = client.post(f"/api/evaluation-tasks/{task.id}/rerun",
                               json={"source_run_id": source.id}, headers={"user_team_id": "other"})
        assert response.status_code == 404
        assert dispatcher.ids == []


def test_dispatch_failure_keeps_new_current_run_for_existing_retry_mechanism(tmp_path):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "dispatch.db", dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        dispatcher.fail = True
        response = rerun(client, task.id, source.id)
        assert response.status_code == 202, response.text
        current = response.json()["data"]["run_ids"][0]
        repo = client.app.state.dependencies.repository
        assert repo.get_run(current).status == RunStatus.WAITING
        assert repo.get_run(current).dispatch_attempts == 1
        assert repo.get_evaluation_task(task.id).previous_run_ids == (source.id,)
        assert repo.get_run(source.id).status == RunStatus.COMPLETED


def test_delete_task_history_is_scoped_to_owning_team(tmp_path):
    with TestClient(create_app(tmp_path / "delete-scope.db", dispatcher=Dispatcher())) as client:
        _, template = completed_task(client)
        repo = client.app.state.dependencies.repository
        source = EvaluationRun.model_validate({
            **template.model_dump(), "id": "team-source", "user_team_id": "owner-team",
        })
        repo.save_run(source)
        task = EvaluationTask(kind="single", run_ids=(source.id,))
        repo.save_evaluation_task(task)
        response = client.post(f"/api/evaluation-tasks/{task.id}/rerun",
                               json={"source_run_id": source.id}, headers={"user_team_id": "owner-team"})
        assert response.status_code == 202, response.text
        current = response.json()["data"]["run_ids"][0]
        assert client.delete(f"/api/evaluation-tasks/{task.id}",
                             headers={"user_team_id": "other-team"}).status_code == 404
        assert repo.get_run(source.id, user_team_id="owner-team") is not None
        assert repo.get_run(current, user_team_id="owner-team") is not None
        assert client.delete(f"/api/evaluation-tasks/{task.id}",
                             headers={"user_team_id": "owner-team"}).status_code == 200
        assert repo.get_run(source.id, user_team_id="owner-team") is None
        assert repo.get_run(current, user_team_id="owner-team") is None


def test_persistence_failure_rolls_back_run_and_task_switch(tmp_path, monkeypatch):
    dispatcher = Dispatcher()
    with TestClient(create_app(tmp_path / "rollback.db", dispatcher=dispatcher)) as client:
        task, source = completed_task(client)
        repo = client.app.state.dependencies.repository
        original_insert = repo._insert_task_run
        inserted = []

        def failing_insert(db, run):
            original_insert(db, run)
            inserted.append(run.id)
            raise RuntimeError("simulated persistence failure")

        monkeypatch.setattr(repo, "_insert_task_run", failing_insert)
        assert rerun(client, task.id, source.id).status_code == 503
        assert len(inserted) == 1
        assert repo.get_run(inserted[0]) is None
        assert repo.get_evaluation_task(task.id).run_ids == (source.id,)
        assert repo.get_evaluation_task(task.id).previous_run_ids == ()
        assert dispatcher.ids == []
