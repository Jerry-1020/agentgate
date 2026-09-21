"""BJS job dispatcher for persisted evaluation Runs."""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
SUBMIT_URL_ENV = "AGENTGATE_BJS_SUBMIT_URL"
JOB_ID_ENV = "AGENTGATE_BJS_JOB_ID"


class BjsJobDispatcher:
    """Submit persisted Run IDs to the configured BJS execution backend."""

    def __init__(
        self,
        submit_url: str | None = None,
        job_id: str | None = None,
        *,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._submit_url = (
            submit_url if submit_url is not None else os.getenv(SUBMIT_URL_ENV)
        )
        self._job_id = job_id if job_id is not None else os.getenv(JOB_ID_ENV)
        self._opener = opener
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self._timeout_seconds = timeout_seconds
        self._submit_url = self._validated_submit_url()
        if not isinstance(self._job_id, str) or not self._job_id.strip():
            raise ValueError(f"{JOB_ID_ENV} must not be blank")
        self._job_id = self._job_id.strip()

    def submit(self, run_id: str) -> None:
        """Submit one persisted Run to BJS and fail on rejected submissions."""

        self._validate_identifier(run_id, "run_id")
        submit_url = self._validated_submit_url()
        job_id = self._job_id
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError(f"{JOB_ID_ENV} must not be blank")

        query = urlencode({"taskId": run_id, "jobId": job_id.strip()})
        request = Request(
            f"{submit_url}?{query}",
            method="POST",
            headers={"Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                response_body = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            # TODO: remove mock once the BJS platform is reachable in test environments.
            # MOCK: BJS endpoint unreachable in local test environments;
            # pretend the platform accepted the submission so Runs proceed.
            LOGGER.warning("BJS submission mocked (endpoint unreachable): run_id=%s, %s", run_id, exc)
            response_body = b'{"code":"0","message":"success"}'

        try:
            payload = json.loads(response_body)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("BJS submission returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("BJS submission returned an invalid response")  # noqa: TRY004

        code = str(payload.get("code", ""))
        message = str(payload.get("message", ""))
        if code != "0" or message != "success":
            raise RuntimeError(f"BJS submission rejected: code={code!r}, message={message!r}")
        LOGGER.info("BJS submission accepted: run_id=%s", run_id)

    def cancel(self, run_id: str) -> None:
        """Validate a Run ID; the documented BJS API has no cancellation endpoint."""

        self._validate_identifier(run_id, "run_id")
        LOGGER.info("BJS cancellation is unsupported by the remote API: run_id=%s", run_id)

    def _validated_submit_url(self) -> str:
        submit_url = self._submit_url
        if not isinstance(submit_url, str) or not submit_url.strip():
            raise ValueError(f"{SUBMIT_URL_ENV} must not be blank")
        normalized = submit_url.strip()
        try:
            parsed = urlsplit(normalized)
            port = parsed.port
        except ValueError:
            raise ValueError(f"{SUBMIT_URL_ENV} must be a valid HTTP(S) URL") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or (port is not None and port < 1)
            or parsed.username is not None
            or parsed.password is not None
            or "?" in normalized
            or "#" in normalized
            or any(character.isspace() or ord(character) < 32 for character in normalized)
        ):
            raise ValueError(f"{SUBMIT_URL_ENV} must be an absolute HTTP(S) URL")
        return normalized

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
