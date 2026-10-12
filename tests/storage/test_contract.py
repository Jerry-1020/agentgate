"""The same public persistence workflows on SQLite and MySQL."""

import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_run_engine import pending_run

from agentgate.application.dataset_management import DatasetManagement
from agentgate.application.target_catalog import TargetCatalog
from agentgate.demo.bootstrap import ensure_demo_target_descriptors
from agentgate.domain import Case, CaseTurn, Dataset, DatasetVersion, RunStatus, utcnow
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.storage.mysql import MySQLRepository
from agentgate.storage.repository import AgentGateRepository


def test_mysql_implements_all_persistence_operations():
    for name, value in AgentGateRepository.__dict__.items():
        if callable(value) and not name.startswith("_"):
            assert callable(getattr(MySQLRepository, name, None)), name


def test_dataset_publish_and_stale_write(repository):
    service = DatasetManagement(repository)
    dataset = service.create_dataset("贷款测试")
    draft = service.create_draft(dataset.id)
    assert repository.get_dataset(dataset.id, user_team_id="") == dataset
    with pytest.raises(ValueError):
        service.create_draft(dataset.id)
    updated = Dataset.model_validate(
        {
            **dataset.model_dump(),
            "name": "更新",
            "updated_at": dataset.updated_at + timedelta(seconds=1),
        }
    )
    repository.save_dataset(updated)
    with pytest.raises(ValueError):
        repository.save_dataset(dataset)
    assert repository.get_dataset_draft(dataset.id, user_team_id="") == draft
    assert repository.get_dataset(dataset.id, user_team_id="other") is None


def test_long_ids_are_exact_and_sort_before_limit(repository):
    now = utcnow()
    ids = ["长" * 1200 + suffix for suffix in ("z", "a", "A", "a ")]
    for identity in ids:
        repository.save_dataset(Dataset(id=identity, name="长标识", created_at=now, updated_at=now))
    assert [item.id for item in repository.list_datasets(user_team_id="")] == sorted(ids)
    for identity in ids:
        assert repository.get_dataset(identity, user_team_id="").id == identity


def test_import_is_atomic(repository):
    dataset = Dataset(name="atomic")
    version = DatasetVersion(dataset_id=dataset.id)
    repository.save_dataset_with_version(dataset, version)
    with pytest.raises(ValueError):
        repository.save_dataset_with_version(Dataset(name="other"), version)
    assert len(repository.list_datasets(user_team_id="")) == 1


def test_full_demo_and_result_idempotency(repository, execute_demo):
    completed, report = execute_demo(repository, "loan-agent-v2-fixed")
    assert completed.status == RunStatus.COMPLETED
    assert report.run.id == completed.id
    results = repository.list_results(completed.id)
    assert results
    repository.save_results(results)
    assert repository.list_results(completed.id) == results
    assert repository.list_traces(completed.id)
    assert (
        repository.list_runs_by_dataset_version(
            completed.manifest.dataset.dataset_id,
            completed.manifest.dataset.version,
            user_team_id="",
        )[0]
        == completed
    )


def test_run_claim_cancel_and_terminal_immutability(repository):
    run = pending_run()
    repository.save_run(run)
    started = run.created_at + timedelta(seconds=1)
    running = repository.claim_pending_run(run.id, started)
    assert running.status == RunStatus.RUNNING
    assert repository.claim_pending_run(run.id, started) is None
    assert repository.cancel_run(run.id, started, user_team_id="other") is None
    cancelled = repository.cancel_run(run.id, started + timedelta(seconds=1), user_team_id="")
    assert cancelled.status == RunStatus.CANCELLED
    with pytest.raises(ValueError):
        repository.save_run(running)
    assert repository.get_run(run.id) == cancelled
    repository.save_run(cancelled)


def test_scheduling_due_boundary(repository):
    base = pending_run()
    due = base.created_at + timedelta(hours=1)
    scheduled = type(base).model_validate(
        {**base.model_dump(), "status": "scheduled", "scheduled_for": due}
    )
    repository.save_run(scheduled)
    assert repository.claim_due_scheduled_runs(due - timedelta(microseconds=1)) == []
    claimed = repository.claim_due_scheduled_runs(due)
    assert [run.id for run in claimed] == [scheduled.id]
    assert repository.claim_due_scheduled_runs(due) == []


def test_task_batch_rollback_and_identity(repository):
    first = pending_run()
    second = type(first).model_validate({**first.model_dump(), "id": str(uuid4())})
    task = EvaluationTask(kind="stability", run_ids=(first.id, second.id))
    repository.save_task_runs(task, [first, second])
    assert repository.get_evaluation_task(task.id) == task
    assert repository.save_evaluation_task(task) == task
    third = type(first).model_validate({**first.model_dump(), "id": str(uuid4())})
    conflicting = EvaluationTask(kind="stability", run_ids=(third.id, first.id))
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        repository.save_task_runs(conflicting, [third, first])
    assert repository.get_run(third.id) is None
    assert repository.get_evaluation_task(conflicting.id) is None


