"""Exact platform directory selection and explicitly local simulated execution."""

from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from agentgate.domain import TargetDescriptor, TargetRef, Trace, TraceSpan, utcnow
from agentgate.integrations.targets.bank_protocol import (
    build_chatabc_payload,
    build_cloudshrimp_payload,
    parse_bank_sse,
)
from agentgate.run.target_protocol import (
    CaseExecutionResult,
    CaseExecutionStatus,
    TargetExecutionError,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PlatformClient:
    """One configured transport; credentials are always per-call arguments."""

    def __init__(self, origin: str):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("local platform execution requires a loopback HTTP origin")
        self.origin = origin.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @classmethod
    def from_environment(cls):
        if os.getenv("AGENTGATE_AGENT_PLATFORM_MODE") != "mock":
            raise ConnectionError("platform mock execution is not enabled")
        return cls(os.getenv("AGENTGATE_AGENT_PLATFORM_ORIGIN", "http://127.0.0.1:8119"))

    def call(self, path: str, token: str, *, query=None, payload=None, timeout=30, raw=False):
        url = self.origin + path + ("?" + urlencode(query) if query else "")
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read(10 * 1024 * 1024 + 1)
                if len(data) > 10 * 1024 * 1024:
                    raise ConnectionError("platform response exceeds limit")
                return data if raw else json.loads(data)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise PermissionError("platform access denied") from None
            if exc.code == 404:
                raise LookupError("platform resource unavailable") from None
            raise ConnectionError("platform HTTP request failed") from None
        except (URLError, TimeoutError, ValueError):
            raise ConnectionError("platform transport or response failed") from None

    def require_mock(self, token):
        value = self.call("/mock/capabilities", token)
        if value != {"mock": True, "protocol": "agentgate-platform-mock-v1"}:
            raise ConnectionError("not the configured simulated platform")

    def wrapped(self, path, token, **kwargs):
        value = self.call(path, token, **kwargs)
        if not isinstance(value, dict) or value.get("code") != "0" or "data" not in value:
            raise ConnectionError("invalid platform envelope")
        return value["data"]

    def pages(self, path, token, *, wrapped, parameters=None, limit=300):
        records, current, identity = [], 1, None
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("directory deadline exceeded")
            call = self.wrapped if wrapped else self.call
            page = call(
                path,
                token,
                query={**(parameters or {}), "page": current, "limit": limit},
                timeout=remaining,
            )
            if not isinstance(page, dict) or not isinstance(page.get("records"), list):
                raise ConnectionError("invalid directory page")
            total, size, pages = (page.get(key) for key in ("total", "size", "pages"))
            if (
                any(type(v) is not int for v in (total, size, pages, page.get("current")))
                or total < 0
                or size < 1
                or pages < 0
                or page["current"] != current
                or (total > 0 and pages != (total + size - 1) // size)
                or (total == 0 and pages not in (0, 1))
            ):
                raise ConnectionError("inconsistent directory pagination")
            if identity is not None and identity != (total, size, pages):
                raise ConnectionError("directory changed during pagination")
            identity = total, size, pages
            if any(not isinstance(row, dict) for row in page["records"]):
                raise ConnectionError("invalid directory records")
            records.extend(page["records"])
            if current >= pages:
                if len(records) != total:
                    raise ConnectionError("incomplete directory")
                return records
            if len(page["records"]) != size:
                raise ConnectionError("incomplete directory page")
            current += 1


def _one(records, key, value):
    matches = [row for row in records if isinstance(row, dict) and row.get(key) == value]
    if not matches:
        raise LookupError("selected platform identity is unavailable")
    if any(row != matches[0] for row in matches[1:]):
        raise ConnectionError("ambiguous platform identity")
    return matches[0]


def resolve_platform_target(
    client, token, *, team_id, agent_id, type_group, agent_version, branch_id
):
    client.require_mock(token)
    if team_id is not None:
        teams = client.pages("/web/ops/team/getTeamRole", token, wrapped=True)
        if not any(row.get("teamId") == team_id for row in teams):
            raise PermissionError("selected team is unavailable")
    agent_parameters = {"name": ""}
    if team_id is not None:
        agent_parameters["teamId"] = team_id
    agents = client.pages(
        "/web/agent/agents",
        token,
        wrapped=False,
        parameters=agent_parameters,
        limit=1000,
    )
    agent = _one(agents, "id", agent_id)
    groups = {
        "base": "base/workflow",
        "workflow": "base/workflow",
        "abcclaw": "abcclaw",
        "abcclaw2": "abcclaw",
    }
    # 与前端目录归一化一致：arrangeType 为权威分类，缺失时回退 agentType。
    authoritative = agent.get("arrangeType") or agent.get("agentType")
    if not authoritative or groups.get(authoritative) != type_group:
        raise ValueError("agent type does not match selection")
    if type_group == "base/workflow":
        if branch_id is not None:
            raise ValueError("base/workflow has no branch")
        mode = agent.get("arrangeType") or agent.get("agentType")
        versions = client.wrapped(
            "/web/agent/getAgentVersionList", token, query={"agentId": agent_id}
        )
    else:
        mode = "abcclaw"
        tree = client.wrapped("/web/abcclaw/v2/branchTree", token, query={"agentId": agent_id})

        def flatten(nodes):
            if not isinstance(nodes, list):
                raise ConnectionError("invalid branch tree")
            for node in nodes:
                if not isinstance(node, dict) or not isinstance(node.get("branchId"), str):
                    raise ConnectionError("invalid branch")
                yield node
                yield from flatten(node.get("children", []))

        branches = list(flatten(tree))
        if len({b["branchId"] for b in branches}) != len(branches):
            raise ConnectionError("ambiguous branch tree")
        _one(branches, "branchId", branch_id)
        versions = client.wrapped(
            "/web/abcclaw/v2/listVersions",
            token,
            query={"agentId": agent_id, "branchId": branch_id},
        )
    if not isinstance(versions, list):
        raise ConnectionError("invalid versions")
    selected = _one(versions, "agentVersion", agent_version)
    if type_group == "abcclaw" and selected.get("branchId") != branch_id:
        raise ConnectionError("version belongs to another branch")
    if not isinstance(agent.get("name"), str) or not agent["name"].strip():
        raise ConnectionError("missing agent name")
    identity = {
        "origin": client.origin,
        "team_id": team_id,
        "agent_id": agent_id,
        "branch_id": branch_id,
    }
    source = (
        "platform-mock-"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    )
    descriptor = TargetDescriptor(
        ref=TargetRef(
            source_id=source,
            target_type="agent",
            external_target_id=agent_id,
            external_version_id=agent_version,
        ),
        display_name=agent["name"],
        metadata={**identity, "type_group": type_group, "runtime_type": mode, "simulated": True},
        input_schema={
            "type": "object",
            "required": ["txt"],
            "properties": {"txt": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    return descriptor


class PlatformAdapter:
    """Synchronous per-case lifecycle; all observed outputs come from the peer."""

    adapter_type = "agent_platform_mock"
    adapter_version = "1"

    def __init__(self, client: PlatformClient, token: str):
        self.client, self.token = client, token
        self.results, self.statuses = {}, {}

    def start(self, request):
        handle = request.execution_id
        if handle in self.statuses:
            raise TargetExecutionError("invalid_request", "duplicate execution")
        self.statuses[handle] = CaseExecutionStatus.RUNNING
        try:
            self.results[handle] = self._execute(request)
            self.statuses[handle] = CaseExecutionStatus.COMPLETED
        except Exception:  # noqa: BLE001 -- Remote exception strings may contain credentials.
            self.statuses[handle] = CaseExecutionStatus.FAILED
            raise TargetExecutionError(
                "rejected",
                "platform execution failed; check peer availability and selected version",
            ) from None
        return handle

    def _execute(self, request):
        config = request.target.invocation_config
        if config["origin"] != self.client.origin:
            raise ValueError("worker origin differs from pinned origin")
        self.client.require_mock(self.token)
        deadline = time.monotonic() + request.timeout_seconds

        def remaining():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("case deadline reached")
            return remaining

        payload = {
            "agentId": request.target.ref.external_target_id,
            "agentVersion": request.target.ref.external_version_id,
        }
        claw = config["runtime_type"] == "abcclaw"
        if claw:
            payload["branchId"] = config["branch_id"]
        value = self.client.wrapped(
            "/mock/abcclaw/instances" if claw else "/web/agent_endpoint/createAgent",
            self.token,
            query={"taskId": request.run_id},
            payload=payload,
            timeout=remaining(),
        )
        if value.get("code") not in {"0", "0000"}:
            raise ConnectionError("instance creation rejected")
        name = value["data"]["agentName"]
        if not isinstance(name, str) or not name.strip():
            raise ConnectionError("missing instance identity")
        prefix = "/agent-api/" + quote(name, safe="")
        try:
            while (
                self.client.wrapped(
                    prefix + "/chatabc/health_check", self.token, timeout=remaining()
                )["data"].get("status")
                != "ok"
            ):
                time.sleep(min(0.2, remaining()))
            session = uuid4().hex
            if not claw:
                variables = (
                    "config_variables"
                    if config["runtime_type"] == "workflow"
                    else "prompt_variables"
                )
                value = self.client.wrapped(
                    prefix + "/chatabc/init_session",
                    self.token,
                    payload=build_chatabc_payload(
                        {variables: []},
                        request_id=uuid4().hex,
                        timestamp_ms=int(time.time() * 1000),
                    ),
                    timeout=remaining(),
                )
                session = value["data"]["session_id"]
                if not isinstance(session, str) or not session.strip():
                    raise ConnectionError("invalid session")
            trace_id = request.traceparent.split("-")[1]
            spans, outcomes = [], {}
            for index, turn in enumerate(request.case.turns):
                started = utcnow()
                text = turn.input["txt"]
                rid = uuid4().hex
                body = (
                    build_cloudshrimp_payload(
                        session_id=session,
                        customer_id="mock-customer",
                        text=text,
                        guardrail="ON_BLOCK",
                    )
                    if claw
                    else build_chatabc_payload(
                        {"session_id": session, "txt": text, "files": [], "stream": True},
                        request_id=rid,
                        timestamp_ms=int(time.time() * 1000),
                    )
                )
                raw = self.client.call(
                    prefix + ("/api/v1/message" if claw else "/chatabc/chat"),
                    self.token,
                    payload=body,
                    raw=True,
                    timeout=remaining(),
                )
                result = parse_bank_sse(
                    raw.decode().splitlines(),
                    protocol="cloudshrimp" if claw else config["runtime_type"],
                    wire_format="json_envelope" if claw else "event_lines",
                    request_id=rid,
                )
                output = {"output": result.output}
                outcomes[turn.id] = {"input": turn.input.to_dict(), "output": output, "state": {}}
                spans.append(
                    TraceSpan(
                        trace_id=trace_id,
                        span_id=uuid4().hex[:16],
                        name="platform.chat",
                        operation_type="turn",
                        sequence=index,
                        started_at=started,
                        ended_at=utcnow(),
                        status="ok",
                        attributes={
                            "agentgate.turn.id": turn.id,
                            "platform.simulated": True,
                            "platform.request_id": rid,
                        },
                    )
                )
            trace = Trace(
                trace_id=trace_id,
                run_id=request.run_id,
                case_id=request.case.id,
                spans=tuple(spans),
                turn_outcomes=outcomes,
                final_output=output,
                final_state={},
            )
            return CaseExecutionResult(request.execution_id, trace_id, trace)
        finally:
            # Cleanup has its own short budget even when the case deadline expired.
            self.client.wrapped(
                "/web/agent_endpoint/deleteAgent", self.token, query={"agentName": name}, timeout=5
            )

    def get_status(self, handle):
        if handle not in self.statuses:
            raise TargetExecutionError("invalid_request", "unknown execution")
        return self.statuses[handle]

    def wait(self, handle, timeout_seconds):
        if timeout_seconds <= 0 or self.get_status(handle) != CaseExecutionStatus.COMPLETED:
            raise TargetExecutionError("rejected", "execution incomplete")
        return self.results[handle]

    def cancel(self, handle):
        self.get_status(handle)


def resolve_platform_trace(request, result):
    if result.inline_trace is None:
        raise TargetExecutionError("protocol_error", "platform execution returned no trace")
    return result.inline_trace
