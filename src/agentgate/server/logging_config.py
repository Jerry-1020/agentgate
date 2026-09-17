"""Logging configuration with console, file, and error file appenders."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
DEFAULT_LOG_PATH = str(_PROJECT_ROOT.parent / "logs" / "agentgate")

LOG_FORMAT = (
    "[%(asctime)s] [%(threadName)s] [%(levelname)s] %(name)s - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 100 * 1024 * 1024
BACKUP_COUNT = 30


class _ErrorOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


def setup_logging() -> None:
    log_path = Path(os.getenv("AGENTGATE_LOG_PATH", DEFAULT_LOG_PATH))
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_path / "agentgate.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    error_handler = RotatingFileHandler(
        log_path / "agentgate-error.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    logging.getLogger("agentgate").setLevel(logging.DEBUG)

    for name in ("uvicorn", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    logging.getLogger("agentgate.server.logging_config").info(
        "Logging initialized, log_path=%s", log_path
    )
