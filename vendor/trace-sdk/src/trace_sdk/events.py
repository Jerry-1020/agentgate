"""Trace SDK 事件模型。

与 implementation_plan/docs/03_SDK采集层实现.md §5.4 一致：
- TraceEvent / SpanEvent / ObservationEvent / SessionEvent 四类链路事件
- 每类都继承 BaseEvent，带 event_id（UUID，幂等写库关键）
- SDK 只负责生成并上报事件，不负责写库

SpanEvent 字段扩展（§5.4）：
  - level: DEBUG/DEFAULT/WARNING/ERROR（对齐 langfuse，默认 None）
  - metadata: 业务 metadata
  - tags: 业务 tags
  - model_parameters: temperature/max_tokens 等
  - time_to_first_token_ms: 流式首 token 延迟

TraceEvent 增加 tags。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TRACE = "trace"
    SPAN = "span"
    OBSERVATION = "observation"
    SESSION = "session"
    LLM_REQUEST = "llm_request"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid4() -> str:
    return str(uuid.uuid4())


class BaseEvent:
    """所有事件的基类：统一序列化、统一生成 event_id。"""

    event_type: EventType
    event_id: str
    created_at: str
    project_id: str | None = None

    def __init__(self, *, project_id: str | None = None, **fields: Any) -> None:
        self.project_id = project_id
        self.event_id = fields.pop("event_id", None) or _uuid4()
        self.created_at = fields.pop("created_at", None) or _now_iso()
        # 业务字段：事件特有的其余字段原样保留
        self._fields: dict[str, Any] = fields

    def to_dict(self) -> dict[str, Any]:
        """已脱敏，序列化用于上报。"""
        d: dict[str, Any] = {
            "event_type": self.event_type.value,
            "event_id": self.event_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
        }
        d.update(self._fields)
        return d

    def __getattr__(self, name: str) -> Any:
        # 让字段可直接通过属性访问（如 ev.trace_id）
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name) from None


class TraceEvent(BaseEvent):
    """一次对话（Trace 级）。"""

    def __init__(
        self,
        *,
        trace_id: str,
        session_id: str | None = None,
        name: str = "agent_run",
        agent_name: str = "agent",
        input: Any = None,
        output: Any = None,
        duration_ms: int = 0,
        total_tokens: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        react_step_count: int = 0,
        tool_count: int = 0,
        span_count: int = 0,
        status: str = "success",
        error_info: dict | None = None,
        tags: list[str] | None = None,
        started_at: str | None = None,
        **kw: Any,
    ) -> None:
        self.event_type = EventType.TRACE
        super().__init__(
            id=trace_id,  # 表主键 = trace_id（与 writer._TRACE_FIELDS 对齐）
            trace_id=trace_id,
            session_id=session_id,
            name=name,
            agent_name=agent_name,
            input=input,
            output=output,
            duration_ms=duration_ms,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            react_step_count=react_step_count,
            tool_count=tool_count,
            span_count=span_count,
            status=status,
            error_info=error_info,
            tags=tags,
            started_at=started_at or _now_iso(),
            **kw,
        )


class SpanEvent(BaseEvent):
    """一个环节（Span 级）。

    span_type: chain / llm / tool / retriever / agent / span（§5.5）
    """

    def __init__(
        self,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        name: str = "span",
        span_type: str = "chain",
        input: Any = None,
        output: Any = None,
        duration_ms: int = 0,
        model: str | None = None,
        model_parameters: dict | None = None,
        tool_name: str | None = None,
        status: str = "success",
        level: str | None = None,
        metadata: dict | None = None,
        tags: list[str] | None = None,
        error_info: dict | None = None,
        time_to_first_token_ms: int | None = None,
        started_at: str | None = None,
        **kw: Any,
    ) -> None:
        self.event_type = EventType.SPAN
        super().__init__(
            id=span_id,  # 表主键 = span_id
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            span_type=span_type,
            input=input,
            output=output,
            duration_ms=duration_ms,
            model=model,
            model_parameters=model_parameters,
            tool_name=tool_name,
            status=status,
            level=level,
            metadata=metadata,
            tags=tags,
            error_info=error_info,
            time_to_first_token_ms=time_to_first_token_ms,
            started_at=started_at or _now_iso(),
            **kw,
        )


class ObservationEvent(BaseEvent):
    """Token 明细（Observation 级，挂到 LLM Span 下）。"""

    def __init__(
        self,
        *,
        trace_id: str,
        span_id: str | None = None,
        model: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        input: Any = None,
        output: Any = None,
        **kw: Any,
    ) -> None:
        self.event_type = EventType.OBSERVATION
        super().__init__(
            id=kw.pop("id", None) or str(uuid.uuid4()),
            trace_id=trace_id,
            span_id=span_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input=input,
            output=output,
            **kw,
        )


class SessionEvent(BaseEvent):
    """会话（Session 级）。"""

    def __init__(
        self,
        *,
        session_id: str,
        trace_id: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
        **kw: Any,
    ) -> None:
        self.event_type = EventType.SESSION
        super().__init__(
            session_id=session_id,
            trace_id=trace_id,
            name=name,
            user_id=user_id,
            metadata=metadata,
            **kw,
        )


class LLMRequestEvent(BaseEvent):
    """真实 LLM 请求（中间件拦截，与 llm span 按 event_id 关联）。

    记录的是"真正发给大模型"的 payload（model/messages/tools/model_settings 等），
    与 span 的 input（回调快照加工版）不同。event_id 复用 llm span 的 event_id，
    作为关联键（幂等写库：ON CONFLICT (event_id) DO NOTHING）。
    """

    def __init__(
        self,
        *,
        trace_id: str,
        session_id: str | None = None,
        span_id: str | None = None,
        event_id: str,
        model: str | None = None,
        input: Any = None,
        output: Any = None,
        status: str = "success",
        error_info: dict | None = None,
        started_at: str | None = None,
        **kw: Any,
    ) -> None:
        self.event_type = EventType.LLM_REQUEST
        super().__init__(
            id=event_id,  # 表主键 = event_id（与 writer._LLM_REQUEST_FIELDS 对齐）
            trace_id=trace_id,
            session_id=session_id,
            span_id=span_id,
            event_id=event_id,
            model=model,
            input=input,
            output=output,
            status=status,
            error_info=error_info,
            started_at=started_at or _now_iso(),
            **kw,
        )
