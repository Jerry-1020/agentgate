"""存储后端包：统一数据访问接口，按配置选择 database / file 后端。"""
from __future__ import annotations

from config import STORAGE_BACKEND

from .base import StorageBackend, TraceData
from .database_backend import DatabaseBackend
from .file_backend import FileBackend


def create_storage_backend(*args, **kwargs) -> StorageBackend:
    """按 STORAGE_BACKEND 配置创建后端实例。

    - database：需要 AsyncSession（由路由依赖注入传入）
    - file    ：无需连接，直接读 DATA_FILE 目录
    """
    if STORAGE_BACKEND == "database":
        return DatabaseBackend(*args, **kwargs)
    if STORAGE_BACKEND == "file":
        return FileBackend()
    raise RuntimeError(f"未知存储后端: {STORAGE_BACKEND!r}")


__all__ = [
    "StorageBackend",
    "TraceData",
    "DatabaseBackend",
    "FileBackend",
    "create_storage_backend",
]
