"""Deleting published LLM assets hides the catalog entry but preserves exact history."""

import json
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentgate.application.evaluator_management import (
    EvaluatorCatalogConflict,
    build_default_evaluator_management,
)
from agentgate.domain import Case, CaseTurn, DatasetVersion, Evaluator, EvaluatorRef, Trace
from agentgate.evaluator.judge.model_protocol import JudgeResponse
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.evaluators import router


class ArchivalTestJudge:
    provider_id = "archival-test"

    def complete(self, request):
        return JudgeResponse(
            text=json.dumps(
                {
                    "verdict": "pass",
                    "score": 0.9,
                    "confidence": 1,
                    "reason": "The answer meets the criterion",
                    "violations": [],
                }
            ),
            resolved_model_id=request.model_id,
            input_tokens=10,
            output_tokens=10,
        )


@contextmanager
def _system(database_path):
    dependencies = build_dependencies(database_path)
    management = build_default_evaluator_management(
        dependencies.repository,
        judge_client=ArchivalTestJudge(),
        judge_model_id="test-model",
        judge_credential_ref="env:TEST_ARCHIVAL_KEY",
    )
    dependencies.evaluators = management
    app = FastAPI()
    app.state.dependencies = dependencies
    app.include_router(router)
    try:
        with TestClient(app) as client:
            yield client, management
    finally:
        dependencies.close()


@pytest.fixture
def system(tmp_path):
    with _system(tmp_path / "archival.db") as current:
        yield current


def _judge_definition():
    return {
        "kind": "llm_judge",
        "dimension": "answer",
        "metric": "answer_quality",
        "implementation_id": "answer_quality",
        "implementation_version": "1",
        "config": {
            "model": {
                "provider_id": "archival-test",
                "model_id": "test-model",
                "credential_ref": "env:TEST_ARCHIVAL_KEY",
            },
            "instruction": "Judge the answer quality.",
            "rubric": {"quality": "The answer meets the criterion"},
            "pass_threshold": 0.8,
        },
    }


def _published_judge(client):
    response = client.post(
        "/api/evaluators",
        json={
            "name": "Saved judge",
            "draft": _judge_definition(),
        },
    )
    assert response.status_code == 201, response.text
    evaluator_id = response.json()["evaluator"]["id"]
    publication = client.post(f"/api/evaluators/{evaluator_id}/drafts/publish")
    assert publication.status_code == 200, publication.text
    enabled = client.patch(f"/api/evaluators/{evaluator_id}", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    return evaluator_id, publication.json()


def _group_body():
    return {
        "name": "Saved group",
        "description": "Two independently configured criteria",
        "pass_threshold": 0.8,
        "children": [
            {
                "name": f"Criterion {index}",
                "weight": weight,
                "definition": _judge_definition(),
            }
            for index, weight in enumerate((0.4, 0.6))
        ],
    }


def _published_group(client):
    response = client.post("/api/evaluators/llm-groups", json=_group_body())
    assert response.status_code == 201, response.text
    draft = response.json()
    evaluator_id = draft["evaluator"]["id"]
    publication = client.post(
        f"/api/evaluators/{evaluator_id}/llm-group/publish",
        json={
            "expected_draft_id": draft["definition"]["id"],
            "expected_draft_updated_at": draft["definition"]["updated_at"],
        },
    )
    assert publication.status_code == 200, publication.text
    return evaluator_id, publication.json()


def test_archived_judge_stays_hidden_after_restart_and_retains_exact_history(tmp_path):
    database_path = tmp_path / "restart.db"
    with _system(database_path) as (client, _):
        evaluator_id, version = _published_judge(client)
        other_id, _ = _published_judge(client)
        assert client.delete(f"/api/evaluators/{evaluator_id}").status_code == 204
        assert client.delete(f"/api/evaluators/{evaluator_id}").status_code == 204

    with _system(database_path) as (client, management):
        for include_disabled in (False, True):
            response = client.get("/api/evaluators", params={"include_disabled": include_disabled})
            assert response.status_code == 200
            listed = {item["id"] for item in response.json()}
            assert evaluator_id not in listed
            assert {other_id, "final-output"} <= listed
        detail = client.get(f"/api/evaluators/{evaluator_id}")
        assert detail.status_code == 200
        assert detail.json()["evaluator"]["archived"] is True
        assert detail.json()["evaluator"]["enabled"] is False
        assert detail.json()["latest"] == version
        assert client.get(f"/api/evaluators/{evaluator_id}/versions").json() == [version]
        assert client.get(f"/api/evaluators/{evaluator_id}/versions/1").json() == version
        assert management.get_version(evaluator_id, "1").content_sha256 == version["content_sha256"]


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("PATCH", "", {"enabled": True}),
        ("PATCH", "", {"name": "Changed name"}),
        ("POST", "/drafts", {"based_on_version": "1"}),
        ("PUT", "/drafts/current", _judge_definition()),
        ("POST", "/drafts/publish", None),
        ("DELETE", "/drafts/current", None),
    ],
)
def test_archived_judge_rejects_writes_without_modifying_saved_draft(system, method, suffix, body):
    client, management = system
    evaluator_id, version = _published_judge(client)
    draft = client.post(f"/api/evaluators/{evaluator_id}/drafts", json={"based_on_version": "1"})
    assert draft.status_code == 201
    assert client.delete(f"/api/evaluators/{evaluator_id}").status_code == 204

    response = client.request(method, f"/api/evaluators/{evaluator_id}{suffix}", json=body)

    assert response.status_code == 409, response.text
    assert management.get_evaluator(evaluator_id).archived
    assert client.get(f"/api/evaluators/{evaluator_id}").json()["draft"] is None
    saved = management.repository.get_evaluator_draft(evaluator_id, user_team_id="")
    assert saved.model_dump(mode="json") == draft.json()
    assert client.get(f"/api/evaluators/{evaluator_id}/versions").json() == [version]


