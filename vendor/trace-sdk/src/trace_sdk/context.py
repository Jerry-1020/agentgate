"""上下文栈（context.py）。

用 contextvars.ContextVar 保存当前 Trace / Span 栈，进程内线程安全。
Span 自动挂到当前栈顶作为父节点，支持任意深度嵌套。
"""
from __future__ import annotations

import contextvars
from typing import Any

_current_trace: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "trace_ctx_current_trace", default=None
)
_span_stack: contextvars.ContextVar[list[dict[str, Any]]] = contextvars.ContextVar(
    "trace_ctx_span_stack", default=[]
)
# 运行标识（区分 agent/tool/subagent 等运行环境）
_current_run: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "trace_ctx_current_run", default=None
)


class TraceContext:
    """线程安全的上下文管理。"""

    # ---- Trace 级 ----
    @classmethod
    def start_trace(cls, trace_id: str, **meta: Any) -> None:
        _current_trace.set({"trace_id": trace_id, **meta})
        _span_stack.set([])

    @classmethod
    def end_trace(cls) -> None:
        _current_trace.set(None)
        _span_stack.set([])
        _current_run.set(None)

    @classmethod
    def current_trace(cls) -> dict[str, Any] | None:
        return _current_trace.get()

    @classmethod
    def trace_id(cls) -> str | None:
        t = _current_trace.get()
        return t["trace_id"] if t else None

    # ---- Span 级 ----
    @classmethod
    def start_span(cls, span_id: str, **meta: Any) -> str | None:
        """入栈，返回父 span_id（栈顶）。"""
        stack = _span_stack.get()
        parent = stack[-1]["span_id"] if stack else None
        entry = {"span_id": span_id, **meta}
        _span_stack.set([*stack, entry])
        return parent

    @classmethod
    def end_span(cls, span_id: str) -> None:
        stack = _span_stack.get()
        if stack and stack[-1]["span_id"] == span_id:
            _span_stack.set(stack[:-1])

    @classmethod
    def current_span_id(cls) -> str | None:
        stack = _span_stack.get()
        return stack[-1]["span_id"] if stack else None

    @classmethod
    def span_stack(cls) -> list[dict[str, Any]]:
        return list(_span_stack.get())

    # ---- Run 级（区分 agent / subagent / tool / remote）----
    @classmethod
    def start_run(cls, run_id: str, run_type: str, name: str, **meta: Any) -> None:
        _current_run.set({"run_id": run_id, "run_type": run_type, "name": name, **meta})

    @classmethod
    def end_run(cls) -> None:
        _current_run.set(None)

    @classmethod
    def current_run(cls) -> dict[str, Any] | None:
        return _current_run.get()
