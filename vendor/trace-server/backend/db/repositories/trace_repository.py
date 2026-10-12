"""Trace/Span/Observation 仓储：封装列表、详情、调用树查询。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LlmRequest, Observation, Project, Span, Trace


class TraceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_projects(self) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(Project.id, Project.name, Project.description).order_by(Project.created_at)
        )
        return [
            {"id": str(r.id), "name": r.name, "description": r.description}
            for r in rows
        ]

    async def create_project(
        self, name: str, description: str | None = None
    ) -> dict[str, Any]:
        """新建项目，id 由后端生成 UUID。返回新建的项目记录。"""
        project = Project(id=uuid.uuid4(), name=name, description=description)
        self._session.add(project)
        await self._session.flush()
        # 每个请求独立 session（见 deps.get_session），必须显式提交，否则 session 关闭即回滚
        await self._session.commit()
        return {"id": str(project.id), "name": project.name, "description": project.description}

    async def update_project(
        self, project_id: str, name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新项目名称/描述，仅更新提供的字段。"""
        project = await self._session.scalar(
            select(Project).where(Project.id == project_id)
        )
        if project is None:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        await self._session.flush()
        await self._session.commit()
        return {"id": str(project.id), "name": project.name, "description": project.description}

    async def delete_project(self, project_id: str) -> bool:
        """删除项目记录（仅元数据，不删除其 trace 数据）。返回是否删除。"""
        project = await self._session.scalar(
            select(Project).where(Project.id == project_id)
        )
        if project is None:
            return False
        await self._session.delete(project)
        await self._session.flush()
        await self._session.commit()
        return True

    async def list_agents(self, project_id: str) -> list[str]:
        """返回去重后的 agent_name 列表（按项目过滤）。"""
        stmt = select(Trace.agent_name).distinct().order_by(Trace.agent_name)
        if project_id and project_id != "all":
            stmt = stmt.where(Trace.project_id.in_(project_id.split(",")))
        rows = await self._session.scalars(stmt)
        return [str(r) for r in rows if r]

    async def list_traces(
        self,
        project_id: str,
        page: int = 1,
        page_size: int = 20,
        agent_name: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[list[Trace], int]:
        """分页查询 traces，返回 (行列表, 总数)。

        project_id 支持 "all"（不过滤）或逗号分隔的多个项目 ID。
        """
        conds: list = []
        if project_id and project_id != "all":
            conds.append(Trace.project_id.in_(project_id.split(",")))
        if agent_name:
            conds.append(Trace.agent_name == agent_name)
        if status:
            conds.append(Trace.status == status)
        # session_id / trace_id 支持子串模糊匹配（同一输入框可查任意 ID）。
        # 二者为 OR 关系：输入一个关键词，命中 trace_id 或 session_id 任一即返回。
        # UUID 列需 cast 为文本后 ILIKE（PostgreSQL 不支持 uuid ~~* uuid）
        if session_id or trace_id:
            keyword = session_id or trace_id
            conds.append(
                or_(
                    cast(Trace.session_id, String).ilike(f"%{keyword}%"),
                    cast(Trace.id, String).ilike(f"%{keyword}%"),
                )
            )
        cond = and_(*conds)

        total = await self._session.scalar(select(func.count()).select_from(Trace).where(cond)) or 0
        stmt = (
            select(Trace)
            .where(cond)
            .order_by(Trace.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self._session.scalars(stmt)).all()
        return list(rows), total

    async def get_trace(self, project_id: str, trace_id: str) -> Trace | None:
        """按 id 查 trace；project_id 为 "all" 时不按项目过滤。"""
        stmt = select(Trace).where(Trace.id == trace_id)
        if project_id and project_id != "all":
            stmt = stmt.where(Trace.project_id.in_(project_id.split(",")))
        return await self._session.scalar(stmt)

    async def get_spans(self, trace_id: str) -> list[Span]:
        stmt = select(Span).where(Span.trace_id == trace_id).order_by(Span.created_at)
        return list((await self._session.scalars(stmt)).all())

    async def get_observations(self, trace_id: str) -> list[Observation]:
        stmt = (
            select(Observation)
            .where(Observation.trace_id == trace_id)
            .order_by(Observation.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def get_token_totals(
        self, trace_ids: list[str]
    ) -> dict[str, dict[str, int]]:
        """按 trace_id 实时聚合 observations 的 token 用量。

        返回 {trace_id: {"prompt_tokens": n, "completion_tokens": n}}。
        跨进程/子 agent 上报的 observation 都会计入，避免 SDK 单进程
        total_tokens 汇总漏计（见多数据源方案）。
        """
        if not trace_ids:
            return {}
        rows = await self._session.execute(
            select(
                Observation.trace_id,
                func.coalesce(func.sum(Observation.prompt_tokens), 0),
                func.coalesce(func.sum(Observation.completion_tokens), 0),
            )
            .where(Observation.trace_id.in_(trace_ids))
            .group_by(Observation.trace_id)
        )
        return {
            str(trace_id): {
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
            }
            for trace_id, prompt, completion in rows.all()
        }

    async def get_llm_requests(
        self, trace_id: str, span_id: str | None = None
    ) -> list[LlmRequest]:
        stmt = (
            select(LlmRequest)
            .where(LlmRequest.trace_id == trace_id)
            .order_by(LlmRequest.started_at)
        )
        if span_id:
            stmt = stmt.where(LlmRequest.span_id == span_id)
        return list((await self._session.scalars(stmt)).all())
