"""Owned LLM groups save atomically and preserve independent model evidence."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.evaluator_management import (
    EvaluatorCatalogConflict,
    build_default_evaluator_management,
)
from agentgate.application.llm_evaluator_groups import LLMGroupChildInput, save_llm_group
from agentgate.domain import (
    Case,
    CaseTurn,
    DatasetVersion,
    EvaluatorDraft,
    EvaluatorRef,
    MetricPlan,
    Outcome,
    Trace,
)
from agentgate.evaluator.judge.model_protocol import JudgeModelTimeout, JudgeResponse
from agentgate.result.metrics import calculate_metrics
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.evaluators import router


class RecordingJudge:
    provider_id = "group-test"

    def __init__(self):
        self.requests = []
        self.fail_at = None

    def complete(self, request):
        self.requests.append(request)
        index = len(self.requests)
        if index == self.fail_at:
            raise JudgeModelTimeout("test timeout")
        score = 0.9 if index % 2 else 0.6
        verdict = "pass" if score >= 0.8 else "fail"
        return JudgeResponse(
            text=json.dumps(
                {
                    "verdict": verdict,
                    "score": score,
                    "confidence": 1,
                    "reason": "Specific independent judgment",
                    "violations": []
                    if verdict == "pass"
                    else [{"criterion": "quality", "detail": "Incomplete answer"}],
                }
            ),
            resolved_model_id=request.model_id,
            input_tokens=20,
            output_tokens=10,
            request_id=f"request-{index}",
        )


@pytest.fixture
def system(tmp_path):
    dependencies = build_dependencies(tmp_path / "groups.db")
    model = RecordingJudge()
    management = build_default_evaluator_management(
        dependencies.repository,
        judge_client=model,
        judge_model_id="test-model",
        judge_credential_ref="env:TEST_GROUP_KEY",
    )
    dependencies.evaluators = management
    app = FastAPI()
    app.state.dependencies = dependencies
    app.include_router(router)
    with TestClient(app) as client:
        yield client, management, model
    dependencies.close()


def payload(count=2):
    return {
        "name": "Answer quality group",
        "description": "Published group description",
        "pass_threshold": 0.75,
        "children": [
            {
                "name": f"Criterion {index}",
                "description": f"Child description {index}",
                "template_id": f"criterion-{index}",
                "weight": 1.0 if count == 1 else 0.6 if index == 0 else 0.4,
                "definition": {
                    "kind": "llm_judge",
                    "dimension": "answer",
                    "metric": f"criterion_{index}",
                    "implementation_id": "answer_quality",
                    "implementation_version": "1",
                    "config": {
                        "model": {
                            "provider_id": "group-test",
                            "model_id": f"test-model-{index}",
                            "credential_ref": "env:TEST_GROUP_KEY",
                        },
                        "instruction": f"Judge criterion {index}. Input: {{{{input}}}} Output: {{{{output}}}}",
                        "render_template": True,
                        "rubric": {"quality": "Answer follows this criterion"},
                        "pass_threshold": 0.8,
                    },
                },
            }
            for index in range(count)
        ],
    }


def create(client, body=None):
    response = client.post("/api/evaluators/llm-groups", json=body or payload())
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, group):
    response = client.post(
        f"/api/evaluators/{group['evaluator']['id']}/llm-group/publish",
        json={
            "expected_draft_id": group["definition"]["id"],
            "expected_draft_updated_at": group["definition"]["updated_at"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def discard(client, group):
    return client.request(
        "DELETE",
        f"/api/evaluators/{group['evaluator']['id']}/llm-group/draft",
        json={
            "expected_draft_id": group["definition"]["id"],
            "expected_draft_updated_at": group["definition"]["updated_at"],
        },
    )


def edit_payload(group):
    body = payload(len(group["children"]))
    for item, saved in zip(body["children"], group["children"], strict=True):
        item["id"] = saved["evaluator"]["id"]
    if group["viewing_draft"]:
        body["expected_draft_id"] = group["definition"]["id"]
        body["expected_draft_updated_at"] = group["definition"]["updated_at"]
    else:
        body["based_on_version"] = group["definition"]["version"]
    return body


def test_group_catalog_and_metadata_lifecycle(system):
    client, management, model = system
    draft = create(client)
    group_id = draft["evaluator"]["id"]
    assert draft["definition"]["kind"] == "llm_group"
    assert draft["viewing_draft"] and draft["has_draft"]
    assert draft["latest_version"] is None and not draft["evaluator"]["enabled"]
    assert all(item["evaluator"]["owner_evaluator_id"] == group_id for item in draft["children"])
    listed = client.get("/api/evaluators?include_disabled=true").json()
    assert next(item for item in listed if item["id"] == group_id)["child_count"] == 2
    assert not {item["evaluator"]["id"] for item in draft["children"]}.intersection(
        item["id"] for item in listed
    )
    first = publish(client, draft)
    assert first["latest_version"] == "1"
    assert first["evaluator"]["enabled"] and not first["has_draft"]
    assert first["evaluator"]["updated_at"] > draft["evaluator"]["updated_at"]
    assert model.requests == []

    body = edit_payload(first)
    body["name"] = "Revised group"
    body["description"] = "Revised group description"
    body["children"][0]["name"] = "Revised criterion"
    body["children"][0]["description"] = "Revised child description"
    response = client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=body)
    assert response.status_code == 200, response.text
    second_draft = response.json()
    assert second_draft["definition"]["based_on_version"] == "1"
    assert second_draft["evaluator"]["updated_at"] > first["evaluator"]["updated_at"]
    second = publish(client, second_draft)
    assert second["definition"]["version"] == "2"
    exact_first = client.get(f"/api/evaluators/{group_id}/llm-group?version=1").json()
    assert exact_first["definition"] == first["definition"]
    assert exact_first["definition"]["config"]["description"] == "Published group description"
    assert exact_first["children"][0]["definition"] == first["children"][0]["definition"]
    assert exact_first["children"][0]["description"] == "Child description 0"
    assert exact_first["children"][0]["template_id"] == "criterion-0"
    assert [
        spec.version
        for spec in management.select_versions(
            (EvaluatorRef(evaluator_id=group_id, evaluator_version="1"),)
        )
    ] == ["1", "1", "1"]


def test_draft_conflicts_and_publish_conflicts_preserve_latest_edit(system):
    client, _, _ = system
    draft = create(client)
    group_id = draft["evaluator"]["id"]
    body = edit_payload(draft)
    body["children"][0]["description"] = "Latest edit"
    updated = client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=body)
    assert updated.status_code == 200, updated.text
    assert client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=body).status_code == 409
    stale_publish = client.post(
        f"/api/evaluators/{group_id}/llm-group/publish",
        json={
            "expected_draft_id": draft["definition"]["id"],
            "expected_draft_updated_at": draft["definition"]["updated_at"],
        },
    )
    assert stale_publish.status_code == 409
    assert discard(client, draft).status_code == 409
    current = client.get(f"/api/evaluators/{group_id}/llm-group").json()
    assert current["children"][0]["description"] == "Latest edit"
    assert current["latest_version"] is None


def test_group_legacy_mutations_cannot_bypass_revision_checks(system):
    client, _, _ = system
    group = create(client)
    group_id = group["evaluator"]["id"]
    assert client.delete(f"/api/evaluators/{group_id}").status_code == 409
    assert client.patch(f"/api/evaluators/{group_id}", json={"name": "Bypass"}).status_code == 409
    assert (
        client.patch(f"/api/evaluators/{group_id}", json={"description": "Bypass"}).status_code
        == 409
    )
    group = publish(client, group)
    assert client.patch(f"/api/evaluators/{group_id}", json={"enabled": False}).status_code == 200


def test_group_read_rejects_a_mixed_snapshot_during_concurrent_save(system, monkeypatch):
    client, management, _ = system
    original = create(client)
    group_id = original["evaluator"]["id"]
    child_id = original["children"][0]["evaluator"]["id"]
    read_draft = management.repository.get_evaluator_draft
    changed = False

    def read_while_saving(evaluator_id, *, user_team_id):
        nonlocal changed
        if evaluator_id == child_id and not changed:
            changed = True
            body = edit_payload(original)
            save_llm_group(
                management,
                evaluator_id=group_id,
                name="Concurrent name",
                description=body["description"],
                pass_threshold=body["pass_threshold"],
                expected_draft_id=body["expected_draft_id"],
                expected_draft_updated_at=read_draft(group_id, user_team_id="").updated_at,
                children=tuple(
                    LLMGroupChildInput(
                        id=item["id"],
                        name=item["name"],
                        description=item["description"],
                        template_id=item["template_id"],
                        weight=item["weight"],
                        definition=EvaluatorDraft(evaluator_id=item["id"], **item["definition"]),
                    )
                    for item in body["children"]
                ),
            )
        return read_draft(evaluator_id, user_team_id=user_team_id)

    monkeypatch.setattr(management.repository, "get_evaluator_draft", read_while_saving)
    response = client.get(f"/api/evaluators/{group_id}/llm-group")
    assert response.status_code == 409, response.text
    assert (
        client.get(f"/api/evaluators/{group_id}/llm-group").json()["evaluator"]["name"]
        == "Concurrent name"
    )


def test_owned_children_cannot_be_mutated_adopted_or_selected_independently(system):
    client, management, _ = system
    group = publish(client, create(client))
    group_id = group["evaluator"]["id"]
    child_id = group["children"][0]["evaluator"]["id"]
    for path, method, body in (
        (f"/{child_id}", "patch", {"enabled": False}),
        (f"/{child_id}/drafts", "post", {"based_on_version": "1"}),
        (f"/{child_id}/drafts/current", "put", payload()["children"][0]["definition"]),
        (f"/{child_id}/drafts/publish", "post", None),
        (f"/{child_id}", "delete", None),
    ):
        assert client.request(method, "/api/evaluators" + path, json=body).status_code == 409
    for requested in ([child_id], [group_id, child_id], [child_id, group_id]):
        with pytest.raises(EvaluatorCatalogConflict, match="independently"):
            management.select(requested)
    foreign = payload()
    foreign["children"][0]["id"] = child_id
    assert client.post("/api/evaluators/llm-groups", json=foreign).status_code == 409
    assert client.post(f"/api/evaluators/{group_id}/drafts", json={}).status_code == 409


def test_remove_child_publish_and_discard_keep_exact_history(system):
    client, management, _ = system
    first = publish(client, create(client))
    group_id = first["evaluator"]["id"]
    removed_id = first["children"][1]["evaluator"]["id"]
    body = edit_payload(first)
    body["children"] = body["children"][:1]
    body["children"][0]["weight"] = 1.0
    response = client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=body)
    assert response.status_code == 200, response.text
    second = publish(client, response.json())
    assert len(second["children"]) == 1
    assert (
        len(
            management.select_versions(
                (EvaluatorRef(evaluator_id=group_id, evaluator_version="1"),)
            )
        )
        == 3
    )
    assert management.get_version(removed_id, "1")
    next_draft = client.put(
        f"/api/evaluators/{group_id}/llm-group/draft", json=edit_payload(second)
    )
    assert next_draft.status_code == 200, next_draft.text
    assert discard(client, next_draft.json()).status_code == 204
    assert (
        client.get(f"/api/evaluators/{group_id}/llm-group").json()["definition"]
        == second["definition"]
    )


def test_discard_unpublished_group_cleans_all_owned_records(system):
    client, management, _ = system
    group = create(client, payload(1))
    group_id = group["evaluator"]["id"]
    child_id = group["children"][0]["evaluator"]["id"]
    assert discard(client, group).status_code == 204
    assert client.get(f"/api/evaluators/{group_id}").status_code == 404
    assert management.repository.get_evaluator(child_id, user_team_id="") is None


@pytest.mark.parametrize("invalid", ["weights", "empty", "rule", "credential", "duplicate"])
def test_invalid_groups_never_create_partial_catalog_entries(system, invalid):
    client, management, _ = system
    body = payload()
    if invalid == "weights":
        body["children"][0]["weight"] = 0.7
    elif invalid == "empty":
        body["children"] = []
    elif invalid == "rule":
        body["children"][0]["definition"]["kind"] = "rule"
    elif invalid == "credential":
        body["children"][0]["definition"]["config"]["model"]["api_key"] = "never-store"
    else:
        body["children"][0]["id"] = body["children"][1]["id"] = "same"
    response = client.post("/api/evaluators/llm-groups", json=body)
    assert response.status_code in (409, 422), response.text
    assert management.repository.list_evaluators(include_disabled=True, user_team_id="") == []


def test_provider_validation_is_before_any_publication(system):
    client, management, model = system
    body = payload()
    body["children"][1]["definition"]["config"]["model"]["provider_id"] = "unavailable"
    group = create(client, body)
    group_id = group["evaluator"]["id"]
    response = client.post(
        f"/api/evaluators/{group_id}/llm-group/publish",
        json={
            "expected_draft_id": group["definition"]["id"],
            "expected_draft_updated_at": group["definition"]["updated_at"],
        },
    )
    assert response.status_code == 422, response.text
    for item_id in (group_id, *(item["evaluator"]["id"] for item in group["children"])):
        assert management.repository.list_evaluator_versions(item_id, user_team_id="") == []
        assert management.repository.get_evaluator_draft(item_id, user_team_id="") is not None
    assert model.requests == []


def test_execution_keeps_each_judge_record_and_counts_only_parent(system):
    client, management, model = system
    group = publish(client, create(client))
    group_id = group["evaluator"]["id"]
    specs = management.select([group_id])
    case = Case(id="case", name="Question", turns=(CaseTurn(input={"question": "What is 2+2?"}),))
    dataset = DatasetVersion(dataset_id="dataset", cases=(case,))
    management.validate_plan(dataset, specs)
    trace = Trace(
        trace_id="0" * 32, run_id="run", case_id=case.id, spans=(), final_output={"answer": "4"}
    )
    results = management.evaluate_case(case, trace, specs)
    assert len(model.requests) == 2
    assert results[0].evaluator_kind == "llm_group"
    assert results[0].outcome == Outcome.PASS and results[0].score == pytest.approx(0.78)
    assert results[0].judge_record is None
    assert [result.judge_record.request_id for result in results[1:]] == ["request-1", "request-2"]
    assert [result.judge_record.requested_model for result in results[1:]] == [
        "test-model-0",
        "test-model-1",
    ]
    assert [item["weight"] for item in results[0].checks[0].actual] == [0.6, 0.4]
    metrics = calculate_metrics(results, (group_id,), MetricPlan())
    assert metrics[0].score == pytest.approx(0.78) and metrics[0].total == 1
    management.update_evaluator(group_id, enabled=False)
    historical = management.evaluate_case(case, trace, specs)
    assert historical[0].score == pytest.approx(0.78)


def test_child_error_is_preserved_and_parent_cannot_report_success(system):
    client, management, model = system
    group = publish(client, create(client))
    model.fail_at = 2
    case = Case(id="case", name="Question", turns=(CaseTurn(input={"question": "Question"}),))
    trace = Trace(
        trace_id="0" * 32,
        run_id="run",
        case_id=case.id,
        spans=(),
        final_output={"answer": "Answer"},
    )
    results = management.evaluate_case(case, trace, management.select([group["evaluator"]["id"]]))
    assert [result.outcome for result in results] == [Outcome.ERROR, Outcome.PASS, Outcome.ERROR]
    assert results[0].score is None and results[2].score is None
    assert results[1].judge_record is not None and results[2].error_detail is not None


def test_historical_base_can_restore_removed_owned_child(system):
    client, _, _ = system
    first = publish(client, create(client))
    group_id = first["evaluator"]["id"]
    body = edit_payload(first)
    body["children"] = body["children"][:1]
    body["children"][0]["weight"] = 1.0
    second_draft = client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=body).json()
    publish(client, second_draft)
    restored = client.put(f"/api/evaluators/{group_id}/llm-group/draft", json=edit_payload(first))
    assert restored.status_code == 200, restored.text
    third = publish(client, restored.json())
    assert third["definition"]["version"] == "3" and len(third["children"]) == 2
    assert third["children"][1]["definition"]["version"] == "2"
