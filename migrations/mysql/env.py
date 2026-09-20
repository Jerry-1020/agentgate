"""Explicit MySQL migrations using the same configuration as application processes."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from agentgate.storage.configuration import TDSQLConfig, load_database_config
from agentgate.storage.mysql_schema import metadata

settings = load_database_config()
if not isinstance(settings, TDSQLConfig):
    raise TypeError("MySQL migrations require AGENTGATE_DB_TYPE=tdsql")
url = make_url(settings.url).set(
    username=settings.username, password=settings.password.get_secret_value()
)
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"charset": "utf8mb4", "connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
