"""Selected evaluator publications remain exact across all task submission paths."""

from functools import partial

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.agent_platform_evaluation import (
    submit_platform_comparison,
    submit_platform_evaluation,
)
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import Case, CaseTurn
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes import (
    agent_platform,
    bank_targets,
    comparisons,
    evaluators,
    runs,
    stability,
)


class Dispatcher:
    def __init__(self):
        self.ids = []

    def submit(self, run_id):
        self.ids.append(run_id)


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "inbank")
    dispatcher = Dispatcher()
    dependencies = build_dependencies(
        tmp_path / "versions.db", dispatcher, ApiKeyEncryptor(b"k" * 32)
    )
    app = FastAPI()
    app.state.dependencies = dependencies
    settings = {
        "repository": dependencies.repository,
        "evaluators": dependencies.evaluators,
        "credentials": dependencies.api_keys,
        "dispatcher": dispatcher,
    }
    app.state.submit_agent_platform_evaluation = partial(submit_platform_evaluation, **settings)
    app.state.submit_agent_platform_comparison = partial(submit_platform_comparison, **settings)
    for router in (
        agent_platform.router,
        bank_targets.router,
        comparisons.router,
        evaluators.router,
        runs.router,
        stability.router,
    ):
        app.include_router(router)
    dataset = dependencies.datasets.create_dataset("Version selection")
    dependencies.datasets.create_draft(dataset.id)
    dependencies.datasets.save_case(
        dataset.id,
        Case(
            name="Text",
            turns=(
                CaseTurn(
                    input={"txt": "hello"},
                    expectations=(
                        {
                            "kind": "output",
                            "path": "output",
                            "condition": {"kind": "equals", "expected": "answer"},
                        },
                    ),
                ),
            ),
        ),
    )
    dependencies.datasets.publish_draft(dataset.id)
    # Exercise the bank boundary without making a network request to a real Agent.
    target = dependencies._resolve_demo_target("loan-agent-v2-fixed")
    descriptor = dependencies.repository.get_target_descriptor(target.descriptor_sha256)
    monkeypatch.setattr(
        bank_targets, "local_bank_target", lambda _client, _mode: (descriptor, target)
    )
    with TestClient(app) as client:
        yield client, dependencies, dispatcher, dataset.id
    dependencies.close()


def create_published_versions(client):
    definition = {
        "kind": "rule",
        "dimension": "answer",
        "metric": "custom_output",
        "severity": "standard",
        "implementation_id": "final_output",
        "implementation_version": "1",
        "config": {},
        "children": [],
        "combination": None,
    }
    created = client.post("/api/evaluators", json={"name": "Pinned output", "draft": definition})
    assert created.status_code == 201, created.text
    evaluator_id = created.json()["evaluator"]["id"]
    first = client.post(f"/api/evaluators/{evaluator_id}/drafts/publish").json()
    assert (
        client.patch(f"/api/evaluators/{evaluator_id}", json={"enabled": True}).status_code == 200
    )
    assert (
        client.post(
            f"/api/evaluators/{evaluator_id}/drafts", json={"based_on_version": "1"}
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/api/evaluators/{evaluator_id}/drafts/current",
            json={**definition, "severity": "blocking"},
        ).status_code
        == 200
    )
    second = client.post(f"/api/evaluators/{evaluator_id}/drafts/publish").json()
    assert second["version"] == "2"
    return evaluator_id, first


PATHS = [
    "demo",
    "stability",
    "bank",
    "bank-stability",
    "platform",
    "platform-stability",
    "platform-ab",
    "demo-ab",
]


def submission(kind, dataset_id, evaluator_id, version="1"):
    selection = [{"evaluator_id": evaluator_id, "evaluator_version": version}]
    common = {"dataset_id": dataset_id, "dataset_version": 1, "evaluator_refs": selection}
    if kind == "demo-ab":
        common.pop("evaluator_refs")
        return "/api/run-comparisons", {
            **common,
            "baseline_version": "loan-agent-v1-risky",
            "candidate_version": "loan-agent-v2-fixed",
            "evaluators": [{"id": evaluator_id, "version": version}],
        }
    if kind.startswith("bank"):
        return "/api/bank-evaluations", {
            **common,
            "mode": "base",
            "repetitions": 3 if kind.endswith("stability") else 1,
        }
    if kind.startswith("platform"):
        target = {
            "agent_id": "selected-agent",
            "agent_version": "v1",
            "type_group": "base/workflow",
            "arrange_type": "workflow",
        }
        if kind.endswith("ab"):
            target.pop("agent_version")
            return "/api/agent-platform/comparisons", {
                **common,
                "timeout_seconds": 30,
                "target": {**target, "baseline_version": "v1", "candidate_version": "v2"},
            }
        return "/api/agent-platform/evaluations", {
            **common,
            "target": target,
            "max_parallel_cases": 1,
            "timeout_seconds": 30,
            "max_retries": 0,
            "repetitions": 3 if kind.endswith("stability") else 1,
        }
    body = {**common, "version": "loan-agent-v2-fixed"}
    if kind == "stability":
        return "/api/stability-experiments", {**body, "repetitions": 3}
    return "/api/evaluations", body


