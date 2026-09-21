"""Synchronously execute a persisted Run without a Celery broker or worker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agentgate.integrations.job_dispatchers.execution import execute_persisted_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronously execute a persisted evaluation Run by id.",
    )
    parser.add_argument("run_id", help="The id of the evaluation Run to execute.")
    args = parser.parse_args()

    try:
        status = execute_persisted_run(args.run_id)
    except Exception as exc:  # noqa: BLE001 -- Process boundary must not print credentials.
        print(f"Run execution failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(status)
    # Existing running/completed/cancelled Runs are acknowledged duplicate deliveries.
    return 0 if status in {"completed", "cancelled", "running"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
