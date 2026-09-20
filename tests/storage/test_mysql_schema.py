"""Verify the frozen migration and the live schema agree."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select

from agentgate.domain import Dataset
from agentgate.storage import mysql as implementation
from agentgate.storage import mysql_schema as schema


def test_initial_migration_matches_table_definitions(mysql_repository):
    with mysql_repository._engine.connect() as db:
        assert compare_metadata(MigrationContext.configure(db), schema.metadata) == []
        assert set(inspect(db).get_table_names()) == set(schema.metadata.tables) | {
            "alembic_version"
        }


def test_digest_collision_is_rejected_without_overwrite(mysql_repository, monkeypatch):
    monkeypatch.setattr(implementation, "_digest", lambda *parts: b"x" * 32)
    mysql_repository.save_dataset(Dataset(id="first", name="first"))
    with pytest.raises(ValueError, match="digest collision"):
        mysql_repository.save_dataset(Dataset(id="second", name="second"))
    assert mysql_repository.get_dataset("first", user_team_id="").name == "first"


def test_corrupt_projection_fails_read(mysql_repository):
    item = Dataset(name="intact")
    mysql_repository.save_dataset(item)
    with mysql_repository._engine.begin() as db:
        db.execute(schema.datasets.update().values(name="corrupted"))
    with pytest.raises(ValueError, match="indexed columns do not match"):
        mysql_repository.get_dataset(item.id, user_team_id="")


def test_single_draft_constraint(mysql_repository):
    from agentgate.domain import DatasetVersion

    item = Dataset(name="draft constraint")
    mysql_repository.save_dataset(item)
    mysql_repository.save_dataset_version(DatasetVersion(dataset_id=item.id))
    with pytest.raises(ValueError):
        mysql_repository.save_dataset_version(DatasetVersion(dataset_id=item.id))
    with mysql_repository._engine.connect() as db:
        assert len(db.execute(select(schema.dataset_versions)).all()) == 1
