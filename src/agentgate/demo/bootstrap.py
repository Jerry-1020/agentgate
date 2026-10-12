"""Idempotent bootstrap for the deterministic loan demonstration."""

import json
from importlib.resources import files

from agentgate.domain import Dataset, DatasetVersion, DatasetVersionStatus
from agentgate.demo.loan import DEMO_CREATED_AT

from agentgate.application.target_catalog import TargetCatalog
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION
from agentgate.demo.targets import LOAN_AGENT_DESCRIPTORS
from agentgate.storage.repository import AgentGateRepository


def ensure_demo_dataset(repository: AgentGateRepository) -> None:
    """Store the demo Dataset and publication when either is not present."""

    dataset = repository.get_dataset(LOAN_DATASET.id, user_team_id="")
    version = repository.get_published_dataset_version(
        LOAN_DATASET.id, LOAN_DATASET_VERSION.version or 0, user_team_id=""
    )
    if dataset is None:
        repository.save_dataset_with_version(LOAN_DATASET, LOAN_DATASET_VERSION)
    elif version is None:
        repository.save_dataset_version(LOAN_DATASET_VERSION)


def ensure_demo_target_descriptors(catalog: TargetCatalog) -> None:
    """Store every immutable Loan Agent descriptor idempotently."""

    for descriptor in LOAN_AGENT_DESCRIPTORS:
        catalog.register_descriptor(descriptor)


def ensure_loan_core_datasets(repository: AgentGateRepository) -> None:
    """Seed portable synthetic cases without replacing any existing user data."""
    records = json.loads(files("agentgate.demo").joinpath("loan-core-datasets.json").read_text(encoding="utf-8"))
    for record in records:
        if repository.get_dataset(record["id"], user_team_id="") is not None:
            continue
        dataset = Dataset(
            id=record["id"], name=record["name"], description=record["description"],
            created_at=DEMO_CREATED_AT, updated_at=DEMO_CREATED_AT,
        )
        version = DatasetVersion(
            id=f"{dataset.id}-bundled-v{record['version']}",
            dataset_id=dataset.id, dataset_name=dataset.name,
            dataset_description=dataset.description, version=record["version"],
            status=DatasetVersionStatus.PUBLISHED, cases=tuple(record["cases"]),
            notes="工程自带核心专项测评集；合成测试数据。",
            created_at=DEMO_CREATED_AT, updated_at=DEMO_CREATED_AT,
            published_at=DEMO_CREATED_AT,
        )
        repository.save_dataset_with_version(dataset, version)
