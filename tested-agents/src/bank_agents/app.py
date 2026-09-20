"""Loopback-only test runtime with bank-compatible chat endpoints."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .model import LiveModel
from .runtime import Runtime, SKILLS, BASE_PROMPT, EXTRACT_PROMPT, ROUTER_PROMPT, SUMMARY_PROMPT
from .store import Store, Conflict
from .telemetry import PROJECT
from .tools import TOOLS

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
AGENTS = {f"loan-{mode}-v1": mode for mode in ("base", "workflow", "cloudshrimp")}


class InitData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_variables: list[dict] = Field(default_factory=list, max_length=10)
    tool_variables: list[dict] = Field(default_factory=list, max_length=10)
    config_variables: list[dict] = Field(default_factory=list, max_length=10)


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appId: str = "BDC201704_01"
    trCode: str = "AISPNLPCHATBOT"
    trVersion: str = "1"
    timestamp: int = Field(ge=0)
    requestId: Identifier
    data: dict


class ChatData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: Identifier
    txt: str = Field(min_length=1, max_length=4000)
    files: list = Field(default_factory=list, max_length=0)
    stream: Literal[True] = True


class CloudData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: Identifier
    custID: Identifier
    txt: str = Field(min_length=1, max_length=4000)
    agentSessionId: Literal[""] = ""
    executionMode: Literal["execute"] = "execute"
    stream: bool = True
    debugTrace: bool = True
    safeGuardrail: Literal["ON_BLOCK"] = "ON_BLOCK"
    config_variables: list = Field(default_factory=list, max_length=0)
    appHistory: list = Field(default_factory=list, max_length=0)
    availableSkills: None = None


def create_app(runtime=None):
    if runtime is None:
        directory = Path(os.environ.get("BANK_RUNTIME_DIR", "runtime/bank-agents")).resolve()
        runtime = Runtime(Store(directory / "bank.db"), LiveModel(), directory / "traces")
    app = FastAPI(title="Bank tested Agents — synthetic local environment", version="0.1.0")
    implementation_sha256 = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    app.state.runtime = runtime

    def mode_of(agent_name, allowed=("base", "workflow", "cloudshrimp")):
        mode = AGENTS.get(agent_name)
        if mode not in allowed:
            raise HTTPException(404, "unknown agent or unsupported protocol")
        return mode

    @app.get("/health")
    def health():
        return {"status": "ok", "test_only": True, "model": runtime.model.name}

    @app.get("/agents")
    def agents():
        return [{"agent_id": f"loan-{mode}", "agent_version": "v1", "agent_name": name,
                 "mode": mode, "model": runtime.model.name, "policy_version": "test-policy-v1",
                 "implementation_sha256": implementation_sha256, "tools": TOOLS,
                 "skills": SKILLS if mode == "cloudshrimp" else [], "test_only": True,
                 "prompt": BASE_PROMPT if mode == "base" else EXTRACT_PROMPT if mode == "workflow" else ROUTER_PROMPT,
                 "summary_prompt": SUMMARY_PROMPT} for name, mode in AGENTS.items()]

    @app.get("/test-cases")
    def cases():
        return runtime.store.cases()

    @app.get("/agent-api/{agent_name}/chatabc/health_check")
    def chat_health(agent_name: str):
        mode_of(agent_name, ("base", "workflow"))
        return {"data": {"status": "ok"}}

    @app.get("/agent-api/{agent_name}/health")
    def cloud_health(agent_name: str):
        mode_of(agent_name, ("cloudshrimp",))
        return {"status": "ok"}

    @app.post("/agent-api/{agent_name}/chatabc/init_session")
    def init(agent_name: str, payload: Envelope):
        mode = mode_of(agent_name, ("base", "workflow"))
        try:
            data = InitData.model_validate(payload.data)
            if mode == "base" and data.config_variables or mode == "workflow" and (data.prompt_variables or data.tool_variables):
                raise ValueError("initialization fields do not match protocol")
            variables = data.config_variables + data.prompt_variables + data.tool_variables
            if any(set(v) != {"name", "value"} or v["name"] != "custID" for v in variables) or len(variables) > 1:
                raise ValueError("only one custID variable is supported; prompts/tools are version-pinned")
            customer = variables[0]["value"] if variables else "test-low"
            # Repeat init request returns the same conversation, not a second session.
            session = runtime.store.create_session(mode, customer, payload.requestId)
            return {"resCode": "FAIAG0000", "data": {"session_id": session}}
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError:
            raise HTTPException(422, "invalid init configuration or test customer") from None

    def frames(mode, session, request_id, text, debug=True):
        def frame(event, value):
            data = value if value == "[DONE]" else json.dumps(value, ensure_ascii=False)
            return f"event: {event}\ndata: {data}\n\n"
        yield frame("start", {"session_id": session, "request_id": request_id})
        try:
            result = runtime.execute(mode, session, request_id, text)
            if mode == "workflow":
                for node in result["workflow_calls"]:
                    yield frame("message", {"node_id": node["node_id"], "additional_kwargs": {"node_output": node["node_output"]}})
            else:
                yield frame("message", result if mode == "cloudshrimp" else {"content": result["output"]})
            if debug:
                yield frame("trace", {"project_id": PROJECT, "trace_id": result["trace_id"],
                    "request_id": request_id, "agent_version": "v1", "final_state": result["final_state"]})
        except Exception as exc:
            yield frame("error" if mode == "cloudshrimp" else "failed",
                        {"error_code": type(exc).__name__, "message": "测试执行失败，请按requestId检查记录"})
        yield frame("done", "[DONE]")

    @app.post("/agent-api/{agent_name}/chatabc/chat")
    def chat(agent_name: str, payload: Envelope):
        mode = mode_of(agent_name, ("base", "workflow"))
        try:
            data = ChatData.model_validate(payload.data)
            runtime.store.session(data.session_id, mode)
        except ValueError:
            raise HTTPException(422, "invalid chat input or session; files are not supported") from None
        return StreamingResponse(frames(mode, data.session_id, payload.requestId, data.txt), media_type="text/event-stream")

    @app.post("/agent-api/{agent_name}/api/v1/message")
    def cloud(agent_name: str, payload: CloudData, x_request_id: str | None = Header(default=None)):
        mode_of(agent_name, ("cloudshrimp",))
        from pydantic import TypeAdapter
        try:
            request_id = TypeAdapter(Identifier).validate_python(x_request_id or str(uuid4()))
            session = runtime.store.create_session("cloudshrimp", payload.custID, payload.sessionId)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError:
            raise HTTPException(422, "invalid request ID or test customer") from None
        if payload.stream:
            return StreamingResponse(frames("cloudshrimp", session, request_id, payload.txt, payload.debugTrace), media_type="text/event-stream")
        try:
            return runtime.execute("cloudshrimp", session, request_id, payload.txt)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(502, "agent execution failed; inspect request record") from None

    def trace_path(request_id):
        try:
            row = runtime.store.request(request_id)
        except ValueError:
            raise HTTPException(404, "request not found") from None
        path = runtime.trace_directory / PROJECT / row["session"] / f"{row['trace_id']}.jsonl"
        if not path.is_file() or row["status"] == "running":
            raise HTTPException(409, "trace is not complete")
        return row, path

    @app.get("/requests/{request_id}")
    def request_info(request_id: str):
        try:
            row = runtime.store.request(request_id)
        except ValueError:
            raise HTTPException(404, "request not found") from None
        return {k: json.loads(v) if k == "result" and v else v for k, v in row.items() if k != "digest"}

    @app.get("/requests/{request_id}/trace")
    def trace(request_id: str):
        _, path = trace_path(request_id)
        return FileResponse(path, media_type="application/x-ndjson")

    @app.get("/web/race_eval/workflow_trace")
    def workflow_trace(request_id: str):
        _, path = trace_path(request_id)
        return {"code": "0", "data": [json.loads(line) for line in path.read_text().splitlines() if line.strip()]}

    return app
