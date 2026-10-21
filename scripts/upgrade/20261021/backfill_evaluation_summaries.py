"""Inspect or rebuild evaluation summaries; source evidence is never executed."""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from dotenv import dotenv_values

from agentgate.application.evaluation_summary_backfill import backfill
from agentgate.storage.configuration import SQLiteConfig, create_repository, load_database_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = (
        SQLiteConfig(str(args.sqlite))
        if args.sqlite
        else load_database_config(dotenv_values(args.env_file))
    )
    if isinstance(config, SQLiteConfig) and not args.apply:
        from agentgate.storage.evaluation_projection import audit

        path = Path(config.path).resolve()
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            report = {"applied": False, "failures": audit(db)}
    else:
        repository = create_repository(config)
        try:
            report = backfill(repository, batch_size=args.batch_size, apply=args.apply)
        finally:
            repository.close()
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
