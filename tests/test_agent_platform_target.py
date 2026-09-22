"""Local peer -> real application -> stored Run -> worker -> evaluation evidence."""

import json
from datetime import UTC, datetime, timedelta

import pytest
import test_agent_platform_mock as peer_fixtures
from fastapi.testclient import TestClient

from agentgate.application.run_scheduling import RunScheduling
from agentgate.domain import Case, CaseTurn
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.job_dispatchers.execution import _execute
from agentgate.integrations.targets.agent_platform import PlatformClient, resolve_platform_target
from agentgate.server.app import create_app

mock_peer = peer_fixtures.mock_peer


class RecordingDispatcher:
    def __init__(self, fail=False):
        self.ids = []
        self.fail = fail

    def submit(self, run_id):
        self.ids.append(run_id)
        if self.fail:
            raise RuntimeError("dispatch unavailable")


def seed(dependencies):
    manager = dependencies.datasets
    dataset = manager.create_dataset("平台本地验收", "文本回显测试")
    manager.create_draft(dataset.id)
    manager.save_case(
        dataset.id,
        Case(
            name="两轮文本",
            turns=tuple(
                CaseTurn(
                    input={"txt": text},
                    expectations=(
                        {
                            "kind": "output",
                            "path": "output",
                            "condition": {"kind": "matches_pattern", "pattern": ".*" + text + ".*"},
                        },
                    ),
                )
                for text in ("你好", "第二轮")
            ),
        ),
    )
    manager.publish_draft(dataset.id)
    return dataset.id


def submission(dataset, mode, repetitions=1):
    return {
        "target": {
            "team_id": "team-local",
            "agent_id": "agent-" + mode,
            "type_group": "abcclaw" if mode == "claw" else "base/workflow",
            "agent_version": "2.0",
            **({"branch_id": "branch-review"} if mode == "claw" else {}),
        },
        "dataset_id": dataset,
        "dataset_version": 1,
        "evaluator_ids": ["final-output"],
        "max_parallel_cases": 2,
        "timeout_seconds": 30,
        "max_retries": 0,
        "repetitions": repetitions,
    }


