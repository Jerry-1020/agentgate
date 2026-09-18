from datetime import datetime

import pytest
from pydantic import ValidationError

from agentgate.domain.evaluation_task import EvaluationTask


def test_single_task_round_trip():
    task = EvaluationTask(kind="single", run_ids=("run-a",))
    assert EvaluationTask.model_validate_json(task.model_dump_json()) == task
    assert task.created_at.tzinfo is not None
    assert "status" not in task.model_dump()


def test_ab_keeps_baseline_candidate_order():
    task = EvaluationTask(
        kind="ab", run_ids=("baseline", "candidate"),
        git_commit_refs=("a" * 40, "b" * 40),
        static_report_ids=("report-a", "report-b"), credential_id="credential-id",
    )
    assert task.run_ids == ("baseline", "candidate")
    with pytest.raises(ValidationError):
        task.kind = "single"


@pytest.mark.parametrize("values", [
    {"kind": "single", "run_ids": ()},
    {"kind": "single", "run_ids": ("a", "b")},
    {"kind": "ab", "run_ids": ("a",)},
    {"kind": "ab", "run_ids": ("a", "a")},
    {"kind": "single", "run_ids": (" ",)},
    {"kind": "single", "run_ids": ("a",), "api_key": "not-allowed"},
    {"kind": "single", "run_ids": ("a",), "credential_id": " "},
    {"kind": "single", "run_ids": ("a",), "git_commit_refs": ("main",)},
    {"kind": "ab", "run_ids": ("a", "b"), "git_commit_refs": ("a" * 40,)},
    {"kind": "single", "run_ids": ("a",), "static_report_ids": ("r", "r2")},
    {"kind": "single", "run_ids": ("a",), "created_at": datetime(2026, 9, 15)},
])
def test_invalid_task_references_are_rejected(values):
    with pytest.raises(ValidationError):
        EvaluationTask(**values)
