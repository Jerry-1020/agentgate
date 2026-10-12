"""Authenticated complete-SDK-bundle ingestion for the bundled Trace Server."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

MAX_BYTES = 10 * 1024 * 1024
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
PROJECTS = {"bank-tested-agents": "sdk", "agent-platform-mock": "simulated"}


def validate_bundle(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "provenance", "events"}
        or value["protocol"] != "agentgate.trace-bundle.v1"
    ):
        raise ValueError("invalid bundle protocol")
    events = value["events"]
    if (
        not isinstance(events, list)
        or not 1 <= len(events) <= 10000
        or any(not isinstance(e, dict) for e in events)
    ):
        raise ValueError("invalid event list")
    roots = [e for e in events if e.get("event_type") == "trace"]
    if len(roots) != 1:
        raise ValueError("exactly one completed trace required")
    root = roots[0]
    project, session, trace = (root.get(k) for k in ("project_id", "session_id", "trace_id"))
    if any(not isinstance(v, str) or not SEGMENT.fullmatch(v) for v in (project, session, trace)):
        raise ValueError("invalid identity")
    if PROJECTS.get(project) != value["provenance"]:
        raise ValueError("invalid provenance/project")
    if root.get("status") not in ("success", "error"):
        raise ValueError("trace not complete")
    identities = set()
    spans = {e.get("span_id") for e in events if e.get("event_type") == "span"}
    for event in events:
        kind, identity = event.get("event_type"), event.get("event_id")
        if kind not in ("trace", "span", "observation", "session", "llm_request"):
            raise ValueError("unsupported event")
        if (
            not isinstance(identity, str)
            or not SEGMENT.fullmatch(identity)
            or (kind, identity) in identities
        ):
            raise ValueError("invalid or duplicate event id")
        identities.add((kind, identity))
        if (
            event.get("project_id") != project
            or event.get("trace_id") != trace
            or event.get("session_id") not in (None, session)
        ):
            raise ValueError("event correlation mismatch")
        if kind == "span" and event.get("id") != event.get("span_id"):
            raise ValueError("SDK span id mismatch")
        if kind == "llm_request" and event.get("span_id") not in spans:
            raise ValueError("orphan model request")
        if value["provenance"] == "simulated" and (
            kind == "llm_request" or event.get("span_type") == "llm"
        ):
            raise ValueError("simulated peer cannot claim real model evidence")
    if len(spans) != sum(e.get("event_type") == "span" for e in events) or any(
        not isinstance(s, str) or not SEGMENT.fullmatch(s) for s in spans
    ):
        raise ValueError("duplicate or missing span id")
    for event in events:
        if event.get("event_type") == "span" and event.get("parent_span_id") not in (None, *spans):
            raise ValueError("orphan span")
    parents = {e["span_id"]: e.get("parent_span_id") for e in events if e["event_type"] == "span"}
    checked = set()
    for identity in parents:
        seen = set()
        current = identity
        while current is not None and current not in checked:
            if current in seen:
                raise ValueError("cyclic spans")
            seen.add(current)
            current = parents[current]
        checked.update(seen)
    if root.get("span_count") is not None and root["span_count"] != len(spans):
        raise ValueError("incomplete span collection")
    return project, session, trace


def persist_bundle(directory: Path, value):
    project, _session, trace = validate_bundle(value)
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    target = directory / trace
    receipt = {
        "trace_id": trace,
        "project_id": project,
        "sha256": digest,
        "event_count": len(value["events"]),
    }
    if target.exists():
        if json.loads((target / "receipt.json").read_text()) != receipt:
            raise HTTPException(409, "trace identity already contains different evidence")
        return {**receipt, "duplicate": True}
    # Stage outside the query directory; publish the complete trace and attachments atomically.
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="trace-upload-", dir=directory.parent))
    try:
        lines = []
        for event in value["events"]:
            line = json.dumps(event, ensure_ascii=False, allow_nan=False)
            if event["event_type"] == "llm_request":
                path = stage / trace / "spn" / f"{event['event_id']}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(line, encoding="utf-8")
            else:
                lines.append(line)
        (stage / f"{trace}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (stage / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {**receipt, "duplicate": False}


def install_ingestion(app, directory: Path, token: str):
    if len(token) < 32:
        raise ValueError("Trace Server requires a token of at least 32 characters")
    lock = Lock()

    @app.middleware("http")
    async def authentication(request: Request, call_next):
        if request.url.path != "/health" and not secrets.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + token
        ):
            return JSONResponse({"detail": "Trace Server authentication required"}, status_code=401)
        matched = re.fullmatch(r"/api/v1/projects/([^/]+)/traces/([^/]+)(?:/.*)?", request.url.path)
        if matched:
            project, trace = matched.groups()
            if not SEGMENT.fullmatch(trace):
                return JSONResponse({"detail": "trace not found"}, status_code=404)
            receipt_file = directory / trace / "receipt.json"
            if (
                not receipt_file.is_file()
                or json.loads(receipt_file.read_text())["project_id"] != project
            ):
                return JSONResponse({"detail": "trace not found"}, status_code=404)
        return await call_next(request)

    @app.post("/api/v1/ingest")
    async def ingest(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "trace bundle exceeds limit")
        try:
            value = json.loads(data)
            with lock:
                receipt = persist_bundle(directory, value)
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(422, "invalid trace bundle") from None
        return receipt
