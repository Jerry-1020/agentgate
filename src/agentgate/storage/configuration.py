"""Explicit database configuration without connection or environment-loading effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

from agentgate.storage.repository import AgentGateRepository


@dataclass(frozen=True, slots=True)
class SQLiteConfig:
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip() or "\x00" in self.path:
            raise ValueError("SQLite database path must be a nonblank string without NUL")


@dataclass(frozen=True, slots=True)
class TDSQLConfig:
    url: str
    username: str
    password: SecretStr

    def __post_init__(self) -> None:
        _validate_tdsql_url(self.url)
        if (
            not isinstance(self.username, str)
            or not self.username
            or self.username != self.username.strip()
        ):
            raise ValueError("AGENTGATE_TDSQL_USER must be nonblank without surrounding whitespace")
        if not isinstance(self.password, SecretStr) or not self.password.get_secret_value():
            raise ValueError("AGENTGATE_TDSQL_PASSWORD is required")


DatabaseConfig = SQLiteConfig | TDSQLConfig


def _validate_tdsql_url(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("AGENTGATE_TDSQL_URL is required")
    # urlsplit silently removes some control characters; reject them before parsing.
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("AGENTGATE_TDSQL_URL must not contain whitespace or control characters")
    if not value.startswith("mysql+pymysql://"):
        raise ValueError("AGENTGATE_TDSQL_URL must use mysql+pymysql")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("AGENTGATE_TDSQL_URL is invalid") from None
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("AGENTGATE_TDSQL_URL must not contain credentials")
    if "?" in value or "#" in value:
        raise ValueError("AGENTGATE_TDSQL_URL must not contain query parameters or fragments")
    if not host or port is None or not parsed.path.removeprefix("/"):
        raise ValueError("AGENTGATE_TDSQL_URL must include a host, port, and database")
    if not 1 <= port <= 65535:
        raise ValueError("AGENTGATE_TDSQL_URL port must be between 1 and 65535")
    if "/" in parsed.path[1:]:
        raise ValueError("AGENTGATE_TDSQL_URL must contain one database name")


def load_database_config(
    environ: Mapping[str, str] | None = None,
    *,
    database_path: str | Path | None = None,
) -> DatabaseConfig:
    """Read the selected backend, preserving explicit SQLite path precedence."""
    source = os.environ if environ is None else environ
    database_type = source.get("AGENTGATE_DB_TYPE", "sqlite")
    if database_type == "sqlite":
        path = (
            str(database_path)
            if database_path is not None
            else source.get("AGENTGATE_DB", "agentgate.db")
        )
        return SQLiteConfig(path=path)
    if database_type != "tdsql":
        raise ValueError("AGENTGATE_DB_TYPE must be 'sqlite' or 'tdsql'")
    if database_path is not None:
        raise ValueError("database_path is only supported in sqlite mode")
    return TDSQLConfig(
        url=source.get("AGENTGATE_TDSQL_URL", ""),
        username=source.get("AGENTGATE_TDSQL_USER", ""),
        password=SecretStr(source.get("AGENTGATE_TDSQL_PASSWORD", "")),
    )


def create_repository(config: DatabaseConfig) -> AgentGateRepository:
    """Create a repository owned and closed by the calling composition root."""
    if isinstance(config, SQLiteConfig):
        from agentgate.storage.sqlite import SQLiteRepository

        return SQLiteRepository(config.path)
    if isinstance(config, TDSQLConfig):
        from agentgate.storage.mysql import MySQLRepository

        return MySQLRepository(config)
    raise TypeError("unsupported database configuration")
