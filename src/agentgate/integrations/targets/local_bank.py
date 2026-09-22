"""HTTP execution of the separately hosted bank-tested-agents runtime.

This is not a generic bank production adapter. Evidence for each turn is
requested from the central Trace Server query plane (trace referenced by the
chat SSE ``trace`` event) and reconciled against the streamed answer before
mapping.
"""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import uuid4

from agentgate.domain import FrozenJsonObject, TargetDescriptor, TargetRef, TargetSnapshot
from agentgate.integrations.observability.trace_sdk import normalize_sdk_exports
from agentgate.integrations.observability.trace_server import TraceServerClient
from agentgate.integrations.targets.bank_protocol import build_chatabc_payload, build_cloudshrimp_payload, parse_bank_sse
from agentgate.run.target_protocol import CaseExecutionResult, CaseExecutionStatus, TargetExecutionError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class LocalBankClient:
    def __init__(self):
        self.base = os.getenv("AGENTGATE_BANK_BASE_URL", "http://127.0.0.1:8107").rstrip("/")
        parsed = urlparse(self.base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("local bank runtime requires a loopback HTTP origin")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, path, payload=None, *, timeout=30, request_id=None, raw=False):
        headers = {"Content-Type": "application/json"}
        if request_id:
            headers["X-Request-ID"] = request_id
        request = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read(10 * 1024 * 1024 + 1)
                if len(data) > 10 * 1024 * 1024:
                    raise TargetExecutionError("protocol_error", "bank response exceeds limit")
                return data if raw else json.loads(data)
        except HTTPError as exc:
            raise TargetExecutionError("unauthorized" if exc.code in (401, 403) else "rejected", f"local bank HTTP {exc.code}") from None
        except (URLError, TimeoutError):
            # Remote actions may already have happened. Never automatically retry.
            raise TargetExecutionError("rejected", "bank transport failed; inspect request evidence before retrying") from None


def local_bank_target(client, mode):
    if mode not in {"base", "workflow", "cloudshrimp"}:
        raise ValueError("unknown bank mode")
    record = next((r for r in client.call("/agents") if r["mode"] == mode), None)
    if not record or record["agent_version"] != "v1" or record.get("test_only") is not True:
        raise ValueError("unsupported local bank runtime descriptor")
    descriptor = TargetDescriptor(
        ref=TargetRef(source_id="local-bank-runtime", target_type="agent", external_target_id="loan-" + mode, external_version_id="v1"),
        display_name={"base": "贷款智能体 · 基础编排", "workflow": "贷款智能体 · 工作流", "cloudshrimp": "贷款智能体 · 云虾"}[mode],
        prompt=record["prompt"],
        tools=tuple({"name": t["function"]["name"], "description": t["function"]["description"],
                     "input_schema": t["function"]["parameters"]} for t in record["tools"]),
        skills=tuple({"external_skill_id": s["id"], "external_version_id": s["version"],
                      "name": s["name"], "description": s["description"],
                      "tools": tuple({"name": t} for t in s["tools"])} for s in record["skills"]),
        input_schema={"type": "object", "required": ["txt"], "properties": {"txt": {"type": "string"}}},
        metadata={"mode": mode, "model": record["model"], "policy_version": record["policy_version"],
                  "implementation_sha256": record["implementation_sha256"],
                  "summary_prompt": record["summary_prompt"], "test_only": True},
    )
    snapshot = TargetSnapshot(ref=descriptor.ref, display_name=descriptor.display_name,
        adapter_type="local_bank", adapter_version="1", descriptor_sha256=descriptor.content_sha256,
        invocation_config={"mode": mode, "agent_name": record["agent_name"], "project_id": "bank-tested-agents"})
    return descriptor, snapshot


