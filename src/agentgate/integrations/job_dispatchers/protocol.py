"""Contract for dispatching an existing evaluation Run."""

from typing import Protocol, TypedDict


class JobSubmission(TypedDict, total=False):
    """Identifiers returned by the execution backend after acceptance."""

    bjs_job_id: str
    bjs_batch_number: str


class JobDispatcher(Protocol):
    """Control execution of a persisted Run outside the caller process."""

    def submit(self, run_id: str) -> JobSubmission | None: ...

    def cancel(self, run_id: str) -> None: ...
