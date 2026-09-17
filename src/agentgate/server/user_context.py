"""Request-scoped user context backed by contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserInfo:
    user_team_id: str
    user_id: str
    user_name: str


_current: ContextVar[UserInfo | None] = ContextVar("user_context", default=None)


def set_user_info(info: UserInfo) -> None:
    _current.set(info)


def get_user_info() -> UserInfo | None:
    return _current.get()
