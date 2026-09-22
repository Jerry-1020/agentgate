"""Application workflow for releasing due Evaluation Runs."""

from __future__ import annotations

import logging
import os
from datetime import datetime

from agentgate.domain import EvaluationRun, RunStatus, transition_run, utcnow
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.storage.repository import AgentGateRepository

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_RUNS_PER_API_KEY = 10
DEFAULT_MAX_DISPATCH_ATTEMPTS = 10


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("env %s=%r is not an integer, using default %d", name, raw, default)
        return default
    if value < 1:
        LOGGER.warning("env %s=%d is below 1, using default %d", name, value, default)
        return default
    return value


MAX_CONCURRENT_RUNS_PER_API_KEY = _positive_int_env(
    "AGENTGATE_MAX_CONCURRENT_RUNS_PER_API_KEY",
    DEFAULT_MAX_CONCURRENT_RUNS_PER_API_KEY,
)
MAX_DISPATCH_ATTEMPTS = _positive_int_env(
    "AGENTGATE_MAX_DISPATCH_ATTEMPTS",
    DEFAULT_MAX_DISPATCH_ATTEMPTS,
)


def _transition_to_waiting(run: EvaluationRun, *, increment_attempts: bool = False) -> EvaluationRun:
    """Transition a Run to WAITING, optionally incrementing dispatch_attempts."""

    waiting = transition_run(run, RunStatus.WAITING)
    if increment_attempts:
        waiting = waiting.model_copy(update={"dispatch_attempts": run.dispatch_attempts + 1})
    return waiting


def _handle_dispatch_failure(
    run: EvaluationRun,
    exc: Exception,
    *,
    occurred_at: datetime,
    repository: AgentGateRepository,
) -> EvaluationRun:
    """Persist a failed dispatch as WAITING (retry) or FAILED (attempts exhausted)."""

    attempts = run.dispatch_attempts + 1
    if attempts < MAX_DISPATCH_ATTEMPTS:
        waiting = transition_run(run, RunStatus.WAITING)
        waiting = waiting.model_copy(update={"dispatch_attempts": attempts})
        repository.save_run(waiting)
        LOGGER.warning(
            "Run dispatch failed (attempt %d/%d): run_id=%s, %s",
            attempts, MAX_DISPATCH_ATTEMPTS, run.id, type(exc).__name__,
        )
        return waiting
    failed = transition_run(
        run,
        RunStatus.FAILED,
        occurred_at=occurred_at,
        error=f"Run dispatch failed after {attempts} attempts: {type(exc).__name__}",
    )
    repository.save_run(failed)
    return failed


class RunScheduling:
    """Move due scheduled Runs into the asynchronous execution queue."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def dispatch_due_runs(
        self,
        dispatcher: JobDispatcher,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> tuple[EvaluationRun, ...]:
        release_time = now or utcnow()
        due_runs = self.repository.claim_due_scheduled_runs(
            release_time,
            limit=limit,
        )
        dispatched: list[EvaluationRun] = []
        for run in due_runs:
            active = self.repository.count_active_runs_by_api_key(run.api_key)
            if active > MAX_CONCURRENT_RUNS_PER_API_KEY:
                waiting = _transition_to_waiting(run)
                self.repository.save_run(waiting)
                continue
            try:
                dispatcher.submit(run.id)
            except Exception as exc:
                _handle_dispatch_failure(
                    run, exc, occurred_at=release_time, repository=self.repository
                )
                continue
            dispatched.append(run)
        return tuple(dispatched)

    def dispatch_waiting_runs(
        self,
        dispatcher: JobDispatcher,
        *,
        limit: int = 100,
    ) -> tuple[EvaluationRun, ...]:
        """Dispatch WAITING Runs when concurrency slots become available."""

        waiting_runs = self.repository.list_runs_by_status(
            RunStatus.WAITING, limit=limit, oldest_first=True
        )
        dispatched: list[EvaluationRun] = []
        for run in waiting_runs:
            active = self.repository.count_active_runs_by_api_key(run.api_key)
            if active >= MAX_CONCURRENT_RUNS_PER_API_KEY:
                continue
            claimed = self.repository.claim_waiting_run(run.id, utcnow())
            if claimed is None:
                continue
            try:
                dispatcher.submit(claimed.id)
            except Exception as exc:
                _handle_dispatch_failure(
                    claimed, exc, occurred_at=utcnow(), repository=self.repository
                )
                continue
            dispatched.append(claimed)
        return tuple(dispatched)
