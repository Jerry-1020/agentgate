"""Request-scoped user context backed by contextvars."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserInfo:
    user_team_id: str
    user_id: str
    user_name: str


_current: ContextVar[UserInfo | None] = ContextVar("user_context", default=None)


def set_user_info(info: UserInfo) -> Token:
    return _current.set(info)


def reset_user_info(token: Token) -> None:
    _current.reset(token)


def get_user_info() -> UserInfo | None:
    return _current.get()
