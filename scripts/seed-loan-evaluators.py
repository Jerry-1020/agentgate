"""Initialize local synthetic datasets and published evaluators without model calls."""

import json

from agentgate.demo.evaluators import ensure_loan_evaluators
from agentgate.server.dependencies import build_dependencies
from agentgate.storage.configuration import SQLiteConfig, load_database_config

if __name__ == "__main__":
    if not isinstance(load_database_config(), SQLiteConfig):
        raise SystemExit(
            "Local demo initialization requires SQLite; in-bank databases are not seeded."
        )
    dependencies = build_dependencies()
    try:
        print(json.dumps(ensure_loan_evaluators(dependencies.evaluators), ensure_ascii=False))
    finally:
        dependencies.close()
