import sqlite3

from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION
from agentgate.storage.sqlite import SQLiteRepository, _T_DATASETS, _T_DATASET_VERSIONS


def test_bootstrap_stores_dataset_and_publication_atomically(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "empty.db")

    ensure_demo_dataset(repository)

    assert repository.get_dataset(LOAN_DATASET.id, user_team_id="") == LOAN_DATASET
    assert repository.get_published_dataset_version(
        LOAN_DATASET.id, LOAN_DATASET_VERSION.version or 0, user_team_id="") == LOAN_DATASET_VERSION


def test_bootstrap_is_idempotent(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "seeded.db")

    ensure_demo_dataset(repository)
    ensure_demo_dataset(repository)

    with sqlite3.connect(repository.path) as connection:
        assert connection.execute(f"SELECT COUNT(*) FROM {_T_DATASETS}").fetchone()[0] == 1
        assert connection.execute(
            f"SELECT COUNT(*) FROM {_T_DATASET_VERSIONS}"
        ).fetchone()[0] == 1


def test_bootstrap_completes_dataset_without_publication(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "partial.db")
    repository.save_dataset(LOAN_DATASET)

    ensure_demo_dataset(repository)

    assert repository.get_published_dataset_version(
        LOAN_DATASET.id, LOAN_DATASET_VERSION.version or 0, user_team_id="") == LOAN_DATASET_VERSION
