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


@pytest.mark.parametrize('failed', [False, True])
def test_mock_reports_explicit_simulation_and_preserves_failure(tmp_path,monkeypatch,failed):
    import json
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'tested-agents/src'))
    import bank_agents.reporting as reporting
    from agentgate.integrations.observability.trace_ingestion import persist_bundle
    monkeypatch.setenv('TRACE_REPORT_URL','http://127.0.0.1:8210')
    monkeypatch.setenv('MOCK_TRACE_SPOOL_DIR',str(tmp_path/'sender'))
    def upload(events,*,simulated):
        assert simulated
        return persist_bundle(tmp_path/'receiver',{'protocol':'agentgate.trace-bundle.v1','provenance':'simulated','events':events})
    monkeypatch.setattr(reporting,'report_events',upload)
    with TestClient(load_peer()) as client:
        created=client.post('/web/agent_endpoint/createAgent?taskId=test',json={'agentId':'agent-workflow','agentVersion':'2.0'}).json()
        name=created['data']['data']['agentName']
        session=client.post(f'/agent-api/{name}/chatabc/init_session',json={}).json()['data']['data']['session_id']
        response=client.post(f'/agent-api/{name}/chatabc/chat',json={'data':{'session_id':session,'txt':'模拟失败' if failed else 'hello'}})
        assert response.status_code==200 and 'event: trace' in response.text
        assert ('event: failed' in response.text)==failed
    traces=list((tmp_path/'receiver').rglob('*.jsonl'));assert len(traces)==1
    events=list(map(json.loads,traces[0].read_text().splitlines()))
    root=next(e for e in events if e['event_type']=='trace')
    assert root['status']==('error' if failed else 'success')
    assert root['tags']==['simulated','protocol-echo-only']
    assert len(list((tmp_path/'sender').glob('*.jsonl')))==1
