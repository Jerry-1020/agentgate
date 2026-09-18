from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from agentgate.integrations.job_dispatchers.bjs_job_dispatcher import (
    BjsJobDispatcher,
)


class Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()
        self.request = None
        self.timeout = None

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class RawResponse(Response):
    def __init__(self, body: bytes) -> None:
        self._body = body


def test_submit_posts_run_and_job_ids_to_bjs() -> None:
    calls: list[tuple[object, float]] = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return Response({"code": "0", "message": "success", "data": ""})

    dispatcher = BjsJobDispatcher(
        "http://bjs.example/web/eval/job/bjs/submit",
        "ai11",
        opener=opener,
    )

    dispatcher.submit("run/123")

    request, timeout = calls[0]
    assert request.method == "POST"
    assert request.full_url == (
        "http://bjs.example/web/eval/job/bjs/submit?taskId=run%2F123&jobId=ai11"
    )
    assert timeout == 10


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"code": "0", "message": "failure", "data": ""}, "BJS submission rejected"),
        ({"code": "1", "message": "submission failed", "data": ""}, "BJS submission rejected"),
        ([{"code": "0"}], "invalid response"),
        ({"code": "0"}, "BJS submission rejected"),
    ],
)
def test_submit_rejects_unsuccessful_bjs_responses(payload, message: str) -> None:
    dispatcher = BjsJobDispatcher(
        "https://bjs.example/web/eval/job/bjs/submit",
        "ai11",
        opener=lambda *_args, **_kwargs: Response(payload),
    )

    with pytest.raises(RuntimeError, match=message):
        dispatcher.submit("run-123")


def test_submit_rejects_invalid_json() -> None:
    dispatcher = BjsJobDispatcher(
        "https://bjs.example/web/eval/job/bjs/submit",
        "ai11",
        opener=lambda *_args, **_kwargs: RawResponse(b"not-json"),
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        dispatcher.submit("run-123")


def test_submit_rejects_http_errors() -> None:
    def opener(*_args, **_kwargs):
        raise HTTPError("https://bjs.example", 503, "unavailable", {}, None)

    dispatcher = BjsJobDispatcher(
        "https://bjs.example/web/eval/job/bjs/submit", "ai11", opener=opener
    )

    with pytest.raises(RuntimeError, match="HTTP error: 503"):
        dispatcher.submit("run-123")


def test_submit_rejects_invalid_configuration_and_run_id() -> None:
    with pytest.raises(ValueError, match="AGENTGATE_BJS_SUBMIT_URL"):
        BjsJobDispatcher("bjs.example", "ai11").submit("run-123")
    with pytest.raises(ValueError, match="AGENTGATE_BJS_JOB_ID"):
        BjsJobDispatcher(
            "https://bjs.example/web/eval/job/bjs/submit", " "
        ).submit("run-123")
    with pytest.raises(ValueError, match="run_id must not be blank"):
        BjsJobDispatcher(
            "https://bjs.example/web/eval/job/bjs/submit", "ai11"
        ).submit(" ")


def test_cancel_only_logs_because_bjs_has_no_cancel_endpoint(caplog) -> None:
    dispatcher = BjsJobDispatcher()

    with caplog.at_level("INFO"):
        dispatcher.cancel("run-123")

    assert "cancellation is unsupported" in caplog.text
    with pytest.raises(ValueError, match="run_id must not be blank"):
        dispatcher.cancel(" ")
