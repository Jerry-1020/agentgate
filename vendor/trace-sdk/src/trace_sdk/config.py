"""Trace SDK 配置。

所有环境相关值通过环境变量或显式参数注入，代码内不保留任何硬编码连接串/密码。
环境变量优先于 dataclass 默认值，显式参数优先于环境变量。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env(key: str, default: Any = None) -> Any:
    return os.getenv(key, default)


def _parse_mask_rules(raw: str) -> dict[str, str | list[str]]:
    """解析 `TRACE_MASK_RULES` 环境变量（JSON 对象）。

    值可为正则字符串（整体打码 `***`），或 `[pattern, repl]` 数组（自定义替换串）：
      TRACE_MASK_RULES='{"bank_card":"\\\\d{16}"}'
      TRACE_MASK_RULES='{"bank_card":["(\\\\d{4})\\\\d{8}(\\\\d{4})","\\\\1****\\\\2"]}'
    """
    if not raw:
        return {}
    try:
        import json
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            out: dict[str, str | list[str]] = {}
            for k, v in parsed.items():
                if isinstance(v, list) and len(v) == 2:
                    out[str(k)] = [str(v[0]), str(v[1])]
                else:
                    out[str(k)] = str(v)
            return out
    except Exception:
        pass
    return {}


@dataclass
class SDKConfig:
    """SDK 全局配置。

    backend 支持：
      - "redis"：写入 Redis Stream（trace_topic），由 trace_consumer 消费入库
      - "kafka"：写入 Kafka（trace_topic），由 trace_consumer 消费入库
      - "file"：直写 JSON Lines 文件
      - "direct_db"：直写 PostgreSQL（复用 trace_consumer.writer 落库）

    上报通道统一为单 topic（trace_topic），与 03_SDK采集层实现.md 一致。

    注意：所有连接串/密码/项目标识均无硬编码默认值，必须通过环境变量或
    构造参数显式提供。未提供时 backend="file" 可免配置运行（用于本地调试）。
    """

    # ---- 基础 ----
    backend: str = "file"  # 默认 file，无需外部依赖即可本地调试
    project_id: str = ""   # 必须由调用方/环境变量提供
    agent_name: str = "agent"

    # ---- 上报通道（redis 模式）----
    redis_url: str = ""          # 必须由环境变量 REDIS_URL 提供
    trace_topic: str = "trace_topic"
    # ---- 上报通道（kafka 模式）----
    kafka_bootstrap: str = ""    # 必须由环境变量 KAFKA_BOOTSTRAP 提供
    # ---- 上报通道（file 模式）----
    output_file: str = "trace_data/sdk_events.jsonl"
    # ---- 上报通道（direct_db 模式）----
    database_url: str = ""       # 必须由环境变量 TRACE_DATABASE_URL 提供

    # ---- 缓冲 ----
    buffer_size: int = 10000
    batch_size: int = 100
    flush_interval: float = 2.0
    discard_on_overflow: bool = True
    # ---- 水位线（0~1）：队列使用率达到该比例立即预刷盘；0 = 关闭
    buffer_high_watermark: float = 0.0

    # ---- 采样（§G 采样：固定比例 + 错误必采）----
    # sample_rate: 0~1，基于 trace_id 哈希判定（确定性、并发安全），命中才记录；
    #              1.0 = 全采（默认）
    sample_rate: float = 1.0
    # error_force_record: 错误 trace 无论是否命中采样都强制记录（不因采样丢弃）
    error_force_record: bool = True

    # ---- 脱敏 ----
    mask_enabled: bool = True
    # 值可为 str（正则，整体打码 ***）或 [pattern, repl]（自定义替换串）
    mask_rules: dict[str, str | list | tuple] = field(default_factory=dict)

    # ---- 框架层隐藏（§5.6）----
    # False: 与 langfuse 一致，seq:step 层照常采集（DEFAULT level）
    # True:  seq:step / graph:step 层标为 DEBUG level（前端默认折叠），数据不丢
    hide_framework_steps: bool = False

    # ---- 调试 ----
    debug: bool = False

    @classmethod
    def from_env(cls, **overrides: Any) -> "SDKConfig":
        """从环境变量 + 显式覆盖构造配置。显式参数优先级最高。

        自定义脱敏规则通过 `TRACE_MASK_RULES`（JSON 对象）或显式 `mask_rules`
        参数传入；值可为正则字符串（整体打码 `***`）或 `[pattern, repl]`
        （自定义替换串），例如：
            TRACE_MASK_RULES='{"bank_card":"\\\\d{16}"}'
            TraceClient(backend=..., mask_rules={"bank_card": r"\\d{16}"})
            TraceClient(backend=..., mask_rules={"bank_card": [r"\\d{16}", "***"]})
        """
        cfg = cls(
            backend=_env("TRACE_BACKEND", "file"),
            project_id=_env("TRACE_PROJECT_ID", ""),
            agent_name=_env("TRACE_AGENT_NAME", "agent"),
            redis_url=_env("REDIS_URL", ""),
            trace_topic=_env("TRACE_TOPIC", "trace_topic"),
            kafka_bootstrap=_env("KAFKA_BOOTSTRAP", ""),
            output_file=_env("TRACE_OUTPUT_FILE", "trace_data/sdk_events.jsonl"),
            database_url=_env("TRACE_DATABASE_URL", ""),
            buffer_size=int(_env("TRACE_BUFFER_SIZE", 10000)),
            batch_size=int(_env("TRACE_BATCH_SIZE", 100)),
            flush_interval=float(_env("TRACE_FLUSH_INTERVAL", 2.0)),
            buffer_high_watermark=float(_env("TRACE_BUFFER_HIGH_WATERMARK", 0.0)),
            sample_rate=float(_env("TRACE_SAMPLE_RATE", 1.0)),
            error_force_record=_env("TRACE_ERROR_FORCE_RECORD", "1") == "1",
            mask_enabled=_env("TRACE_MASK_ENABLED", "1") == "1",
            mask_rules=_parse_mask_rules(_env("TRACE_MASK_RULES", "")),
            hide_framework_steps=_env("TRACE_HIDE_FRAMEWORK_STEPS", "0") == "1",
            debug=_env("TRACE_DEBUG", "0") == "1",
        )
        for k, v in overrides.items():
            if hasattr(cfg, k) and v is not None:
                setattr(cfg, k, v)
        return cfg
