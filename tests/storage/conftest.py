"""Opt-in integration tests confined to the dedicated MySQL test database."""

import os

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from agentgate.storage.configuration import TDSQLConfig
from agentgate.storage.mysql import MySQLRepository
from agentgate.storage.mysql_schema import metadata
from agentgate.storage.sqlite import SQLiteRepository


@pytest.fixture
def mysql_config():
    address = os.getenv("AGENTGATE_TEST_MYSQL_URL")
    if not address:
        pytest.skip("AGENTGATE_TEST_MYSQL_URL is not configured")
    if make_url(address).database != "eric_agentgate_test":
        pytest.fail("MySQL tests only allow the isolated eric_agentgate_test database")
    return TDSQLConfig(
        address,
        os.environ["AGENTGATE_TEST_MYSQL_USER"],
        SecretStr(os.environ["AGENTGATE_TEST_MYSQL_PASSWORD"]),
    )


@pytest.fixture
def mysql_repository(mysql_config):
    url = make_url(mysql_config.url).set(
        username=mysql_config.username, password=mysql_config.password.get_secret_value()
    )
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            for table in reversed(metadata.sorted_tables):
                connection.execute(table.delete())
    finally:
        engine.dispose()
    repository = MySQLRepository(mysql_config)
    try:
        yield repository
    finally:
        repository.close()


@pytest.fixture(params=["sqlite", "mysql"])
def repository(request, tmp_path):
    if request.param == "mysql":
        return request.getfixturevalue("mysql_repository")
    return SQLiteRepository(tmp_path / "contract.db")
