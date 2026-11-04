from base64 import urlsafe_b64encode
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from test_evaluator_api import _create_payload
from test_run_engine import pending_run

from agentgate.domain import EvaluatorRef, EvaluatorSpec, RunStatus, transition_run
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.app import create_app

CREATED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
TEAM = {"X-Team-Id": "history-team"}


def _run(repo, run_id, specs, *, primary=None, team=TEAM["X-Team-Id"]):
    run = pending_run(
        evaluator_specs=specs, primary_evaluator_ids=(primary or specs[0].id,)
    ).model_copy(update={"id": run_id, "user_team_id": team, "created_at": CREATED})
    repo.save_run(run)
    return run


def _builtin(dependencies):
    return dependencies.evaluators.list_versions(dependencies.evaluators.list_evaluators()[0].id)[0]


def _path(spec):
    return f"/api/evaluators/{spec.id}/versions/{spec.version}/related-tasks"


def test_related_tasks_page_groups_ab_and_reruns_and_keeps_legacy_runs(tmp_path):
    app = create_app(tmp_path / "task-history.db")
    deps = app.state.dependencies
    repo = deps.repository
    spec = _builtin(deps)
    for run_id in ("ab-first", "ab-second", "original", "legacy"):
        _run(repo, run_id, (spec,))

    repo.save_evaluation_task(
        EvaluationTask(
            id="ab-task",
            name="Comparison",
            kind="ab",
            run_ids=("ab-first", "ab-second"),
            created_at=CREATED,
        )
    )
    second = repo.get_run("ab-second", user_team_id=TEAM["X-Team-Id"])
    repo.save_run(transition_run(second, RunStatus.FAILED, error="Run failed"))
    repo.save_evaluation_task(
        EvaluationTask(
            id="single-task",
            name="Rerun",
            kind="single",
            run_ids=("original",),
            created_at=CREATED,
        )
    )
    original = repo.get_run("original", user_team_id=TEAM["X-Team-Id"])
    repo.save_run(transition_run(original, RunStatus.CANCELLED))
    replacement = original.model_copy(update={"id": "replacement"})
    repo.save_task_rerun(
        "single-task",
        original.id,
        replacement,
        user_team_id=TEAM["X-Team-Id"],
    )

    with TestClient(app) as client:
        cursor = None
        items = []
        for index in range(3):
            params = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(_path(spec), params=params, headers=TEAM)
            assert response.status_code == 200, response.text
            page = response.json()["data"]
            assert set(page) == {"items", "next_cursor"}
            assert len(page["items"]) == 1
            items.extend(page["items"])
            cursor = page["next_cursor"]
            assert bool(cursor) == (index < 2)

        assert client.get(_path(spec), params={"limit": 0}, headers=TEAM).status_code == 422
        assert (
            client.get(_path(spec), params={"cursor": "invalid"}, headers=TEAM).status_code == 422
        )
        nested_cursor = urlsafe_b64encode(b"[" * 1200 + b"0" + b"]" * 1200).decode()
        assert (
            client.get(_path(spec), params={"cursor": nested_cursor}, headers=TEAM).status_code
            == 422
        )
        assert client.get(_path(spec), headers={"X-Team-Id": "other"}).json()["data"] == {
            "items": [],
            "next_cursor": None,
        }

    assert [item["task_id"] or item["run_id"] for item in items] == [
        "ab-task",
        "legacy",
        "single-task",
    ]
    assert items[0] == {
        "task_id": "ab-task",
        "run_id": "ab-first",
        "name": "Comparison",
        "kind": "ab",
        "status": "failed",
        "created_at": "2026-09-07T12:00:00Z",
        "evaluator_version": spec.version,
    }
    assert items[1]["task_id"] is None
    assert items[1]["kind"] == "single"
    assert items[2]["run_id"] == "replacement"
    assert items[2]["status"] == "pending"


def test_related_tasks_matches_published_version_and_composite_child_in_own_team(tmp_path):
    app = create_app(tmp_path / "evaluator-history.db")
    repo = app.state.dependencies.repository

    with TestClient(app) as client:
        created = client.post("/api/evaluators", json=_create_payload(), headers=TEAM)
        assert created.status_code == 201, created.text
        evaluator_id = created.json()["data"]["evaluator"]["id"]
        catalog = f"/api/evaluators/{evaluator_id}"
        first = client.post(f"{catalog}/drafts/publish", headers=TEAM)
        assert first.status_code == 200, first.text
        v1 = EvaluatorSpec.model_validate(first.json()["data"])
        assert (
            client.post(
                f"{catalog}/drafts", json={"based_on_version": "1"}, headers=TEAM
            ).status_code
            == 201
        )
        second = client.post(f"{catalog}/drafts/publish", headers=TEAM)
        assert second.status_code == 200, second.text
        v2 = EvaluatorSpec.model_validate(second.json()["data"])
        builtin = _builtin(app.state.dependencies)
        composite = EvaluatorSpec(
            id="composite",
            name="Composite",
            kind="hybrid",
            dimension="answer",
            metric="composite",
            implementation_id="composite",
            combination="all",
            children=(
                EvaluatorRef(evaluator_id=v1.id, evaluator_version=v1.version),
                EvaluatorRef(evaluator_id=builtin.id, evaluator_version=builtin.version),
            ),
        )
        _run(repo, "composite-run", (composite, v1, builtin), primary=composite.id)
        _run(repo, "newer-version", (v2,))
        _run(repo, "foreign-run", (v1,), team="other")
        _run(repo, "mixed-own-run", (v1,))
        _run(repo, "mixed-foreign-run", (v1,), team="other")
        repo.save_evaluation_task(
            EvaluationTask(
                id="mixed-task",
                kind="stability",
                run_ids=("mixed-own-run", "mixed-foreign-run"),
            )
        )

        first_page = client.get(_path(v1), headers=TEAM)
        second_page = client.get(_path(v2), headers=TEAM)
        assert first_page.status_code == second_page.status_code == 200
        assert [item["run_id"] for item in first_page.json()["data"]["items"]] == ["composite-run"]
        assert [item["run_id"] for item in second_page.json()["data"]["items"]] == ["newer-version"]
        assert client.get(_path(v1), headers={"X-Team-Id": "other"}).status_code == 404
        assert client.get(f"{catalog}/versions/99/related-tasks", headers=TEAM).status_code == 404


def test_related_tasks_excludes_task_with_foreign_representative_before_pagination(tmp_path):
    app = create_app(tmp_path / "stale-task-history.db")
    deps = app.state.dependencies
    repo = deps.repository
    spec = _builtin(deps)
    foreign = _run(repo, "foreign", (spec,), team="other")
    visible = _run(repo, "visible", (spec,))
    for index in range(2):
        current = _run(repo, f"current-{index}", (spec,))
        repo.save_evaluation_task(
            EvaluationTask(
                id=f"hidden-{index}",
                kind="single",
                run_ids=(current.id,),
            )
        )
    # Emulate stale task projection metadata.
    with repo._connect() as db:
        db.execute("UPDATE agentgate_evaluation_tasks SET first_run_id=?", (foreign.id,))

    with TestClient(app) as client:
        response = client.get(_path(spec), params={"limit": 1}, headers=TEAM)

    assert response.status_code == 200, response.text
    page = response.json()["data"]
    assert [item["run_id"] for item in page["items"]] == [visible.id]
    assert page["next_cursor"] is None
