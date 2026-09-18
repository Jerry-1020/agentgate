"""通用工具：UUID 生成、W3C traceparent 注入/提取。"""
from __future__ import annotations

import re
import uuid

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$")


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_trace_id() -> str:
    return uuid.uuid4().hex  # 32 位十六进制，用于 W3C traceparent


def gen_span_id() -> str:
    return uuid.uuid4().hex[:16]


def make_traceparent(trace_id: str, span_id: str) -> str:
    """生成 W3C traceparent：00-{trace_id}-{span_id}-01。"""
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """解析 traceparent，返回 (trace_id, parent_span_id)；格式非法返回 None。"""
    if not header:
        return None
    m = _TRACEPARENT_RE.match(header.strip())
    if not m:
        return None
    return m.group(1), m.group(2)
