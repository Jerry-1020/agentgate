"""Team quotas ignore credentials and preserve independent scheduling pools."""
from datetime import timedelta
from uuid import uuid4

import pytest
from test_run_engine import pending_run
from test_run_scheduling import RecordingDispatcher

from agentgate.application import RunManagement, RunScheduling, run_management, run_scheduling
from agentgate.domain import RunStatus, transition_run, utcnow
from agentgate.server.user_context import UserInfo, reset_user_info, set_user_info


def create(repo, team, key=None, status=RunStatus.PENDING):
    now = utcnow()
    run = pending_run().model_copy(update={
        "id": str(uuid4()), "user_team_id": team, "api_key": key,
        "created_at": now, "status": status,
        "scheduled_for": now + timedelta(hours=1) if status == RunStatus.SCHEDULED else None,
    })
    repo.save_run(run)
    return run


def test_count_uses_team_not_key_and_excludes_inactive(repository):
    first = create(repository, "A", "same")
    create(repository, "A", "different")
    create(repository, "B", "same")
    create(repository, "", "same")
    create(repository, "", "different")
    for status in (RunStatus.WAITING, RunStatus.SCHEDULED):
        create(repository, "A", status=status)
    repository.claim_pending_run(first.id, utcnow())
    assert repository.count_active_runs_by_team("A") == 2
    assert repository.count_active_runs_by_team("B") == 1
    assert repository.count_active_runs_by_team("") == 2
    assert repository.count_active_runs_by_team("unknown") == 0


@pytest.mark.parametrize("terminal", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_team_slot_release_does_not_block_other_team(repository, monkeypatch, terminal):
    monkeypatch.setattr(run_scheduling, "MAX_CONCURRENT_RUNS_PER_TEAM", 1)
    busy = create(repository, "A", "shared")
    running = repository.claim_pending_run(busy.id, utcnow())
    queued = create(repository, "A", "other", RunStatus.WAITING)
    independent = create(repository, "B", "shared", RunStatus.WAITING)
    dispatcher = RecordingDispatcher()
    scheduler = RunScheduling(repository)
    assert [r.id for r in scheduler.dispatch_waiting_runs(dispatcher)] == [independent.id]
    repository.save_run(transition_run(running, terminal, error="test failure" if terminal == RunStatus.FAILED else None))
    assert [r.id for r in scheduler.dispatch_waiting_runs(dispatcher)] == [queued.id]
    assert repository.count_active_runs_by_team("A") == 1
    assert repository.count_active_runs_by_team("B") == 1


def test_immediate_dispatch_and_scheduled_dispatch_use_stored_team(repository, monkeypatch):
    monkeypatch.setattr(run_management, "MAX_CONCURRENT_RUNS_PER_TEAM", 1)
    monkeypatch.setattr(run_scheduling, "MAX_CONCURRENT_RUNS_PER_TEAM", 1)
    create(repository, "A", "first")
    throttled = create(repository, "A", "second")
    dispatcher = RecordingDispatcher()
    context = set_user_info(UserInfo("A", "user", "name"))
    try:
        assert RunManagement(repository, None).dispatch_run(throttled.id, dispatcher).status == RunStatus.WAITING
    finally:
        reset_user_info(context)
    scheduled_a = create(repository, "A", status=RunStatus.SCHEDULED)
    scheduled_b = create(repository, "B", status=RunStatus.SCHEDULED)
    released = RunScheduling(repository).dispatch_due_runs(dispatcher, now=scheduled_b.scheduled_for)
    assert [r.id for r in released] == [scheduled_b.id]
    assert repository.get_run(scheduled_a.id).status == RunStatus.WAITING
