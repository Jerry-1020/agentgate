"""Unified API response envelope."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseBase(BaseModel, Generic[T]):
    """Unified response envelope: {code, message, data}."""

    code: str
    message: str
    data: T | None = None
