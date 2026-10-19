"""Preserve HTTP-authored expectations through publication and real rule execution."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.dataset_management import DatasetManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.application.result_reader import ResultReader
from agentgate.application.run_management import RunManagement
from agentgate.application.target_catalog import TargetCatalog
from agentgate.domain import (
    DatasetVersion,
    Outcome,
    RunStatus,
    TargetDescriptor,
    TargetRef,
    TargetSnapshot,
    Trace,
)
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionResult,
    CaseExecutionStatus,
)
from agentgate.server.dependencies import get_dependencies
from agentgate.server.routes.datasets import router
from agentgate.storage.sqlite import SQLiteRepository

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "expectation-rules"
EVALUATOR_IDS = ("final-state", "tool-arguments", "final-output")
EXPECTED_CHECKS = {
    "final-state": ("review-state", "approve-state"),
    "tool-arguments": ("review-tool", "approve-tool"),
    "final-output": ("review-output", "approve-output"),
}


class SyntheticTraceTarget:
    """Replay one retained trace using the execution identity supplied by RunEngine."""

    adapter_type = "expectation-trace-replay"
    adapter_version = "1"

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self.requests: dict[str, CaseExecutionRequest] = {}
        self.cancelled: list[str] = []

    def start(self, request: CaseExecutionRequest) -> str:
        self.requests[request.execution_id] = request
        return request.execution_id

    def get_status(self, handle: str) -> CaseExecutionStatus:
        return CaseExecutionStatus.COMPLETED

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        request = self.requests[handle]
        trace_id = request.traceparent.split("-")[1]
        payload = self.trace.model_dump(mode="json")
        payload.update(trace_id=trace_id, run_id=request.run_id, case_id=request.case.id)
        for span in payload["spans"]:
            span["trace_id"] = trace_id
        trace = Trace.model_validate(payload)
        return CaseExecutionResult(request.execution_id, trace_id, trace)

    def cancel(self, handle: str) -> None:
        self.cancelled.append(handle)


@pytest.fixture
def dataset_client(tmp_path):
    repository = SQLiteRepository(tmp_path / "expectations.db")
    app = FastAPI()
    dependencies = SimpleNamespace(datasets=DatasetManagement(repository))
    app.dependency_overrides[get_dependencies] = lambda: dependencies
    app.include_router(router)
    try:
        with TestClient(app) as client:
            yield client, repository
    finally:
        repository.close()


@pytest.fixture
def case_payload():
    return json.loads((EXAMPLE / "dataset.json").read_text())["version"]["cases"][0]


def save_and_publish(client, case_payload):
    created = client.post("/api/datasets", json={"name": "Expectation contract"})
    assert created.status_code == 201
    dataset_id = created.json()["dataset"]["id"]
    prefix = f"/api/datasets/{dataset_id}"

    original = deepcopy(case_payload)
    original["turns"][0]["expectations"][0]["condition"] = {
        "kind": "equals", "expected": {"status": "before-edit", "history": []},
    }
    added = client.post(f"{prefix}/drafts/cases", json=original)
    assert added.status_code == 201, added.text
    assert added.json()["cases"] == [original]
    assert client.get(f"{prefix}/drafts/current").json()["cases"] == [original]

    updated = client.put(f"{prefix}/drafts/cases/{case_payload['id']}", json=case_payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["cases"] == [case_payload]
    assert client.get(f"{prefix}/drafts/current").json()["cases"] == [case_payload]

    published = client.post(f"{prefix}/drafts/publish")
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    assert published.json()["cases"] == [case_payload]
    reloaded = client.get(f"{prefix}/versions/1")
    assert reloaded.status_code == 200
    assert reloaded.json() == published.json()
    exported = client.get(f"{prefix}/versions/1/export")
    assert exported.status_code == 200
    assert exported.json()["version"]["cases"] == [case_payload]
    return DatasetVersion.model_validate(reloaded.json())


@pytest.mark.parametrize("scenario", ["pass", "fail"])
def test_http_expectations_survive_edit_publish_and_real_rules(
    dataset_client, case_payload, scenario
):
    client, repository = dataset_client
    published = save_and_publish(client, case_payload)
    assert published.cases[0].is_multi_turn
    assert published.cases[0].model_dump(mode="json") == case_payload

    evaluators = build_default_evaluator_management(repository)
    specs = evaluators.select(EVALUATOR_IDS)
    evaluators.validate_plan(published, specs)
    trace = Trace.model_validate(json.loads((EXAMPLE / "traces.json").read_text())[scenario])
    results = evaluators.evaluate_case(published.cases[0], trace, specs)

    assert tuple(result.evaluator_id for result in results) == EVALUATOR_IDS
    for result in results:
        assert result.outcome == Outcome(scenario)
        assert result.score == (1.0 if scenario == "pass" else 0.0)
        assert tuple(check.expectation_id for check in result.checks) == EXPECTED_CHECKS[
            result.evaluator_id
        ]
        assert tuple(check.turn_id for check in result.checks) == (
            "review-turn", "approve-turn",
        )
        assert all(check.outcome == Outcome(scenario) for check in result.checks)
        assert result.error_detail is None

    state_checks, tool_checks, output_checks = (result.checks for result in results)
    state_json = state_checks[1].model_dump(mode="json")
    assert state_json["expected"]["expected"] == {
        "approved": True, "limit": 120000,
        "reasons": [{"code": "verified", "sources": ["manual"]}], "reviewer": None,
    }
    assert state_json["actual"]["approved"] == (True if scenario == "pass" else "true")
    assert tool_checks[0].actual == ("C-100" if scenario == "pass" else "C-999")
    assert tool_checks[0].span_ids == ("0000000000000003",)
    assert tool_checks[1].actual == (120000, 130000 if scenario == "pass" else 90000)
    assert output_checks[1].methods[0].implementation_id == "matches_json_schema"
    assert output_checks[1].actual == trace.final_output

    # Creating a new draft cannot mutate the publication used for evaluation.
    prefix = f"/api/datasets/{published.dataset_id}"
    assert client.post(f"{prefix}/drafts", json={"based_on_version": 1}).status_code == 201
    edited = deepcopy(case_payload)
    edited["turns"][1]["expectations"][0]["condition"]["expected"]["limit"] = 99999
    assert client.put(f"{prefix}/drafts/cases/{edited['id']}", json=edited).status_code == 200
    assert client.get(f"{prefix}/versions/1").json()["cases"] == [case_payload]
    assert client.get(f"{prefix}/drafts/current").json()["cases"] == [edited]


@pytest.mark.parametrize(
    "occurrence, expected_outcome, expected_actual",
    [
        ("first", Outcome.FAIL, "C-000"),
        ("last", Outcome.PASS, "C-100"),
        ("any", Outcome.PASS, ("C-000", "C-100")),
        ("all", Outcome.FAIL, ("C-000", "C-100")),
    ],
)
def test_saved_tool_occurrence_controls_nested_argument_evaluation(
    dataset_client, case_payload, occurrence, expected_outcome, expected_actual
):
    client, repository = dataset_client
    case_payload["turns"][0]["expectations"][1]["occurrence"] = occurrence
    published = save_and_publish(client, case_payload)
    evaluators = build_default_evaluator_management(repository)
    trace = Trace.model_validate(json.loads((EXAMPLE / "traces.json").read_text())["pass"])

    result, = evaluators.evaluate_case(
        published.cases[0], trace, evaluators.select(("tool-arguments",))
    )

    assert result.outcome == expected_outcome
    assert result.checks[0].expectation_id == "review-tool"
    assert result.checks[0].outcome == expected_outcome
    assert result.checks[0].actual == expected_actual
    assert result.checks[1].outcome == Outcome.PASS


@pytest.mark.parametrize("scenario", ["pass", "fail"])
def test_published_expectations_execute_from_run_manifest_into_report(
    dataset_client, case_payload, scenario
):
    client, repository = dataset_client
    published = save_and_publish(client, case_payload)
    descriptor = TargetDescriptor(
        ref=TargetRef(
            source_id="expectation-contract",
            target_type="agent",
            external_target_id="synthetic-evidence",
            external_version_id="1",
        ),
        display_name="Synthetic expectation trace",
    )
    TargetCatalog(repository).register_descriptor(descriptor)
    target = TargetSnapshot(
        ref=descriptor.ref,
        display_name=descriptor.display_name,
        descriptor_sha256=descriptor.content_sha256,
        adapter_type=SyntheticTraceTarget.adapter_type,
        adapter_version=SyntheticTraceTarget.adapter_version,
    )
    evaluators = build_default_evaluator_management(repository)
    runs = RunManagement(repository, evaluators)
    run = runs.create_run(
        target,
        dataset_id=published.dataset_id,
        dataset_version=1,
        evaluator_ids=EVALUATOR_IDS,
    )
    assert run.status == RunStatus.PENDING
    assert repository.get_run(run.id).manifest.dataset == published
    assert run.manifest.dataset.cases[0].model_dump(mode="json") == case_payload

    # A publication made after task creation must not replace the pinned sample.
    prefix = f"/api/datasets/{published.dataset_id}"
    assert client.post(f"{prefix}/drafts", json={"based_on_version": 1}).status_code == 201
    changed = deepcopy(case_payload)
    changed["turns"][0]["expectations"][0]["condition"] = {
        "kind": "equals", "expected": {"status": "new-version"},
    }
    assert client.put(f"{prefix}/drafts/cases/{changed['id']}", json=changed).status_code == 200
    newer = client.post(f"{prefix}/drafts/publish")
    assert newer.status_code == 200
    assert newer.json()["version"] == 2

    evidence = Trace.model_validate(json.loads((EXAMPLE / "traces.json").read_text())[scenario])
    adapter = SyntheticTraceTarget(evidence)

    def resolve_trace(request, result):
        assert result.execution_id == request.execution_id
        assert result.inline_trace is not None
        return result.inline_trace

    completed = runs.execute_run(run.id, adapter, resolve_trace)
    report = ResultReader(repository).get_report(run.id)

    assert completed.status == RunStatus.COMPLETED
    assert report.run == completed
    assert report.run.manifest == run.manifest
    assert len(adapter.requests) == 1
    request, = adapter.requests.values()
    assert request.case == published.cases[0]
    assert adapter.cancelled == []
    stored_trace = repository.get_trace(run.id, request.case.id)
    assert stored_trace is not None
    assert stored_trace.turn_outcomes == evidence.turn_outcomes
    results = {result.evaluator_id: result for result in report.results}
    assert set(results) == set(EVALUATOR_IDS)
    for evaluator_id, expected_ids in EXPECTED_CHECKS.items():
        result = results[evaluator_id]
        assert result.outcome == Outcome(scenario)
        assert result.trace_id == stored_trace.trace_id
        assert result.run_id == run.id
        assert tuple(check.expectation_id for check in result.checks) == expected_ids
        assert tuple(check.turn_id for check in result.checks) == (
            "review-turn", "approve-turn",
        )
        assert all(check.outcome == Outcome(scenario) for check in result.checks)
        assert result.error_detail is None


def test_retained_example_replays_the_three_real_rules(tmp_path):
    output = tmp_path / "results.json"
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE / "run.py"), "--output", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text())
    assert report["offline_rules_verified"] is True
    assert report["trace_source"] == "synthetic"
    assert report == json.loads((EXAMPLE / "results.json").read_text())
    for scenario in ("pass", "fail"):
        results = report["scenarios"][scenario]
        assert [result["evaluator_id"] for result in results] == list(EVALUATOR_IDS)
        assert all(result["outcome"] == scenario for result in results)
        assert len([check for result in results for check in result["checks"]]) == 6
