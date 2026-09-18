"""Kafka Exporter（exporters/kafka_exporter.py）。

写入 Kafka 的 trace_topic，value 存 JSON 字节（与
trace_consumer/src/trace_consumer/kafka_consumer.py 消费格式一致）。
单 topic：四类链路事件全部进 trace_topic，由 consumer 按 event_type 分表。

用法：backend="kafka"，并指定 bootstrap_servers（KAFKA_BOOTSTRAP 或参数）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from kafka import KafkaProducer

from .base import BaseExporter

logger = logging.getLogger("trace_sdk.exporter.kafka")


class KafkaExporter(BaseExporter):
    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._producer = KafkaProducer(
            bootstrap_servers=config.kafka_bootstrap,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False, default=str).encode("utf-8"),
            acks="all",
        )
        self._topic = config.trace_topic

    def export(self, events: list[Any]) -> None:
        if not events:
            return
        for ev in events:
            payload = ev.to_dict() if hasattr(ev, "to_dict") else ev
            if self.config.debug:
                print("[trace_sdk] >>", json.dumps(payload, ensure_ascii=False, default=str), file=__import__("sys").stderr)
            self._producer.send(self._topic, value=payload)
        # 阻塞 flush，确保批次送达（与 buffer 后台线程同步调用契约一致）
        self._producer.flush(timeout=10)
        logger.info("已写入 %d 条事件到 Kafka %s", len(events), self._topic)

    def close(self) -> None:
        try:
            self._producer.flush(timeout=10)
            self._producer.close(timeout=10)
        except Exception:
            pass
