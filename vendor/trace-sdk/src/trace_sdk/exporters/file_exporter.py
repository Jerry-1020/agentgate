"""直写文件 Exporter（exporters/file_exporter.py）。

JSON Lines 格式，供无中间件时的快速验证。

文件布局（一个 trace_id 一个文件，含该 trace 全部 4 类事件）：
  <data_dir>/<project_id>/<session_id>/<trace_id>.jsonl     # 有 session_id：二级目录为 session_id
  <data_dir>/<project_id>/_no_session/<trace_id>.jsonl      # 无 session_id（映射缺失时兜底）
  <data_dir>/_no_trace/<agent_name>.jsonl                   # 兜底：无 trace_id 的异常事件

关联机制：
- session_id 的唯一权威来源是 session / trace 事件（span/observation 无 session_id 字段）
- 收到 session 事件时建立 trace_id -> session_id 映射（start_trace 时 session 事件最先发出），
  后续 span/observation/trace 按所在 trace_id 归入同一 session 目录，保证一 trace 一文件不分裂
- 前端按 project/session/trace 查询由 file_backend 的内存索引承担，与目录解耦
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from .base import BaseExporter

logger = logging.getLogger("trace_sdk.exporter.file")

_SAFE = re.compile(r"[^0-9A-Za-z_\-\.]")
_SESSION_TYPE = "session"


class FileExporter(BaseExporter):
    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._root = Path(config.output_file)
        # 向后兼容：config.output_file 为文件路径时，取其所在目录
        if self._root.suffix == ".jsonl":
            self._root = self._root.parent
        self._root.mkdir(parents=True, exist_ok=True)
        # 并发保护：后台 flush 线程（export）与主线程（_handle 增删句柄）可能同时访问
        # _handles/_handle_order/_trace_session，必须持锁，否则遍历字典时被并发增删会
        # 抛 RuntimeError: dictionary changed size during iteration。
        self._lock = threading.RLock()
        # key -> 文件句柄缓存（路由用，避免每批重复打开）。
        # 有界 LRU：避免长跑时 trace 文件数无限增长导致文件描述符耗尽。
        self._handles: dict[str, Any] = {}
        self._handle_order: list[str] = []
        self._max_handles = int(getattr(config, "max_file_handles", 512))
        # trace_id -> session_id：trace 事件带 session_id，span/observation 的
        # session_id 可能为 None，需按所在 trace 归入同一目录（保证一 trace 一文件）
        self._trace_session: dict[str, str] = {}

    # ---- 路由 ----

    @staticmethod
    def _safe(seg: str, fallback: str) -> str:
        if seg is None:
            return fallback
        s = _SAFE.sub("_", str(seg))
        return s or fallback

    def _trace_path(self, ev: Any) -> Path:
        pid = self._safe(getattr(ev, "project_id", None) or "default", "default")
        tid = self._safe(getattr(ev, "trace_id", None) or getattr(ev, "id", None), "unknown")
        # span/observation 创建时即带 session_id（见 client.start_trace/start_span）；
        # 缺失时用所在 trace 记录的 session_id 兜底
        sid = getattr(ev, "session_id", None)
        if not sid:
            with self._lock:
                sid = self._trace_session.get(tid)
        sid_s = self._safe(sid, "unknown")
        if sid_s and sid_s != "unknown":
            return self._root / pid / sid_s / f"{tid}.jsonl"
        return self._root / pid / "_no_session" / f"{tid}.jsonl"

    def _fallback_path(self, ev: Any) -> Path:
        agent = self._safe(getattr(ev, "agent_name", None) or "agent", "agent")
        return self._root / "_no_trace" / f"{agent}.jsonl"

    def _spn_path(self, ev: Any) -> Path | None:
        """真实 LLM 请求专用：<session>/<trace_id>/spn/<event_id>.json（一事件一文件）。

        与 trace 文件同目录层级（<root>/<pid>/<sid>/<trace_id>/spn/），
        保证一 trace 一目录、spn 按 trace 天然隔离（不混在同 session 下）。
        """
        eid = getattr(ev, "event_id", None)
        if not eid:
            return None
        # 复用 trace 目录计算（同 project/session/trace），仅文件名换成 spn/<event_id>.json
        trace_file = self._trace_path(ev)
        spn_dir = trace_file.parent / trace_file.stem / "spn"
        return spn_dir / f"{eid}.json"

    def _handle(self, path: Path) -> Any:
        key = str(path)
        with self._lock:
            fh = self._handles.get(key)
            if fh is None:
                # 缓存有界：超限时淘汰最久未用句柄并关闭，防文件描述符耗尽
                while len(self._handles) >= self._max_handles and self._handle_order:
                    old = self._handle_order.pop(0)
                    old_fh = self._handles.pop(old, None)
                    if old_fh is not None:
                        try:
                            old_fh.close()
                        except Exception:
                            pass
                path.parent.mkdir(parents=True, exist_ok=True)
                fh = path.open("a", encoding="utf-8")
                self._handles[key] = fh
                self._handle_order.append(key)
            else:
                # 刷新 LRU 顺序
                if key in self._handle_order:
                    self._handle_order.remove(key)
                self._handle_order.append(key)
        return fh

    def export(self, events: list[Any]) -> None:
        if not events:
            return
        for ev in events:
            try:
                payload = ev.to_dict() if hasattr(ev, "to_dict") else ev
                line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
                etype = getattr(ev, "event_type", None)
                tid = getattr(ev, "trace_id", None) or getattr(ev, "id", None)
                # session / trace 事件带 session_id：建立或刷新 trace_id -> session_id 映射
                # （start_trace 时 session 事件最先发出，后续 span/obs 可据此归入同目录）
                if etype in ("session", "trace") and tid:
                    sid = getattr(ev, "session_id", None)
                    if sid:
                        with self._lock:
                            self._trace_session[str(tid)] = sid
                if etype == "llm_request":
                    # 真实 LLM 请求：写入 <session>/<trace_id>/spn/<event_id>.json（一 trace 一目录）
                    spn = self._spn_path(ev)
                    if spn is not None:
                        self._handle(spn).write(line)
                    continue
                if tid or etype == _SESSION_TYPE:
                    path = self._trace_path(ev)
                else:
                    path = self._fallback_path(ev)
                self._handle(path).write(line)
            except Exception:
                logger.exception("写文件失败，丢弃 1 条事件")
        # 每批 flush，保证内容即时可见（避免崩溃时丢失缓冲数据）
        with self._lock:
            for fh in self._handles.values():
                try:
                    fh.flush()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            for fh in self._handles.values():
                try:
                    fh.close()
                except Exception:
                    pass
            self._handles.clear()
            self._handle_order.clear()
