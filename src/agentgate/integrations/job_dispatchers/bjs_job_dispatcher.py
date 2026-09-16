"""BJS job dispatcher for persisted evaluation Runs."""

from __future__ import annotations


class BjsJobDispatcher:
    """Submit persisted Run IDs to a BJS execution backend."""

    def submit(self, run_id: str) -> None:
        print(f"BjsJobDispatcher.submit: run_id={run_id}")

    def cancel(self, run_id: str) -> None:
        print(f"BjsJobDispatcher.cancel: run_id={run_id}")
