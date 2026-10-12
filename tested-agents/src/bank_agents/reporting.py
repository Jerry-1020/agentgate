"""Upload completed SDK evidence; retries never repeat the business operation."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def report_events(events, *, simulated=False):
    url, token = os.environ.get("TRACE_REPORT_URL", ""), os.environ.get("TRACE_REPORT_TOKEN", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("TRACE_REPORT_URL must be an HTTP(S) origin")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Remote trace reporting requires HTTPS")
    if len(token) < 32:
        raise ValueError("TRACE_REPORT_TOKEN must contain at least 32 characters")
    bundle = {
        "protocol": "agentgate.trace-bundle.v1",
        "provenance": "simulated" if simulated else "sdk",
        "events": events,
    }
    raw = json.dumps(
        bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("trace bundle exceeds limit")
    digest = hashlib.sha256(raw).hexdigest()
    root = next(e for e in events if e["event_type"] == "trace")
    opener = build_opener(NoRedirect())
    for attempt in range(3):
        try:
            request = Request(
                url.rstrip("/") + "/api/v1/ingest",
                data=raw,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            with opener.open(request, timeout=10) as response:
                receipt = json.loads(response.read(4096))
            if (
                receipt.get("sha256") != digest
                or receipt.get("trace_id") != root["trace_id"]
                or receipt.get("project_id") != root["project_id"]
                or receipt.get("event_count") != len(events)
            ):
                raise RuntimeError("Trace Server acknowledgement mismatch")
            return receipt
        except HTTPError as exc:
            if exc.code < 500:
                raise RuntimeError(f"Trace Server rejected upload (HTTP {exc.code})") from None
        except (URLError, TimeoutError):
            pass
        if attempt < 2:
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(
        "Trace Server upload failed; local evidence retained, business request is not retried"
    )


def report_file(path: Path):
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for item in sorted((path.parent / path.stem / "spn").glob("*.json")):
        events.append(json.loads(item.read_text()))
    return report_events(events)
