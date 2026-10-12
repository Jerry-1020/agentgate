import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "local_launcher", Path(__file__).resolve().parents[1] / "scripts/start-integration.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_local_settings_are_portable_and_preserve_vault_key(tmp_path, monkeypatch):
    for name in (
        "AGENTGATE_DB_TYPE",
        "AGENT_TASK_DISPATCHER_TYPE",
        "AGENTGATE_DB",
        "AGENTGATE_API_KEY_ENCRYPTION_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTGATE_REDIS_URL", "redis://example.com:6379/0")
    first, ports = launcher.local_environment(tmp_path, 1000)
    second, _ = launcher.local_environment(tmp_path, 1000)
    assert first["AGENTGATE_API_KEY_ENCRYPTION_KEY"] == second["AGENTGATE_API_KEY_ENCRYPTION_KEY"]
    assert (tmp_path / "runtime/credential.key").stat().st_mode & 0o777 == 0o600
    assert first["AGENTGATE_REDIS_URL"] == "redis://127.0.0.1:7397/0"
    assert first["AGENTGATE_DB"] == str((tmp_path / "runtime/agentgate.db").resolve())
    assert first["VITE_LOCAL_PLATFORM_ORIGIN"] == "http://127.0.0.1:9119"
    assert first["AGENTGATE_TRACE_SERVER_URL"] == "http://127.0.0.1:9210"
    assert ports["web"] == 6197


def test_launcher_preserves_in_bank_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "tdsql")
    monkeypatch.setenv("AGENT_TASK_DISPATCHER_TYPE", "bjs")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "gateway")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", "https://bank.example")
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_URL", "https://trace.bank.example")
    monkeypatch.setenv("AGENTGATE_REDIS_URL", "redis://bank.example:6379/0")
    env, _ = launcher.local_environment(tmp_path)
    assert env["AGENTGATE_DB_TYPE"] == "tdsql"
    assert env["AGENT_TASK_DISPATCHER_TYPE"] == "bjs"
    assert env["AGENTGATE_AGENT_PLATFORM_ORIGIN"] == "https://bank.example"
    assert env["AGENTGATE_TRACE_SERVER_URL"] == "https://trace.bank.example"
    assert env["AGENTGATE_REDIS_URL"] == "redis://bank.example:6379/0"


def test_service_start_never_stops_existing_processes(tmp_path):
    import subprocess

    root = tmp_path / "copy"
    (root / "scripts").mkdir(parents=True)
    (root / ".venv/bin").mkdir(parents=True)
    (root / "scripts/run.sh").write_text(
        (Path(__file__).resolve().parents[1] / "scripts/run.sh").read_text()
    )
    python = root / ".venv/bin/python"
    python.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then echo bjs; fi\n')
    python.chmod(0o755)
    spy = root / ".venv/bin/pgrep"
    marker = root / "process-scan"
    spy.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
    spy.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(python.parent) + ":" + os.environ["PATH"],
        "AGENTGATE_MODEL_ENV_FILE": str(root / "absent.env"),
        "AGENTGATE_API_KEY_ENCRYPTION_KEY": "test-placeholder",
    }
    for service in ("api", "worker", "scheduler"):
        subprocess.run(["bash", str(root / "scripts/run.sh"), service], env=env, check=True)
    assert not marker.exists()
