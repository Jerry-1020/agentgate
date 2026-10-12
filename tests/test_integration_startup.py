"""The supervisor isolates its processes and respects configured dispatch/storage."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("kind", ["bjs", "celery"])
@pytest.mark.parametrize("with_bank_agents", [False, True])
def test_supervisor_selects_services_and_ports(tmp_path, monkeypatch, kind, with_bank_agents):
    source = Path(__file__).resolve().parents[1] / "scripts/start-integration.py"
    spec = importlib.util.spec_from_file_location("integration_startup", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    monkeypatch.setenv("AGENT_TASK_DISPATCHER_TYPE", kind)
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    for key in ("BASE_URL", "NAME", "API_KEY"):
        monkeypatch.setenv("BANK_MODEL_" + key, "test-placeholder")
    checked_ports, started = [], []
    probe = MagicMock()
    probe.__enter__.return_value = probe
    probe.connect_ex.side_effect = lambda address: checked_ports.append(address[1]) or 1
    monkeypatch.setattr(module.socket, "socket", lambda: probe)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/" + name)
    seed = MagicMock()
    monkeypatch.setattr(module.subprocess, "run", seed)
    processes = []

    def start(command, **kwargs):
        started.append(command)
        child = MagicMock()
        child.poll.return_value = None
        child.pid = 98765
        processes.append(child)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", start)
    kill = MagicMock()
    monkeypatch.setattr(module.os, "killpg", kill)
    monkeypatch.setattr(module, "build_opener", lambda *_: MagicMock())

    class StartupComplete(Exception):
        pass

    def finish(_url):
        raise StartupComplete

    monkeypatch.setattr(module.webbrowser, "open", finish)
    monkeypatch.setattr(
        sys, "argv", [str(source), *(["--with-bank-agents"] if with_bank_agents else [])]
    )
    with pytest.raises(StartupComplete):
        module.main()
    commands = [" ".join(c) for c in started]
    assert (6397 in checked_ports) == (kind == "celery")
    assert any("celery" in c for c in commands) == (kind == "celery")
    assert any("dispatch-scheduled-runs.py" in c for c in commands) == (kind == "bjs")
    assert (8107 in checked_ports) == with_bank_agents
    assert 8210 in checked_ports
    assert any("trace-server.py" in c for c in commands)
    assert 8119 in checked_ports
    assert kill.call_count == len(started)
    assert all(p.wait.called for p in processes)
    seed.assert_called_once()
