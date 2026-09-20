"""Composition roots use the configured database and release their connections."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_run_engine import pending_run
from typer.testing import CliRunner

from agentgate.application import TargetCatalog
from agentgate.cli.main import app as cli_app
from agentgate.demo.bootstrap import ensure_demo_dataset, ensure_demo_target_descriptors
from agentgate.domain import utcnow
from agentgate.integrations.job_dispatchers import celery as jobs
from agentgate.server.app import create_app
from agentgate.server.dependencies import build_dependencies
from agentgate.storage.configuration import SQLiteConfig, create_repository, load_database_config


def select_mysql(monkeypatch, config):
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "tdsql")
    monkeypatch.setenv("AGENTGATE_TDSQL_URL", config.url)
    monkeypatch.setenv("AGENTGATE_TDSQL_USER", config.username)
    monkeypatch.setenv("AGENTGATE_TDSQL_PASSWORD", config.password.get_secret_value())


class RecordingDispatcher:
    def __init__(self):
        self.run_ids = []

    def submit(self, run_id):
        self.run_ids.append(run_id)

    def cancel(self, run_id):
        pass


def test_api_cli_and_worker_share_mysql_without_automatic_seed(
    mysql_repository, mysql_config, monkeypatch
):
    select_mysql(monkeypatch, mysql_config)
    dispatcher = RecordingDispatcher()
    application = create_app(dispatcher=dispatcher)
    assert mysql_repository.list_datasets(user_team_id="") == []
    assert mysql_repository.list_target_descriptors() == []
    ensure_demo_dataset(mysql_repository)
    ensure_demo_target_descriptors(TargetCatalog(mysql_repository))
    with TestClient(application) as client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": "loan-risk-policy",
                "dataset_version": 1,
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        assert dispatcher.run_ids == [run_id]
        assert jobs.execute_evaluation_run.run(run_id) == "completed"
        assert client.get(f"/api/runs/{run_id}").status_code == 200
        assert mysql_repository.list_results(run_id)
        assert mysql_repository.list_traces(run_id)
        assert client.get("/api/evaluation-tasks").json()
    with pytest.raises(RuntimeError, match="repository must be open"):
        application.state.dependencies.repository.get_run(run_id)
    result = CliRunner().invoke(cli_app, ["dataset", "list"])
    assert result.exit_code == 0, result.output
    assert any(item["id"] == "loan-risk-policy" for item in json.loads(result.output))


def test_scheduler_releases_mysql_run(mysql_repository, mysql_config, monkeypatch):
    select_mysql(monkeypatch, mysql_config)
    template = pending_run()
    now = utcnow()
    run = type(template).model_validate(
        {
            **template.model_dump(),
            "status": "scheduled",
            "created_at": now - timedelta(minutes=2),
            "scheduled_for": now - timedelta(minutes=1),
        }
    )
    mysql_repository.save_run(run)
    submitted = []
    monkeypatch.setattr(
        jobs.CeleryJobDispatcher, "submit", lambda self, run_id: submitted.append(run_id)
    )
    assert jobs.dispatch_due_evaluation_runs.run() == 1
    assert submitted == [run.id]
    assert mysql_repository.get_run(run.id).status == "pending"


def test_initialization_failure_closes_repository(mysql_repository, mysql_config, monkeypatch):
    from agentgate.server import dependencies

    select_mysql(monkeypatch, mysql_config)
    monkeypatch.setattr(dependencies, "create_repository", lambda config: mysql_repository)

    def fail():
        raise ValueError("invalid Judge configuration")

    monkeypatch.setattr(dependencies, "load_judge_model_from_environment", fail)
    with pytest.raises(ValueError, match="invalid Judge"):
        build_dependencies()
    with pytest.raises(RuntimeError, match="repository must be open"):
        mysql_repository.get_run("missing")


def test_default_factory_uses_sqlite(tmp_path):
    config = load_database_config({}, database_path=tmp_path / "default.db")
    assert isinstance(config, SQLiteConfig)
    repository = create_repository(config)
    try:
        assert repository.list_runs(user_team_id="") == []
    finally:
        repository.close()
