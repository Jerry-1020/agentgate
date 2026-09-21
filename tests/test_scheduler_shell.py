"""Exercise Shell routing without starting schedulers or contacting a broker."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from test_bjs_execution import run_script


@pytest.mark.parametrize("kind", ["bjs", "celery", "invalid"])
def test_scheduler_shell_selects_configured_process(tmp_path, kind):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "deployed project"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(source / "scripts/run.sh", root / "scripts/run.sh")
    (root / "src").symlink_to(source / "src", target_is_directory=True)
    (root / ".env").write_text(f"AGENT_TASK_DISPATCHER_TYPE={kind}\n")
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    # Use the real configuration parser, but record the selected process instead of launching it.
    python.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if sys.argv[1] == '-c':\n"
        f"    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
        "print(json.dumps(sys.argv[1:]))\n"
    )
    python.chmod(0o755)

    result = run_script(root, "scheduler")

    if kind == "invalid":
        assert result.returncode != 0
        assert "AGENT_TASK_DISPATCHER_TYPE must be celery or bjs" in result.stderr
        assert not result.stdout.strip()
        return
    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)
    if kind == "bjs":
        assert arguments == ["scripts/dispatch-scheduled-runs.py"]
    else:
        assert arguments[:5] == [
            "-m",
            "celery",
            "-A",
            "agentgate.integrations.job_dispatchers.celery:celery_app",
            "worker",
        ]
        assert "--queues=agentgate.scheduler" in arguments
        assert "--beat" in arguments
