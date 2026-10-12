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


def test_core_datasets_survive_restart_and_preserve_user_changes(tmp_path) -> None:
    from agentgate.demo.bootstrap import ensure_loan_core_datasets
    from agentgate.application.dataset_management import DatasetManagement

    path = tmp_path / "portable.db"
    repository = SQLiteRepository(path)
    ensure_loan_core_datasets(repository)
    datasets = DatasetManagement(repository).list_datasets()
    assert len(datasets) == 3
    expected = {}
    for dataset in datasets:
        version = repository.get_published_dataset_version(dataset.id, 3, user_team_id="")
        assert version is not None
        assert len(version.cases) == 12
        assert sum(len(case.turns) for case in version.cases) == 14
        assert any(e.kind == "execution_path" for c in version.cases for t in c.turns for e in t.expectations)
        expected[dataset.id] = version
    changed = datasets[0].model_copy(update={"name": "用户已修改名称", "archived": True})
    repository.save_dataset(changed)
    repository.close()
    repository = SQLiteRepository(path)
    ensure_loan_core_datasets(repository)
    assert repository.get_dataset(changed.id, user_team_id="") == changed
    for dataset_id, version in expected.items():
        assert repository.get_published_dataset_version(dataset_id, 3, user_team_id="") == version
    with sqlite3.connect(path) as connection:
        assert connection.execute(f"SELECT COUNT(*) FROM {_T_DATASETS}").fetchone()[0] == 3
        assert connection.execute(f"SELECT COUNT(*) FROM {_T_DATASET_VERSIONS}").fetchone()[0] == 3
    repository.close()
