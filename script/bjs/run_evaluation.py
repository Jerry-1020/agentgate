"""Synchronously execute a persisted evaluation Run by id.
本脚本放在NH Linux服务器上执行，负责执行评测任务。要关闭系统的Celery调度开关
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agentgate.integrations.job_dispatchers.celery import execute_evaluation_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronously execute a persisted evaluation Run by id.",
    )
    parser.add_argument("run_id", help="The id of the evaluation Run to execute.")
    args = parser.parse_args()

    status = execute_evaluation_run.run(args.run_id)
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
