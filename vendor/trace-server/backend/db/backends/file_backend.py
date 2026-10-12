"""file 存储后端：索引 + 惰性读文件（按需加载方案 B）。

读取策略（相对旧版"每请求全量重扫"的优化）：
- 索引懒加载：只解析每个 trace 文件里的 `event_type=trace` 行，
  得 trace_id → 完整 trace 摘要（token 统计由 SDK 写在 trace 事件内，列表页无需聚合）。
  列表 / 项目 / agent 查询走索引，复杂度 O(索引量) 而非 O(全量行)。
- 惰性读文件：详情 / llm_request 按 trace_id 精准读 1 个文件或该 trace 目录的 spn/*.json。
- 表查询（spans/observations/sessions 表）：仅在访问这些表时全扫（按需，非每请求）。

目录布局（SDK 写入）：
  <DATA_FILE>/<project_id>/<session_id>/<trace_id>.jsonl              # 有 session_id
  <DATA_FILE>/<project_id>/_no_session/<trace_id>.jsonl               # 无 session_id
  <DATA_FILE>/<project_id>/<session_id>/<trace_id>/spn/<event_id>.json  # 真实 LLM 请求
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from config import DATA_FILE
from .base import StorageBackend, TraceData

# JSONL 中 event_type → 类型
_EVENT_TRACE = "trace"
_EVENT_SPAN = "span"
_EVENT_OBSERVATION = "observation"
_EVENT_SESSION = "session"
_EVENT_LLM_REQUEST = "llm_request"

# 项目元数据文件：存放前端创建/编辑的项目名称与描述（SDK 直写 JSONL 之外的补充）
_PROJECTS_META_FILE = "projects.json"


class FileBackend(StorageBackend):
    def __init__(self, data_dir: str | Path | None = None):
        self._data_dir = Path(data_dir or DATA_FILE)
        # 懒加载索引：trace_id → trace 事件 dict（完整，含 SDK 自带的 token 统计）
        self._traces: dict[str, dict[str, Any]] = {}
        # trace_id → 所在文件路径（详情/llm_request 精准读）
        self._trace_files: dict[str, Path] = {}
        # 真实 LLM 请求（spn/<event_id>.json），key=event_id（按需读单 trace 目录）
        self._llm_requests: dict[str, dict[str, Any]] = {}
        # 项目元数据（id → {name, description}），读写 projects.json 持久化
        self._projects_meta: dict[str, dict[str, Any]] = {}
        # 索引指纹：目录文件清单 + 各文件 (size, mtime)，变了才重建
        self._fingerprint: Any = None
        self._ensure_index()
        self._load_projects_meta()

    @property
    def _projects_meta_path(self) -> Path:
        return self._data_dir / _PROJECTS_META_FILE

    def _load_projects_meta(self) -> None:
        """读取项目元数据文件（若存在）。"""
        path = self._projects_meta_path
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._projects_meta = data
        except (json.JSONDecodeError, OSError):
            self._projects_meta = {}

    def _save_projects_meta(self) -> None:
        """将项目元数据写回 projects.json。"""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._projects_meta_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._projects_meta, fh, ensure_ascii=False, indent=2)
        tmp.replace(self._projects_meta_path)

    # ---- 索引（懒加载） ----

    def _compute_fingerprint(self) -> Any | None:
        """目录指纹：文件相对路径 → (size, mtime)。变化即需重建索引。"""
        if not self._data_dir.exists():
            return None
        fp: dict[str, tuple[int, float]] = {}
        for f in self._data_dir.rglob("*.jsonl"):
            try:
                st = f.stat()
                fp[str(f.relative_to(self._data_dir))] = (st.st_size, st.st_mtime)
            except OSError:
                continue
        return fp

    def _ensure_index(self) -> None:
        """懒加载索引：指纹没变直接复用；变了只解析 trace 行。"""
        fp = self._compute_fingerprint()
        if fp == self._fingerprint:
            return
        self._fingerprint = fp
        self._traces.clear()
        self._trace_files.clear()
        if fp is None:
            return
        for f in sorted(self._data_dir.rglob("*.jsonl")):
            self._index_file(f)

    def _index_file(self, path: Path) -> None:
        """只解析一个文件里的 trace 行（跳过 span/obs/session）。"""
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("event_type")
                    if etype == _EVENT_TRACE:
                        tid = ev.get("trace_id") or ev.get("id")
                        if tid:
                            ev.setdefault("id", str(tid))
                            self._traces[str(tid)] = ev
                            self._trace_files[str(tid)] = path
        except OSError:
            pass

    # ---- 惰性读文件 ----

    def _read_trace_file(self, path: Path) -> list[dict[str, Any]]:
        """读单个 trace 文件全部事件行（详情用，每次读盘保证最新）。"""
        events: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    events.append(ev)
        except OSError:
            pass
        return events

    def _read_llm_requests(self, trace_id: str) -> list[dict[str, Any]]:
        """按 trace 精准读其目录下 spn/*.json（一事件一文件）。

        spn 与 trace 文件同目录层级（<session>/<trace_id>/spn/），一 trace 一目录，
        天然按 trace 隔离，无需按文件内容过滤（与 database 模式语义一致）。
        """
        path = self._trace_files.get(trace_id)
        if path is None:
            return []
        spn_dir = path.parent / path.stem / "spn"
        if not spn_dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for f in sorted(spn_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    ev = json.load(fh)
                if isinstance(ev, dict):
                    out.append(ev)
            except (json.JSONDecodeError, OSError):
                continue
        return out

    # ---- 统一查询接口 ----

    async def list_projects(self) -> list[dict[str, Any]]:
        self._ensure_index()
        # 从索引里的 trace 记录聚合真实 project_id
        ids: list[str] = []
        for t in self._traces.values():
            pid = str(t.get("project_id") or "default")
            if pid not in ids:
                ids.append(pid)
        # 补充元数据文件中已创建但尚无 trace 的项目
        for pid in self._projects_meta:
            if pid not in ids:
                ids.append(pid)
        if not ids:
            ids = ["default"]
        return [
            {
                "id": pid,
                "name": self._project_name(pid),
                "description": self._projects_meta.get(pid, {}).get("description"),
            }
            for pid in ids
        ]

    def _project_name(self, pid: str) -> str:
        """项目显示名：优先元数据文件，其次按 id 截断。"""
        meta = self._projects_meta.get(pid)
        if meta and meta.get("name"):
            return meta["name"]
        return "默认项目（文件模式）" if pid == "default" else f"项目 {pid[:8]}"

    async def create_project(
        self, name: str, description: str | None = None
    ) -> dict[str, Any]:
        pid = str(uuid.uuid4())
        self._projects_meta[pid] = {"name": name, "description": description}
        self._save_projects_meta()
        return {"id": pid, "name": name, "description": description}

    async def update_project(
        self, project_id: str, name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        entry = self._projects_meta.setdefault(project_id, {})
        if name is not None:
            entry["name"] = name
        if description is not None:
            entry["description"] = description
        self._save_projects_meta()
        return {"id": project_id, "name": entry.get("name", self._project_name(project_id)),
                "description": entry.get("description")}

    async def delete_project(self, project_id: str) -> None:
        if project_id in self._projects_meta:
            del self._projects_meta[project_id]
            self._save_projects_meta()

    async def list_agents(self, project_id: str) -> list[str]:
        """返回去重后的 agent_name 列表（按项目过滤，走索引）。"""
        self._ensure_index()
        names: list[str] = []
        if project_id and project_id != "all":
            allowed = set(project_id.split(","))
            traces = (
                t for t in self._traces.values()
                if str(t.get("project_id") or "default") in allowed
            )
        else:
            traces = self._traces.values()
        for t in traces:
            name = str(t.get("agent_name") or "")
            if name and name not in names:
                names.append(name)
        return names

    async def list_traces(
        self,
        project_id: str,
        page: int = 1,
        page_size: int = 20,
        agent_name: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_index()
        items = self._traces.values()
        # project_id 支持 "all" 或逗号分隔多值
        if project_id and project_id != "all":
            allowed = set(project_id.split(","))
            items = [
                t for t in items
                if str(t.get("project_id") or "default") in allowed
            ]
        # 关键词：trace_id / session_id 任一命中即返回（OR 语义）
        if session_id or trace_id:
            items = [
                t for t in items
                if (trace_id and trace_id in str(t.get("trace_id") or t.get("id") or ""))
                or (session_id and session_id in str(t.get("session_id") or ""))
            ]
        if agent_name:
            items = [t for t in items if t.get("agent_name") == agent_name]
        if status:
            items = [t for t in items if t.get("status") == status]
        items = list(items)
        # 按时间倒序（无则保持文件顺序）
        items.sort(key=lambda t: t.get("created_at") or t.get("started_at") or "", reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        # token 统计 SDK 已写在 trace 事件内（total_tokens/prompt_tokens/completion_tokens），无需聚合
        return page_items, total

    async def get_trace(self, project_id: str, trace_id: str) -> dict[str, Any] | None:
        self._ensure_index()
        return self._traces.get(trace_id)

    async def get_trace_detail(
        self, project_id: str, trace_id: str
    ) -> TraceData | None:
        self._ensure_index()
        trace = self._traces.get(trace_id)
        if trace is None:
            return None
        # 惰性读单文件：每次读盘拿到最新（新追加的 span/obs 也在）
        path = self._trace_files.get(trace_id)
        spans: list[dict[str, Any]] = []
        obs: list[dict[str, Any]] = []
        if path is not None:
            for ev in self._read_trace_file(path):
                if ev.get("event_type") == _EVENT_SPAN and str(ev.get("trace_id")) == trace_id:
                    spans.append(ev)
                elif ev.get("event_type") == _EVENT_OBSERVATION and str(ev.get("trace_id")) == trace_id:
                    obs.append(ev)
        return TraceData(trace=trace, spans=spans, observations=obs)

    async def get_llm_requests(
        self, project_id: str, trace_id: str, span_id: str | None = None
    ) -> list[dict[str, Any]]:
        self._ensure_index()
        items = self._read_llm_requests(trace_id)
        if span_id:
            items = [ev for ev in items if str(ev.get("span_id")) == span_id]
        items.sort(key=lambda ev: ev.get("started_at") or ev.get("created_at") or "")
        return items
