from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_run_engine import pending_run

from agentgate.domain import Dataset, DatasetVersion, RunStatus, transition_run
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.app import create_app

TEAM_ID = "dataset-history"
TEAM = {"X-Team-Id": TEAM_ID}
CREATED = datetime(2026, 9, 7, 12, tzinfo=UTC)


def test_dataset_related_tasks_matches_version_and_pages_visible_tasks(tmp_path):
    app = create_app(tmp_path / "dataset-history.db")
    repo = app.state.dependencies.repository
    dataset = Dataset(name="History dataset", user_team_id=TEAM_ID)
    repo.save_dataset(dataset)
    versions = [
        DatasetVersion(
            dataset_id=dataset.id,
            version=number,
            status="published",
            cases=pending_run().manifest.dataset.cases,
            created_at=CREATED,
            updated_at=CREATED,
            published_at=CREATED,
            user_team_id=TEAM_ID,
        )
        for number in (1, 2)
    ]
    for version in versions:
        repo.save_dataset_version(version)
    v1, v2 = versions

    def run(run_id, *, version=v1, team=TEAM_ID):
        result = pending_run(dataset=version).model_copy(
            update={
                "id": run_id,
                "user_team_id": team,
                "created_at": CREATED,
            }
        )
        repo.save_run(result)
        return result

    a, b = run("ab-a"), run("ab-b")
    repo.save_run(transition_run(b, RunStatus.FAILED, error="Failed"))
    repo.save_evaluation_task(
        EvaluationTask(
            id="ab",
            name="Comparison",
            kind="ab",
            run_ids=(a.id, b.id),
            created_at=CREATED + timedelta(minutes=1),
        )
    )
    original = run("original")
    task = repo.save_evaluation_task(
        EvaluationTask(
            id="rerun",
            name="Retried",
            kind="single",
            run_ids=(original.id,),
            created_at=CREATED,
        )
    )
    repo.save_run(transition_run(original, RunStatus.CANCELLED))
    replacement = original.model_copy(update={"id": "replacement"})
    repo.save_task_rerun(task.id, original.id, replacement, user_team_id=TEAM_ID)
    run("legacy")
    run("v2-run", version=v2)
    run("other-team", team="other")
    mixed_first, mixed_second = run("mixed-own"), run("mixed-foreign", team="other")
    repo.save_evaluation_task(
        EvaluationTask(
            id="mixed",
            name="Private",
            kind="ab",
            run_ids=(mixed_first.id, mixed_second.id),
        )
    )

    base = f"/api/datasets/{dataset.id}/versions"
    path = f"{base}/1/related-tasks"
    with TestClient(app) as client:
        page, items = {}, []
        for index in range(3):
            params = {"limit": 1}
            if page.get("next_cursor"):
                params["cursor"] = page["next_cursor"]
            response = client.get(path, params=params, headers=TEAM)
            assert response.status_code == 200, response.text
            page = response.json()["data"]
            assert set(page) == {"items", "next_cursor"}
            assert len(page["items"]) == 1
            assert bool(page["next_cursor"]) == (index < 2)
            items.extend(page["items"])

        other_version = client.get(f"{base}/2/related-tasks", headers=TEAM)
        assert other_version.status_code == 200, other_version.text
        assert [item["run_id"] for item in other_version.json()["data"]["items"]] == ["v2-run"]
        assert client.get(path, headers={"X-Team-Id": "other"}).status_code == 404
        assert client.get(f"{base}/3/related-tasks", headers=TEAM).status_code == 404
        assert client.get(f"{base}/0/related-tasks", headers=TEAM).status_code == 422
        assert client.get(path, params={"cursor": "invalid"}, headers=TEAM).status_code == 422

    assert [item["task_id"] for item in items] == ["ab", None, "rerun"]
    assert [item["run_id"] for item in items] == ["ab-a", "legacy", "replacement"]
    assert items[0] == {
        "task_id": "ab",
        "run_id": "ab-a",
        "name": "Comparison",
        "kind": "ab",
        "status": "failed",
        "created_at": "2026-09-07T12:01:00Z",
        "dataset_version": 1,
    }
    assert items[2]["status"] == "pending"
