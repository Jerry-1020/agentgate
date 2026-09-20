"""MySQL table definitions; importing this module never connects or runs DDL.

References are enforced by repository transactions so the same schema can be used
on TDSQL deployments that do not implement foreign keys.
"""

from sqlalchemy import BigInteger, Column, Index, MetaData, SmallInteger, Table, UniqueConstraint
from sqlalchemy.dialects.mysql import BINARY, CHAR, DATETIME, LONGTEXT, VARCHAR

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _text(name: str, *, nullable: bool = False) -> Column:
    return Column(name, LONGTEXT(collation="utf8mb4_bin"), nullable=nullable)


def _key(name: str, *, primary: bool = False) -> Column:
    return Column(name, BINARY(32), primary_key=primary, nullable=False)


def _hash(name: str) -> Column:
    return Column(name, CHAR(64, charset="ascii", collation="ascii_bin"), nullable=False)


def _time(name: str, *, nullable: bool = False) -> Column:
    return Column(name, DATETIME(fsp=6), nullable=nullable)


def _identity() -> list[Column]:
    return [_key("id_key", primary=True), _text("id")]


def _team() -> list[Column]:
    return [_key("user_team_key"), _text("user_team_id"), _text("user_id"), _text("user_name")]


def _table(name: str, *items) -> Table:
    return Table(
        name,
        metadata,
        *items,
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
        mysql_row_format="DYNAMIC",
    )


datasets = _table(
    "agentgate_datasets",
    *_identity(),
    _text("name"),
    Column("archived", SmallInteger, nullable=False),
    _time("updated_at"),
    *_team(),
    _text("payload"),
    Index("ix_datasets_team_updated", "user_team_key", "updated_at"),
)

dataset_versions = _table(
    "agentgate_dataset_versions",
    *_identity(),
    _key("dataset_key"),
    _text("dataset_id"),
    Column("version", BigInteger),
    Column("status", VARCHAR(16), nullable=False),
    Column("draft_slot", SmallInteger),
    _time("created_at"),
    _hash("content_sha256"),
    *_team(),
    _text("payload"),
    UniqueConstraint("dataset_key", "version", name="uq_dataset_publication"),
    UniqueConstraint("dataset_key", "draft_slot", name="uq_dataset_draft"),
    Index("ix_dataset_versions_lookup", "dataset_key", "status", "version"),
)

evaluators = _table(
    "agentgate_evaluators",
    *_identity(),
    Column("source", VARCHAR(16), nullable=False),
    Column("enabled", SmallInteger, nullable=False),
    _time("created_at"),
    _time("updated_at"),
    *_team(),
    _text("payload"),
    Index("ix_evaluators_team_updated", "user_team_key", "enabled", "updated_at"),
)

evaluator_drafts = _table(
    "agentgate_evaluator_drafts",
    *_identity(),
    _key("evaluator_key"),
    _text("evaluator_id"),
    _time("created_at"),
    _time("updated_at"),
    *_team(),
    _text("payload"),
    UniqueConstraint("evaluator_key", name="uq_evaluator_draft"),
)

evaluator_versions = _table(
    "agentgate_evaluator_versions",
    _key("evaluator_key", primary=True),
    Column("version", BigInteger, primary_key=True),
    _text("evaluator_id"),
    _hash("content_sha256"),
    *_team(),
    _text("payload"),
)

runs = _table(
    "agentgate_runs",
    *_identity(),
    Column("status", VARCHAR(16), nullable=False),
    _time("created_at"),
    _time("scheduled_for", nullable=True),
    *_team(),
    _text("api_key", nullable=True),
    Column("case_max_parallel", SmallInteger),
    _text("payload"),
    Index("ix_runs_status_created", "status", "created_at"),
    Index("ix_runs_due", "status", "scheduled_for", "created_at"),
    Index("ix_runs_team_created", "user_team_key", "created_at"),
    Index("ix_runs_team_status", "user_team_key", "status", "created_at"),
)

run_asset_refs = _table(
    "agentgate_run_asset_refs",
    _key("reference_key", primary=True),
    _key("run_key"),
    _text("run_id"),
    _key("asset_lookup_key"),
    Column("asset_kind", VARCHAR(16), nullable=False),
    _text("source_id"),
    _text("asset_id"),
    _text("version"),
    _hash("content_sha256"),
    Index("ix_run_refs_run", "run_key"),
    Index("ix_run_refs_lookup", "asset_lookup_key", "content_sha256", "run_key"),
)

traces = _table(
    "agentgate_traces",
    *_identity(),
    _key("run_key"),
    _text("run_id"),
    _key("case_key"),
    _text("case_id"),
    _text("payload"),
    UniqueConstraint("run_key", "case_key", name="uq_trace_run_case"),
)

results = _table(
    "agentgate_results",
    *_identity(),
    _key("run_key"),
    _text("run_id"),
    _key("case_key"),
    _text("case_id"),
    _key("trace_key"),
    _text("trace_id"),
    _key("evaluator_key"),
    _text("evaluator_id"),
    _text("payload"),
    UniqueConstraint("run_key", "case_key", "evaluator_key", name="uq_result_run_case_evaluator"),
)

target_descriptors = _table(
    "agentgate_target_descriptors",
    Column("content_sha256", CHAR(64, charset="ascii", collation="ascii_bin"), primary_key=True),
    _key("target_ref_key"),
    _text("source_id"),
    Column("target_type", VARCHAR(16), nullable=False),
    _text("external_target_id"),
    _text("external_version_id"),
    _time("fetched_at"),
    _text("payload"),
    Index("ix_target_ref", "target_ref_key", "fetched_at"),
)

skill_analysis_reports = _table(
    "agentgate_skill_analysis_reports",
    *_identity(),
    _hash("target_descriptor_sha256"),
    _hash("content_sha256"),
    _time("created_at"),
    _text("payload"),
    Index("ix_skill_reports_target", "target_descriptor_sha256", "created_at"),
)

skill_analysis_reviews = _table(
    "agentgate_skill_analysis_reviews",
    _key("report_key", primary=True),
    _key("finding_key", primary=True),
    _text("report_id"),
    _text("finding_id"),
    _time("reviewed_at"),
    _text("payload"),
)

evaluation_tasks = _table(
    "evaluation_tasks",
    *_identity(),
    _time("created_at"),
    _text("payload"),
    Index("ix_tasks_created", "created_at"),
)
evaluation_task_runs = _table(
    "evaluation_task_runs",
    _key("run_key", primary=True),
    _text("run_id"),
    _key("task_key"),
    _text("task_id"),
    Index("ix_task_runs_task", "task_key"),
)
optimization_reports = _table(
    "optimization_reports",
    _key("evidence_key_digest", primary=True),
    _text("evidence_key"),
    _key("run_key"),
    _text("run_id"),
    _time("created_at"),
    _text("payload"),
    Index("ix_optimization_run", "run_key"),
)
api_keys = _table(
    "agentgate_api_keys",
    *_identity(),
    Column("scope", VARCHAR(16), nullable=False),
    _text("provider_id"),
    _time("created_at"),
    _text("metadata_payload"),
    _text("encrypted_api_key"),
    Index("ix_api_keys_created", "created_at"),
)
