"""Exporter 抽象基类（exporters/base.py）。

实现必须保证幂等（事件带 event_id，由消费端 ON CONFLICT DO NOTHING 保证）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExporter(ABC):
    def __init__(self, config: Any) -> None:
        self.config = config

    @abstractmethod
    def export(self, events: list[Any]) -> None:
        """把一批事件写入目标。"""
