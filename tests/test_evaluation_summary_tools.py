import importlib.util
import json
from pathlib import Path
import sys
import pytest
from agentgate.storage.sqlite import SQLiteRepository
from test_evaluation_queries import seed


def module(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_coverage_gate_has_separate_thresholds():
    tool = module("check_evaluation_coverage")
    report = {
        "files": {
            "src/a.py": {
                "summary": {
                    "covered_lines": 9,
                    "num_statements": 10,
                    "covered_branches": 1,
                    "num_branches": 2,
                }
            }
        }
    }
    assert "branches 50.00%" in tool.check(report, ["src/a.py"], 80)[0]
    assert tool.check(report, ["missing.py"], 80) == ["missing.py: missing coverage"]
    assert not tool.check(report, ["src/a.py"], 50)
    report["files"]["src/a.py"]["summary"]["num_branches"] = 0
    assert not tool.check(report, ["src/a.py"], 80)
    report["files"]["src/a.py"]["summary"]["covered_lines"] = 1
    assert "lines 10.00%" in tool.check(report, ["src/a.py"], 80)[0]


def test_sqlite_tools_check_and_apply(tmp_path, monkeypatch):
    path = tmp_path / "tools.db"
    repo = SQLiteRepository(path)
    seed(repo, "a")
    migrate = module("migrate_evaluation_summaries")
    for flag in ["--check", "--apply"]:
        monkeypatch.setattr(sys, "argv", ["migrate", "--sqlite", str(path), flag])
        assert migrate.main() == 0
    fill = module("backfill_evaluation_summaries")
    report = tmp_path / "report.json"
    for flag in ["--check", "--apply", "--check"]:
        monkeypatch.setattr(
            sys, "argv", ["backfill", "--sqlite", str(path), flag, "--report", str(report)]
        )
        assert fill.main() == 0
        assert not json.loads(report.read_text())["failures"]
    with repo._connect() as db:
        db.execute("DELETE FROM agentgate_run_summaries")
    monkeypatch.setattr(
        sys, "argv", ["backfill", "--sqlite", str(path), "--check", "--report", str(report)]
    )
    assert fill.main() == 1
    with repo._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM agentgate_run_summaries").fetchone()[0] == 0
    monkeypatch.setattr(sys, "argv", ["migrate", "--sqlite", str(tmp_path / "missing.db")])
    with pytest.raises(ValueError):
        migrate.main()


def test_coverage_command_exit_status(tmp_path, monkeypatch):
    tool = module("check_evaluation_coverage")
    coverage = tmp_path / "c.json"
    files = tmp_path / "f.txt"
    coverage.write_text(json.dumps({"files": {}}))
    files.write_text("missing.py\n")
    monkeypatch.setattr(
        sys, "argv", ["check", "--coverage-json", str(coverage), "--files", str(files)]
    )
    assert tool.main() == 1


def test_changed_line_gate(monkeypatch):
    from types import SimpleNamespace

    tool = module("check_evaluation_coverage")

    def run(command, **kwargs):
        return SimpleNamespace(stdout="@@ -1,2 +1,2 @@\n", returncode=0)

    monkeypatch.setattr(tool.subprocess, "run", run)
    data = {"files": {"src/a.py": {"executed_lines": [1], "missing_lines": [2]}}}
    assert tool.check_changed_lines(data, ["src/a.py"], "HEAD", 80)
    assert not tool.check_changed_lines(data, ["src/a.py"], "HEAD", 50)
    assert not tool.check_changed_lines(data, ["absent.py"], "HEAD", 80)
    monkeypatch.setattr(
        tool.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="", returncode=1)
    )
    assert tool.check_changed_lines(data, ["src/a.py"], "HEAD", 80)


def test_cli_entrypoints_and_legacy_sqlite_upgrade(tmp_path, monkeypatch):
    import runpy
    import sqlite3

    root = Path(__file__).resolve().parents[1] / "scripts"
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as db:
        db.executescript("""
        CREATE TABLE agentgate_runs(id TEXT PRIMARY KEY);
        CREATE TABLE agentgate_evaluation_tasks(id TEXT PRIMARY KEY,created_at TEXT,payload TEXT);
        CREATE TABLE agentgate_evaluation_task_runs(run_id TEXT PRIMARY KEY,task_id TEXT);
        CREATE TABLE agentgate_dataset_versions(id TEXT PRIMARY KEY);
        """)
    for flag in ["--check", "--apply", "--check"]:
        monkeypatch.setattr(sys, "argv", ["migration", "--sqlite", str(legacy), flag])
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(root / "migrate_evaluation_summaries.py"), run_name="__main__")
        assert exc.value.code == 0
    full = tmp_path / "full.db"
    SQLiteRepository(full)
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill", "--sqlite", str(full), "--check", "--report", str(tmp_path / "report.json")],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(root / "backfill_evaluation_summaries.py"), run_name="__main__")
    assert exc.value.code == 0
