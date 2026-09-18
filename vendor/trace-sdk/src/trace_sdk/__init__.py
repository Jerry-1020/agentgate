"""Trace SDK：零侵入 Agent 全链路采集。

用法（对齐 langfuse）：
    from trace_sdk import TraceClient, CallbackHandler
    client = TraceClient({"project_id": "..."})   # 构造即注册为默认
    handler = CallbackHandler()                   # 无参自动用默认 client
    agent.invoke(..., config={"callbacks": [handler]})
    client.shutdown()   # 关闭后默认引用自动清除，下次构造自动重建
"""
from __future__ import annotations

from .callback_handler import CallbackHandler, TraceCallbackHandler
from .client import TraceClient
from .config import SDKConfig

__all__ = ["TraceClient", "SDKConfig", "CallbackHandler", "TraceCallbackHandler"]
__version__ = "0.1.0"
