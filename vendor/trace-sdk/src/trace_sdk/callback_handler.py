"""Trace 采集 Callback Handler（对齐 langfuse 的 LangChain 回调实现）。

§2.4 父子关系核心规则（对齐 langfuse `_get_parent_observation`）：
  - `parent_run_id` 在 `_runs` 中 → 挂对应 span（parent_span_id = 父 span_id）
  - `parent_run_id` 不在 `_runs` 中 → 挂根（parent_span_id = None）
  - **没有 merge 归并、没有前缀过滤、没有按名字猜父子**
  - 并行同名节点不归并（经实测 langfuse 4.7.1 云端同样为每个并行任务
    生成独立的 tools 节点，本 SDK 保持一致）

§5.8 根节点语义：
  - `on_chain_start(parent_run_id is None)` 时同时创建 trace 和根 span
  - 根 span 的 parent_span_id = None

§5.5 span_type 映射（6 类）：
  - tool / retriever / llm / agent / chain / span

§5.6 隐藏机制：
  - langsmith:hidden tag → level=DEBUG（数据保留，不丢弃）
  - seq:step / graph:step 层照常采集，可选 hide_framework_steps=True 降级 DEBUG

§5.9 错误处理：
  - on_chain_error / on_llm_error / on_tool_error / on_retriever_error
  - GraphBubbleUp（interrupt/handoff）不算错误

§5.10 流式 TTFT：
  - on_llm_new_token 记录首 token 时间

用法（对齐 langfuse，见 §5.7 采集方式）：
    from trace_sdk import TraceClient, CallbackHandler
    client = TraceClient({...})          # 构造即注册为默认
    handler = CallbackHandler()          # 无参自动用默认 client
    agent.invoke(..., config={"callbacks": [handler]})
跨进程串联（C21）：
    CallbackHandler(trace_context={"trace_id": ..., "parent_span_id": ...})
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .model_extract import extract_model_name, parse_model_parameters
from .util.serialize import _message_to_dict, _to_jsonable

logger = logging.getLogger("trace_sdk.callback_handler")

LANGSMITH_TAG_HIDDEN = "langsmith:hidden"


# ---- 辅助函数 ----

def _chain_input(inputs: Any) -> Any:
    """chain 节点 input（对齐 langfuse：原样保存，但把消息对象转 dict）。"""
    return _to_jsonable(inputs)


def _llm_output(response: Any) -> Any:
    """LLM 输出（对齐 langfuse on_llm_end：最后一条 generation 的 message 转 dict）。"""
    try:
        gen = response.generations[-1][-1]
        msg = getattr(gen, "message", None)
        if msg is not None:
            return _message_to_dict(msg)
        if hasattr(gen, "text"):
            return gen.text
        return str(gen)
    except Exception:
        return None


def _llm_usage(response: Any) -> tuple[int, int]:
    """Token 用量（对齐 langfuse _parse_usage）。"""
    pt = ct = 0
    try:
        lo = getattr(response, "llm_output", None) or {}
        tu = lo.get("token_usage") or {}
        pt = int(tu.get("prompt_tokens") or 0)
        ct = int(tu.get("completion_tokens") or 0)
        if pt or ct:
            return pt, ct
        for gen in response.generations[-1]:
            msg = getattr(gen, "message", None)
            um = getattr(msg, "usage_metadata", None)
            if um:
                return (
                    int(um.get("input_tokens") or 0),
                    int(um.get("output_tokens") or 0),
                )
    except Exception:
        pass
    return pt, ct


# ---- span_type 映射表（§5.5 / §7.2）----

_NAME_TO_TYPE: dict[str, str] = {
    "agent": "agent",
}


def _span_type_from_serialized(
    serialized: Any,
    callback_type: str,
    name: str | None = None,
    **kwargs: Any,
) -> str:
    """推断 span_type（对齐 langfuse 6 类：chain/llm/tool/retriever/agent/span）。

    callback_type 取值：
      - "tool"     → tool
      - "retriever" → retriever
      - "llm"      → llm
      - "chain"    → 按名字/id 区分 agent / chain
      - 其他       → span
    """
    if callback_type == "tool":
        return "tool"
    if callback_type == "retriever":
        return "retriever"
    if callback_type == "llm":
        return "llm"
    if callback_type == "chain":
        n = (name or "").lower()
        # 按名字匹配类型表
        for k, v in _NAME_TO_TYPE.items():
            if k in n:
                return v
        if "agent" in n:
            return "agent"
        # 检查 serialized id
        if serialized and isinstance(serialized, dict):
            sid = serialized.get("id")
            if isinstance(sid, list) and sid:
                last = str(sid[-1]).lower()
                if "agent" in last:
                    return "agent"
        return "chain"
    return "span"


def _level_from_tags(tags: list[str] | None) -> str | None:
    """对齐 langfuse：langsmith:hidden tag → DEBUG level。"""
    if tags and LANGSMITH_TAG_HIDDEN in tags:
        return "DEBUG"
    return None


def _is_framework_step(name: str | None) -> bool:
    """判断是否为框架内部包装层（seq:step / graph:step）。"""
    n = name or ""
    return n.startswith("seq:step") or n.startswith("graph:step")


# ---- trace 属性解析（§5.7）----

def _parse_trace_attributes(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """从 metadata 中提取 langfuse 约定 key（§5.7）。

    返回 dict 含 session_id / user_id / trace_name / tags，剩余 metadata 剔除约定 key。
    """
    if not metadata:
        return {"session_id": None, "user_id": None, "trace_name": None, "tags": None, "metadata": {}}
    result: dict[str, Any] = {
        "session_id": metadata.get("langfuse_session_id"),
        "user_id": metadata.get("langfuse_user_id"),
        "trace_name": metadata.get("langfuse_trace_name"),
        "tags": metadata.get("langfuse_tags"),
    }
    # 剔除约定 key 后剩余为业务 metadata
    remaining = {k: v for k, v in metadata.items()
                 if k not in ("langfuse_session_id", "langfuse_user_id",
                              "langfuse_trace_name", "langfuse_tags")}
    result["metadata"] = remaining
    return result


class TraceCallbackHandler(BaseCallbackHandler):
    """Trace 采集回调处理器（对齐 langfuse LangchainCallbackHandler）。

    核心机制（§2.4）：
    - `_runs`：run_id → 节点记录（kind/span_id/meta/start）
    - `_get_parent_observation(parent_run_id)`：parent_run_id 在 `_runs` 中
      → 返回父 span_id；否则返回 None（挂根）
    - **无 merge 归并、无前缀过滤、无按名字猜父子**
    """

    ignore_chain: bool = False
    ignore_agent: bool = False

    def __init__(self, client: Any = None, *, trace_context: dict | None = None) -> None:
        super().__init__()
        # client 缺省时自动取进程默认实例（对齐 langfuse get_client()）
        if client is None:
            from .client import TraceClient
            client = TraceClient.default_client()
        self._collector = client.collector
        self._config = client.config
        self._trace_context = trace_context
        # run_id → 节点记录
        self._runs: dict[str, dict[str, Any]] = {}

    # ---- 核心父子解析（§2.4）----
    def _get_parent_span_id(self, parent_run_id: Any) -> str | None:
        """对齐 langfuse _get_parent_observation。

        parent_run_id 在 _runs 中 → 返回父 span_id；
        不在 _runs 中 → 返回 None（挂根 span）。
        不做向上遍历、不做 merge、不做前缀过滤。
        """
        if parent_run_id is not None:
            rec = self._runs.get(str(parent_run_id))
            if rec is not None:
                return rec.get("span_id")
        return None

    # ---- 内部辅助 ----
    def _trace_meta(self, metadata: Any) -> dict[str, Any]:
        """提取 metadata（dict 原样；其余转 dict/置空）。"""
        if isinstance(metadata, dict):
            return {k: _to_jsonable(v) for k, v in metadata.items()}
        if metadata is None:
            return {}
        try:
            return dict(metadata)  # type: ignore[arg-type]
        except Exception:
            return {}

    def _start_ts(self) -> float:
        return time.monotonic()

    def _dur_ms(self, start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    def _error_level(self, error: Any) -> tuple[str | None, str | None]:
        """对齐 langfuse §5.9：GraphBubbleUp 不算错误。"""
        try:
            from langgraph.errors import GraphBubbleUp
        except ImportError:
            GraphBubbleUp = ()  # type: ignore[assignment,misc]
        if isinstance(error, GraphBubbleUp):
            return (None, None)
        return ("ERROR", f"{error.__class__.__name__}: {error}")

    def _error_info(self, error: Any) -> dict[str, Any]:
        import traceback
        return {
            "error_type": error.__class__.__name__,
            "error_code": None,
            "error_category": "internal",
            "message": str(error),
            "stack_trace": traceback.format_exc(),
        }

    def _join_tags_and_metadata(
        self,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
    ) -> tuple[list[str] | None, dict[str, Any] | None]:
        """合并 tags 与 metadata（对齐 langfuse __join_tags_and_metadata）。"""
        merged_tags = list(tags) if tags else None
        merged_meta = dict(metadata) if metadata else None
        return merged_tags, merged_meta

    # ---- 公共关闭逻辑 ----
    def _close_run(
        self,
        run_id: Any,
        *,
        output: Any = None,
        status: str = "success",
        error_info: dict | None = None,
        level: str | None = None,
    ) -> None:
        """关闭 run：从 _runs 弹出并 end_span/end_trace。"""
        rec = self._runs.pop(str(run_id), None)
        if rec is None:
            return
        dur = self._dur_ms(rec["start"])
        # 合并 level（error 时覆盖）
        if level is not None:
            rec["level"] = level
        # §5.10 流式 TTFT：on_llm_new_token 记录 completion_start，此处换算为毫秒
        ttft = rec.get("time_to_first_token_ms")
        if ttft is None and rec.get("completion_start") is not None:
            ttft = int((rec["completion_start"] - rec["start"]) * 1000)

        if rec["kind"] == "trace":
            # 根 span：先 end_span 写入 SpanEvent，再 end_trace 写入 TraceEvent
            self._collector.end_span(
                rec["meta"],
                output=output,
                duration_ms=dur,
                status=status,
                error_info=error_info,
                time_to_first_token_ms=ttft,
            )
            stats = self._collector.stats_snapshot()
            self._collector.end_trace(
                output=output,
                duration_ms=dur,
                total_tokens=stats["prompt_tokens"] + stats["completion_tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                react_step_count=stats["llm_calls"],
                tool_count=stats["tool_calls"],
                span_count=stats["spans"],
                status=status,
                error_info=error_info,
                tags=rec.get("tags"),
            )
        else:
            self._collector.end_span(
                rec["meta"],
                output=output,
                duration_ms=dur,
                status=status,
                error_info=error_info,
                time_to_first_token_ms=ttft,
            )

    # ---- chain 生命周期 ----
    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            span_name = name or "<unknown>"
            input_data = _chain_input(inputs)
            level = _level_from_tags(tags)

            # 可选：hide_framework_steps=True 时给 seq:step/graph:step 降级 DEBUG
            if not level and self._config.hide_framework_steps and _is_framework_step(name):
                level = "DEBUG"

            # 合并 tags 和 metadata（剔除 langfuse 约定 key）
            attr = _parse_trace_attributes(metadata)
            joined_tags, joined_meta = self._join_tags_and_metadata(tags, attr["metadata"])

            if parent_run_id is None:
                # §5.8 根节点：同时创建 trace 和根 span
                from .util.ids import gen_uuid
                tc = self._trace_context or {}
                trace_id = tc.get("trace_id") or gen_uuid()
                session_id = attr["session_id"] or gen_uuid()
                trace_name = attr["trace_name"] or span_name
                agent_name = getattr(self._config, "agent_name", None) or span_name
                self._collector.start_trace(
                    trace_id=trace_id,
                    session_id=session_id,
                    name=trace_name,
                    agent_name=agent_name,
                    input=input_data,
                    tags=joined_tags,
                    user_id=attr["user_id"],
                )
                # 根 span：span_type 从 serialized 推断；
                # 跨进程（C21）：trace_context 携带 parent_span_id 时挂到上游 span
                span_type = _span_type_from_serialized(serialized, "chain", name=span_name)
                meta = self._collector.start_span(
                    name=span_name,
                    span_type=span_type,
                    parent=tc.get("parent_span_id") or "root",
                    input=input_data,
                    level=level,
                    metadata=joined_meta,
                    tags=joined_tags,
                )
                self._runs[str(run_id)] = {
                    "kind": "trace",
                    "span_id": meta["span_id"],
                    "meta": meta,
                    "start": self._start_ts(),
                    "tags": joined_tags,
                }
            else:
                # §2.4 子节点：_get_parent_observation 简单查找
                parent_span_id = self._get_parent_span_id(parent_run_id)
                span_type = _span_type_from_serialized(serialized, "chain", name=span_name)
                meta = self._collector.start_span(
                    name=span_name,
                    span_type=span_type,
                    parent=parent_span_id or "root",
                    input=input_data,
                    level=level,
                    metadata=joined_meta,
                    tags=joined_tags,
                )
                self._runs[str(run_id)] = {
                    "kind": "span",
                    "span_id": meta["span_id"],
                    "meta": meta,
                    "start": self._start_ts(),
                }
        except Exception:
            logger.exception("on_chain_start 采集失败")

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._close_run(run_id, output=_chain_input(outputs))
        except Exception:
            logger.exception("on_chain_end 采集失败")

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            level, msg = self._error_level(error)
            self._close_run(
                run_id,
                status="error" if level else "success",
                error_info=self._error_info(error) if level else None,
                level=level,
            )
        except Exception:
            logger.exception("on_chain_error 采集失败")

    # ---- LLM 生命周期 ----
    def on_chat_model_start(
        self,
        serialized: Any,
        messages: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._on_llm_start(serialized, messages, run_id=run_id,
                           parent_run_id=parent_run_id, tags=tags,
                           metadata=metadata, **kwargs)

    def on_llm_start(
        self,
        serialized: Any,
        prompts: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._on_llm_start(serialized, prompts, run_id=run_id,
                           parent_run_id=parent_run_id, tags=tags,
                           metadata=metadata, **kwargs)

    def _on_llm_start(
        self,
        serialized: Any,
        prompts_or_messages: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            # messages: List[List[BaseMessage]]（对齐 langfuse：含 system message）
            flat: list[Any] = []
            if prompts_or_messages:
                for item in prompts_or_messages:
                    if isinstance(item, list):
                        flat.extend(item)
                    else:
                        flat.append(item)
            input_data = [_message_to_dict(m) for m in flat]

            # 追加工具定义（对齐 langfuse __on_llm_action）
            tools = (kwargs.get("invocation_params") or {}).get("tools")
            if isinstance(tools, list) and tools:
                input_data.extend({"role": "tool", "content": t} for t in tools)

            span_name = (
                serialized.get("name") if isinstance(serialized, dict) and serialized else None
            ) or "unknown"
            model_name = extract_model_name(serialized, **kwargs)
            model_params = parse_model_parameters(kwargs)
            level = _level_from_tags(tags)
            attr = _parse_trace_attributes(metadata)
            joined_tags, joined_meta = self._join_tags_and_metadata(tags, attr["metadata"])

            parent_span_id = self._get_parent_span_id(parent_run_id)
            meta = self._collector.start_span(
                name=span_name,
                span_type="llm",
                parent=parent_span_id or "root",
                input=input_data,
                model=model_name,
                model_parameters=model_params or None,
                level=level,
                metadata=joined_meta,
                tags=joined_tags,
            )
            # 供中间件在 wrap_model_call 的 handler 返回后关联真实 LLM 请求
            # （RealLLMRequestMiddleware 在 on_chat_model_start 之后、on_llm_end 之前取用）
            self._collector.last_llm_meta = {
                "event_id": meta["event_id"],
                "span_id": meta["span_id"],
                "trace_id": self._collector.active_trace_id,
            }
            self._runs[str(run_id)] = {
                "kind": "llm",
                "span_id": meta["span_id"],
                "meta": meta,
                "start": self._start_ts(),
                "model": model_name,
                "input": input_data,
            }
        except Exception:
            logger.exception("on_chat_model_start 采集失败")

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            rec = self._runs.get(str(run_id))
            if rec is None or rec["kind"] != "llm":
                return
            output = _llm_output(response)
            pt, ct = _llm_usage(response)
            self._collector.add_observation(
                span_id=rec["span_id"],
                model=rec.get("model"),
                prompt_tokens=pt,
                completion_tokens=ct,
                input=rec.get("input"),
                output=output,
            )
            self._collector.bump_llm()
            self._close_run(run_id, output=output)
        except Exception:
            logger.exception("on_llm_end 采集失败")

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            level, msg = self._error_level(error)
            self._close_run(
                run_id,
                status="error" if level else "success",
                error_info=self._error_info(error) if level else None,
                level=level,
            )
        except Exception:
            logger.exception("on_llm_error 采集失败")

    def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """§5.10 流式 TTFT：记录首 token 到达时间。"""
        try:
            rec = self._runs.get(str(run_id))
            if rec and rec.get("kind") == "llm" and "completion_start" not in rec:
                rec["completion_start"] = time.monotonic()
        except Exception:
            pass

    # ---- Tool 生命周期 ----
    def on_tool_start(
        self,
        serialized: Any,
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            span_name = (
                serialized.get("name") if isinstance(serialized, dict) and serialized else None
            ) or "<unknown>"
            try:
                import json
                input_data = json.loads(input_str) if isinstance(input_str, str) else input_str
            except Exception:
                input_data = input_str
            level = _level_from_tags(tags)
            attr = _parse_trace_attributes(metadata)
            joined_tags, joined_meta = self._join_tags_and_metadata(tags, attr["metadata"])

            parent_span_id = self._get_parent_span_id(parent_run_id)
            meta = self._collector.start_span(
                name=span_name,
                span_type="tool",
                parent=parent_span_id or "root",
                input=input_data,
                tool_name=span_name,
                level=level,
                metadata=joined_meta,
                tags=joined_tags,
            )
            self._runs[str(run_id)] = {
                "kind": "tool",
                "span_id": meta["span_id"],
                "meta": meta,
                "start": self._start_ts(),
            }
        except Exception:
            logger.exception("on_tool_start 采集失败")

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._collector.bump_tool()
            self._close_run(run_id, output=_to_jsonable(output))
        except Exception:
            logger.exception("on_tool_end 采集失败")

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            level, msg = self._error_level(error)
            self._collector.bump_tool()
            self._close_run(
                run_id,
                status="error" if level else "success",
                error_info=self._error_info(error) if level else None,
                level=level,
            )
        except Exception:
            logger.exception("on_tool_error 采集失败")

    # ---- Retriever 生命周期（§5.5 补齐）----
    def on_retriever_start(
        self,
        serialized: Any,
        query: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            span_name = name or (
                serialized.get("name") if isinstance(serialized, dict) and serialized else "retriever"
            )
            level = _level_from_tags(tags)
            attr = _parse_trace_attributes(metadata)
            joined_tags, joined_meta = self._join_tags_and_metadata(tags, attr["metadata"])

            parent_span_id = self._get_parent_span_id(parent_run_id)
            meta = self._collector.start_span(
                name=span_name,
                span_type="retriever",
                parent=parent_span_id or "root",
                input=query,
                level=level,
                metadata=joined_meta,
                tags=joined_tags,
            )
            self._runs[str(run_id)] = {
                "kind": "retriever",
                "span_id": meta["span_id"],
                "meta": meta,
                "start": self._start_ts(),
            }
        except Exception:
            logger.exception("on_retriever_start 采集失败")

    def on_retriever_end(
        self,
        documents: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._close_run(run_id, output=_to_jsonable(documents))
        except Exception:
            logger.exception("on_retriever_end 采集失败")

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            level, msg = self._error_level(error)
            self._close_run(
                run_id,
                status="error" if level else "success",
                error_info=self._error_info(error) if level else None,
                level=level,
            )
        except Exception:
            logger.exception("on_retriever_error 采集失败")


# 对齐 langfuse：对外导出名为 CallbackHandler（同 langfuse.langchain.CallbackHandler）
CallbackHandler = TraceCallbackHandler

__all__ = ["TraceCallbackHandler", "CallbackHandler"]
