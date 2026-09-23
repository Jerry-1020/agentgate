"""Platform submission HTTP contract; no remote service or task persistence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.server.routes.agent_platform import router
from agentgate.server.user_context import UserInfo, get_user_info, reset_user_info, set_user_info

PATH = "/api/agent-platform/evaluations"
SECRET = "secret-for-test-only"
HEADERS = {"X-Agent-Platform-Token": SECRET}


def payload():
    return {
        "target": {
            "team_id": "external-team",
            "agent_id": "agent/raw",
            "type_group": "base/workflow",
            "agent_version": "v1",
            "arrange_type": "workflow",
        },
        "dataset_id": "dataset",
        "dataset_version": 2,
        "evaluator_ids": ["judge"],
        "max_parallel_cases": 2,
        "timeout_seconds": 300,
        "max_retries": 0,
        "repetitions": 1,
    }


def created(**kwargs):
    count = kwargs["repetitions"]
    return EvaluationTask(
        id="task",
        kind="single" if count == 1 else "stability",
        run_ids=tuple(f"run-{i}" for i in range(count)),
        credential_id="internal-secret-reference",
    )


def client_for(submitter=created, *, context=True):
    app = FastAPI()
    app.state.submit_agent_platform_evaluation = submitter
    if context:

        @app.middleware("http")
        async def caller_context(request, call_next):
            token = set_user_info(
                UserInfo(
                    request.headers.get("user_team_id", "gate-team"),
                    request.headers.get("user_id", "user"),
                    "User",
                )
            )
            try:
                return await call_next(request)
            finally:
                reset_user_info(token)

    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("claw,count", [(False, 1), (True, 1), (True, 3), (False, 20)])
def test_exact_submission_and_safe_response(claw, count):
    calls = []

    def submit(**kwargs):
        calls.append(kwargs)
        assert get_user_info().user_team_id == "gate-team"
        return created(**kwargs)

    body = payload()
    body["repetitions"] = count
    body["case_ids"] = ["case-2", "case-1"]
    if claw:
        body["target"].pop("arrange_type")
        body["target"].update(type_group="abcclaw", branch_id="branch/raw")
    with client_for(submit) as client:
        response = client.post(PATH, json=body, headers=HEADERS)
        assert set(client.app.state._state) == {"submit_agent_platform_evaluation"}
    assert response.status_code == 202
    assert response.json() == {
        "id": "task",
        "kind": "stability" if count > 1 else "single",
        "run_ids": [f"run-{i}" for i in range(count)],
    }
    assert calls == [
        {
            **body["target"],
            "arrange_type": None if claw else "workflow",
            "branch_id": "branch/raw" if claw else None,
            **{k: v for k, v in body.items() if k != "target"},
            "case_ids": ("case-2", "case-1"),
            "evaluator_ids": ("judge",),
            "scheduled_for": None,
            "token": SECRET,
            "user_team_id": "gate-team",
            "user_id": "user",
            "user_name": "User",
        }
    ]
    assert SECRET not in response.text
    assert "credential" not in response.text
    assert get_user_info() is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_id", " "),
        ("dataset_id", 1),
        ("dataset_version", 0),
        ("dataset_version", True),
        ("dataset_version", "2"),
        ("evaluator_ids", []),
        ("evaluator_ids", ["a", "a"]),
        ("evaluator_ids", [" "]),
        ("evaluator_ids", [1]),
        ("case_ids", None),
        ("case_ids", []),
        ("case_ids", ["x", "x"]),
        ("case_ids", "x"),
        ("max_parallel_cases", 0),
        ("max_parallel_cases", 31),
        ("max_parallel_cases", 1.5),
        ("timeout_seconds", 0),
        ("timeout_seconds", 3601),
        ("timeout_seconds", "300"),
        ("max_retries", -1),
        ("max_retries", 6),
        ("repetitions", 0),
        ("repetitions", 21),
        ("repetitions", False),
        ("scheduled_for", None),
        ("scheduled_for", 1900000000),
        ("scheduled_for", "2999-01-01T00:00:00"),
        ("scheduled_for", "2020-01-01T00:00:00Z"),
        ("token", SECRET),
        ("scheduled_for", SECRET),
    ],
)
def test_invalid_fields_never_submit_or_echo(field, value):
    calls = []
    body = payload()
    body[field] = value
    with client_for(lambda **kwargs: calls.append(kwargs)) as client:
        response = client.post(PATH, json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid platform evaluation request"}
    assert not calls
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "target",
    [
        {"branch_id": None},
        {"branch_id": "branch"},
        {"type_group": "abcclaw"},
        {"type_group": "abcclaw", "branch_id": " "},
        {"type_group": "abcclaw", "branch_id": None},
        {"type_group": "workflow"},
        {"team_id": ""},
        {"agent_version": 1},
        {"agentName": SECRET},
    ],
)
def test_target_invariants(target):
    body = payload()
    body["target"].update(target)
    calls = []
    with client_for(lambda **kwargs: calls.append(kwargs)) as client:
        response = client.post(PATH, json=body, headers=HEADERS)
    assert response.status_code == 422
    assert not calls
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": f"Bearer {SECRET}"},
        {"Cookie": f"token={SECRET}"},
        {"X-Agent-Platform-Token": ""},
        {"X-Agent-Platform-Token": "x" * 513},
        {"X-Agent-Platform-Token": "Bearer-value"},
        {"X-Agent-Platform-Token": "a b"},
        {"X-Agent-Platform-Token": "a\t"},
        {"X-Agent-Platform-Token": "a\x00"},
        [("X-Agent-Platform-Token", SECRET), ("x-agent-platform-token", "second")],
    ],
)
def test_invalid_token_sources(headers):
    calls = []
    with client_for(lambda **kwargs: calls.append(kwargs)) as client:
        response = client.post(PATH + "?token=" + SECRET, json=payload(), headers=headers)
    assert response.status_code == 422
    assert not calls
    assert SECRET not in response.text


def test_max_token_exact_ids_defaults_and_utc_schedule():
    calls = []

    def submit(**kwargs):
        calls.append(kwargs)
        return created(**kwargs)

    body = payload()
    body["target"]["agent_id"] = " untrimmed-agent "
    future = datetime.now(UTC) + timedelta(days=1)
    body["scheduled_for"] = future.astimezone(timezone(timedelta(hours=8))).isoformat()
    with client_for(submit, context=False) as client:
        response = client.post(PATH, json=body, headers={"X-Agent-Platform-Token": "x" * 512})
    assert response.status_code == 202
    call = calls[0]
    assert call["agent_id"] == " untrimmed-agent "
    assert call["scheduled_for"] == future and call["scheduled_for"].tzinfo == UTC
    assert call["case_ids"] is None and call["token"] == "x" * 512
    assert (call["user_team_id"], call["user_id"], call["user_name"]) == (
        "",
        "anonymous",
        "匿名用户",
    )
    body["repetitions"] = 2
    with client_for(submit) as client:
        assert client.post(PATH, json=body, headers=HEADERS).status_code == 422
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body,media,status",
    [
        ('{"token":"' + SECRET, "application/json", 422),
        ('["' + SECRET + '"]', "application/json", 422),
        ("null", "application/json", 422),
        (SECRET, "text/plain", 415),
    ],
)
def test_body_errors_are_sanitized(body, media, status):
    with client_for(lambda **_: pytest.fail("must not submit")) as client:
        response = client.post(PATH, content=body, headers={**HEADERS, "Content-Type": media})
    assert response.status_code == status
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "error,status",
    [
        (PermissionError, 403),
        (LookupError, 404),
        (ValueError, 422),
        (TimeoutError, 503),
        (ConnectionError, 503),
        (RuntimeError, 500),
        (TypeError, 500),
    ],
)
def test_application_failures_are_safe_and_not_retried(error, status, caplog):
    calls = []

    def submit(**kwargs):
        calls.append(kwargs)
        raise error(SECRET)

    with client_for(submit) as client:
        response = client.post(PATH, json=payload(), headers=HEADERS)
    assert response.status_code == status and len(calls) == 1
    assert SECRET not in response.text + caplog.text
    if status >= 500:
        assert "uncertain" in response.text


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"id": "task", "kind": "single", "run_ids": ["run"]},
        EvaluationTask(id="task", kind="ab", run_ids=("a", "b")),
        EvaluationTask.model_construct(id="task", kind="single", run_ids=("x", "x")),
        EvaluationTask.model_construct(id="task", kind="single", run_ids=("",)),
        EvaluationTask.model_construct(id="", kind="single", run_ids=("x",)),
        EvaluationTask.model_construct(id="task", kind="single", run_ids=(1,)),
    ],
)
def test_invalid_creation_result_is_uncertain_not_input_rejection(result):
    with client_for(lambda **_: result) as client:
        response = client.post(PATH, json=payload(), headers=HEADERS)
    assert response.status_code == 500 and "uncertain" in response.text


def test_missing_dependency_and_untrusted_http_exception():
    with client_for(None) as client:
        assert client.post(PATH, json=payload(), headers=HEADERS).status_code == 503
        del client.app.state.submit_agent_platform_evaluation
        assert client.post(PATH, json=payload(), headers=HEADERS).status_code == 503

    def submit(**_):
        raise HTTPException(418, SECRET)

    with client_for(submit) as client:
        response = client.post(PATH, json=payload(), headers=HEADERS)
    assert response.status_code == 500 and SECRET not in response.text


def test_concurrent_requests_keep_caller_and_credentials_separate():
    barrier = Barrier(2)
    calls = []

    def submit(**kwargs):
        barrier.wait(timeout=5)
        assert get_user_info().user_id == kwargs["user_id"]
        calls.append(kwargs)
        return created(**kwargs)

    with client_for(submit) as client, ThreadPoolExecutor(max_workers=2) as pool:

        def send(index):
            body = deepcopy(payload())
            body["target"]["team_id"] = f"external-{index}"
            return client.post(
                PATH,
                json=body,
                headers={
                    "X-Agent-Platform-Token": f"secret-{index}",
                    "user_id": f"user-{index}",
                    "user_team_id": f"gate-{index}",
                },
            )

        responses = list(pool.map(send, range(2)))
    assert all(response.status_code == 202 for response in responses)
    assert {(c["token"], c["team_id"], c["user_team_id"], c["user_id"]) for c in calls} == {
        (f"secret-{i}", f"external-{i}", f"gate-{i}", f"user-{i}") for i in range(2)
    }


def test_existing_response_envelope_wraps_once(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "envelope.db"))
    from agentgate.server.app import ResponseEnvelopeMiddleware

    client = client_for()
    client.app.add_middleware(ResponseEnvelopeMiddleware)
    with client:
        response = client.post(PATH, json=payload(), headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {
        "code": "0",
        "message": "success",
        "data": {"id": "task", "kind": "single", "run_ids": ["run-0"]},
    }


@pytest.mark.parametrize(
    "field",
    [
        "target",
        "dataset_id",
        "dataset_version",
        "evaluator_ids",
        "max_parallel_cases",
        "timeout_seconds",
        "max_retries",
        "repetitions",
    ],
)
def test_required_fields_have_no_silent_defaults(field):
    body = payload()
    del body[field]
    with client_for(lambda **_: pytest.fail("must not submit")) as client:
        assert client.post(PATH, json=body, headers=HEADERS).status_code == 422


def test_valid_domain_task_with_wrong_requested_repeat_count_is_uncertain():
    body = payload()
    body["repetitions"] = 2
    result = EvaluationTask(id="task", kind="stability", run_ids=("one", "two", "three"))
    with client_for(lambda **_: result) as client:
        response = client.post(PATH, json=body, headers=HEADERS)
    assert response.status_code == 500
    assert "uncertain" in response.text
