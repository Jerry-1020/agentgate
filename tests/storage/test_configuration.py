"""Database selection and validation must not open a database."""

import socket
import sqlite3
from dataclasses import FrozenInstanceError

import pytest
from pydantic import SecretStr

from agentgate.storage.configuration import SQLiteConfig, TDSQLConfig, load_database_config


@pytest.fixture
def tdsql_environment():
    return {
        "AGENTGATE_DB_TYPE": "tdsql",
        "AGENTGATE_TDSQL_URL": "mysql+pymysql://localhost:3306/eric",
        "AGENTGATE_TDSQL_USER": "eric",
        "AGENTGATE_TDSQL_PASSWORD": " synthetic@password:/?#% ",
    }


def test_sqlite_default_and_explicit_path_precedence(tmp_path):
    assert load_database_config({}) == SQLiteConfig("agentgate.db")
    environment = {"AGENTGATE_DB": "environment.db"}
    assert load_database_config(environment) == SQLiteConfig("environment.db")
    path = tmp_path / " explicit path.db "
    assert load_database_config(environment, database_path=path) == SQLiteConfig(str(path))
    assert not path.exists()


@pytest.mark.parametrize("path", ["", "   ", "bad\x00path"])
def test_invalid_sqlite_paths_are_rejected(path):
    with pytest.raises(ValueError, match="SQLite database path"):
        SQLiteConfig(path)
    with pytest.raises(ValueError, match="SQLite database path"):
        load_database_config({"AGENTGATE_DB": path})
    with pytest.raises(ValueError, match="SQLite database path"):
        load_database_config({"AGENTGATE_DB": "valid.db"}, database_path=path)


@pytest.mark.parametrize("value", ["", "MYSQL", "mysql", "SQLite", "TDSQL", " tdsql", "sqlite "])
def test_database_type_is_strict(value):
    with pytest.raises(ValueError, match="AGENTGATE_DB_TYPE"):
        load_database_config({"AGENTGATE_DB_TYPE": value})


def test_sqlite_ignores_inactive_tdsql_configuration(tdsql_environment):
    tdsql_environment.update(AGENTGATE_DB_TYPE="sqlite", AGENTGATE_TDSQL_URL="invalid")
    assert load_database_config(tdsql_environment) == SQLiteConfig("agentgate.db")


def test_tdsql_preserves_credentials_without_mutating_environment(tdsql_environment):
    tdsql_environment["AGENTGATE_DB"] = "unused.db"
    before = tdsql_environment.copy()
    config = load_database_config(tdsql_environment)
    assert isinstance(config, TDSQLConfig)
    assert config.url == "mysql+pymysql://localhost:3306/eric"
    assert config.username == "eric"
    assert config.password.get_secret_value() == before["AGENTGATE_TDSQL_PASSWORD"]
    assert before["AGENTGATE_TDSQL_PASSWORD"] not in repr(config)
    assert before["AGENTGATE_TDSQL_PASSWORD"] not in str(config.password)
    assert tdsql_environment == before
    with pytest.raises(FrozenInstanceError):
        config.username = "other"


def test_tdsql_rejects_explicit_sqlite_path(tdsql_environment):
    with pytest.raises(ValueError, match="database_path is only supported in sqlite mode"):
        load_database_config(tdsql_environment, database_path="explicit.db")


@pytest.mark.parametrize(
    "key", ["AGENTGATE_TDSQL_URL", "AGENTGATE_TDSQL_USER", "AGENTGATE_TDSQL_PASSWORD"]
)
@pytest.mark.parametrize("missing", [True, False])
def test_tdsql_requires_all_fields(tdsql_environment, key, missing):
    if missing:
        del tdsql_environment[key]
    else:
        tdsql_environment[key] = ""
    with pytest.raises(ValueError, match=key):
        load_database_config(tdsql_environment)


@pytest.mark.parametrize("username", ["", " ", " eric", "eric "])
def test_direct_config_rejects_invalid_username(username):
    with pytest.raises(ValueError, match="AGENTGATE_TDSQL_USER"):
        TDSQLConfig("mysql+pymysql://localhost:3306/eric", username, SecretStr("synthetic"))


@pytest.mark.parametrize("password", [SecretStr(""), "unwrapped-secret"])
def test_direct_config_requires_nonempty_secret(password):
    with pytest.raises(ValueError, match="AGENTGATE_TDSQL_PASSWORD") as raised:
        TDSQLConfig("mysql+pymysql://localhost:3306/eric", "eric", password)
    assert "unwrapped-secret" not in str(raised.value)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "mysql://localhost:3306/eric",
        "MYSQL+PYMYSQL://localhost:3306/eric",
        "mysql+pymysql://localhost/eric",
        "mysql+pymysql://localhost:3306/",
        "mysql+pymysql://:3306/eric",
        "mysql+pymysql://localhost:0/eric",
        "mysql+pymysql://localhost:65536/eric",
        "mysql+pymysql://localhost:invalid/eric",
        "mysql+pymysql://[invalid:3306/eric",
        "mysql+pymysql://user:synthetic-secret@localhost:3306/eric",
        "mysql+pymysql://user@localhost:3306/eric",
        "mysql+pymysql://@localhost:3306/eric",
        "mysql+pymysql://localhost:3306/eric?password=synthetic-secret",
        "mysql+pymysql://localhost:3306/eric#synthetic-secret",
        "mysql+pymysql://localhost:3306/eric?",
        "mysql+pymysql://localhost:3306/eric#",
        "mysql+pymysql://localhost:3306/eric/other",
        " mysql+pymysql://localhost:3306/eric",
        "mysql+pymysql://local\nhost:3306/eric",
        "mysql+pymysql://localhost:3306/eric\x00",
    ],
)
def test_url_validation_is_shared_and_does_not_expose_input(tdsql_environment, url):
    tdsql_environment["AGENTGATE_TDSQL_URL"] = url
    for construct in (
        lambda: load_database_config(tdsql_environment),
        lambda: TDSQLConfig(url, "eric", SecretStr("synthetic")),
    ):
        with pytest.raises(ValueError, match="AGENTGATE_TDSQL_URL") as raised:
            construct()
        assert "synthetic-secret" not in str(raised.value)
        if url:
            assert url not in str(raised.value)


def test_ipv6_url_is_supported(tdsql_environment):
    tdsql_environment["AGENTGATE_TDSQL_URL"] = "mysql+pymysql://[::1]:3306/eric"
    assert load_database_config(tdsql_environment).url == tdsql_environment["AGENTGATE_TDSQL_URL"]


def test_environment_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", "first.db")
    assert load_database_config() == SQLiteConfig("first.db")
    monkeypatch.setenv("AGENTGATE_DB", "second.db")
    assert load_database_config() == SQLiteConfig("second.db")
    assert load_database_config({}) == SQLiteConfig("agentgate.db")


def test_loading_configuration_does_not_connect(monkeypatch, tdsql_environment):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("configuration loading must not connect")

    monkeypatch.setattr(sqlite3, "connect", unexpected_connection)
    monkeypatch.setattr(socket.socket, "connect", unexpected_connection)
    assert isinstance(load_database_config({}), SQLiteConfig)
    assert isinstance(load_database_config(tdsql_environment), TDSQLConfig)
