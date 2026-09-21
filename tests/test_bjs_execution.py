"""BJS process entry points execute persisted Runs without Redis or Celery workers."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from test_celery_dispatcher import seed_demo, target

from agentgate.application import RunManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import RunStatus, transition_run
from agentgate.integrations.job_dispatchers.bjs_job_dispatcher import BjsJobDispatcher
from agentgate.storage.sqlite import SQLiteRepository

ROOT = Path(__file__).resolve().parents[1]


def prepare_script_tree(tmp_path, settings):
    """Copy launchers to exercise deployment paths, with an isolated .env and database."""
    root = tmp_path / "deployed project"
    for name in (
        "scripts/run.sh",
        "scripts/dispatch-scheduled-runs.py",
        "scripts/bjs/run_eval.sh",
        "scripts/bjs/run_evaluation.py",
    ):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    (root / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    (root / "src").symlink_to(ROOT / "src", target_is_directory=True)
    (root / ".env").write_text(
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in settings.items()) + "\n"
    )
    return root


def run_script(root, *arguments):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AGENTGATE_", "AGENT_TASK_"))
    }
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        AGENTGATE_LOG_PATH=str(root / "logs"),
        # BJS execution must not import/validate unrelated Celery configuration.
        AGENTGATE_WORKER_CONCURRENCY="not-a-celery-worker",
    )
    return subprocess.run(
        ["bash", str(root / "scripts/run.sh"), *arguments],
        cwd=root.parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def create_demo_run(repository):
    seed_demo(repository)
    management = RunManagement(repository, build_default_evaluator_management(repository))
    return management, management.create_run(target(), dataset_id="loan-risk-policy")


@pytest.mark.parametrize("state", ["pending", "cancelled", "failed", "scheduled", "running"])
def test_bjs_process_reads_config_and_obeys_persisted_state(tmp_path, state):
    from datetime import timedelta

    repository = SQLiteRepository(tmp_path / "configured.db")
    management, run = create_demo_run(repository)
    if state == "cancelled":
        management.cancel_run(run.id, BjsJobDispatcher("https://bjs.example/submit", "ai11"))
    elif state == "failed":
        repository.save_run(transition_run(run, RunStatus.FAILED, error="execution failed"))
    elif state == "running":
        repository.claim_pending_run(run.id, run.created_at)
    elif state == "scheduled":
        run = management.create_run(
            target(),
            dataset_id="loan-risk-policy",
            scheduled_for=run.created_at + timedelta(hours=1),
        )
    root = prepare_script_tree(
        tmp_path,
        {
            "AGENTGATE_DB_TYPE": "sqlite",
            "AGENTGATE_DB": str(repository.path),
            "AGENT_TASK_DISPATCHER_TYPE": "bjs",
        },
    )
    result = run_script(root, "execute-run", run.id)
    expected = "completed" if state == "pending" else state
    assert result.stdout.strip() == expected, result.stderr
    assert result.returncode == (1 if state in {"failed", "scheduled"} else 0)
    assert repository.get_run(run.id).status.value == expected
    if state == "pending":
        traces = repository.list_traces(run.id)
        results = repository.list_results(run.id)
        assert traces and results
        repeated = run_script(root, "execute-run", run.id)
        assert repeated.returncode == 0
        assert repository.list_traces(run.id) == traces
        assert repository.list_results(run.id) == results
    else:
        assert not repository.list_traces(run.id)
        assert not repository.list_results(run.id)


def test_bjs_shell_wrapper_uses_same_configuration(tmp_path):
    repository = SQLiteRepository(tmp_path / "wrapper.db")
    _, run = create_demo_run(repository)
    root = prepare_script_tree(
        tmp_path,
        {
            "AGENTGATE_DB_TYPE": "sqlite",
            "AGENTGATE_DB": str(repository.path),
        },
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("AGENTGATE_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AGENTGATE_LOG_PATH"] = str(tmp_path / "logs")
    result = subprocess.run(
        ["bash", str(root / "scripts/bjs/run_eval.sh"), run.id],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert repository.get_run(run.id).status is RunStatus.COMPLETED


def test_unknown_run_returns_nonzero_exit_without_traceback(tmp_path):
    root = prepare_script_tree(
        tmp_path,
        {
            "AGENTGATE_DB_TYPE": "sqlite",
            "AGENTGATE_DB": str(tmp_path / "missing.db"),
        },
    )
    result = run_script(root, "execute-run", "missing")
    assert result.returncode == 1
    assert result.stderr.strip() == "Run execution failed: ValueError"
