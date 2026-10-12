"""database 存储后端：基于现有 SQLAlchemy Repository 的查询实现。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.trace_repository import TraceRepository
from .base import StorageBackend, TraceData


def _decode_jsonb(value: Any) -> Any:
    """ORM jsonb 字段默认以 str 返回，前端需要原生对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class DatabaseBackend(StorageBackend):
    def __init__(self, session: AsyncSession):
        self._trace_repo = TraceRepository(session)

    # ---- Trace 查询 ----

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self._trace_repo.list_projects()

    async def create_project(
        self, name: str, description: str | None = None
    ) -> dict[str, Any]:
        return await self._trace_repo.create_project(name, description)

    async def update_project(
        self, project_id: str, name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._trace_repo.update_project(project_id, name, description)

    async def delete_project(self, project_id: str) -> None:
        await self._trace_repo.delete_project(project_id)

    async def list_agents(self, project_id: str) -> list[str]:
        return await self._trace_repo.list_agents(project_id)

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
        rows, total = await self._trace_repo.list_traces(
            project_id,
            page=page,
            page_size=page_size,
            agent_name=agent_name,
            status=status,
            session_id=session_id,
            trace_id=trace_id,
        )
        # ORM → dict（Route 层不再依赖 ORM）
        items = [_trace_dict(t) for t in rows]
        await self._apply_token_totals(items)
        return items, total

    async def _apply_token_totals(self, items: list[dict[str, Any]]) -> None:
        """把 observations 实时聚合的 token 用量覆盖到 trace dict。

        traces 表的 total_tokens 是 SDK 单进程汇总，跨进程子 agent 会漏计；
        查询时按 trace_id SUM observations 才能得到全量正确值。
        """
        if not items:
            return
        ids = [str(t["id"]) for t in items]
        totals = await self._trace_repo.get_token_totals(ids)
        for t in items:
            agg = totals.get(t["id"])
            prompt = agg["prompt_tokens"] if agg else 0
            completion = agg["completion_tokens"] if agg else 0
            t["total_tokens"] = prompt + completion
            t["prompt_tokens"] = prompt
            t["completion_tokens"] = completion

    async def get_trace(self, project_id: str, trace_id: str) -> dict[str, Any] | None:
        t = await self._trace_repo.get_trace(project_id, trace_id)
        if t is None:
            return None
        item = _trace_dict(t)
        await self._apply_token_totals([item])
        return item

    async def get_trace_detail(
        self, project_id: str, trace_id: str
    ) -> TraceData | None:
        t = await self._trace_repo.get_trace(project_id, trace_id)
        if t is None:
            return None
        spans = await self._trace_repo.get_spans(trace_id)
        obs = await self._trace_repo.get_observations(trace_id)
        trace = _trace_dict(t)
        await self._apply_token_totals([trace])
        return TraceData(
            trace=trace,
            spans=[_span_dict(s) for s in spans],
            observations=[_obs_dict(o) for o in obs],
        )

    async def get_llm_requests(
        self, project_id: str, trace_id: str, span_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = await self._trace_repo.get_llm_requests(trace_id, span_id=span_id)
        return [_llm_request_dict(r) for r in rows]


# ---- ORM 对象 → dict ----

def _trace_dict(t: Any) -> dict:
    return {
        "id": str(t.id),
        "project_id": str(t.project_id),
        "name": t.name,
        "agent_name": t.agent_name,
        "input": _decode_jsonb(t.input),
        "output": _decode_jsonb(t.output),
        "duration_ms": t.duration_ms,
        "react_step_count": t.react_step_count,
        "tool_count": t.tool_count,
        "span_count": t.span_count,
        "session_id": t.session_id,
        "status": t.status,
        "error_info": t.error_info,
        "started_at": t.started_at,
        "created_at": t.created_at,
    }


def _span_dict(s: Any) -> dict:
    return {
        "id": str(s.id),
        "event_id": str(s.event_id),
        "trace_id": str(s.trace_id),
        "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
        "name": s.name,
        "span_type": s.span_type,
        "input": _decode_jsonb(s.input),
        "output": _decode_jsonb(s.output),
        "duration_ms": s.duration_ms,
        "model": s.model,
        "tool_name": s.tool_name,
        "status": s.status,
        "error_info": s.error_info,
        "started_at": s.started_at,
        "created_at": s.created_at,
    }


def _llm_request_dict(r: Any) -> dict:
    return {
        "event_id": str(r.event_id),
        "id": str(r.id),
        "trace_id": str(r.trace_id),
        "span_id": str(r.span_id) if r.span_id else None,
        "model": r.model,
        "input": _decode_jsonb(r.input),
        "output": _decode_jsonb(r.output),
        "status": r.status,
        "error_info": r.error_info,
        "started_at": r.started_at,
    }


def _obs_dict(o: Any) -> dict:
    return {
        "id": str(o.id),
        "span_id": str(o.span_id) if o.span_id else None,
        "model": o.model,
        "prompt_tokens": o.prompt_tokens,
        "completion_tokens": o.completion_tokens,
        "input": _decode_jsonb(o.input),
        "output": _decode_jsonb(o.output),
    }
