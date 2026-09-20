from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.domain import FrozenJsonObject
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.results import router


def test_trace_api_preserves_request_uuid_and_redacts_pii_without_changing_storage(tmp_path):
    dependencies = build_dependencies(tmp_path / "trace-api.db")
    run = dependencies.execute_demo_run("loan-agent-v2-fixed")
    case_id = run.manifest.execution_cases[0].id
    original = dependencies.repository.get_trace(run.id, case_id)
    request_id = "11843294-6268-4d2e-a97b-8666ab7e6076"
    attributes = dict(original.spans[0].attributes)
    attributes.update({
        "bank.request_id": request_id,
        "api_key": "test-secret",
        "message": "card 4111 1111 1111 1111",
    })
    canonical = original.model_copy(update={"spans": (
        original.spans[0].model_copy(update={"attributes": FrozenJsonObject(attributes)}),
        *original.spans[1:],
    )})
    dependencies.repository.save_trace(canonical)
    app = FastAPI()
    app.state.dependencies = dependencies
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run.id}/traces/{case_id}")
        repeated = client.get(f"/api/runs/{run.id}/traces/{case_id}")
    assert response.status_code == 200
    assert repeated.json() == response.json()
    protected = response.json()["spans"][0]["attributes"]
    assert protected["bank.request_id"] == request_id
    assert protected["api_key"] == "[redacted]"
    assert protected["message"] == "card [redacted]"
    assert dependencies.repository.get_trace(run.id, case_id) == canonical
