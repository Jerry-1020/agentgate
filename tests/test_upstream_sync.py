"""Regression coverage for the 33db48a integration, not customer-environment proof."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from agentgate.application.dataset_management import DatasetManagement
from agentgate.domain import Case, CaseTurn, EvaluationRun, RunManifest
from agentgate.server.app import create_app
from agentgate.integrations.job_dispatchers.configuration import create_dispatcher
from agentgate.server.user_context import UserInfo, get_user_info, set_user_info, reset_user_info
from agentgate.storage.sqlite import SQLiteRepository


class Dispatcher:
    def submit(self, run_id):
        pass

    def cancel(self, run_id):
        pass


def team_dataset(repo):
    token = set_user_info(UserInfo("alpha", "user-a", "Tester"))
    try:
        service = DatasetManagement(repo)
        ds = service.create_dataset("Team dataset")
        service.create_draft(ds.id)
        service.save_case(ds.id, Case(name="Test", turns=(CaseTurn(input={"txt": "loan"}),)))
        service.publish_draft(ds.id)
        return ds.id
    finally:
        reset_user_info(token)


@pytest.mark.parametrize("repetitions", [1, 2])
def test_team_scope_covers_local_task_and_sample_endpoints(tmp_path, repetitions):
    app = create_app(tmp_path / "db", dispatcher=Dispatcher())
    ds_id = team_dataset(app.state.dependencies.repository)
    headers = {"user_team_id": "alpha", "user_id": "user-a", "user_name": "Tester"}
    with TestClient(app) as client:
        body = {"version": "loan-agent-v2-fixed", "dataset_id": ds_id,
                "dataset_version": 1, "evaluator_ids": ["final-state"], "max_parallel_cases": 3}
        url = "/api/evaluations" if repetitions == 1 else "/api/stability-experiments"
        if repetitions > 1:
            body["repetitions"] = repetitions
        response = client.post(url, json=body, headers=headers)
        assert response.status_code == 202, response.text
        ids = [response.json()["data"]["run_id"]] if repetitions == 1 else response.json()["data"]["run_ids"]
        assert len(client.get("/api/evaluation-tasks", headers=headers).json()["data"]) == 1
        for run_id in ids:
            run = app.state.dependencies.repository.get_run(run_id)
            assert (run.user_team_id, run.user_id, run.user_name) == ("alpha", "user-a", "Tester")
            assert run.manifest.max_parallel_cases == 3
            for suffix in ("samples", "target-descriptor", "manifest", "status"):
                path = f"/api/runs/{run_id}/{suffix}"
                assert client.get(path, headers=headers).status_code == 200
                assert client.get(path, headers={"user_team_id": "beta"}).status_code == 404
            assert client.post(f"/api/runs/{run_id}/cancel", headers={"user_team_id": "beta"}).status_code == 404
        for other in ({}, {"user_team_id": "beta"}):
            assert client.get("/api/evaluation-tasks", headers=other).json()["data"] == []
            assert client.get("/api/runs", headers=other).json()["data"] == []
            assert client.get(f"/api/evaluation-tasks/{ids[0]}", headers=other).status_code == 404
            if repetitions > 1:
                assert client.get(f"/api/stability-experiments/{ids[0]}", headers=other).status_code == 404
        assert get_user_info() is None


def test_existing_database_prefix_and_identity_migration_preserves_payloads(tmp_path):
    path = tmp_path / "legacy.db"
    app = create_app(path, dispatcher=Dispatcher())
    run = app.state.dependencies.execute_demo_run("loan-agent-v2-fixed")
    repo = app.state.dependencies.repository
    before_manifest = run.manifest.manifest_sha256
    before_results = repo.list_results(run.id)
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if row[0].startswith("agentgate_")]
        original_payloads = {t: db.execute(f'SELECT payload FROM "{t}"').fetchall() for t in tables if t != "agentgate_api_keys" and t != "agentgate_run_asset_refs"}
        for table in tables:
            for name in ("user_team_id", "user_id", "user_name", "api_key"):
                if name in {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}:
                    db.execute(f'ALTER TABLE "{table}" DROP COLUMN "{name}"')
            db.execute(f'ALTER TABLE "{table}" RENAME TO "{table.removeprefix("agentgate_")}"')
    migrated = SQLiteRepository(path)
    SQLiteRepository(path)  # idempotent reopen
    assert migrated.get_run(run.id).manifest.manifest_sha256 == before_manifest
    assert migrated.list_results(run.id) == before_results
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, payloads in original_payloads.items():
            assert db.execute(f'SELECT payload FROM "{table}"').fetchall() == payloads


def test_unsupported_raw_model_key_is_not_persisted(tmp_path):
    app = create_app(tmp_path / "db", dispatcher=Dispatcher())
    with TestClient(app) as client:
        response = client.post("/api/evaluations", json={"version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy", "api_key": "test-secret-not-a-real-key"})
        assert response.status_code == 422
        assert app.state.dependencies.repository.list_runs(user_team_id="") == []


@pytest.mark.parametrize("kind", ["typo", "", " "])
def test_unknown_dispatcher_is_rejected(monkeypatch, kind):
    monkeypatch.setenv("AGENT_TASK_DISPATCHER_TYPE", kind)
    with pytest.raises((RuntimeError, ValueError)):
        create_dispatcher()


@pytest.mark.parametrize("parallel", [0, 1.5])
def test_new_parallel_parameter_has_domain_bounds(parallel):
    from test_run_engine import pending_run
    base = pending_run().manifest.model_dump()
    base["max_parallel_cases"] = parallel
    with pytest.raises(ValueError):
        RunManifest(**base)
