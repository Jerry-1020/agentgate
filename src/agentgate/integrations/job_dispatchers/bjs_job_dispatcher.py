"""BJS job dispatcher for persisted evaluation Runs."""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class BjsJobDispatcher:
    """Submit persisted Run IDs to a BJS execution backend."""

    def submit(self, run_id: str) -> None:
        LOGGER.info("BjsJobDispatcher.submit: run_id=%s", run_id)

    def cancel(self, run_id: str) -> None:
        LOGGER.info("BjsJobDispatcher.cancel: run_id=%s", run_id)
