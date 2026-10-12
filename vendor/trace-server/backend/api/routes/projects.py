"""项目接口：项目列表 + 项目增删改查（支持数据库 / 文件两种后端）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_storage_backend
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from db.backends.base import StorageBackend

router = APIRouter()


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(backend: StorageBackend = Depends(get_storage_backend)):
    rows = await backend.list_projects()
    return [
        ProjectOut(id=r["id"], name=r["name"], description=r.get("description"))
        for r in rows
    ]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    backend: StorageBackend = Depends(get_storage_backend),
):
    """新建项目：后端自动生成 project_id（UUID），供 SDK 作为入参使用。"""
    row = await backend.create_project(body.name, body.description)
    return ProjectOut(id=row["id"], name=row["name"], description=row.get("description"))


@router.put("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    backend: StorageBackend = Depends(get_storage_backend),
):
    """更新项目名称/描述。"""
    row = await backend.update_project(project_id, body.name, body.description)
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ProjectOut(id=row["id"], name=row["name"], description=row.get("description"))


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    backend: StorageBackend = Depends(get_storage_backend),
):
    """删除项目（仅元数据，不删除其 trace 数据）。"""
    await backend.delete_project(project_id)


@router.get("/projects/{project_id}/agents")
async def list_agents(
    project_id: str,
    backend: StorageBackend = Depends(get_storage_backend),
):
    """返回指定项目下去重后的 agent 名称列表（供前端下拉全量展示）。"""
    return await backend.list_agents(project_id)
