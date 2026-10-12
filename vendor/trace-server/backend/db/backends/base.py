"""存储后端抽象：统一"读取 trace 数据"接口。

database / file 后端都实现这些方法，路由层只依赖本抽象（Repository Pattern）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TraceRow(dict):
    """一行 trace 数据（普通 dict，便于序列化）。"""


class TraceData:
    """一次 trace 的完整数据（含 spans / observations）。"""

    def __init__(
        self,
        trace: dict[str, Any],
        spans: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ):
        self.trace = trace
        self.spans = spans
        self.observations = observations


class StorageBackend(ABC):
    """存储后端统一接口（当前只读场景：查询展示）。"""

    @abstractmethod
    async def list_projects(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def create_project(
        self, name: str, description: str | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def update_project(
        self, project_id: str, name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def delete_project(self, project_id: str) -> None: ...

    @abstractmethod
    async def list_agents(self, project_id: str) -> list[str]: ...

    @abstractmethod
    async def list_traces(
        self,
        project_id: str,
        page: int = 1,
        page_size: int = 20,
        agent_name: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    @abstractmethod
    async def get_trace(self, project_id: str, trace_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def get_trace_detail(
        self, project_id: str, trace_id: str
    ) -> TraceData | None: ...

    @abstractmethod
    async def get_llm_requests(
        self, project_id: str, trace_id: str, span_id: str | None = None
    ) -> list[dict[str, Any]]: ...
