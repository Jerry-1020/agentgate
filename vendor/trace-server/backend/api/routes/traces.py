"""Trace 接口：列表 / 详情 / 调用树（经存储后端访问数据）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_storage_backend
from ..helpers import (
    build_tree,
    llm_request_out,
    observation_out,
    span_out,
    trace_out,
)
from ..schemas import (
    LlmRequestsOut,
    TraceDetailOut,
    TraceListOut,
    TraceTreeOut,
)
from db.backends.base import StorageBackend

router = APIRouter()


@router.get("/projects/{project_id}/traces", response_model=TraceListOut)
async def list_traces(
    project_id: str,
    page: int = 1,
    page_size: int = 20,
    agent_name: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    backend: StorageBackend = Depends(get_storage_backend),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    rows, total = await backend.list_traces(
        project_id,
        page=page,
        page_size=page_size,
        agent_name=agent_name,
        status=status,
        session_id=session_id,
        trace_id=trace_id,
    )
    return TraceListOut(
        items=[trace_out(t) for t in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/projects/{project_id}/traces/{trace_id}", response_model=TraceDetailOut)
async def get_trace_detail(
    project_id: str,
    trace_id: str,
    backend: StorageBackend = Depends(get_storage_backend),
):
    # 详情按 trace_id 直查（跨项目可见，不按 project_id 过滤）
    data = await backend.get_trace_detail("all", trace_id)
    if data is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return TraceDetailOut(
        trace=trace_out(data.trace),
        spans=[span_out(s) for s in data.spans],
        observations=[observation_out(o) for o in data.observations],
    )


@router.get("/projects/{project_id}/traces/{trace_id}/tree", response_model=TraceTreeOut)
async def get_trace_tree(
    project_id: str,
    trace_id: str,
    backend: StorageBackend = Depends(get_storage_backend),
):
    # 调用树按 trace_id 直查（跨项目可见，不按 project_id 过滤）
    data = await backend.get_trace_detail("all", trace_id)
    if data is None:
        raise HTTPException(status_code=404, detail="trace not found")
    span_list = [span_out(s) for s in data.spans]
    return TraceTreeOut(trace=trace_out(data.trace), tree=build_tree(span_list))


@router.get(
    "/projects/{project_id}/traces/{trace_id}/llm_requests",
    response_model=LlmRequestsOut,
)
async def get_trace_llm_requests(
    project_id: str,
    trace_id: str,
    span_id: str | None = None,
    backend: StorageBackend = Depends(get_storage_backend),
):
    # 真实 LLM 请求按 trace_id 直查（跨项目可见，不按 project_id 过滤）
    items = await backend.get_llm_requests("all", trace_id, span_id=span_id)
    return LlmRequestsOut(items=[llm_request_out(r) for r in items])
