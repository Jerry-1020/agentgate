"""JSON-safe serialization helpers for LangChain callback payloads."""

from __future__ import annotations

import dataclasses
from typing import Any


def to_jsonable(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if depth > 8:
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(val, depth + 1) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item, depth + 1) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(dataclasses.asdict(value), depth + 1)
    if hasattr(value, "model_dump"):
        try:
            return to_jsonable(value.model_dump(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return to_jsonable(value.dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "value"):
        try:
            return {"value": to_jsonable(getattr(value, "value"), depth + 1)}
        except Exception:
            pass
    return str(value)


def message_to_dict(message: Any) -> dict[str, Any] | str:
    if isinstance(message, dict):
        return to_jsonable(message)
    try:
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
            "function": "assistant",
        }
        message_type = getattr(message, "type", "")
        data: dict[str, Any] = {
            "role": role_map.get(message_type, message_type or "unknown"),
            "content": to_jsonable(getattr(message, "content", "")),
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = to_jsonable(tool_calls)
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            data["tool_call_id"] = tool_call_id
        return data
    except Exception:
        return str(message)


_to_jsonable = to_jsonable
_message_to_dict = message_to_dict
