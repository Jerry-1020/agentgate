"""数据库访问层：SQLAlchemy async engine + Session。

连接地址来自 config.DATABASE_URL（.env / 环境变量），无硬编码。
通过更换 URL 可在 PostgreSQL / SQLite 之间切换。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import DATABASE_URL

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """根据 DATABASE_URL 创建 async engine 与 session 工厂（幂等）。"""
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=5)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_engine() -> None:
    """应用关闭时释放连接池。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database engine not initialized")
    return _session_factory
