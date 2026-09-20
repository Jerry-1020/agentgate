"""真实 LLM 请求中间件（middleware/llm_request.py）。

通过 `AgentMiddleware.wrap_model_call` 拦截"真正发给大模型"的请求与响应，
按 event_id 与 SDK 采集的 llm span 关联，另存一份 1:1 的真实 payload。

用法（对用例零侵入，仅加一个 middleware 参数）：
    from trace_sdk import TraceClient
    from trace_sdk.middleware import RealLLMRequestMiddleware
    client = TraceClient({"project_id": "..."})
    agent = create_deep_agent(
        model=build_llm(),
        system_prompt="...",
        tools=[...],
        middleware=[RealLLMRequestMiddleware(client=client)],
    )

关联机制：
- wrap_model_call 在最外层（langchain/agents/factory.py `_execute_model_sync` 之外），
  而 SDK 的 on_chat_model_start/on_llm_end 回调在 `model_.invoke()` 内部触发；
- handler(request) 返回后，SDK 已将本次 llm span 的 {event_id, span_id, trace_id}
  保存在 `collector.last_llm_meta`，中间件据此关联，event_id 天然与 llm span 一致。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
)

from trace_sdk.client import TraceClient
from trace_sdk.util.ids import gen_uuid

logger = logging.getLogger("trace_sdk.middleware.llm_request")


def _msg_to_dict(m: Any) -> dict[str, Any] | str:
    """BaseMessage → OpenAI 风格 dict（role/content/tool_calls 等）。"""
    if m is None:
        return ""
    try:
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
            "function": "assistant",
        }
        role = role_map.get(getattr(m, "type", ""), getattr(m, "type", "unknown"))
        d: dict[str, Any] = {"role": role}
        content = getattr(m, "content", "")
        # content 可能是字符串或 content block 列表
        d["content"] = content
        # tool_calls（AIMessage）
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": tc.get("args"),
                    },
                }
                for tc in tool_calls
            ]
        # tool_call_id（ToolMessage）
        tcid = getattr(m, "tool_call_id", None)
        if tcid:
            d["tool_call_id"] = tcid
        return d
    except Exception:
        return str(m)


def _tools_to_schema(tools: list[Any]) -> list[dict[str, Any]] | None:
    """工具列表 → OpenAI Tool JSON schema（保留 name/description/parameters）。"""
    if not tools:
        return None
    out: list[dict[str, Any]] = []
    for t in tools:
        try:
            if isinstance(t, dict):
                out.append(t)
                continue
            schema = {
                "type": "function",
                "function": {
                    "name": getattr(t, "name", None),
                    "description": getattr(t, "description", None),
                },
            }
            # args_schema（BaseTool）或 model_dump 提取 parameters
            try:
                args = getattr(t, "args_schema", None)
                if args is not None and hasattr(args, "model_json_schema"):
                    schema["function"]["parameters"] = args.model_json_schema()
                else:
                    dd = t.model_dump() if hasattr(t, "model_dump") else None
                    if isinstance(dd, dict) and "args_schema" in dd:
                        schema["function"]["parameters"] = dd["args_schema"]
            except Exception:
                pass
            out.append(schema)
        except Exception:
            logger.exception("工具转 schema 失败")
    return out or None


def _as_model_response(result: Any) -> dict[str, Any] | None:
    """ModelResponse / AIMessage → 真实响应 dict。"""
    try:
        if isinstance(result, ModelResponse):
            msgs = result.result
            structured = getattr(result, "structured_response", None)
            d: dict[str, Any] = {
                "messages": [_msg_to_dict(m) for m in msgs],
            }
            if structured is not None:
                d["structured_response"] = structured
            return d
        # AIMessage 或 dict 包装
        if isinstance(result, dict):
            if "result" in result and isinstance(result["result"], list):
                return {
                    "messages": [_msg_to_dict(m) for m in result["result"]],
                }
            return result
        # BaseMessage
        return {"messages": [_msg_to_dict(result)]}
    except Exception:
        return None


class RealLLMRequestMiddleware(AgentMiddleware):
    """拦截真实 LLM 请求/响应，按 event_id 关联 llm span 并上报。

    使用方式：只传 `middleware=[RealLLMRequestMiddleware(client=client)]` 即可，
    中间件始终拦截并上报（采集与否由是否挂载该中间件决定）。
    """

    def __init__(self, client: TraceClient | None = None) -> None:
        super().__init__()
        self._client = client or TraceClient.default_client()

    def _build_payload_in(self, request: ModelRequest) -> dict[str, Any]:
        model = request.model
        msgs: list[Any] = []
        if request.system_message is not None:
            msgs.append(request.system_message)
        msgs.extend(request.messages or [])
        return {
            "model": getattr(model, "model_name", None) or type(model).__name__,
            "messages": [_msg_to_dict(m) for m in msgs],
            "tools": _tools_to_schema(request.tools),
            "model_settings": request.model_settings or {},
            "tool_choice": getattr(request, "tool_choice", None),
            "response_format": getattr(request, "response_format", None),
        }

    def _record(self, payload_in: dict[str, Any], payload_out: dict[str, Any] | None,
                status: str = "success", error_info: dict | None = None) -> None:
        client = self._client
        collector = client.collector
        # handler 返回后，SDK 已把本次 llm span 的元信息存到 last_llm_meta
        meta = getattr(collector, "last_llm_meta", None) or {}
        event_id = meta.get("event_id") or gen_uuid()
        try:
            collector.record_llm_request(
                event_id=event_id,
                span_id=meta.get("span_id"),
                model=payload_in.get("model"),
                input=payload_in,
                output=payload_out,
                status=status,
                error_info=error_info,
                started_at=None,
            )
        except Exception:
            logger.exception("上报真实 LLM 请求失败")

    def wrap_model_call(self, request: ModelRequest, handler):
        payload_in = self._build_payload_in(request)
        try:
            result = handler(request)
            payload_out = _as_model_response(result)
            self._record(payload_in, payload_out)
        except Exception as e:
            self._record(
                payload_in,
                None,
                status="error",
                error_info={"type": type(e).__name__, "message": str(e)},
            )
            raise
        return result

    async def awrap_model_call(self, request: ModelRequest, handler):
        payload_in = self._build_payload_in(request)
        try:
            result = await handler(request)
            payload_out = _as_model_response(result)
            self._record(payload_in, payload_out)
        except Exception as e:
            self._record(
                payload_in,
                None,
                status="error",
                error_info={"type": type(e).__name__, "message": str(e)},
            )
            raise
        return result
