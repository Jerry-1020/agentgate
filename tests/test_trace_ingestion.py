import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.integrations.observability.trace_ingestion import install_ingestion, persist_bundle


def bundle():
    common = {
        "project_id": "agent-platform-mock",
        "trace_id": "trace-1",
        "session_id": "session-1",
        "status": "success",
    }
    return {
        "protocol": "agentgate.trace-bundle.v1",
        "provenance": "simulated",
        "events": [
            dict(
                common,
                event_type="span",
                event_id="event-1",
                span_id="span-1",
                id="span-1",
                parent_span_id=None,
                name="mock.reply",
                span_type="chain",
            ),
            dict(
                common,
                event_type="trace",
                event_id="event-2",
                input={"txt": "hi"},
                output={"output": "echo hi"},
            ),
        ],
    }


def client(directory):
    app = FastAPI()
    install_ingestion(app, directory, "x" * 32)
    return TestClient(app)


def test_auth_atomic_publication_and_idempotent_restart(tmp_path):
    root = tmp_path / "received"
    value = bundle()
    with client(root) as c:
        assert c.post("/api/v1/ingest", json=value).status_code == 401
        assert not root.exists()
        c.headers["Authorization"] = "Bearer " + "x" * 32
        response = c.post("/api/v1/ingest", json=value)
        assert response.status_code == 200 and not response.json()["duplicate"]
        assert len(list(root.rglob("*.jsonl"))) == 1
    with client(root) as c:
        c.headers["Authorization"] = "Bearer " + "x" * 32
        assert c.post("/api/v1/ingest", json=value).json()["duplicate"]
        value["events"][-1]["output"] = {"output": "changed"}
        assert c.post("/api/v1/ingest", json=value).status_code == 409
    assert not list(tmp_path.glob("trace-upload-*"))


@pytest.mark.parametrize(
    "mutation",
    ["traversal", "project", "cross_trace", "duplicate", "parent", "fake_llm", "incomplete"],
)
def test_invalid_evidence_never_published(tmp_path, mutation):
    value = bundle()
    if mutation == "traversal":
        value["events"][-1]["session_id"] = "../escape"
    if mutation == "project":
        value["provenance"] = "sdk"
    if mutation == "cross_trace":
        value["events"][0]["trace_id"] = "other"
    if mutation == "duplicate":
        value["events"].append(value["events"][0])
    if mutation == "parent":
        value["events"][0]["parent_span_id"] = "missing"
    if mutation == "fake_llm":
        value["events"][0]["span_type"] = "llm"
    if mutation == "incomplete":
        value["events"][-1]["status"] = "running"
    with client(tmp_path / "received") as c:
        c.headers["Authorization"] = "Bearer " + "x" * 32
        assert c.post("/api/v1/ingest", json=value).status_code == 422
    assert not (tmp_path / "received").exists()


def test_complete_model_attachments_are_published_with_trace(tmp_path):
    value = bundle()
    value["provenance"] = "sdk"
    for event in value["events"]:
        event["project_id"] = "bank-tested-agents"
    value["events"].append(
        dict(
            value["events"][0],
            event_type="llm_request",
            event_id="event-1",
            request={"messages": []},
        )
    )
    result = persist_bundle(tmp_path / "received", value)
    assert result["event_count"] == 3
    assert len(list((tmp_path / "received").rglob("spn/event-1.json"))) == 1
    assert len(list((tmp_path / "received").rglob("*.jsonl"))) == 1


def test_oversized_and_malformed_requests(tmp_path):
    from agentgate.integrations.observability.trace_ingestion import MAX_BYTES

    with client(tmp_path / "received") as c:
        c.headers["Authorization"] = "Bearer " + "x" * 32
        assert c.post("/api/v1/ingest", content=b"x" * (MAX_BYTES + 1)).status_code == 413
        assert c.post("/api/v1/ingest", content=b"{").status_code == 422


def test_query_auth_and_project_scope(tmp_path):
    root = tmp_path / "received"
    value = bundle()
    app = FastAPI()
    install_ingestion(app, root, "x" * 32)

    @app.get("/api/v1/projects/{project}/traces/{trace}")
    def query(project, trace):
        return {"found": True}

    with TestClient(app) as c:
        assert c.get("/api/v1/projects/agent-platform-mock/traces/trace-1").status_code == 401
        c.headers["Authorization"] = "Bearer " + "x" * 32
        assert c.post("/api/v1/ingest", json=value).status_code == 200
        assert c.get("/api/v1/projects/agent-platform-mock/traces/trace-1").status_code == 200
        assert c.get("/api/v1/projects/bank-tested-agents/traces/trace-1").status_code == 404
        for event in value["events"]:
            event["project_id"] = "bank-tested-agents"
        value["provenance"] = "sdk"
        assert c.post("/api/v1/ingest", json=value).status_code == 409
