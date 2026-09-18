"""BJS job dispatcher for persisted evaluation Runs."""

from __future__ import annotations

import json
import logging
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
        self._timeout_seconds = timeout_seconds

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
        except HTTPError as exc:
            raise RuntimeError(f"BJS submission HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("BJS submission connection failed") from exc
        except TimeoutError as exc:
            raise RuntimeError("BJS submission timed out") from exc

        try:
            payload = json.loads(response_body)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("BJS submission returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("BJS submission returned an invalid response")

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
        normalized = submit_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{SUBMIT_URL_ENV} must be an absolute HTTP(S) URL")
        return normalized

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
