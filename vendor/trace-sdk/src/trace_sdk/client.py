"""Trace SDK 对外入口（client.py）。

TraceClient 管理：
- 全局唯一 Collector（采集器）：持有 buffer + exporter + 上下文

用法（对齐 langfuse）：
    from trace_sdk import TraceClient, CallbackHandler
    client = TraceClient({"backend": "redis", "project_id": "..."})  # 构造即注册默认
    handler = CallbackHandler()   # 无参自动用默认 client（从环境变量亦可）
    agent.invoke(..., config={"callbacks": [handler]})
    ...
    client.shutdown()   # 进程退出前调用，确保数据送达
"""
from __future__ import annotations

import datetime
import hashlib
import logging
from typing import Any

from .buffer import EventBuffer
from .config import SDKConfig
from .context import TraceContext
from .events import (
    LLMRequestEvent,
    ObservationEvent,
    SessionEvent,
    SpanEvent,
    TraceEvent,
)
from .exporters import DatabaseExporter, FileExporter, KafkaExporter, RedisExporter
from .security import mask_value
from .util.ids import gen_uuid

logger = logging.getLogger("trace_sdk")


class Collector:
    """采集器：生成事件 → 缓冲 → 上报。全局单例。"""

    def __init__(self, config: SDKConfig) -> None:
        self.config = config
        if config.backend == "redis":
            self._exporter = RedisExporter(config)
        elif config.backend == "kafka":
            self._exporter = KafkaExporter(config)
        elif config.backend == "file":
            self._exporter = FileExporter(config)
        elif config.backend == "direct_db":
            self._exporter = DatabaseExporter(config)
        else:
            raise ValueError(f"不支持的 backend: {config.backend}")
        self.buffer = EventBuffer(
            self._exporter,
            size=config.buffer_size,
            batch_size=config.batch_size,
            flush_interval=config.flush_interval,
            discard_on_overflow=config.discard_on_overflow,
            high_watermark=config.buffer_high_watermark,
        )
        # 当前 Trace 的统计（Span/LLM/Tool 计数、Token 汇总）
        self._stats: dict[str, int] = {
            "spans": 0, "llm_calls": 0, "tool_calls": 0,
            "prompt_tokens": 0, "completion_tokens": 0,
        }
        # 当前活动 Trace 与 Span 栈（实例级，主/子 agent 共用同一 collector 时共享）
        self._trace: dict[str, Any] | None = None
        self._span_stack: list[dict[str, Any]] = []
        # 采样命中标记（start_trace 时按 trace_id 哈希判定，默认全采）
        self._sampled: bool = True
        # 最近一次完成的 llm span 元信息（{event_id, span_id, trace_id}），
        # 供中间件在 wrap_model_call 的 handler 返回后关联真实 LLM 请求
        self.last_llm_meta: dict[str, str] | None = None
        # 最近一次完成的 trace_id（供测试/外部查询，end_trace 时更新）
        self.last_trace_id: str | None = None

    def reset_stats(self) -> None:
        self._stats = {
            "spans": 0, "llm_calls": 0, "tool_calls": 0,
            "prompt_tokens": 0, "completion_tokens": 0,
        }

    def stats_snapshot(self) -> dict[str, int]:
        return dict(self._stats)

    def bump_llm(self) -> None:
        self._stats["llm_calls"] += 1

    def bump_tool(self) -> None:
        self._stats["tool_calls"] += 1

    # ---- 上报入口：先脱敏，再入缓冲 ----
    def emit(self, event: Any) -> None:
        self.buffer.add(event)

    def _sanitize_content(self, value: Any) -> Any:
        """按配置脱敏，返回处理后的内容。"""
        return mask_value(value, rules=self.config.mask_rules,
                          enabled=self.config.mask_enabled)

    # ---- Trace 级（实例状态） ----
    @property
    def active_trace_id(self) -> str | None:
        return self._trace["trace_id"] if self._trace else None

    @property
    def current_span_id(self) -> str | None:
        """当前栈顶 span_id（供跨进程注入 parent_span_id，C21）。"""
        if self._span_stack:
            return self._span_stack[-1]["span_id"]
        return None

    def start_trace(self, *, trace_id: str, session_id: str | None,
                    name: str, agent_name: str, input: Any,
                    tags: list[str] | None = None,
                    user_id: str | None = None) -> None:
        self._trace = {"trace_id": trace_id, "session_id": session_id,
                       "name": name, "agent_name": agent_name, "input": input,
                       "tags": tags}
        self._span_stack = []
        # 采样判定（基于 trace_id 哈希，确定性、并发安全）
        self._sampled = self._should_sample(trace_id)
        # Session 事件：确保会话存在
        if session_id:
            self._emit_trace_event(SessionEvent(
                session_id=session_id,
                trace_id=trace_id,
                name=f"session-{session_id[:8]}",
                user_id=user_id,
                project_id=self.config.project_id,
            ))

    def _emit_trace_event(self, event: Any) -> None:
        """上报某个 trace 的事件。

        未命中采样时先入观望缓冲（add_pending），等 end_trace 裁决：
        命中/错误必采 → release_trace 放行；否则 drop_trace 丢弃。
        这样该 trace 的事件在裁决前不会进入刷盘队列，杜绝「应丢弃却落库」的时序竞争。
        """
        trace_id = getattr(event, "trace_id", None)
        if trace_id and not self._sampled:
            self.buffer.add_pending(trace_id, event)
        else:
            self.emit(event)

    def emit_trace_event(self, event: Any) -> None:
        """采样感知的公开上报入口（供中间件等外部调用）。

        与 span/observation 走同一裁决路径：未命中采样先入观望缓冲，
        end_trace 裁决后放行或丢弃，避免「trace 丢了却存了 llm_request」的孤儿记录。
        """
        self._emit_trace_event(event)

    def _should_sample(self, trace_id: str) -> bool:
        """按 trace_id 哈希判定是否命中采样（§G 采样）。

        sample_rate=1.0 全采；0.0 全丢；中间值按哈希比例命中。
        同一 trace_id 恒定同结果，可复现、并发安全。
        """
        rate = getattr(self.config, "sample_rate", 1.0)
        if rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        h = hashlib.sha256(trace_id.encode("utf-8")).digest()
        # 取哈希前 53 bit 转成 [0,1)，与比例比较（53 bit 保证双精度无偏）
        val = int.from_bytes(h[:7], "big") / (1 << 56)
        return val < rate

    def end_trace(self, *, output: Any = None, error: Any = None,
                  duration_ms: int = 0, total_tokens: int = 0,
                  prompt_tokens: int = 0, completion_tokens: int = 0,
                  react_step_count: int = 0, tool_count: int = 0,
                  span_count: int = 0, status: str = "success",
                  error_info: dict | None = None,
                  tags: list[str] | None = None) -> None:
        ctx = self._trace
        if not ctx:
            return
        self.last_trace_id = ctx["trace_id"]
        # 错误必采：未命中采样但 status=error 且开启 error_force_record → 强制记录
        is_error = status == "error"
        force_record = (
            self._sampled
            or (is_error and getattr(self.config, "error_force_record", True))
        )
        if force_record:
            ev = TraceEvent(
                trace_id=ctx["trace_id"],
                session_id=ctx.get("session_id"),
                name=ctx.get("name", "agent_run"),
                agent_name=ctx.get("agent_name", "agent"),
                input=self._sanitize_content(ctx.get("input")),
                output=self._sanitize_content(output),
                duration_ms=duration_ms,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                react_step_count=react_step_count,
                tool_count=tool_count,
                span_count=span_count,
                status=status,
                error_info=error_info,
                tags=tags or ctx.get("tags"),
                project_id=self.config.project_id,
            )
            self.emit(ev)
            # 观望缓冲放行：该 trace 未命中采样时，之前暂存的 span/observation 一并落库
            self.buffer.release_trace(ctx["trace_id"])
        else:
            # 未命中采样且非错误必采：丢弃该 trace 的全部事件（含已入队的 span/observation）
            self.buffer.drop_trace(ctx["trace_id"])
        self._trace = None
        self._span_stack = []
        self._sampled = True
        self.reset_stats()

    # ---- Span 级（实例状态） ----
    def start_span(self, *, name: str, span_type: str = "chain",
                   input: Any = None, model: str | None = None,
                   model_parameters: dict | None = None,
                   tool_name: str | None = None,
                   parent: str | None = None,
                   level: str | None = None,
                   metadata: dict | None = None,
                   tags: list[str] | None = None) -> dict[str, Any]:
        """入栈并返回 span 元数据。

        parent:
          - None（默认）：取栈顶作父（用于顺序嵌套，如子 agent 挂在 task tool 下）
          - "root"：强制挂 trace 根下（parent_span_id=None）
          - 其他字符串：显式指定父 span_id（用于并发工具互不嵌套）
        """
        span_id = gen_uuid()
        event_id = gen_uuid()
        if parent == "root":
            parent_span_id = None
        elif isinstance(parent, str) and parent:
            parent_span_id = parent
        else:
            parent_span_id = self._span_stack[-1]["span_id"] if self._span_stack else None
        self._span_stack.append({
            "span_id": span_id,
            "event_id": event_id,
            "name": name,
            "span_type": span_type,
        })
        self._stats["spans"] += 1
        return {
            "span_id": span_id,
            "event_id": event_id,
            "parent_span_id": parent_span_id,
            "name": name,
            "span_type": span_type,
            "input": input,
            "model": model,
            "model_parameters": model_parameters,
            "tool_name": tool_name,
            "level": level,
            "metadata": metadata,
            "tags": tags,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def end_span(self, meta: dict[str, Any], *, output: Any = None,
                 error: Any = None, duration_ms: int = 0,
                 status: str = "success", error_info: dict | None = None,
                 time_to_first_token_ms: int | None = None) -> None:
        trace_id = self.active_trace_id
        if not trace_id:
            # 无活动 trace：仅出栈
            if self._span_stack and self._span_stack[-1]["span_id"] == meta["span_id"]:
                self._span_stack.pop()
            return
        self._emit_trace_event(SpanEvent(
            trace_id=trace_id,
            session_id=self._trace.get("session_id") if self._trace else None,
            span_id=meta["span_id"],
            event_id=meta.get("event_id"),
            parent_span_id=meta.get("parent_span_id"),
            name=meta.get("name", "span"),
            span_type=meta.get("span_type", "chain"),
            input=self._sanitize_content(meta.get("input")),
            output=self._sanitize_content(output),
            duration_ms=duration_ms,
            model=meta.get("model"),
            model_parameters=meta.get("model_parameters"),
            tool_name=meta.get("tool_name"),
            status=status,
            level=meta.get("level"),
            metadata=meta.get("metadata"),
            tags=meta.get("tags"),
            error_info=error_info,
            time_to_first_token_ms=time_to_first_token_ms,
            started_at=meta.get("started_at"),
            project_id=self.config.project_id,
        ))
        # 按 span_id 精确移除（并发场景下栈顶不一定是当前 span）
        for i in range(len(self._span_stack) - 1, -1, -1):
            if self._span_stack[i]["span_id"] == meta["span_id"]:
                self._span_stack.pop(i)
                break

    def add_observation(self, *, span_id: str | None, model: str | None,
                        prompt_tokens: int, completion_tokens: int,
                        input: Any = None, output: Any = None) -> None:
        trace_id = self.active_trace_id
        if not trace_id:
            return
        self._stats["prompt_tokens"] += prompt_tokens
        self._stats["completion_tokens"] += completion_tokens
        self._emit_trace_event(ObservationEvent(
            trace_id=trace_id,
            session_id=self._trace.get("session_id") if self._trace else None,
            span_id=span_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input=self._sanitize_content(input),
            output=self._sanitize_content(output),
            project_id=self.config.project_id,
        ))

    # ---- 工具 / 子 agent 计数 ----

    def record_llm_request(self, *, event_id: str, span_id: str | None = None,
                           model: str | None = None, input: Any = None,
                           output: Any = None, status: str = "success",
                           error_info: dict | None = None,
                           started_at: str | None = None) -> None:
        """上报真实 LLM 请求（采样感知，与 span/observation 同一裁决路径）。

        供中间件（RealLLMRequestMiddleware）调用；event_id 与 llm span 的 event_id 一致，
        作为关联键幂等落库。
        """
        trace_id = self.active_trace_id
        if not trace_id:
            return
        self._emit_trace_event(LLMRequestEvent(
            trace_id=trace_id,
            # 显式携带 session_id（与 SpanEvent 一致），file 模式 spn 目录据此稳定归位，
            # 不依赖 _trace_session 映射（跨 flush 批次顺序不确定会导致落 _no_session）
            session_id=self._trace.get("session_id") if self._trace else None,
            span_id=span_id,
            event_id=event_id,
            model=model,
            input=self._sanitize_content(input),
            output=self._sanitize_content(output),
            status=status,
            error_info=error_info,
            started_at=started_at,
            project_id=self.config.project_id,
        ))

    def flush(self) -> None:
        self.buffer.flush()

    def shutdown(self) -> None:
        self.flush()
        self.buffer.shutdown()
        if hasattr(self._exporter, "close"):
            self._exporter.close()


class TraceClient:
    """对外入口：创建采集器、获取中间件、关闭。

    进程级默认单例（对齐 langfuse `Langfuse()` 行为）：
      - `TraceClient({...})` 构造即注册为默认实例，之后 `CallbackHandler()` /
        `TraceClient.default_client()` 复用；
      - `shutdown()` 关闭后默认实例自动清除，下次构造/取值自动重建。
    一个项目通常只有一个采集实例，使用默认单例即可。
    """

    _default: "TraceClient | None" = None  # 进程级默认实例

    def __init__(self, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        # 对齐 langfuse：支持直接关键字传参 TraceClient(backend=..., project_id=...)
        merged: dict[str, Any] = dict(config or {})
        merged.update(kwargs)
        self.config = SDKConfig.from_env(**merged)
        self.collector = Collector(self.config)
        self._closed = False
        TraceClient._default = self  # 构造即注册为默认（对齐 langfuse）

    @classmethod
    def default_client(cls, config: dict[str, Any] | None = None, **kwargs: Any) -> "TraceClient":
        """返回默认实例；不存在或已关闭则新建。config 仅在新建时生效。"""
        if cls._default is None or cls._default._closed:
            merged: dict[str, Any] = dict(config or {})
            merged.update(kwargs)
            cls._default = cls(merged)
        return cls._default

    @classmethod
    def reset_default(cls) -> None:
        """清空默认实例引用（用于测试隔离/强制重建）。"""
        cls._default = None

    def middleware(self) -> Any:
        """已移除：deepagents middleware 路线已删除，统一用 callback 路线。"""
        raise NotImplementedError(
            "middleware 路线已移除，请用 config={'callbacks': [CallbackHandler()]} 采集"
        )

    @property
    def active_trace_id(self) -> str | None:
        """当前活动 trace_id（代理到 collector）。"""
        return self.collector.active_trace_id

    @property
    def current_span_id(self) -> str | None:
        """当前栈顶 span_id（供跨进程注入 parent_span_id，C21）。"""
        return self.collector.current_span_id

    def flush(self) -> None:
        self.collector.flush()

    def shutdown(self) -> None:
        self.collector.shutdown()
        self._closed = True
        if TraceClient._default is self:
            TraceClient._default = None