def test_target_descriptor_roundtrip(repository):
    catalog = TargetCatalog(repository)
    ensure_demo_target_descriptors(catalog)
    descriptors = repository.list_target_descriptors()
    assert descriptors
    for descriptor in descriptors:
        repository.save_target_descriptor(descriptor)
        assert repository.get_target_descriptor(descriptor.content_sha256) == descriptor
        assert descriptor in repository.list_target_descriptors(descriptor.ref)


def test_evaluator_publication_and_delete(repository):
    from test_evaluator_repository import draft_for, evaluator

    from agentgate.evaluator.versioning import publish_evaluator_draft

    item = evaluator()
    draft = draft_for(item)
    repository.save_evaluator_with_draft(item, draft)
    assert repository.get_evaluator_draft(item.id, user_team_id="") == draft
    publication = publish_evaluator_draft(item, draft, 1)
    repository.publish_evaluator_draft(draft.id, publication)
    assert repository.get_evaluator_draft(item.id, user_team_id="") is None
    assert repository.get_evaluator_version(item.id, "1", user_team_id="") == publication
    assert repository.get_latest_evaluator_version(item.id, user_team_id="") == publication
    with pytest.raises(ValueError):
        repository.delete_unpublished_evaluator(item.id, user_team_id="")
    assert repository.get_evaluator_version(item.id, "1", user_team_id="other") is None


def test_skill_reports_reviews_and_immutability(repository):
    from test_skill_analysis_storage import descriptor, report, review

    target = descriptor()
    repository.save_target_descriptor(target)
    item = report(target)
    repository.save_skill_analysis_report(item)
    repository.save_skill_analysis_report(item)
    assert repository.get_skill_analysis_report(item.id) == item
    assert repository.list_skill_analysis_reports(target.content_sha256) == [item]
    decision = review()
    repository.save_skill_analysis_review(item.id, decision)
    repository.save_skill_analysis_review(item.id, decision)
    assert repository.list_skill_analysis_reviews(item.id) == [decision]


def test_api_key_roundtrip_and_delete(repository):
    from test_credential_repository import metadata

    item = metadata("private-key")
    repository.save_api_key(item, "synthetic-ciphertext")
    assert repository.get_api_key_metadata(item.id) == item
    assert repository.get_encrypted_api_key(item.id) == "synthetic-ciphertext"
    assert repository.list_api_key_metadata() == [item]
    with pytest.raises(ValueError):
        repository.save_api_key(item, "different-ciphertext")
    assert repository.get_encrypted_api_key(item.id) == "synthetic-ciphertext"
    repository.delete_api_key(item.id)
    assert repository.get_api_key_metadata(item.id) is None


def test_dataset_publication_atomicity(repository):
    service = DatasetManagement(repository)


    item = service.create_dataset("publish")
    service.create_draft(item.id)
    service.save_case(item.id, Case(name="case", turns=(CaseTurn(input={"text": "test"}),)))
    publication = service.publish_draft(item.id)
    assert repository.get_dataset_draft(item.id, user_team_id="") is None
    assert repository.get_published_dataset_version(item.id, 1, user_team_id="") == publication
    repository.save_dataset_version(publication)
    assert repository.get_latest_published_dataset_version(item.id, user_team_id="") == publication


def test_result_batch_failure_rolls_back(repository, execute_demo):
    completed, _ = execute_demo(repository, "loan-agent-v2-fixed")
    existing = repository.list_results(completed.id)
    sample = existing[0]
    first = type(sample).model_validate(
        {**sample.model_dump(), "id": str(uuid4()), "evaluator_id": "additional-evaluator"}
    )
    second = type(sample).model_validate(
        {
            **sample.model_dump(),
            "id": str(uuid4()),
            "trace_id": "f" * 32,
            "evaluator_id": "missing-trace-evaluator",
        }
    )
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        repository.save_results([first, second])
    assert repository.list_results(completed.id) == existing


def test_optimization_report_cache(repository):
    from test_optimization_models import report

    item = report()
    template = pending_run()
    run = type(template).model_validate({**template.model_dump(), "id": item.run_id})
    repository.save_run(run)
    key = "evidence" * 1000
    assert repository.save_optimization_report(key, item) == item
    assert repository.save_optimization_report(key, item) == item
    assert repository.get_optimization_report(key) == item
    assert repository.get_optimization_report("missing") is None


def test_delete_dataset_record_removes_draft_only_dataset(repository):
    service = DatasetManagement(repository)
    dataset = service.create_dataset("整删验证")
    service.create_draft(dataset.id)
    service.delete_record(dataset.id)
    assert repository.get_dataset(dataset.id, user_team_id="") is None
    assert repository.list_dataset_versions(dataset.id, user_team_id="") == []


def test_delete_dataset_record_rejects_published_versions(repository):
    service = DatasetManagement(repository)
    dataset = service.create_dataset("已发布不可整删")
    service.create_draft(dataset.id)
    service.save_case(
        dataset.id, Case(id="c1", name="c1", turns=(CaseTurn(id="t", input={"txt": "hi"}),))
    )
    service.publish_draft(dataset.id)
    with pytest.raises(ValueError):
        service.delete_record(dataset.id)
    assert repository.get_dataset(dataset.id, user_team_id="") is not None