def test_archived_group_preserves_child_history_and_rejects_group_writes(system):
    client, management = system
    evaluator_id, first = _published_group(client)
    body = _group_body()
    body["based_on_version"] = "1"
    for item, saved in zip(body["children"], first["children"], strict=True):
        item["id"] = saved["evaluator"]["id"]
    edited = client.put(f"/api/evaluators/{evaluator_id}/llm-group/draft", json=body)
    assert edited.status_code == 200, edited.text
    draft = edited.json()
    revision = {
        "expected_draft_id": draft["definition"]["id"],
        "expected_draft_updated_at": draft["definition"]["updated_at"],
    }
    body.pop("based_on_version")
    body.update(revision)
    assert client.delete(f"/api/evaluators/{evaluator_id}").status_code == 204

    historical = client.get(f"/api/evaluators/{evaluator_id}/llm-group?version=1")
    assert historical.status_code == 200, historical.text
    assert historical.json()["evaluator"]["archived"] is True
    assert historical.json()["definition"] == first["definition"]
    for actual, expected in zip(historical.json()["children"], first["children"], strict=True):
        assert actual["definition"] == expected["definition"]
        child_id = actual["evaluator"]["id"]
        assert client.get(f"/api/evaluators/{child_id}/versions/1").json() == expected["definition"]
        assert client.delete(f"/api/evaluators/{child_id}").status_code == 409
    assert (
        client.put(f"/api/evaluators/{evaluator_id}/llm-group/draft", json=body).status_code == 409
    )
    assert (
        client.post(
            f"/api/evaluators/{evaluator_id}/llm-group/publish",
            json=revision,
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE",
            f"/api/evaluators/{evaluator_id}/llm-group/draft",
            json=revision,
        ).status_code
        == 409
    )
    assert (
        client.patch(f"/api/evaluators/{evaluator_id}", json={"enabled": True}).status_code == 409
    )
    listed = client.get("/api/evaluators?include_disabled=true").json()
    assert {evaluator_id, *(item["evaluator"]["id"] for item in first["children"])}.isdisjoint(
        item["id"] for item in listed
    )
    assert len(management.list_versions(evaluator_id)) == 1


@pytest.mark.parametrize("create", [_published_judge, _published_group], ids=["judge", "group"])
def test_archive_blocks_new_selection_but_saved_plan_can_still_validate_and_execute(system, create):
    client, management = system
    evaluator_id, _ = create(client)
    saved_specs = management.select([evaluator_id])
    assert client.delete(f"/api/evaluators/{evaluator_id}").status_code == 204
    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        management.select([evaluator_id])
    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        management.select_versions(
            (EvaluatorRef(evaluator_id=evaluator_id, evaluator_version="1"),)
        )

    case = Case(id="case", name="Question", turns=(CaseTurn(input={"question": "What is 2+2?"}),))
    dataset = DatasetVersion(dataset_id="dataset", cases=(case,))
    management.validate_plan(dataset, saved_specs)
    trace = Trace(
        trace_id="0" * 32,
        run_id="saved-run",
        case_id=case.id,
        spans=(),
        final_output={"answer": "4"},
    )
    results = management.evaluate_case(case, trace, saved_specs)
    assert len(results) == len(saved_specs)
    assert all(result.outcome == "pass" for result in results)
    assert results[0].score == pytest.approx(0.9)


@pytest.mark.parametrize("source,enabled", [("user", True), ("builtin", True), ("builtin", False)])
def test_archived_evaluator_must_be_disabled_and_user_owned(source, enabled):
    with pytest.raises(ValidationError):
        Evaluator(name="Deleted asset", archived=True, source=source, enabled=enabled)
