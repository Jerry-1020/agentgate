"""Real HTTP fixtures for the local platform peer."""

import importlib.util
import socket
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest
import uvicorn
from fastapi.testclient import TestClient


def load_peer():
    path = Path(__file__).resolve().parents[1] / "scripts/agent-platform-mock/server.py"
    spec = importlib.util.spec_from_file_location("platform_mock_peer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_app()


@pytest.fixture
def mock_peer():
    app = load_peer()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = monotonic() + 5
        while not server.started:
            if monotonic() > deadline:
                raise RuntimeError("mock startup timeout")
            sleep(0.01)
        try:
            yield "http://127.0.0.1:" + str(sock.getsockname()[1]), app
        finally:
            server.should_exit = True
            thread.join(5)
            assert not thread.is_alive()


def test_directory_document_shapes_and_no_authentication():
    with TestClient(load_peer()) as client:
        for headers in ({}, {"Authorization": "Bearer anything"}):
            result = client.get("/web/ops/team/getTeamRole?page=1&limit=1", headers=headers).json()
            assert result["code"] == "0"
            assert result["data"]["pages"] == 2
            assert result["data"]["records"][0]["id"] != result["data"]["records"][0]["teamId"]
        agents = client.get("/web/agent/agents", params={"teamId": "team-local"}).json()
        assert "data" not in agents and len(agents["records"]) == 3
        assert (
            client.get("/web/agent/agents", params={"teamId": "team-empty"}).json()["records"] == []
        )
        assert (
            client.get(
                "/web/agent/getAgentVersionList", params={"agentId": "agent-workflow"}
            ).json()["data"][1]["agentVersion"]
            == "2.0"
        )
        tree = client.get("/web/abcclaw/v2/branchTree", params={"agentId": "agent-claw"}).json()[
            "data"
        ]
        assert tree[0]["children"][0]["branchId"] == "branch-review"
        versions = client.get(
            "/web/abcclaw/v2/listVersions",
            params={"agentId": "agent-claw", "branchId": "branch-review"},
        ).json()["data"]
        assert all(v["branchId"] == "branch-review" for v in versions)
        assert (
            client.get(
                "/web/abcclaw/v2/listVersions",
                params={"agentId": "agent-claw", "branchId": "missing"},
            ).status_code
            == 404
        )


def test_workflow_creation_never_accepts_branch_or_wrong_version():
    with TestClient(load_peer()) as client:
        for extra in ({"branchId": "branch-main"}, {"agentVersion": "missing"}):
            response = client.post(
                "/web/agent_endpoint/createAgent?taskId=run",
                json={"agentId": "agent-workflow", "agentVersion": "1.0", **extra},
            )
            assert response.status_code in (404, 422)
        response = client.post(
            "/web/agent_endpoint/createAgent?taskId=run",
            json={"agentId": "agent-workflow", "agentVersion": "1.0"},
        )
        name = response.json()["data"]["data"]["agentName"]
        assert (
            client.get("/agent-api/" + name + "/chatabc/health_check").json()["data"]["data"][
                "status"
            ]
            == "ok"
        )
        client.get("/web/agent_endpoint/deleteAgent", params={"agentName": name})
        assert client.get("/mock/evidence").json()["active_instances"] == 0
