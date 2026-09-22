from __future__ import annotations

from datetime import timedelta

from agentgate.application import RunManagement, RunScheduling, TargetCatalog
from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import RunStatus, utcnow
from agentgate.storage.sqlite import SQLiteRepository


class RecordingDispatcher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.failure is not None:
            raise self.failure

    def cancel(self, run_id: str) -> None:
        del run_id


def create_scheduled_run(
    repository: SQLiteRepository,
    *,
    scheduled_for,
):
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    management = RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )
    target = build_demo_target_snapshot(
        get_demo_target_descriptor("loan-agent-v2-fixed")
    )
    return management.create_run(
        target,
        dataset_id=LOAN_DATASET.id,
        scheduled_for=scheduled_for,
    )


def test_repository_atomically_releases_only_due_scheduled_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "scheduled-runs.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)

    assert run.status is RunStatus.SCHEDULED
    assert repository.claim_due_scheduled_runs(
        scheduled_for - timedelta(seconds=1)
    ) == []

    claimed = repository.claim_due_scheduled_runs(scheduled_for)

    assert [item.id for item in claimed] == [run.id]
    assert claimed[0].status is RunStatus.PENDING
    assert claimed[0].scheduled_for == scheduled_for
    assert repository.claim_due_scheduled_runs(scheduled_for) == []


def test_scheduling_dispatches_each_due_run_once(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-due.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)
    dispatcher = RecordingDispatcher()
    scheduling = RunScheduling(repository)

    dispatched = scheduling.dispatch_due_runs(
        dispatcher,
        now=scheduled_for,
    )
    repeated = scheduling.dispatch_due_runs(
        dispatcher,
        now=scheduled_for,
    )

    assert [item.id for item in dispatched] == [run.id]
    assert repeated == ()
    assert dispatcher.run_ids == [run.id]
    assert repository.get_run(run.id).status is RunStatus.PENDING


def test_scheduling_records_sanitized_dispatch_failure(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "scheduled-failure.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)

    dispatched = RunScheduling(repository).dispatch_due_runs(
        RecordingDispatcher(ConnectionError("redis password=secret")),
        now=scheduled_for,
    )

    stored = repository.get_run(run.id)
    assert dispatched == ()
    assert stored.status is RunStatus.WAITING
    assert stored.dispatch_attempts == 1
    assert stored.error is None


def test_scheduled_run_can_be_cancelled_before_release(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "cancel-scheduled.db")
    run = create_scheduled_run(
        repository,
        scheduled_for=utcnow() + timedelta(hours=1),
    )

    cancelled = repository.cancel_run(run.id, run.created_at, user_team_id="")

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert repository.claim_due_scheduled_runs(run.scheduled_for) == []


def _create_pending_run(repository, *, api_key=None):
    management = RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )
    target = build_demo_target_snapshot(
        get_demo_target_descriptor("loan-agent-v2-fixed")
    )
    return management.create_run(
        target,
        dataset_id=LOAN_DATASET.id,
        api_key=api_key,
    )


def test_dispatch_run_transitions_to_waiting_when_concurrency_limit_reached(
    tmp_path, monkeypatch
) -> None:
    from agentgate.application import run_scheduling as scheduling_module
    from agentgate.application import run_management as management_module

    monkeypatch.setattr(scheduling_module, "MAX_CONCURRENT_RUNS_PER_API_KEY", 2)
    monkeypatch.setattr(management_module, "MAX_CONCURRENT_RUNS_PER_API_KEY", 2)
    repository = SQLiteRepository(tmp_path / "concurrency-limit.db")
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))

    first = _create_pending_run(repository, api_key="key-A")
    second = _create_pending_run(repository, api_key="key-A")
    repository.claim_pending_run(first.id, first.created_at)
    repository.claim_pending_run(second.id, second.created_at)

    management = RunManagement(
        repository, build_default_evaluator_management(repository)
    )
    third = _create_pending_run(repository, api_key="key-A")
    dispatcher = RecordingDispatcher()
    result = management.dispatch_run(third.id, dispatcher)

    assert result.status is RunStatus.WAITING
    assert dispatcher.run_ids == []
    assert repository.count_active_runs_by_api_key("key-A") == 2


def test_dispatch_waiting_runs_releases_when_slot_becomes_available(
    tmp_path, monkeypatch
) -> None:
    from agentgate.application import run_scheduling as scheduling_module
    from agentgate.application import run_management as management_module

    monkeypatch.setattr(scheduling_module, "MAX_CONCURRENT_RUNS_PER_API_KEY", 1)
    monkeypatch.setattr(management_module, "MAX_CONCURRENT_RUNS_PER_API_KEY", 1)
    repository = SQLiteRepository(tmp_path / "waiting-dispatch.db")
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))

    first = _create_pending_run(repository, api_key="key-B")
    management = RunManagement(
        repository, build_default_evaluator_management(repository)
    )
    dispatcher = RecordingDispatcher()
    management.dispatch_run(first.id, dispatcher)
    assert repository.get_run(first.id).status is RunStatus.PENDING

    second = _create_pending_run(repository, api_key="key-B")
    result = management.dispatch_run(second.id, dispatcher)
    assert result.status is RunStatus.WAITING

    completed = repository.claim_pending_run(first.id, first.created_at)
    assert completed is not None
    from agentgate.domain import transition_run

    finished = transition_run(completed, RunStatus.COMPLETED)
    repository.save_run(finished)

    scheduling = RunScheduling(repository)
    dispatched = scheduling.dispatch_waiting_runs(dispatcher)

    assert len(dispatched) == 1
    assert dispatched[0].id == second.id
    assert repository.get_run(second.id).status is RunStatus.PENDING


def test_count_active_runs_by_api_key_separates_keys(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "count-active.db")
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))

    run_a = _create_pending_run(repository, api_key="key-A")
    run_b = _create_pending_run(repository, api_key="key-B")
    run_none = _create_pending_run(repository, api_key=None)

    assert repository.count_active_runs_by_api_key("key-A") == 1
    assert repository.count_active_runs_by_api_key("key-B") == 1
    assert repository.count_active_runs_by_api_key(None) == 1

    repository.claim_pending_run(run_a.id, run_a.created_at)
    assert repository.count_active_runs_by_api_key("key-A") == 1
    assert repository.count_active_runs_by_api_key("key-B") == 1

    assert run_a.id != run_b.id
    assert run_none.api_key is None
