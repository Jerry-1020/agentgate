from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from test_run_engine import pending_run

from agentgate.domain import RunStatus


def test_only_one_worker_claims_run(mysql_repository):
    run = pending_run()
    mysql_repository.save_run(run)
    barrier = Barrier(4)

    def claim():
        barrier.wait()
        return mysql_repository.claim_pending_run(run.id, run.created_at + timedelta(seconds=1))

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim(), range(4)))
    assert sum(item is not None for item in claims) == 1
    assert mysql_repository.get_run(run.id).status == RunStatus.RUNNING


def test_schedulers_do_not_duplicate_claims(mysql_repository):
    run = pending_run()
    due = run.created_at + timedelta(seconds=1)
    scheduled = type(run).model_validate(
        {**run.model_dump(), "status": "scheduled", "scheduled_for": due}
    )
    mysql_repository.save_run(scheduled)
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return mysql_repository.claim_due_scheduled_runs(due)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert [item.id for batch in claims for item in batch] == [run.id]