class LocalBankAdapter:
    adapter_type = "local_bank"
    adapter_version = "1"

    def __init__(self, client=None, trace_client=None):
        self.client = client or LocalBankClient()
        self.trace_server = trace_client or TraceServerClient()
        self.results = {}
        self.statuses = {}

    def start(self, request):
        handle = request.execution_id
        if handle in self.statuses:
            raise TargetExecutionError("invalid_request", "duplicate execution ID")
        self.statuses[handle] = CaseExecutionStatus.RUNNING
        try:
            self.results[handle] = self._execute(request)
        except Exception:
            self.statuses[handle] = CaseExecutionStatus.FAILED
            raise
        self.statuses[handle] = CaseExecutionStatus.COMPLETED
        return handle

    def _execute(self, request):
        config = request.target.invocation_config
        mode = config["mode"]
        descriptor, snapshot = local_bank_target(self.client, mode)
        if snapshot.content_sha256 != request.target.content_sha256:
            raise TargetExecutionError("invalid_request", "bank target changed since manifest was created")
        customer = request.case.initial_state.get("customer", "test-low")
        if customer not in {"test-low", "test-high", "test-blocked"}:
            raise TargetExecutionError("invalid_request", "unknown synthetic test customer")
        deadline = time.monotonic() + request.timeout_seconds
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TargetExecutionError("rejected", "bank case deadline reached; inspect remote execution")
            return value
        prefix = "/agent-api/" + config["agent_name"]
        session = str(uuid4())
        if mode != "cloudshrimp":
            variables = {"config_variables" if mode == "workflow" else "prompt_variables": [{"name": "custID", "value": customer}]}
            result = self.client.call(prefix + "/chatabc/init_session", build_chatabc_payload(variables, request_id=session, timestamp_ms=int(time.time()*1000)), timeout=remaining())
            if result.get("resCode") != "FAIAG0000" or result.get("data", {}).get("session_id") != session:
                raise TargetExecutionError("protocol_error", "bank session creation failed")
        exports, outputs, requests, inputs = {}, {}, {}, {}
        for turn in request.case.turns:
            if set(turn.input) != {"txt"} or not isinstance(turn.input["txt"], str):
                raise TargetExecutionError("invalid_request", "bank CaseTurn input must contain only txt")
            rid = str(uuid4())
            requests[turn.id] = rid
            if mode == "cloudshrimp":
                payload = build_cloudshrimp_payload(session_id=session, customer_id=customer, text=turn.input["txt"], guardrail="ON_BLOCK")
                path = prefix + "/api/v1/message"
            else:
                payload = build_chatabc_payload({"session_id": session, "txt": turn.input["txt"], "files": [], "stream": True}, request_id=rid, timestamp_ms=int(time.time()*1000))
                path = prefix + "/chatabc/chat"
            data = self.client.call(path, payload, timeout=remaining(), request_id=rid, raw=True)
            chat = parse_bank_sse(data.decode().splitlines(), protocol=mode, wire_format="event_lines", request_id=rid)
            trace_ids = {item.get("trace_id") for item in chat.trace_payloads
                         if isinstance(item, dict) and isinstance(item.get("trace_id"), str) and item["trace_id"].strip()}
            if len(trace_ids) != 1:
                raise TargetExecutionError("protocol_error", "chat stream must reference exactly one trace server trace")
            events = self.trace_server.fetch_events(config["project_id"], trace_ids.pop(), timeout=remaining())
            root = next((event for event in events if event.get("event_type") == "trace"), None)
            result = (root or {}).get("output") or {}
            if (root is None or root.get("status") != "success"
                    or result.get("mode") != mode or result.get("agent_version") != "v1"
                    or result.get("request_id") != rid or result.get("session_id") != session
                    or result.get("output") != chat.output):
                raise TargetExecutionError("protocol_error", "trace server evidence correlation mismatch")
            if not isinstance(root.get("input"), dict):
                raise TargetExecutionError("protocol_error", "SDK trace is missing the executed input")
            inputs[turn.id] = root["input"]
            exports[turn.id] = (root["trace_id"], "\n".join(
                json.dumps(event, ensure_ascii=False) for event in events).encode())
            outputs[turn.id] = result
        trace = normalize_sdk_exports(request, exports, project_id=config["project_id"])
        spans = []
        for span in trace.spans:
            attrs = span.attributes.to_dict()
            operation = span.operation_type
            if operation == "turn":
                attrs["trace_sdk.replay"] = False
                attrs["bank.request_id"] = requests[attrs["agentgate.turn.id"]]
            if attrs.get("trace_sdk.name") == "skill.route":
                selected = attrs.get("trace_sdk.output", {}).get("selected_skill")
                if selected not in {s.external_skill_id for s in descriptor.skills}:
                    raise TargetExecutionError("protocol_error", "unknown recorded Skill decision")
                operation = "routing"
                attrs["selected_skill"] = selected
            spans.append(span.model_copy(update={"operation_type": operation, "attributes": FrozenJsonObject(attrs)}))
        outcomes = {t.id: {"input": inputs[t.id], "output": {"output": outputs[t.id]["output"]}, "state": outputs[t.id]["final_state"]} for t in request.case.turns}
        final = outcomes[request.case.turns[-1].id]
        trace = trace.model_copy(update={"spans": tuple(spans), "turn_outcomes": FrozenJsonObject(outcomes),
            "final_output": FrozenJsonObject(final["output"]), "final_state": FrozenJsonObject(final["state"])})
        return CaseExecutionResult(request.execution_id, trace.trace_id, trace)

    def get_status(self, handle):
        if handle not in self.statuses:
            raise TargetExecutionError("invalid_request", "unknown execution")
        return self.statuses[handle]

    def wait(self, handle, timeout_seconds):
        if timeout_seconds <= 0 or self.get_status(handle) != CaseExecutionStatus.COMPLETED:
            raise TargetExecutionError("protocol_error", "execution is not complete")
        return self.results[handle]

    def cancel(self, handle):
        # Synchronous HTTP disconnect cannot undo committed remote tool actions.
        self.get_status(handle)


def resolve_local_bank_trace(request, result):
    if result.inline_trace is None:
        raise TargetExecutionError("protocol_error", "bank runtime returned no trace")
    return result.inline_trace
