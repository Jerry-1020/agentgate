"""内存缓冲 + 批量刷盘（buffer.py）。

后台线程定时/按量取出整批事件传给 Exporter，Agent 主流程零阻塞。
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

logger = logging.getLogger("trace_sdk.buffer")


class EventBuffer:
    def __init__(self, exporter: Any, *, size: int = 10000, batch_size: int = 100,
                 flush_interval: float = 2.0, discard_on_overflow: bool = True,
                 high_watermark: float = 0.0) -> None:
        self._exporter = exporter
        self._q: queue.Queue[Any] = queue.Queue(maxsize=size)
        # 采样观望缓冲：未命中采样、待 end_trace 裁决的 trace_id -> 其暂存事件。
        # 观望期间事件不进刷盘队列（避免 worker 提前刷出造成"应丢弃却落库"的时序竞争），
        # 裁决后 release_trace（放行）或 drop_trace（丢弃）。
        self._pending: dict[str, list[Any]] = {}
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._discard_on_overflow = discard_on_overflow
        self._size = size
        # 水位线（0~1）：缓冲事件数达到 size*水位线 时，worker 不等攒批立即整批刷出；0 = 关闭
        self._high_watermark = max(0.0, min(high_watermark, 1.0))
        self._stop = threading.Event()
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._worker, name="trace_sdk_buffer", daemon=True)
        self._thread.start()

    def _put_locked(self, event: Any) -> None:
        """入队（须持有 self._cv）；满时按 discard_on_overflow 丢最旧。"""
        try:
            self._q.put_nowait(event)
        except queue.Full:
            if self._discard_on_overflow:
                try:
                    self._q.get_nowait()
                    self._q.put_nowait(event)
                except queue.Empty:
                    pass
                logger.warning("缓冲区满，丢弃最旧事件（兜底）")

    def add(self, event: Any) -> None:
        """入队（微秒级）：只 put_nowait + notify，不碰网络/磁盘，主线程不被阻塞。"""
        with self._cv:
            self._put_locked(event)
            self._cv.notify()

    def add_pending(self, trace_id: str, event: Any) -> None:
        """观望暂存：未命中采样 trace 的事件先不入刷盘队列，等 end_trace 裁决。

        采样未命中时，trace 的 span/observation/session 事件都先放这里，
        避免 worker 提前刷出造成「应丢弃却落库」的时序竞争；
        裁决后由 release_trace（放行）或 drop_trace（丢弃）处理。
        """
        with self._cv:
            self._pending.setdefault(trace_id, []).append(event)

    def release_trace(self, trace_id: str) -> None:
        """裁决放行：命中采样 / 错误必采 → 观望事件进入刷盘队列。"""
        with self._cv:
            evs = self._pending.pop(trace_id, None)
            if evs:
                for ev in evs:
                    self._put_locked(ev)
                self._cv.notify()

    def _worker(self) -> None:
        pending: list[Any] = []
        while True:
            do_flush = False
            with self._cv:
                # 拿光当前队列，攒到 pending
                while True:
                    try:
                        pending.append(self._q.get_nowait())
                    except queue.Empty:
                        break
                if self._stop.is_set():
                    break
                # 触发刷盘的三种时机：攒够一批 / 达到水位线（预刷盘，不等攒批）/ 定时兜底
                if (
                    len(pending) >= self._batch_size
                    or (self._high_watermark > 0
                        and len(pending) >= self._size * self._high_watermark)
                ):
                    do_flush = True
                else:
                    # 锁在 wait 期间释放：add() 仍可随时入队/notify，互不阻塞。
                    # 定时兜底：攒批不足时等待 flush_interval，超时后如有数据则刷出
                    self._cv.wait(timeout=self._flush_interval)
                    if pending:
                        do_flush = True
            if do_flush and pending:
                self._flush(pending)
                pending = []
        if pending:
            self._flush(pending)

    def _flush(self, events: list[Any]) -> None:
        try:
            self._exporter.export(events)
        except Exception:
            logger.exception("事件刷盘失败，丢失 %d 条", len(events))

    def flush(self) -> None:
        """立即刷完队列（拿光当前剩余事件一次刷出）。"""
        pending: list[Any] = []
        with self._cv:
            while True:
                try:
                    pending.append(self._q.get_nowait())
                except queue.Empty:
                    break
        if pending:
            self._flush(pending)

    def drop_trace(self, trace_id: str) -> None:
        """丢弃某 trace 的全部事件（采样未命中、非错误必采时）。

        观望缓冲（_pending）里该 trace 的暂存事件直接丢弃。
        该 trace 的事件在裁决前不会进入刷盘队列（见 add_pending），
        因此无需（也无法）清理已刷出的数据。
        """
        with self._cv:
            self._pending.pop(trace_id, None)
        logger.debug("采样丢弃 trace %s 的事件", trace_id)

    def shutdown(self) -> None:
        """优雅关闭：先阻塞刷完剩余数据再退出（含 worker 手里攒的批）。"""
        with self._cv:
            self._stop.set()
            self._cv.notify_all()
        self.flush()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
