"""直写 PostgreSQL Exporter（exporters/database_exporter.py）。

backend="direct_db" 时复用 trace_consumer 的 writer.handle_event 落库逻辑，
SDK 侧不写一行 SQL：只负责"何时把哪些事件交给 writer"，
解析、映射、分表、幂等全部由复用的 writer 完成（见
implementation_plan/docs/08_SDK_direct_db设计方案.md）。

线程衔接（关键差异）：
  - buffer 的后台 worker 线程同步调用 export(events)，这是 BaseExporter 硬契约
    （file/redis 都是同步实现）；
  - 但 writer/db 是 asyncpg 异步的。因此本 exporter 内部自持一个专属后台线程 +
    asyncio 事件循环，把 export() 里的异步 handle_event 通过
    asyncio.run_coroutine_threadsafe 提交到该循环执行并阻塞等待，对外保持同步。
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from .base import BaseExporter

logger = logging.getLogger("trace_sdk.exporter.database")

# trace_consumer 包根目录（repo 下 trace_consumer/src）。SDK 运行目录未必把
# trace_consumer/src 加入 sys.path，这里按同仓布局自动补路径，保证可 import。
_CONSUMER_SRC = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "trace_consumer" / "src"
)


def _import_consumer():
    """懒加载并返回 (db, writer)，必要时把 trace_consumer/src 加入 sys.path。"""
    try:
        import trace_consumer.db as _db
        import trace_consumer.writer as _writer
    except (ModuleNotFoundError, ImportError):
        # 首次失败可能已把残缺的 trace_consumer 包登记进 sys.modules，
        # 先清除再补路径重试，避免复用错误的父包定位不到子模块。
        sys.modules.pop("trace_consumer", None)
        sys.modules.pop("trace_consumer.db", None)
        sys.modules.pop("trace_consumer.writer", None)
        sys.path.insert(0, str(_CONSUMER_SRC))
        import trace_consumer.db as _db
        import trace_consumer.writer as _writer
    return _db, _writer


class DatabaseExporter(BaseExporter):
    """直写 PostgreSQL，复用 trace_consumer 的 writer 落库逻辑。"""

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._db, self._writer = _import_consumer()
        # SDK 显式给 database_url 时，覆盖 consumer 的 DATABASE_URL 来源
        if getattr(config, "database_url", ""):
            os.environ["DATABASE_URL"] = config.database_url
            self._db.DATABASE_URL = config.database_url
        # 专属后台线程 + asyncio 事件循环
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run_loop, name="trace_sdk_db_exporter", daemon=True
        )
        self._thread.start()
        # 等待事件循环就绪并完成连接池初始化
        self._ready.wait(timeout=10)
        if self._error:
            raise self._error

    # ---- 后台线程：事件循环 + 连接池 ----
    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._db.init_pool())
        except BaseException as exc:  # noqa: BLE001 - 传播给主线程构造失败
            self._error = exc
        finally:
            self._ready.set()
        if self._error is None:
            self._loop.run_forever()
            # run_forever 退出后收尾：关闭池、关闭循环
            self._loop.run_until_complete(self._db.close_pool())
            self._loop.close()

    def _call(self, coro: Any) -> Any:
        """把异步任务提交到专属事件循环并阻塞等待结果。"""
        if self._loop is None:
            raise RuntimeError("database exporter 事件循环未就绪")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    # ---- 实现 BaseExporter 契约 ----
    def export(self, events: list[Any]) -> None:
        if not events:
            return
        payloads = [ev.to_dict() if hasattr(ev, "to_dict") else ev for ev in events]
        self._call(self._write_batch(payloads))
        logger.info("已直写 %d 条事件到 PostgreSQL", len(events))

    async def _write_batch(self, payloads: list[dict[str, Any]]) -> None:
        # 复用 consumer writer.handle_event，逐条落库（内部含 ensure_project / 分表 / 幂等）
        for ev in payloads:
            await self._writer.handle_event(ev)

    def close(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        self._loop = None
