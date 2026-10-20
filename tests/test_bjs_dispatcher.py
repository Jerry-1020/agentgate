from __future__ import annotations

import json
from io import BytesIO
from socket import gaierror
from typing import Self
from urllib.error import HTTPError, URLError

import pytest

from agentgate.integrations.job_dispatchers.bjs_job_dispatcher import (
    BjsJobDispatcher,
)


class Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()
        self.request = None
        self.timeout = None

    def __enter__(self) -> Self:
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

    with pytest.raises(RuntimeError, match="acceptance is unconfirmed"):
        dispatcher.submit("run-123")


def test_submit_logs_request_context_before_sending(caplog) -> None:
    logs_before_request = []

    def opener(request, *, timeout):
        logs_before_request.extend(record.getMessage() for record in caplog.records)
        assert request.method == "POST"
        assert request.full_url == (
            "https://bjs.example/submit?taskId=run-123&jobId=ai28"
        )
        assert timeout == 15
        return Response({"code": "0", "message": "success", "data": ""})

    dispatcher = BjsJobDispatcher(
        "https://bjs.example/submit", " ai28 ", opener=opener, timeout_seconds=15
    )
    with caplog.at_level("INFO"):
        dispatcher.submit("run-123")

    started = next(log for log in logs_before_request if "BJS submission started" in log)
    assert "run_id=run-123" in started
    assert "job_id=ai28" in started
    assert "method=POST" in started
    assert "endpoint=https://bjs.example/submit" in started
    assert "timeout_seconds=15" in started
    assert "BJS submission accepted: run_id=run-123" in caplog.text


@pytest.mark.parametrize(
    "status, reason",
    [
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (404, "Not Found"),
        (405, "Method Not Allowed"),
        (500, "Internal Server Error"),
        (502, "Bad Gateway"),
        (503, "Service Unavailable"),
        (599, "Unknown HTTP status"),
    ],
)
def test_http_failure_logs_status_without_remote_secrets(caplog, status, reason) -> None:
    body = BytesIO(b'{"message":"private-body-secret"}')
    error = HTTPError(
        "https://redirect.example/private-url-secret",
        status,
        "private-reason-secret\nforged-log",
        {"Set-Cookie": "private-cookie-secret"},
        body,
    )
    calls = []

    def opener(*args, **kwargs):
        calls.append(args)
        raise error

    dispatcher = BjsJobDispatcher("https://bjs.example/submit", "ai28", opener=opener)
    with caplog.at_level("INFO"), pytest.raises(RuntimeError) as caught:
        dispatcher.submit("run-123")

    assert str(caught.value) == "BJS submission transport failed; acceptance is unconfirmed"
    assert caught.value.__suppress_context__
    assert len(calls) == 1
    assert body.tell() == 0
    assert f"http_status={status}" in caplog.text
    assert f"reason={reason}" in caplog.text
    assert "error_type=HTTPError" in caplog.text
    assert "run_id=run-123" in caplog.text
    assert "job_id=ai28" in caplog.text
    assert "endpoint=https://bjs.example/submit" in caplog.text
    assert "private-" not in caplog.text
    assert "forged-log" not in caplog.text
    assert "BJS submission accepted" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize(
    "error, error_type, reason_type",
    [
        (URLError("private-token"), "URLError", "str"),
        (URLError(gaierror(-2, "private-token")), "URLError", "gaierror"),
        (TimeoutError("private-token"), "TimeoutError", "TimeoutError"),
        (OSError("private-token"), "OSError", "OSError"),
    ],
    ids=["url-error", "dns-error", "timeout", "os-error"],
)
def test_transport_failure_logs_safe_context(caplog, error, error_type, reason_type) -> None:
    def opener(*args, **kwargs):
        raise error

    dispatcher = BjsJobDispatcher("https://bjs.example/submit", "ai28", opener=opener)
    with caplog.at_level("INFO"), pytest.raises(RuntimeError) as caught:
        dispatcher.submit("run-123")

    assert str(caught.value) == "BJS submission transport failed; acceptance is unconfirmed"
    assert caught.value.__suppress_context__
    assert "BJS submission transport failed" in caplog.text
    assert f"error_type={error_type}" in caplog.text
    assert f"reason_type={reason_type}" in caplog.text
    assert "job_id=ai28" in caplog.text
    assert "endpoint=https://bjs.example/submit" in caplog.text
    assert "http_status=" not in caplog.text
    assert "private-token" not in caplog.text
    assert "BJS submission accepted" not in caplog.text


def test_submit_rejects_invalid_configuration_and_run_id() -> None:
    with pytest.raises(ValueError, match="AGENTGATE_BJS_SUBMIT_URL"):
        BjsJobDispatcher("bjs.example", "ai11").submit("run-123")
    with pytest.raises(ValueError, match="AGENTGATE_BJS_JOB_ID"):
        BjsJobDispatcher("https://bjs.example/web/eval/job/bjs/submit", " ").submit("run-123")
    with pytest.raises(ValueError, match="run_id must not be blank"):
        BjsJobDispatcher("https://bjs.example/web/eval/job/bjs/submit", "ai11").submit(" ")


def test_cancel_only_logs_because_bjs_has_no_cancel_endpoint(caplog) -> None:
    dispatcher = BjsJobDispatcher("https://bjs.example/submit", "ai11")

    with caplog.at_level("INFO"):
        dispatcher.cancel("run-123")

    assert "cancellation is unsupported" in caplog.text
    with pytest.raises(ValueError, match="run_id must not be blank"):
        dispatcher.cancel(" ")


@pytest.mark.parametrize("error", [URLError("private-token"), TimeoutError("private-token"),
    OSError("private-token"), HTTPError("https://bjs.example/submit", 503, "private-token", None, None)])
def test_submit_reports_network_failure_without_retry(error):
    calls = []

    def opener(*args, **kwargs):
        calls.append(args)
        raise error

    dispatcher = BjsJobDispatcher("https://bjs.example/submit", "ai11", opener=opener)

    with pytest.raises(RuntimeError, match="acceptance is unconfirmed") as caught:
        dispatcher.submit("run-123")
    assert "private-token" not in str(caught.value)
    assert calls
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://bjs.example/submit?existing=1",
        "https://bjs.example/submit#fragment",
        "https://bjs.example:invalid/submit",
        "https://bjs.example:0/submit",
        "https://user:secret@bjs.example/submit",
        "https://bjs.exa mple/submit",
        "https://bjs.example/\nsubmit",
    ],
)
def test_invalid_submit_url_fails_at_configuration_time(url):
    with pytest.raises(ValueError, match="AGENTGATE_BJS_SUBMIT_URL") as error:
        BjsJobDispatcher(url, "ai11")
    assert url not in str(error.value)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        BjsJobDispatcher("https://bjs.example/submit", "ai11", timeout_seconds=timeout)


def test_environment_configuration_is_used(monkeypatch):
    monkeypatch.setenv("AGENTGATE_BJS_SUBMIT_URL", "https://bjs.example/submit/")
    monkeypatch.setenv("AGENTGATE_BJS_JOB_ID", " job+1 ")
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        return Response({"code": 0, "message": "success"})

    BjsJobDispatcher(opener=opener).submit("run & 1")
    assert calls == ["https://bjs.example/submit/?taskId=run+%26+1&jobId=job%2B1"]
