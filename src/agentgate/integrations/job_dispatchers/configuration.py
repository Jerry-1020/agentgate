"""Select the execution backend consistently at process entry points."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from .protocol import JobDispatcher


def load_dispatcher_type(environ: Mapping[str, str] | None = None) -> Literal["celery", "bjs"]:
    settings = os.environ if environ is None else environ
    kind = settings.get("AGENT_TASK_DISPATCHER_TYPE", "celery").strip().lower()
    if kind == "celery":
        return "celery"
    if kind == "bjs":
        return "bjs"
    raise ValueError("AGENT_TASK_DISPATCHER_TYPE must be celery or bjs")


def create_dispatcher() -> JobDispatcher:
    if load_dispatcher_type() == "bjs":
        from .bjs_job_dispatcher import BjsJobDispatcher

        return BjsJobDispatcher()
    from .celery import CeleryJobDispatcher

    return CeleryJobDispatcher()
