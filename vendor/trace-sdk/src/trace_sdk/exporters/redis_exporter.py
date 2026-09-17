"""Redis Stream Exporter（exporters/redis_exporter.py）。

写入 trace_topic，字段 data 存 JSON 字符串（与
trace_consumer/src/trace_consumer/redis_consumer.py 消费格式一致）。
单 topic：四类链路事件全部进 trace_topic，由 consumer 按 event_type 分表。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis

from .base import BaseExporter

logger = logging.getLogger("trace_sdk.exporter.redis")


class RedisExporter(BaseExporter):
    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._redis = redis.Redis.from_url(config.redis_url, decode_responses=False)
        self._topic = config.trace_topic

    def export(self, events: list[Any]) -> None:
        if not events:
            return
        pipe = self._redis.pipeline()
        for ev in events:
            payload = ev.to_dict() if hasattr(ev, "to_dict") else ev
            if self.config.debug:
                print("[trace_sdk] >>", json.dumps(payload, ensure_ascii=False, default=str), file=__import__("sys").stderr)
            pipe.xadd(self._topic, {"data": json.dumps(payload, ensure_ascii=False, default=str)})
        pipe.execute()
        logger.info("已写入 %d 条事件到 %s", len(events), self._topic)

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            pass