@pytest.mark.parametrize("kind", PATHS)
def test_selected_version_survives_newer_publication_and_is_persisted(system, kind):
    client, dependencies, dispatcher, dataset_id = system
    evaluator_id, first = create_published_versions(client)
    path, body = submission(kind, dataset_id, evaluator_id)
    response = client.post(
        path, json=body, headers={"X-Agent-Platform-Token": "real-session-test-token"}
    )
    assert response.status_code == 202, response.text
    assert dispatcher.ids
    manifests = [dependencies.repository.get_run(run_id).manifest for run_id in dispatcher.ids]
    for manifest in manifests:
        assert [spec.model_dump(mode="json") for spec in manifest.evaluator_specs] == [first]
        assert manifest.primary_evaluator_ids == (evaluator_id,)
    assert len({manifest.evaluator_specs[0].content_sha256 for manifest in manifests}) == 1
    # A subsequent draft edit cannot mutate the already-persisted run inputs.
    client.post(f"/api/evaluators/{evaluator_id}/drafts", json={"based_on_version": "2"})
    assert dependencies.repository.get_run(dispatcher.ids[0]).manifest == manifests[0]


@pytest.mark.parametrize(
    "kind,invalid",
    [
        (kind, invalid)
        for kind in PATHS
        for invalid in ("unpublished_version", "disabled", "both_selections")
        if not (kind == "demo-ab" and invalid == "both_selections")
    ],
)
def test_invalid_evaluator_selection_never_dispatches(system, kind, invalid):
    client, dependencies, dispatcher, dataset_id = system
    evaluator_id, _ = create_published_versions(client)
    path, body = submission(
        kind, dataset_id, evaluator_id, "draft" if invalid == "unpublished_version" else "1"
    )
    if invalid == "disabled":
        client.patch(f"/api/evaluators/{evaluator_id}", json={"enabled": False})
    if invalid == "both_selections":
        body["evaluator_ids"] = [evaluator_id]
    response = client.post(
        path, json=body, headers={"X-Agent-Platform-Token": "real-session-test-token"}
    )
    assert response.status_code in (404, 409, 422), response.text
    assert dispatcher.ids == []
    assert dependencies.repository.list_evaluation_tasks() == []


@pytest.mark.parametrize("kind", ["platform-ab", "platform", "demo", "stability", "bank"])
@pytest.mark.parametrize("selection", ["ids", "refs"])
def test_composite_dependencies_are_pinned_without_becoming_primary(system, kind, selection):
    client, dependencies, dispatcher, dataset_id = system

    class JudgeClient:
        provider_id = "test-provider"

        def complete(self, request):
            raise AssertionError("submission must not invoke the model")

    management = build_default_evaluator_management(
        dependencies.repository,
        judge_client=JudgeClient(),
        judge_model_id="test-model",
        judge_credential_ref="env:TEST_JUDGE_KEY",
    )
    dependencies.evaluators = management
    dependencies.runs.evaluator_management = management
    for name, submitter in (
        ("submit_agent_platform_evaluation", submit_platform_evaluation),
        ("submit_agent_platform_comparison", submit_platform_comparison),
    ):
        setattr(
            client.app.state,
            name,
            partial(
                submitter,
                repository=dependencies.repository,
                evaluators=management,
                credentials=dependencies.api_keys,
                dispatcher=dispatcher,
            ),
        )
    created = client.post(
        "/api/evaluators",
        json={
            "name": "Composite only",
            "draft": {
                "kind": "hybrid",
                "dimension": "quality",
                "metric": "combined_quality",
                "severity": "standard",
                "implementation_id": "composite",
                "implementation_version": "1",
                "config": {},
                "children": [
                    {"evaluator_id": "final-output", "evaluator_version": "1"},
                    {"evaluator_id": "answer-quality", "evaluator_version": "1"},
                ],
                "combination": "all",
            },
        },
    )
    assert created.status_code == 201, created.text
    evaluator_id = created.json()["evaluator"]["id"]
    published = client.post(f"/api/evaluators/{evaluator_id}/drafts/publish")
    assert published.status_code == 200, published.text
    assert (
        client.patch(f"/api/evaluators/{evaluator_id}", json={"enabled": True}).status_code == 200
    )
    path, body = submission(kind, dataset_id, evaluator_id)
    if selection == "ids":
        body.pop("evaluator_refs")
        body["evaluator_ids"] = [evaluator_id]
    response = client.post(path, json=body, headers={"X-Agent-Platform-Token": "test-session"})
    assert response.status_code == 202, response.text
    manifests = [dependencies.repository.get_run(run_id).manifest for run_id in dispatcher.ids]
    assert len(manifests) == (2 if kind == "platform-ab" else 3 if kind == "stability" else 1)
    for manifest in manifests:
        assert manifest.primary_evaluator_ids == (evaluator_id,)
        assert {spec.id for spec in manifest.evaluator_specs} == {
            evaluator_id,
            "final-output",
            "answer-quality",
        }
        assert manifest.evaluator_specs == manifests[0].evaluator_specs
