"""Inspect projection structures; changes require --apply explicitly."""

import argparse
import json
import sqlite3
from pathlib import Path

from dotenv import dotenv_values

from agentgate.storage.configuration import SQLiteConfig, create_repository, load_database_config
from agentgate.storage.evaluation_migration import (
    SQLITE_COLUMNS,
    inspect_or_upgrade_mysql,
    upgrade_sqlite,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--sqlite", type=Path)
    args = parser.parse_args()
    config = (
        SQLiteConfig(str(args.sqlite))
        if args.sqlite
        else load_database_config(dotenv_values(args.env_file))
    )
    if isinstance(config, SQLiteConfig):
        path = Path(config.path).resolve()
        if not path.exists():
            raise ValueError("migration requires an existing SQLite database")
        with sqlite3.connect(f"file:{path}?mode={'rw' if args.apply else 'ro'}", uri=True) as db:
            pending = []
            for table, columns in SQLITE_COLUMNS.items():
                existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                pending.extend(f"{table}.{c}" for c in columns if c not in existing)
            for table in (
                "agentgate_run_summaries",
                "agentgate_run_case_progress",
                "agentgate_run_expected_evaluators",
            ):
                if not db.execute(
                    'SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)
                ).fetchone():
                    pending.append(table)
            if args.apply:
                upgrade_sqlite(db)
        print(json.dumps({"database": str(path), "applied": args.apply, "pending_before": pending}))
    else:
        repository = create_repository(config)
        try:
            pending = inspect_or_upgrade_mysql(repository._engine, apply=args.apply)
        finally:
            repository.close()
        print(
            json.dumps({"database": config.url, "applied": args.apply, "pending_before": pending})
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
