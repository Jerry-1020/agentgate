"""The local supervisor only starts services required by the selected dispatcher."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("kind", ["bjs", "celery"])
@pytest.mark.parametrize("with_bank_agents", [False, True])
def test_supervisor_selects_services_and_ports(tmp_path, monkeypatch, kind, with_bank_agents):
    source = Path(__file__).resolve().parents[1] / "scripts/start-integration.py"
    spec = importlib.util.spec_from_file_location("integration_startup", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.root = tmp_path
    checked_ports = []
    started_services = []
    probe = MagicMock()
    probe.__enter__.return_value = probe

    def connect_ex(address):
        checked_ports.append(address[1])
        return 1

    probe.connect_ex.side_effect = connect_ex
    monkeypatch.setattr(module.socket, "socket", lambda: probe)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=kind))

    def start(command, **kwargs):
        started_services.append(command[-1])
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(module.subprocess, "Popen", start)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *a, **k: SimpleNamespace(close=lambda: None)
    )

    class StartupComplete(Exception):
        pass

    def finish(_url):
        raise StartupComplete

    monkeypatch.setattr(module.webbrowser, "open", finish)
    monkeypatch.setattr(
        sys, "argv", [str(source), *(["--with-bank-agents"] if with_bank_agents else [])]
    )
    try:
        with pytest.raises(StartupComplete):
            module.main()
    finally:
        for log in module.logs:
            log.close()
    expected = (
        ["api", "scheduler", "web"]
        if kind == "bjs"
        else [
            "redis",
            "api",
            "worker",
            "scheduler",
            "web",
        ]
    )
    assert started_services == (["bank-agents", *expected] if with_bank_agents else expected)
    assert (6397 in checked_ports) == (kind == "celery")
    assert (8107 in checked_ports) == with_bank_agents
