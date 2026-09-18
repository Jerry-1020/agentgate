"""Back up a legacy database into this workspace and verify lossless migration.

Source is read-only. Refuses to replace an existing destination database.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from agentgate.storage.sqlite import SQLiteRepository

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1]).resolve()
destination = root / "runtime/agentgate.db"
if destination.exists():
    raise SystemExit("Refusing to replace existing runtime/agentgate.db")
destination.parent.mkdir(exist_ok=True)


def inventory(connection):
    result = {}
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        if "payload" in columns:
            values = sorted(row[columns.index("payload")] for row in rows)
        else:
            values = sorted(repr(row) for row in rows)
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(json.dumps(values).encode()).hexdigest()}
    return result


with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
    before = inventory(dst)
repository = SQLiteRepository(destination)
with sqlite3.connect(destination) as db:
    after = inventory(db)
    checked = {}
    for table, state in before.items():
        current = "agentgate_" + table if "agentgate_" + table in after else table
        assert after[current] == state, f"row/payload changed: {table}"
        checked[table] = {"new_table": current, **state, "unchanged": True}
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    run_ids = [row[0] for row in db.execute("SELECT id FROM agentgate_runs")]
    for run_id in run_ids:
        assert repository.get_run(run_id) is not None
        repository.list_results(run_id)
report = {"source": str(source), "destination": str(destination), "verified": True,
          "runs_loaded": len(run_ids), "foreign_key_errors": 0, "tables": checked}
(root / "runtime/upstream-migration.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
print(json.dumps({"verified": True, "tables": len(checked), "runs_loaded": len(run_ids)}))