@pytest.mark.parametrize("mode,repetitions", [("base", 1), ("workflow", 1), ("claw", 3)])
def test_persisted_platform_execution(mode, repetitions, mock_peer, monkeypatch, tmp_path):
    import base64

    origin, peer = mock_peer
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", origin)
    monkeypatch.setenv(
        "AGENTGATE_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode()
    )
    dispatcher = RecordingDispatcher()
    path = tmp_path / "tasks.db"
    app = create_app(path, dispatcher, ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    dataset = seed(deps)
    with TestClient(app) as client:
        response = client.post(
            "/api/agent-platform/evaluations",
            json=submission(dataset, mode, repetitions),
            headers={"X-Agent-Platform-Token": "test-private-token"},
        )
        assert response.status_code == 202, response.text
        task = response.json()["data"]
        assert dispatcher.ids == task["run_ids"]
        assert task["id"] == task["run_ids"][0]
        for run_id in dispatcher.ids:
            before = deps.repository.get_run(run_id)
            assert before.api_key is None and before.manifest.target.credential_ref
            assert "test-private-token" not in before.model_dump_json()
            assert _execute(deps.repository, run_id) == "completed"
            report = client.get("/api/runs/" + run_id).json()["data"]
            assert report["run"]["status"] == "completed", report
            stored = deps.repository.get_run(run_id)
            assert stored.manifest.target.ref.external_version_id == "2.0"
            assert report["results"], report
            assert all(result["outcome"] == "pass" for result in report["results"])
            assert "test-private-token" not in json.dumps(report)
        assert peer.state.instances == {}
        creations = [e for e in peer.state.events if e["operation"] == "create"]
        assert len(creations) == repetitions
        assert all(
            e["agentId"] == "agent-" + mode and e["agentVersion"] == "2.0" for e in creations
        )
        assert all(
            e["branchId"] == ("branch-review" if mode == "claw" else None) for e in creations
        )
        assert len([e for e in peer.state.events if e["operation"] == "chat"]) == 2 * repetitions
        assert len([e for e in peer.state.events if e["operation"] == "delete"]) == repetitions
        if mode != "claw":
            assert len([e for e in peer.state.events if e["operation"] == "init"]) == repetitions
    assert b"test-private-token" not in path.read_bytes()


def test_invalid_selection_and_dispatch_failure_preserve_truth(mock_peer, monkeypatch, tmp_path):
    origin, _ = mock_peer
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", origin)
    dispatcher = RecordingDispatcher(fail=True)
    app = create_app(tmp_path / "tasks.db", dispatcher, ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    dataset = seed(deps)
    with TestClient(app) as client:
        body = submission(dataset, "claw")
        body["target"]["branch_id"] = "missing"
        assert (
            client.post(
                "/api/agent-platform/evaluations",
                json=body,
                headers={"X-Agent-Platform-Token": "t"},
            ).status_code
            == 404
        )
        assert not dispatcher.ids and not deps.repository.list_evaluation_tasks()
        response = client.post(
            "/api/agent-platform/evaluations",
            json=submission(dataset, "base"),
            headers={"X-Agent-Platform-Token": "t"},
        )
        assert response.status_code == 202
        assert deps.repository.get_run(dispatcher.ids[0]).status == "failed"
        assert deps.repository.get_evaluation_task(response.json()["data"]["id"])


def test_reservation_uses_existing_scheduler(mock_peer, monkeypatch, tmp_path):
    origin, _ = mock_peer
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", origin)
    dispatcher = RecordingDispatcher()
    app = create_app(tmp_path / "tasks.db", dispatcher, ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    dataset = seed(deps)
    future = datetime.now(UTC) + timedelta(minutes=5)
    with TestClient(app) as client:
        body = submission(dataset, "workflow")
        body["scheduled_for"] = future.isoformat()
        response = client.post(
            "/api/agent-platform/evaluations",
            json=body,
            headers={"X-Agent-Platform-Token": "scheduled-token"},
        )
        assert response.status_code == 202, response.text
        assert dispatcher.ids == []
        run_id = response.json()["data"]["run_ids"][0]
        assert deps.repository.get_run(run_id).status == "scheduled"
        assert not RunScheduling(deps.repository).dispatch_due_runs(dispatcher)
        assert (
            len(
                RunScheduling(deps.repository).dispatch_due_runs(
                    dispatcher, now=future + timedelta(seconds=1)
                )
            )
            == 1
        )
        assert dispatcher.ids == [run_id]


def test_wrong_group_team_and_branch_are_rejected(mock_peer):
    origin, _ = mock_peer
    client = PlatformClient(origin)
    for target, error in [
        ({"team_id": "team-empty"}, LookupError),
        ({"team_id": "missing"}, PermissionError),
        ({"type_group": "abcclaw"}, ValueError),
        ({"agent_version": "missing"}, LookupError),
    ]:
        selection = {
            "team_id": "team-local",
            "agent_id": "agent-workflow",
            "type_group": "base/workflow",
            "agent_version": "1.0",
            "branch_id": None,
            **target,
        }
        with pytest.raises(error):
            resolve_platform_target(client, "token", **selection)


@pytest.mark.parametrize("failure", ["chat", "credential"])
def test_execution_failure_is_persisted_and_instance_is_cleaned(
    failure, mock_peer, monkeypatch, tmp_path
):
    import base64

    from agentgate.run.target_protocol import TargetExecutionError

    origin, peer = mock_peer
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", origin)
    monkeypatch.setenv(
        "AGENTGATE_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode()
    )
    dispatcher = RecordingDispatcher()
    app = create_app(tmp_path / "fail.db", dispatcher, ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    dataset = deps.datasets.create_dataset("失败验收")
    deps.datasets.create_draft(dataset.id)
    deps.datasets.save_case(
        dataset.id, Case(name="失败样本", turns=(CaseTurn(input={"txt": "模拟失败"}),))
    )
    deps.datasets.publish_draft(dataset.id)
    with TestClient(app) as client:
        response = client.post(
            "/api/agent-platform/evaluations",
            json=submission(dataset.id, "workflow"),
            headers={"X-Agent-Platform-Token": "failure-secret"},
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["data"]["run_ids"][0]
        if failure == "credential":
            deps.api_keys.delete_api_key(
                deps.repository.get_run(run_id).manifest.target.credential_ref
            )
            assert _execute(deps.repository, run_id) == "failed"
        else:
            with pytest.raises(TargetExecutionError):
                _execute(deps.repository, run_id)
            assert [e["operation"] for e in peer.state.events][-1] == "delete"
        run = deps.repository.get_run(run_id)
        assert run.status == "failed" and "failure-secret" not in run.model_dump_json()
        assert not peer.state.instances


def test_initial_state_rejected_without_leaving_credentials_or_tasks(
    mock_peer, monkeypatch, tmp_path
):
    origin, _ = mock_peer
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock")
    monkeypatch.setenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", origin)
    app = create_app(tmp_path / "invalid.db", RecordingDispatcher(), ApiKeyEncryptor(b"k" * 32))
    deps = app.state.dependencies
    dataset = deps.datasets.create_dataset("不支持的状态")
    deps.datasets.create_draft(dataset.id)
    deps.datasets.save_case(
        dataset.id,
        Case(
            name="状态",
            initial_state={"account": "unhandled"},
            turns=(CaseTurn(input={"txt": "hello"}),),
        ),
    )
    deps.datasets.publish_draft(dataset.id)
    with TestClient(app) as client:
        response = client.post(
            "/api/agent-platform/evaluations",
            json=submission(dataset.id, "base"),
            headers={"X-Agent-Platform-Token": "invalid-secret"},
        )
        assert response.status_code == 422
        assert not deps.repository.list_evaluation_tasks()
        assert not deps.api_keys.list_api_keys()
