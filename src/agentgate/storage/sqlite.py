from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agentgate.domain import (
    Dataset,
    DatasetVersion,
    DatasetVersionStatus,
    EvaluationResult,
    EvaluationRun,
    Evaluator,
    EvaluatorDraft,
    EvaluatorSource,
    EvaluatorSpec,
    OptimizationReport,
    RunStatus,
    SkillAnalysisReport,
    SkillAnalysisReview,
    TargetDescriptor,
    TargetRef,
    TargetType,
    Trace,
    canonical_json,
    content_sha256,
    normalize_utc,
    transition_run,
)
from agentgate.domain.credential import ApiKeyMetadata
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.evaluator.versioning import (
    publish_evaluator_draft as build_evaluator_publication,
)


TABLE_PREFIX = "agentgate_"

_T_API_KEYS = f"{TABLE_PREFIX}api_keys"
_T_TARGET_DESCRIPTORS = f"{TABLE_PREFIX}target_descriptors"
_T_SKILL_ANALYSIS_REPORTS = f"{TABLE_PREFIX}skill_analysis_reports"
_T_SKILL_ANALYSIS_REVIEWS = f"{TABLE_PREFIX}skill_analysis_reviews"
_T_EVALUATORS = f"{TABLE_PREFIX}evaluators"
_T_EVALUATOR_DRAFTS = f"{TABLE_PREFIX}evaluator_drafts"
_T_EVALUATOR_VERSIONS = f"{TABLE_PREFIX}evaluator_versions"
_T_DATASETS = f"{TABLE_PREFIX}datasets"
_T_DATASET_VERSIONS = f"{TABLE_PREFIX}dataset_versions"
_T_RUN_ASSET_REFS = f"{TABLE_PREFIX}run_asset_refs"
_T_TRACES = f"{TABLE_PREFIX}traces"
_T_RESULTS = f"{TABLE_PREFIX}results"
_T_RUNS = f"{TABLE_PREFIX}runs"
_T_RUNS_NEW = f"{TABLE_PREFIX}runs_new"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_T_API_KEYS} (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK(scope IN ('shared', 'private')),
    provider_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_payload TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_keys_created
    ON {_T_API_KEYS}(created_at, id);
CREATE TABLE IF NOT EXISTS {_T_TARGET_DESCRIPTORS} (
    content_sha256 TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('agent', 'skill')),
    external_target_id TEXT NOT NULL,
    external_version_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_target_descriptor_ref
    ON {_T_TARGET_DESCRIPTORS}(
        source_id,
        target_type,
        external_target_id,
        external_version_id
    );
CREATE TABLE IF NOT EXISTS {_T_SKILL_ANALYSIS_REPORTS} (
    id TEXT PRIMARY KEY,
    target_descriptor_sha256 TEXT NOT NULL
        REFERENCES {_T_TARGET_DESCRIPTORS}(content_sha256),
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_analysis_reports_target
    ON {_T_SKILL_ANALYSIS_REPORTS}(
        target_descriptor_sha256,
        created_at DESC,
        id
    );
CREATE TABLE IF NOT EXISTS {_T_SKILL_ANALYSIS_REVIEWS} (
    report_id TEXT NOT NULL
        REFERENCES {_T_SKILL_ANALYSIS_REPORTS}(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(report_id, finding_id)
);
CREATE TABLE IF NOT EXISTS {_T_EVALUATORS} (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK(source = 'user'),
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluators_enabled_updated
    ON {_T_EVALUATORS}(enabled, updated_at DESC, id);
CREATE TABLE IF NOT EXISTS {_T_EVALUATOR_DRAFTS} (
    id TEXT PRIMARY KEY,
    evaluator_id TEXT NOT NULL UNIQUE
        REFERENCES {_T_EVALUATORS}(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {_T_EVALUATOR_VERSIONS} (
    evaluator_id TEXT NOT NULL REFERENCES {_T_EVALUATORS}(id),
    version INTEGER NOT NULL CHECK(version >= 1),
    content_sha256 TEXT NOT NULL,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    PRIMARY KEY(evaluator_id, version)
);
CREATE TABLE IF NOT EXISTS {_T_DATASETS} (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL CHECK(archived IN (0, 1)),
    updated_at TEXT NOT NULL,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {_T_DATASET_VERSIONS} (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES {_T_DATASETS}(id),
    version INTEGER,
    status TEXT NOT NULL CHECK(status IN ('draft', 'published')),
    created_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    CHECK(
        (status = 'draft' AND version IS NULL)
        OR (status = 'published' AND version >= 1)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_published_version
    ON {_T_DATASET_VERSIONS}(dataset_id, version)
    WHERE status = 'published';
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_active_draft
    ON {_T_DATASET_VERSIONS}(dataset_id)
    WHERE status = 'draft';
CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset
    ON {_T_DATASET_VERSIONS}(dataset_id, status, version);
CREATE TABLE IF NOT EXISTS {_T_RUN_ASSET_REFS} (
    run_id TEXT NOT NULL REFERENCES {_T_RUNS}(id) ON DELETE CASCADE,
    asset_kind TEXT NOT NULL CHECK(
        asset_kind IN ('dataset', 'case', 'agent', 'skill', 'evaluator')
    ),
    source_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY(
        run_id,
        asset_kind,
        source_id,
        asset_id,
        version,
        content_sha256
    )
);
CREATE INDEX IF NOT EXISTS idx_run_asset_lookup
    ON {_T_RUN_ASSET_REFS}(
        asset_kind,
        source_id,
        asset_id,
        version,
        content_sha256,
        run_id
    );
CREATE TABLE IF NOT EXISTS {_T_TRACES} (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, case_id),
    UNIQUE(id, run_id, case_id)
);
CREATE TABLE IF NOT EXISTS {_T_RESULTS} (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, case_id, evaluator_id),
    FOREIGN KEY(run_id) REFERENCES {_T_RUNS}(id),
    FOREIGN KEY(trace_id, run_id, case_id) REFERENCES {_T_TRACES}(id, run_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_traces_run ON {_T_TRACES}(run_id);
CREATE INDEX IF NOT EXISTS idx_results_run ON {_T_RESULTS}(run_id);
"""

_RUNS_TABLE_SCHEMA = f"""
CREATE TABLE {_T_RUNS} (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(
        status IN (
            'scheduled', 'pending', 'running', 'completed', 'failed', 'cancelled'
        )
    ),
    created_at TEXT NOT NULL,
    scheduled_for TEXT,
    user_team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_name TEXT NOT NULL DEFAULT '',
    api_key TEXT,
    payload TEXT NOT NULL
)
"""

_RUNS_INDEX_SCHEMA = f"""
CREATE INDEX IF NOT EXISTS idx_runs_status_created
    ON {_T_RUNS}(status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_runs_due
    ON {_T_RUNS}(status, scheduled_for, created_at, id);
"""


class SQLiteRepository:
    """SQLite JSON-document adapter behind a PostgreSQL-compatible domain boundary."""

    def __init__(
        self, path: str | Path = "agentgate.db", busy_timeout_ms: int = 5_000
    ) -> None:
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be at least 1")
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def close(self) -> None:
        """No persistent connection is held; each operation closes its connection."""

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path, timeout=self.busy_timeout_ms / 1_000
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            self._migrate_table_prefix(db)
            db.executescript(_SCHEMA)
            self._ensure_runs_schema(db)
            self._ensure_identity_columns(db)
            db.executescript(_RUNS_INDEX_SCHEMA)
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS optimization_reports (
                    evidence_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES {_T_RUNS}(id),
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_tasks (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_task_runs (
                    run_id TEXT PRIMARY KEY REFERENCES {_T_RUNS}(id),
                    task_id TEXT NOT NULL REFERENCES evaluation_tasks(id)
                );
            """)

    def save_task_runs(self, task: EvaluationTask, runs: Sequence[EvaluationRun]) -> None:
        if task.run_ids != tuple(r.id for r in runs):
            raise ValueError("invalid task run associations")
        if any(r.status not in {RunStatus.PENDING, RunStatus.SCHEDULED} for r in runs):
            raise ValueError("task creation requires unstarted runs")
        if task.kind == "stability" and any(r.manifest != runs[0].manifest or r.status != RunStatus.PENDING for r in runs):
            raise ValueError("stability requires identical snapshots and pending runs")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for run in runs:
                references = self._run_asset_references(db, run)
                db.execute(f"INSERT INTO {_T_RUNS}(id,status,created_at,scheduled_for,payload,user_team_id,user_id,user_name) VALUES(?,?,?,?,?,?,?,?)",
                           (run.id, run.status, run.created_at.isoformat(), run.scheduled_for.isoformat() if run.scheduled_for else None, canonical_json(run),
                            run.user_team_id, run.user_id, run.user_name))
                db.executemany(f"INSERT INTO {_T_RUN_ASSET_REFS}(run_id,asset_kind,source_id,asset_id,version,content_sha256) VALUES(?,?,?,?,?,?)", references)
            db.execute("INSERT INTO evaluation_tasks VALUES(?,?,?)", (task.id, task.created_at.isoformat(), canonical_json(task)))
            db.executemany("INSERT INTO evaluation_task_runs VALUES(?,?)", [(r.id, task.id) for r in runs])

    def get_optimization_report(self, evidence_key: str) -> OptimizationReport | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM optimization_reports WHERE evidence_key=?", (evidence_key,)).fetchone()
        return OptimizationReport.model_validate_json(row["payload"]) if row else None

    def save_optimization_report(self, evidence_key: str, report: OptimizationReport) -> OptimizationReport:
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO optimization_reports VALUES(?,?,?,?)",
                       (evidence_key, report.run_id, report.created_at.isoformat(), canonical_json(report)))
            row = db.execute("SELECT payload FROM optimization_reports WHERE evidence_key=?", (evidence_key,)).fetchone()
        return OptimizationReport.model_validate_json(row["payload"])

    def save_evaluation_task(self, task: EvaluationTask) -> EvaluationTask:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM evaluation_tasks WHERE id=?", (task.id,)).fetchone()
            if row:
                previous = EvaluationTask.model_validate_json(row["payload"])
                for field in ("kind", "run_ids", "git_commit_refs", "credential_id"):
                    if getattr(previous, field) != getattr(task, field):
                        raise ValueError("task identity and run associations are immutable")
                reports_by_target = {}
                for report_id in previous.static_report_ids + task.static_report_ids:
                    report_row = db.execute(f"SELECT payload FROM {_T_SKILL_ANALYSIS_REPORTS} WHERE id=?", (report_id,)).fetchone()
                    if report_row is None:
                        raise ValueError("unknown static report")
                    report = SkillAnalysisReport.model_validate_json(report_row["payload"])
                    reports_by_target[report.target_descriptor_sha256] = report_id
                task = EvaluationTask.model_validate({
                    **previous.model_dump(),
                    "static_report_ids": tuple(reports_by_target.values()),
                })
            for report_id in task.static_report_ids:
                if db.execute(f"SELECT 1 FROM {_T_SKILL_ANALYSIS_REPORTS} WHERE id=?", (report_id,)).fetchone() is None:
                    raise ValueError("unknown static report")
            try:
                if not row:
                    db.execute("INSERT INTO evaluation_tasks VALUES(?,?,?)",
                               (task.id, task.created_at.isoformat(), canonical_json(task)))
                    db.executemany("INSERT INTO evaluation_task_runs VALUES(?,?)",
                                   [(run_id, task.id) for run_id in task.run_ids])
                else:
                    db.execute("UPDATE evaluation_tasks SET payload=? WHERE id=?", (canonical_json(task), task.id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("run does not exist or already belongs to another task") from exc
        return task

    def get_evaluation_task(self, task_id: str) -> EvaluationTask | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM evaluation_tasks WHERE id=?", (task_id,)).fetchone()
        return EvaluationTask.model_validate_json(row["payload"]) if row else None

    def list_evaluation_tasks(self) -> list[EvaluationTask]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM evaluation_tasks ORDER BY created_at DESC,id").fetchall()
        return [EvaluationTask.model_validate_json(row["payload"]) for row in rows]

    @staticmethod
    def _migrate_table_prefix(db: sqlite3.Connection) -> None:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = (_T_API_KEYS, _T_TARGET_DESCRIPTORS, _T_SKILL_ANALYSIS_REPORTS,
                 _T_SKILL_ANALYSIS_REVIEWS, _T_EVALUATORS, _T_EVALUATOR_DRAFTS,
                 _T_EVALUATOR_VERSIONS, _T_DATASETS, _T_DATASET_VERSIONS,
                 _T_RUN_ASSET_REFS, _T_TRACES, _T_RESULTS, _T_RUNS)
        if any(name in tables and name.removeprefix(TABLE_PREFIX) in tables for name in names):
            raise ValueError("Both legacy and prefixed tables exist; restore a backup before migration")
        db.execute("BEGIN IMMEDIATE")
        for name in names:
            old = name.removeprefix(TABLE_PREFIX)
            if old in tables:
                db.execute(f'ALTER TABLE "{old}" RENAME TO "{name}"')
        db.commit()

    @staticmethod
    def _ensure_identity_columns(db: sqlite3.Connection) -> None:
        # Additive migration: retain original payloads, immutable hashes and associations.
        for table in (_T_DATASETS, _T_DATASET_VERSIONS, _T_EVALUATORS,
                      _T_EVALUATOR_DRAFTS, _T_EVALUATOR_VERSIONS, _T_RUNS):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for name in ("user_team_id", "user_id", "user_name"):
                if name not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
                    db.execute(f"UPDATE {table} SET {name}=COALESCE(json_extract(payload, '$.{name}'), '')")
            if table == _T_RUNS:
                for name, kind in (("api_key", "TEXT"),):
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    @staticmethod
    def _ensure_runs_schema(db: sqlite3.Connection) -> None:
        row = db.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{_T_RUNS}'"
        ).fetchone()
        if row is None:
            db.execute(_RUNS_TABLE_SCHEMA)
            return

        columns = {
            column[1] for column in db.execute(f"PRAGMA table_info({_T_RUNS})").fetchall()
        }
        if "scheduled_for" in columns and "'scheduled'" in row[0]:
            return

        db.execute("PRAGMA foreign_keys = OFF")
        try:
            db.execute(_RUNS_TABLE_SCHEMA.replace(f"CREATE TABLE {_T_RUNS}", f"CREATE TABLE {_T_RUNS_NEW}", 1))
            db.execute(
                f"""
                INSERT INTO {_T_RUNS_NEW}(id, status, created_at, scheduled_for, payload)
                SELECT id, status, created_at, NULL, payload FROM {_T_RUNS}
                """
            )
            db.execute(f"DROP TABLE {_T_RUNS}")
            db.execute(f"ALTER TABLE {_T_RUNS_NEW} RENAME TO {_T_RUNS}")
        finally:
            db.execute("PRAGMA foreign_keys = ON")

    def save_api_key(
        self, metadata: ApiKeyMetadata, encrypted_api_key: str
    ) -> None:
        if not isinstance(encrypted_api_key, str) or not encrypted_api_key.strip():
            raise ValueError("encrypted API Key must be a nonblank string")
        with self._connect() as db:
            try:
                db.execute(
                    f"""
                    INSERT INTO {_T_API_KEYS}(
                        id,scope,provider_id,created_at,
                        metadata_payload,encrypted_api_key
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        metadata.id,
                        metadata.scope.value,
                        metadata.provider_id,
                        metadata.created_at.isoformat(),
                        canonical_json(metadata),
                        encrypted_api_key,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = db.execute(
                    f"SELECT 1 FROM {_T_API_KEYS} WHERE id=?", (metadata.id,)
                ).fetchone()
                if existing is not None:
                    raise ValueError(
                        f"API Key already exists: {metadata.id}"
                    ) from None
                raise

    def get_api_key_metadata(
        self, api_key_id: str
    ) -> ApiKeyMetadata | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT metadata_payload FROM {_T_API_KEYS} WHERE id=?",
                (api_key_id,),
            ).fetchone()
        return ApiKeyMetadata.model_validate_json(row[0]) if row else None

    def list_api_key_metadata(self) -> list[ApiKeyMetadata]:
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT metadata_payload FROM {_T_API_KEYS}
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [ApiKeyMetadata.model_validate_json(row[0]) for row in rows]

    def get_encrypted_api_key(self, api_key_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT encrypted_api_key FROM {_T_API_KEYS} WHERE id=?",
                (api_key_id,),
            ).fetchone()
        return row[0] if row else None

    def delete_api_key(self, api_key_id: str) -> None:
        with self._connect() as db:
            cursor = db.execute(f"DELETE FROM {_T_API_KEYS} WHERE id=?", (api_key_id,))
            if cursor.rowcount != 1:
                raise ValueError(f"unknown API Key: {api_key_id}")

    def save_target_descriptor(self, descriptor: TargetDescriptor) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_TARGET_DESCRIPTORS} WHERE content_sha256 = ?",
                (descriptor.content_sha256,),
            ).fetchone()
            if existing is not None:
                stored = TargetDescriptor.model_validate_json(existing[0])
                stored_content = stored.model_dump(
                    mode="json", exclude={"fetched_at"}
                )
                incoming_content = descriptor.model_dump(
                    mode="json", exclude={"fetched_at"}
                )
                if stored_content != incoming_content:
                    raise ValueError("TargetDescriptor content hash collision")
                return
            db.execute(
                f"""
                INSERT INTO {_T_TARGET_DESCRIPTORS}(
                    content_sha256,
                    source_id,
                    target_type,
                    external_target_id,
                    external_version_id,
                    fetched_at,
                    payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    descriptor.content_sha256,
                    descriptor.ref.source_id,
                    descriptor.ref.target_type.value,
                    descriptor.ref.external_target_id,
                    descriptor.ref.external_version_id,
                    descriptor.fetched_at.isoformat(),
                    canonical_json(descriptor),
                ),
            )

    def get_target_descriptor(
        self, content_sha256: str
    ) -> TargetDescriptor | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_TARGET_DESCRIPTORS} WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
        return TargetDescriptor.model_validate_json(row[0]) if row else None

    def list_target_descriptors(
        self, ref: TargetRef | None = None
    ) -> list[TargetDescriptor]:
        query = f"SELECT payload FROM {_T_TARGET_DESCRIPTORS}"
        parameters: tuple[object, ...] = ()
        if ref is not None:
            query += (
                " WHERE source_id=? AND target_type=?"
                " AND external_target_id=? AND external_version_id=?"
            )
            parameters = (
                ref.source_id,
                ref.target_type.value,
                ref.external_target_id,
                ref.external_version_id,
            )
        query += " ORDER BY fetched_at DESC, content_sha256"
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [TargetDescriptor.model_validate_json(row[0]) for row in rows]

    def save_skill_analysis_report(self, report: SkillAnalysisReport) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_SKILL_ANALYSIS_REPORTS} WHERE id=?",
                (report.id,),
            ).fetchone()
            if existing is not None:
                stored = SkillAnalysisReport.model_validate_json(existing[0])
                if stored != report:
                    raise ValueError("SkillAnalysisReport is immutable")
                return
            db.execute(
                f"""
                INSERT INTO {_T_SKILL_ANALYSIS_REPORTS}(
                    id,
                    target_descriptor_sha256,
                    content_sha256,
                    created_at,
                    payload
                ) VALUES(?,?,?,?,?)
                """,
                (
                    report.id,
                    report.target_descriptor_sha256,
                    report.content_sha256,
                    report.created_at.isoformat(),
                    canonical_json(report),
                ),
            )

    def get_skill_analysis_report(
        self, report_id: str
    ) -> SkillAnalysisReport | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_SKILL_ANALYSIS_REPORTS} WHERE id=?",
                (report_id,),
            ).fetchone()
        return SkillAnalysisReport.model_validate_json(row[0]) if row else None

    def list_skill_analysis_reports(
        self, target_descriptor_sha256: str, limit: int = 50
    ) -> list[SkillAnalysisReport]:
        if limit < 1:
            raise ValueError("SkillAnalysisReport list limit must be at least 1")
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT payload FROM {_T_SKILL_ANALYSIS_REPORTS}
                WHERE target_descriptor_sha256=?
                ORDER BY created_at DESC,id
                LIMIT ?
                """,
                (target_descriptor_sha256, limit),
            ).fetchall()
        return [SkillAnalysisReport.model_validate_json(row[0]) for row in rows]

    def save_skill_analysis_review(
        self, report_id: str, review: SkillAnalysisReview
    ) -> None:
        with self._connect() as db:
            db.execute(
                f"""
                INSERT INTO {_T_SKILL_ANALYSIS_REVIEWS}(
                    report_id,finding_id,reviewed_at,payload
                ) VALUES(?,?,?,?)
                ON CONFLICT(report_id,finding_id) DO UPDATE SET
                    reviewed_at=excluded.reviewed_at,
                    payload=excluded.payload
                """,
                (
                    report_id,
                    review.finding_id,
                    review.reviewed_at.isoformat(),
                    canonical_json(review),
                ),
            )

    def list_skill_analysis_reviews(
        self, report_id: str
    ) -> list[SkillAnalysisReview]:
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT payload FROM {_T_SKILL_ANALYSIS_REVIEWS}
                WHERE report_id=? ORDER BY finding_id
                """,
                (report_id,),
            ).fetchall()
        return [SkillAnalysisReview.model_validate_json(row[0]) for row in rows]

    def save_evaluator(self, evaluator: Evaluator) -> None:
        _require_user_evaluator(evaluator)
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_EVALUATORS} WHERE id=?", (evaluator.id,)
            ).fetchone()
            if existing is not None:
                stored = Evaluator.model_validate_json(existing[0])
                if evaluator.source != stored.source:
                    raise ValueError("Evaluator source is immutable")
                if evaluator.created_at != stored.created_at:
                    raise ValueError("Evaluator created_at is immutable")
                if evaluator.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale Evaluator")
                if evaluator == stored:
                    return
            db.execute(
                f"""
                INSERT INTO {_T_EVALUATORS}(
                    id,source,enabled,created_at,updated_at,
                    user_team_id,user_id,user_name,payload
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    user_team_id=excluded.user_team_id,
                    user_id=excluded.user_id,
                    user_name=excluded.user_name,
                    payload=excluded.payload
                """,
                (
                    evaluator.id,
                    evaluator.source.value,
                    int(evaluator.enabled),
                    evaluator.created_at.isoformat(),
                    evaluator.updated_at.isoformat(),
                    evaluator.user_team_id,
                    evaluator.user_id,
                    evaluator.user_name,
                    canonical_json(evaluator),
                ),
            )

    def save_evaluator_with_draft(
        self,
        evaluator: Evaluator,
        draft: EvaluatorDraft,
    ) -> None:
        _require_user_evaluator(evaluator)
        if draft.evaluator_id != evaluator.id:
            raise ValueError("EvaluatorDraft must belong to Evaluator")
        if draft.created_at < evaluator.created_at:
            raise ValueError("EvaluatorDraft cannot precede Evaluator creation")
        with self._connect() as db:
            db.execute(
                f"""
                INSERT INTO {_T_EVALUATORS}(
                    id,source,enabled,created_at,updated_at,
                    user_team_id,user_id,user_name,payload
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    evaluator.id,
                    evaluator.source.value,
                    int(evaluator.enabled),
                    evaluator.created_at.isoformat(),
                    evaluator.updated_at.isoformat(),
                    evaluator.user_team_id,
                    evaluator.user_id,
                    evaluator.user_name,
                    canonical_json(evaluator),
                ),
            )
            db.execute(
                f"""
                INSERT INTO {_T_EVALUATOR_DRAFTS}(
                    id,evaluator_id,created_at,updated_at,
                    user_team_id,user_id,user_name,payload
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    draft.id,
                    draft.evaluator_id,
                    draft.created_at.isoformat(),
                    draft.updated_at.isoformat(),
                    draft.user_team_id,
                    draft.user_id,
                    draft.user_name,
                    canonical_json(draft),
                ),
            )

    def get_evaluator(
        self, evaluator_id: str, *, user_team_id: str
    ) -> Evaluator | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_EVALUATORS} WHERE id=? AND user_team_id=?",
                (evaluator_id, user_team_id),
            ).fetchone()
        return Evaluator.model_validate_json(row[0]) if row else None

    def list_evaluators(
        self,
        include_disabled: bool = False,
        *,
        user_team_id: str,
    ) -> list[Evaluator]:
        query = f"SELECT payload FROM {_T_EVALUATORS} WHERE user_team_id=?"
        parameters: tuple[object, ...] = (user_team_id,)
        if not include_disabled:
            query += " AND enabled=1"
        query += " ORDER BY updated_at DESC, id"
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [Evaluator.model_validate_json(row[0]) for row in rows]

    def delete_unpublished_evaluator(
        self, evaluator_id: str, *, user_team_id: str
    ) -> None:
        with self._connect() as db:
            evaluator = db.execute(
                f"SELECT 1 FROM {_T_EVALUATORS} WHERE id=? AND user_team_id=?",
                (evaluator_id, user_team_id),
            ).fetchone()
            if evaluator is None:
                raise ValueError(f"unknown Evaluator: {evaluator_id}")
            publication = db.execute(
                f"SELECT 1 FROM {_T_EVALUATOR_VERSIONS} WHERE evaluator_id=? LIMIT 1",
                (evaluator_id,),
            ).fetchone()
            if publication is not None:
                raise ValueError("published Evaluator cannot be deleted")
            db.execute(f"DELETE FROM {_T_EVALUATORS} WHERE id=?", (evaluator_id,))

    def save_evaluator_draft(self, draft: EvaluatorDraft) -> None:
        with self._connect() as db:
            evaluator_row = db.execute(
                f"SELECT payload FROM {_T_EVALUATORS} WHERE id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if evaluator_row is None:
                raise ValueError(f"unknown Evaluator: {draft.evaluator_id}")
            evaluator = Evaluator.model_validate_json(evaluator_row[0])
            if draft.created_at < evaluator.created_at:
                raise ValueError("EvaluatorDraft cannot precede Evaluator creation")

            existing = db.execute(
                f"SELECT payload FROM {_T_EVALUATOR_DRAFTS} WHERE id=?", (draft.id,)
            ).fetchone()
            if existing is not None:
                stored = EvaluatorDraft.model_validate_json(existing[0])
                if draft.evaluator_id != stored.evaluator_id:
                    raise ValueError("EvaluatorDraft evaluator_id is immutable")
                if draft.created_at != stored.created_at:
                    raise ValueError("EvaluatorDraft created_at is immutable")
                if draft.based_on_version != stored.based_on_version:
                    raise ValueError("EvaluatorDraft based_on_version is immutable")
                if draft.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale EvaluatorDraft")
                if draft == stored:
                    return
                db.execute(
                    f"""
                    UPDATE {_T_EVALUATOR_DRAFTS}
                    SET updated_at=?, user_team_id=?, user_id=?, user_name=?, payload=?
                    WHERE id=?
                    """,
                    (
                        draft.updated_at.isoformat(),
                        draft.user_team_id,
                        draft.user_id,
                        draft.user_name,
                        canonical_json(draft),
                        draft.id,
                    ),
                )
                return

            active = db.execute(
                f"SELECT id FROM {_T_EVALUATOR_DRAFTS} WHERE evaluator_id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if active is not None:
                raise ValueError("Evaluator already has an active draft")
            db.execute(
                f"""
                INSERT INTO {_T_EVALUATOR_DRAFTS}(
                    id,evaluator_id,created_at,updated_at,
                    user_team_id,user_id,user_name,payload
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    draft.id,
                    draft.evaluator_id,
                    draft.created_at.isoformat(),
                    draft.updated_at.isoformat(),
                    draft.user_team_id,
                    draft.user_id,
                    draft.user_name,
                    canonical_json(draft),
                ),
            )

    def get_evaluator_draft(
        self,
        evaluator_id: str,
        *,
        user_team_id: str,
    ) -> EvaluatorDraft | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_EVALUATOR_DRAFTS} WHERE evaluator_id=? AND user_team_id=?",
                (evaluator_id, user_team_id),
            ).fetchone()
        return EvaluatorDraft.model_validate_json(row[0]) if row else None

    def delete_evaluator_draft(
        self,
        evaluator_id: str,
        expected_draft_id: str,
        *,
        user_team_id: str,
    ) -> None:
        with self._connect() as db:
            cursor = db.execute(
                f"""
                DELETE FROM {_T_EVALUATOR_DRAFTS}
                WHERE evaluator_id=? AND id=? AND user_team_id=?
                """,
                (evaluator_id, expected_draft_id, user_team_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Evaluator draft does not exist")

    def list_evaluator_versions(
        self,
        evaluator_id: str,
        *,
        user_team_id: str,
    ) -> list[EvaluatorSpec]:
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT version,content_sha256,payload
                FROM {_T_EVALUATOR_VERSIONS}
                WHERE evaluator_id=? AND user_team_id=?
                ORDER BY version DESC
                """,
                (evaluator_id, user_team_id),
            ).fetchall()
        return [_load_evaluator_spec(row) for row in rows]

    def get_evaluator_version(
        self,
        evaluator_id: str,
        version: str,
        *,
        user_team_id: str,
    ) -> EvaluatorSpec | None:
        version_number = _parse_evaluator_version(version)
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT version,content_sha256,payload
                FROM {_T_EVALUATOR_VERSIONS}
                WHERE evaluator_id=? AND version=? AND user_team_id=?
                """,
                (evaluator_id, version_number, user_team_id),
            ).fetchone()
        return _load_evaluator_spec(row) if row else None

    def get_latest_evaluator_version(
        self,
        evaluator_id: str,
        *,
        user_team_id: str,
    ) -> EvaluatorSpec | None:
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT version,content_sha256,payload
                FROM {_T_EVALUATOR_VERSIONS}
                WHERE evaluator_id=? AND user_team_id=?
                ORDER BY version DESC
                LIMIT 1
                """,
                (evaluator_id, user_team_id),
            ).fetchone()
        return _load_evaluator_spec(row) if row else None

    def publish_evaluator_draft(
        self,
        expected_draft_id: str,
        published: EvaluatorSpec,
    ) -> None:
        version = _parse_evaluator_version(published.version)
        with self._connect() as db:
            draft_row = db.execute(
                f"SELECT payload FROM {_T_EVALUATOR_DRAFTS} WHERE id=?",
                (expected_draft_id,),
            ).fetchone()
            if draft_row is None:
                raise ValueError("expected Evaluator draft does not exist")
            draft = EvaluatorDraft.model_validate_json(draft_row[0])

            evaluator_row = db.execute(
                f"SELECT payload FROM {_T_EVALUATORS} WHERE id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if evaluator_row is None:
                raise ValueError(f"unknown Evaluator: {draft.evaluator_id}")
            evaluator = Evaluator.model_validate_json(evaluator_row[0])

            latest_row = db.execute(
                f"""
                SELECT MAX(version) FROM {_T_EVALUATOR_VERSIONS}
                WHERE evaluator_id=?
                """,
                (evaluator.id,),
            ).fetchone()
            next_version = (latest_row[0] or 0) + 1
            if version != next_version:
                raise ValueError(
                    f"Evaluator publication requires version {next_version}"
                )

            expected = build_evaluator_publication(
                evaluator,
                draft,
                next_version,
            )
            if published != expected:
                raise ValueError(
                    "published EvaluatorSpec does not match the current draft"
                )

            db.execute(
                f"""
                INSERT INTO {_T_EVALUATOR_VERSIONS}(
                    evaluator_id,version,content_sha256,
                    user_team_id,user_id,user_name,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    published.id,
                    version,
                    published.content_sha256,
                    published.user_team_id,
                    published.user_id,
                    published.user_name,
                    canonical_json(published),
                ),
            )
            cursor = db.execute(
                f"DELETE FROM {_T_EVALUATOR_DRAFTS} WHERE id=?",
                (expected_draft_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Evaluator draft does not exist")

    def save_dataset(self, dataset: Dataset) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_DATASETS} WHERE id = ?", (dataset.id,)
            ).fetchone()
            if existing:
                stored = Dataset.model_validate_json(existing[0])
                if dataset.created_at != stored.created_at:
                    raise ValueError("Dataset created_at is immutable")
                if dataset.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale Dataset")
                if dataset == stored:
                    return
            db.execute(
                f"""
                INSERT INTO {_T_DATASETS}(
                    id,name,archived,updated_at,
                    user_team_id,user_id,user_name,payload
                )
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    archived=excluded.archived,
                    updated_at=excluded.updated_at,
                    user_team_id=excluded.user_team_id,
                    user_id=excluded.user_id,
                    user_name=excluded.user_name,
                    payload=excluded.payload
                """,
                (
                    dataset.id, dataset.name, int(dataset.archived),
                    dataset.updated_at.isoformat(),
                    dataset.user_team_id, dataset.user_id, dataset.user_name,
                    canonical_json(dataset),
                ),
            )

    def save_dataset_with_version(
        self, dataset: Dataset, version: DatasetVersion
    ) -> None:
        if version.dataset_id != dataset.id:
            raise ValueError("DatasetVersion must belong to Dataset")
        with self._connect() as db:
            db.execute(
                f"""
                INSERT INTO {_T_DATASETS}(
                    id,name,archived,updated_at,
                    user_team_id,user_id,user_name,payload
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    dataset.id,
                    dataset.name,
                    int(dataset.archived),
                    dataset.updated_at.isoformat(),
                    dataset.user_team_id,
                    dataset.user_id,
                    dataset.user_name,
                    canonical_json(dataset),
                ),
            )
            db.execute(
                f"""
                INSERT INTO {_T_DATASET_VERSIONS}(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    version.id,
                    version.dataset_id,
                    version.version,
                    version.status.value,
                    version.created_at.isoformat(),
                    version.content_sha256,
                    canonical_json(version),
                ),
            )

    def get_dataset(
        self, dataset_id: str, *, user_team_id: str
    ) -> Dataset | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_DATASETS} WHERE id=? AND user_team_id=?",
                (dataset_id, user_team_id),
            ).fetchone()
        return Dataset.model_validate_json(row[0]) if row else None

    def list_datasets(
        self, include_archived: bool = False, *, user_team_id: str
    ) -> list[Dataset]:
        query = f"SELECT payload FROM {_T_DATASETS} WHERE user_team_id=?"
        parameters: tuple[object, ...] = (user_team_id,)
        if not include_archived:
            query += " AND archived=0"
        query += " ORDER BY updated_at DESC, id"
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [Dataset.model_validate_json(row[0]) for row in rows]

    def save_dataset_version(self, version: DatasetVersion) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_DATASET_VERSIONS} WHERE id = ?", (version.id,)
            ).fetchone()
            if existing:
                stored = DatasetVersion.model_validate_json(existing[0])
                if stored.status == DatasetVersionStatus.PUBLISHED:
                    if stored != version:
                        raise ValueError("published DatasetVersion is immutable")
                    return
                if version.status != DatasetVersionStatus.DRAFT:
                    raise ValueError(
                        "draft DatasetVersion cannot be published through save"
                    )
                if version.dataset_id != stored.dataset_id:
                    raise ValueError("DatasetVersion dataset_id is immutable")
                if version.created_at != stored.created_at:
                    raise ValueError("DatasetVersion created_at is immutable")
                if version.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale DatasetVersion draft")
                if version == stored:
                    return
                db.execute(
                    f"""
                    UPDATE {_T_DATASET_VERSIONS}
                    SET content_sha256 = ?,
                        user_team_id = ?, user_id = ?, user_name = ?,
                        payload = ?
                    WHERE id = ? AND status = 'draft'
                    """,
                    (
                        version.content_sha256,
                        version.user_team_id, version.user_id, version.user_name,
                        canonical_json(version),
                        version.id,
                    ),
                )
                return
            if version.status == DatasetVersionStatus.PUBLISHED:
                conflict = db.execute(
                    f"""
                    SELECT payload FROM {_T_DATASET_VERSIONS}
                    WHERE dataset_id=? AND version=? AND status='published'
                    """,
                    (version.dataset_id, version.version),
                ).fetchone()
                if conflict:
                    stored = DatasetVersion.model_validate_json(conflict[0])
                    if stored != version:
                        raise ValueError("published Dataset version number already exists")
                    return
            db.execute(
                f"""
                INSERT INTO {_T_DATASET_VERSIONS}(
                    id,dataset_id,version,status,created_at,content_sha256,
                    user_team_id,user_id,user_name,
                    payload
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version.id, version.dataset_id, version.version, version.status.value,
                    version.created_at.isoformat(), version.content_sha256,
                    version.user_team_id, version.user_id, version.user_name,
                    canonical_json(version),
                ),
            )

    def get_published_dataset_version(
        self, dataset_id: str, version: int, *, user_team_id: str
    ) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT payload FROM {_T_DATASET_VERSIONS}
                WHERE dataset_id=? AND version=? AND status='published'
                    AND user_team_id=?
                """,
                (dataset_id, version, user_team_id),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def get_latest_published_dataset_version(
        self, dataset_id: str, *, user_team_id: str
    ) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT payload FROM {_T_DATASET_VERSIONS}
                WHERE dataset_id=? AND status='published' AND user_team_id=?
                ORDER BY version DESC LIMIT 1
                """,
                (dataset_id, user_team_id),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def get_dataset_draft(
        self, dataset_id: str, *, user_team_id: str
    ) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT payload FROM {_T_DATASET_VERSIONS}
                WHERE dataset_id=? AND status='draft' AND user_team_id=?
                """,
                (dataset_id, user_team_id),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def list_dataset_versions(
        self, dataset_id: str, include_draft: bool = True, *, user_team_id: str
    ) -> list[DatasetVersion]:
        query = (
            f"SELECT payload FROM {_T_DATASET_VERSIONS} "
            f"WHERE dataset_id=? AND user_team_id=?"
        )
        parameters: tuple[object, ...] = (dataset_id, user_team_id)
        if not include_draft:
            query += " AND status='published'"
        query += " ORDER BY CASE status WHEN 'draft' THEN 0 ELSE 1 END, version DESC"
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [DatasetVersion.model_validate_json(row[0]) for row in rows]

    def delete_dataset_draft(
        self, dataset_id: str, expected_draft_id: str, *, user_team_id: str
    ) -> None:
        with self._connect() as db:
            cursor = db.execute(
                f"""
                DELETE FROM {_T_DATASET_VERSIONS}
                WHERE dataset_id=? AND id=? AND status='draft' AND user_team_id=?
                """,
                (dataset_id, expected_draft_id, user_team_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Dataset draft does not exist")

    def replace_dataset_draft(
        self, expected_draft_id: str, published: DatasetVersion
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT payload FROM {_T_DATASET_VERSIONS}
                WHERE id=? AND status='draft' AND user_team_id=?
                """,
                (expected_draft_id, published.user_team_id),
            ).fetchone()
            if row is None:
                raise ValueError("expected Dataset draft does not exist")
            draft = DatasetVersion.model_validate_json(row[0])
            if draft.dataset_id != published.dataset_id:
                raise ValueError("published DatasetVersion does not match the draft")
            if published.status != DatasetVersionStatus.PUBLISHED:
                raise ValueError("replacement DatasetVersion must be published")
            if published.id == draft.id:
                raise ValueError("published DatasetVersion requires a new identity")
            if published.content_sha256 != draft.content_sha256:
                raise ValueError("published DatasetVersion content does not match the draft")
            if published.created_at != draft.created_at:
                raise ValueError("published DatasetVersion must preserve draft created_at")
            if published.based_on_version != draft.based_on_version:
                raise ValueError("published DatasetVersion must preserve draft ancestry")
            if published.updated_at < draft.updated_at:
                raise ValueError("cannot replace a newer DatasetVersion draft")
            db.execute(
                f"""
                INSERT INTO {_T_DATASET_VERSIONS}(
                    id,dataset_id,version,status,created_at,content_sha256,
                    user_team_id,user_id,user_name,
                    payload
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    published.id, published.dataset_id, published.version,
                    published.status.value, published.created_at.isoformat(),
                    published.content_sha256,
                    published.user_team_id, published.user_id, published.user_name,
                    canonical_json(published),
                ),
            )
            db.execute(f"DELETE FROM {_T_DATASET_VERSIONS} WHERE id=?", (draft.id,))

    def save_run(self, run: EvaluationRun) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_RUNS} WHERE id = ?", (run.id,)
            ).fetchone()
            if existing is None:
                references = self._run_asset_references(db, run)
                db.execute(
                    f"""
                    INSERT INTO {_T_RUNS}(
                        id,status,created_at,scheduled_for,
                        user_team_id,user_id,user_name,
                        api_key,
                        payload
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run.id,
                        run.status,
                        run.created_at.isoformat(),
                        (
                            run.scheduled_for.isoformat()
                            if run.scheduled_for is not None
                            else None
                        ),
                        run.user_team_id,
                        run.user_id,
                        run.user_name,
                        run.api_key,
                        canonical_json(run),
                    ),
                )
                db.executemany(
                    f"""
                    INSERT INTO {_T_RUN_ASSET_REFS}(
                        run_id,asset_kind,source_id,asset_id,version,content_sha256
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    references,
                )
                return

            stored = EvaluationRun.model_validate_json(existing[0])
            if run == stored:
                return
            if run.manifest != stored.manifest:
                raise ValueError("EvaluationRun manifest is immutable")
            if run.created_at != stored.created_at:
                raise ValueError("EvaluationRun created_at is immutable")
            if run.scheduled_for != stored.scheduled_for:
                raise ValueError("EvaluationRun scheduled_for is immutable")
            if stored.started_at is not None and run.started_at != stored.started_at:
                raise ValueError("EvaluationRun started_at is immutable once set")
            if stored.completed_at is not None:
                raise ValueError("terminal EvaluationRun is immutable")
            db.execute(
                f"""
                UPDATE {_T_RUNS} SET status = ?, payload = ?,
                    user_team_id = ?, user_id = ?, user_name = ?,
                    api_key = ?
                WHERE id = ?
                """,
                (
                    run.status, canonical_json(run),
                    run.user_team_id, run.user_id, run.user_name,
                    run.api_key,
                    run.id,
                ),
            )

    def get_run(
        self, run_id: str, *, user_team_id: str | None = None
    ) -> EvaluationRun | None:
        with self._connect() as db:
            if user_team_id is None:
                row = db.execute(
                    f"SELECT payload FROM {_T_RUNS} WHERE id=?", (run_id,)
                ).fetchone()
            else:
                row = db.execute(
                    f"SELECT payload FROM {_T_RUNS} WHERE id=? AND user_team_id=?",
                    (run_id, user_team_id),
                ).fetchone()
        return EvaluationRun.model_validate_json(row[0]) if row else None

    def list_runs(
        self, limit: int = 50, *, user_team_id: str
    ) -> list[EvaluationRun]:
        if limit < 1:
            raise ValueError("Run list limit must be at least 1")
        with self._connect() as db:
            rows = db.execute(
                f"SELECT payload FROM {_T_RUNS} WHERE user_team_id=? "
                f"ORDER BY created_at DESC, id LIMIT ?",
                (user_team_id, limit),
            ).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def list_runs_by_dataset_version(
        self, dataset_id: str, version: int, limit: int = 50, *, user_team_id: str
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "dataset", "", dataset_id, str(version), limit=limit,
            user_team_id=user_team_id,
        )

    def list_runs_by_case_content(
        self,
        dataset_id: str,
        version: int,
        case_id: str,
        content_sha256: str,
        limit: int = 50,
        *,
        user_team_id: str,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "case",
            dataset_id,
            case_id,
            str(version),
            content_sha256=content_sha256,
            limit=limit,
            user_team_id=user_team_id,
        )

    def list_runs_by_target_version(
        self,
        source_id: str,
        target_type: TargetType,
        target_id: str,
        version: str,
        limit: int = 50,
        *,
        content_sha256: str | None = None,
        user_team_id: str,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            target_type.value,
            source_id,
            target_id,
            version,
            content_sha256=content_sha256,
            limit=limit,
            user_team_id=user_team_id,
        )

    def list_runs_by_skill_version(
        self,
        source_id: str,
        skill_id: str,
        version: str,
        limit: int = 50,
        *,
        content_sha256: str | None = None,
        user_team_id: str,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "skill",
            source_id,
            skill_id,
            version,
            content_sha256=content_sha256,
            limit=limit,
            user_team_id=user_team_id,
        )

    def list_runs_by_evaluator_version(
        self, evaluator_id: str, version: str, limit: int = 50, *, user_team_id: str
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "evaluator", "", evaluator_id, version, limit=limit,
            user_team_id=user_team_id,
        )

    def _run_asset_references(
        self,
        db: sqlite3.Connection,
        run: EvaluationRun,
    ) -> list[tuple[str, str, str, str, str, str]]:
        manifest = run.manifest
        dataset = manifest.dataset
        references = [
            (
                run.id,
                "dataset",
                "",
                dataset.dataset_id,
                str(dataset.version),
                dataset.content_sha256,
            )
        ]
        references.extend(
            (
                run.id,
                "case",
                dataset.dataset_id,
                case.id,
                str(dataset.version),
                content_sha256(case),
            )
            for case in manifest.execution_cases
        )

        target = manifest.target
        references.append(
            (
                run.id,
                target.ref.target_type.value,
                target.ref.source_id,
                target.ref.external_target_id,
                target.ref.external_version_id,
                target.descriptor_sha256,
            )
        )
        descriptor_row = db.execute(
            f"SELECT payload FROM {_T_TARGET_DESCRIPTORS} WHERE content_sha256=?",
            (target.descriptor_sha256,),
        ).fetchone()
        if descriptor_row is not None:
            descriptor = TargetDescriptor.model_validate_json(descriptor_row[0])
            if descriptor.ref != target.ref:
                raise ValueError(
                    "TargetDescriptor reference does not match TargetSnapshot"
                )
            references.extend(
                (
                    run.id,
                    "skill",
                    descriptor.ref.source_id,
                    skill.external_skill_id,
                    skill.external_version_id,
                    content_sha256(skill),
                )
                for skill in descriptor.skills
            )

        references.extend(
            (
                run.id,
                "evaluator",
                "",
                evaluator.id,
                evaluator.version,
                evaluator.content_sha256,
            )
            for evaluator in manifest.evaluator_specs
        )
        return references

    def _list_runs_by_asset(
        self,
        asset_kind: str,
        source_id: str,
        asset_id: str,
        version: str,
        *,
        content_sha256: str | None = None,
        limit: int,
        user_team_id: str,
    ) -> list[EvaluationRun]:
        if limit < 1:
            raise ValueError("Run list limit must be at least 1")
        query = f"""
            SELECT {_T_RUNS}.payload
            FROM {_T_RUN_ASSET_REFS}
            JOIN {_T_RUNS} ON {_T_RUNS}.id={_T_RUN_ASSET_REFS}.run_id
            WHERE asset_kind=? AND source_id=? AND asset_id=? AND version=?
                AND {_T_RUNS}.user_team_id=?
        """
        parameters: tuple[object, ...] = (
            asset_kind,
            source_id,
            asset_id,
            version,
            user_team_id,
        )
        if content_sha256 is not None:
            query += " AND content_sha256=?"
            parameters += (content_sha256,)
        query += f" ORDER BY {_T_RUNS}.created_at DESC, {_T_RUNS}.id LIMIT ?"
        parameters += (limit,)
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def claim_pending_run(
        self, run_id: str, started_at: datetime
    ) -> EvaluationRun | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_RUNS} WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None

            pending = EvaluationRun.model_validate_json(row[0])
            if pending.status is not RunStatus.PENDING:
                return None
            running = transition_run(
                pending, RunStatus.RUNNING, occurred_at=started_at
            )
            cursor = db.execute(
                f"""
                UPDATE {_T_RUNS} SET status=?, payload=?
                WHERE id=? AND status='pending'
                """,
                (running.status, canonical_json(running), run_id),
            )
            return running if cursor.rowcount == 1 else None

    def claim_due_scheduled_runs(
        self, due_at: datetime, limit: int = 100
    ) -> list[EvaluationRun]:
        if limit < 1:
            raise ValueError("scheduled Run claim limit must be at least 1")
        current_time = normalize_utc(due_at, "scheduled Run due_at")
        claimed: list[EvaluationRun] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                f"""
                SELECT payload FROM {_T_RUNS}
                WHERE status='scheduled' AND scheduled_for<=?
                ORDER BY scheduled_for, created_at, id
                LIMIT ?
                """,
                (current_time.isoformat(), limit),
            ).fetchall()
            for row in rows:
                scheduled = EvaluationRun.model_validate_json(row[0])
                pending = transition_run(
                    scheduled,
                    RunStatus.PENDING,
                    occurred_at=current_time,
                )
                cursor = db.execute(
                    f"""
                    UPDATE {_T_RUNS} SET status=?, payload=?
                    WHERE id=? AND status='scheduled'
                    """,
                    (
                        pending.status,
                        canonical_json(pending),
                        pending.id,
                    ),
                )
                if cursor.rowcount == 1:
                    claimed.append(pending)
        return claimed

    def cancel_run(
        self, run_id: str, cancelled_at: datetime, *, user_team_id: str
    ) -> EvaluationRun | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT payload FROM {_T_RUNS} WHERE id=? AND user_team_id=?",
                (run_id, user_team_id),
            ).fetchone()
            if row is None:
                return None

            current = EvaluationRun.model_validate_json(row[0])
            if current.status not in {
                RunStatus.SCHEDULED,
                RunStatus.PENDING,
                RunStatus.RUNNING,
            }:
                return None
            cancelled = transition_run(
                current,
                RunStatus.CANCELLED,
                occurred_at=cancelled_at,
            )
            cursor = db.execute(
                f"""
                UPDATE {_T_RUNS} SET status=?, payload=?
                WHERE id=? AND status=? AND user_team_id=?
                """,
                (
                    cancelled.status,
                    canonical_json(cancelled),
                    run_id,
                    current.status,
                    user_team_id,
                ),
            )
            return cancelled if cursor.rowcount == 1 else None

    def list_runs_by_status(
        self,
        status: RunStatus,
        limit: int | None = None,
        oldest_first: bool = False,
        *,
        user_team_id: str | None = None,
    ) -> list[EvaluationRun]:
        if limit is not None and limit < 1:
            raise ValueError("Run list limit must be at least 1")
        direction = "ASC" if oldest_first else "DESC"
        order_column = (
            "COALESCE(scheduled_for, created_at)"
            if status in {RunStatus.SCHEDULED, RunStatus.PENDING}
            else "created_at"
        )
        query = f"SELECT payload FROM {_T_RUNS} WHERE status=?"
        parameters: tuple[object, ...] = (status.value,)
        if user_team_id is not None:
            query += " AND user_team_id=?"
            parameters += (user_team_id,)
        query += f" ORDER BY {order_column} {direction}, id"
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def count_runs_by_status(self, *, user_team_id: str) -> dict[RunStatus, int]:
        counts = {status: 0 for status in RunStatus}
        with self._connect() as db:
            rows = db.execute(
                f"SELECT status, COUNT(*) AS count FROM {_T_RUNS} "
                f"WHERE user_team_id=? GROUP BY status",
                (user_team_id,),
            ).fetchall()
        for row in rows:
            counts[RunStatus(row["status"])] = row["count"]
        return counts
    def save_trace(self, trace: Trace) -> None:
        with self._connect() as db:
            existing = db.execute(
                f"SELECT payload FROM {_T_TRACES} WHERE id = ?", (trace.trace_id,)
            ).fetchone()
            if existing:
                stored = Trace.model_validate_json(existing[0])
                if (trace.run_id, trace.case_id) != (stored.run_id, stored.case_id):
                    raise ValueError("Trace Run and Case identity are immutable")
                if trace == stored:
                    return
                db.execute(
                    f"UPDATE {_T_TRACES} SET payload = ? WHERE id = ?",
                    (canonical_json(trace), trace.trace_id),
                )
                return

            occupied = db.execute(
                f"SELECT id FROM {_T_TRACES} WHERE run_id = ? AND case_id = ?",
                (trace.run_id, trace.case_id),
            ).fetchone()
            if occupied:
                raise ValueError("Run and Case already have a different Trace")
            db.execute(
                f"INSERT INTO {_T_TRACES}(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                (trace.trace_id, trace.run_id, trace.case_id, canonical_json(trace)),
            )

    def get_trace(self, run_id: str, case_id: str) -> Trace | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM {_T_TRACES} WHERE run_id=? AND case_id=?", (run_id, case_id)
            ).fetchone()
        return Trace.model_validate_json(row[0]) if row else None

    def list_traces(self, run_id: str) -> list[Trace]:
        with self._connect() as db:
            rows = db.execute(
                f"SELECT payload FROM {_T_TRACES} WHERE run_id=? ORDER BY case_id,id", (run_id,)
            ).fetchall()
        return [Trace.model_validate_json(row[0]) for row in rows]

    def save_results(self, results: Sequence[EvaluationResult]) -> None:
        result_items = tuple(results)
        result_ids = tuple(result.id for result in result_items)
        result_keys = tuple(
            (result.run_id, result.case_id, result.evaluator_id)
            for result in result_items
        )
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("EvaluationResult ids must be unique within a batch")
        if len(set(result_keys)) != len(result_keys):
            raise ValueError(
                "EvaluationResults must be unique by Run, Case, and Evaluator"
            )

        with self._connect() as db:
            for result in result_items:
                existing = db.execute(
                    f"SELECT payload FROM {_T_RESULTS} WHERE id = ?", (result.id,)
                ).fetchone()
                if existing:
                    stored = EvaluationResult.model_validate_json(existing[0])
                    if stored != result:
                        raise ValueError("EvaluationResult is immutable")
                    continue

                occupied = db.execute(
                    f"""
                    SELECT id FROM {_T_RESULTS}
                    WHERE run_id = ? AND case_id = ? AND evaluator_id = ?
                    """,
                    (result.run_id, result.case_id, result.evaluator_id),
                ).fetchone()
                if occupied:
                    raise ValueError(
                        "Run, Case, and Evaluator already have an EvaluationResult"
                    )
                db.execute(
                    f"""
                    INSERT INTO {_T_RESULTS}(
                        id,run_id,case_id,trace_id,evaluator_id,payload
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        result.id,
                        result.run_id,
                        result.case_id,
                        result.trace_id,
                        result.evaluator_id,
                        canonical_json(result),
                    ),
                )

    def list_results(self, run_id: str) -> list[EvaluationResult]:
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT payload FROM {_T_RESULTS}
                WHERE run_id=? ORDER BY case_id,evaluator_id,id
                """,
                (run_id,),
            ).fetchall()
        return [EvaluationResult.model_validate_json(row[0]) for row in rows]


def _require_user_evaluator(evaluator: Evaluator) -> None:
    if evaluator.source != EvaluatorSource.USER:
        raise ValueError("only user Evaluators can be persisted")


def _parse_evaluator_version(version: str) -> int:
    if (
        not isinstance(version, str)
        or not version.isascii()
        or not version.isdecimal()
    ):
        raise ValueError("Evaluator version must be a canonical positive integer")
    parsed = int(version)
    if parsed < 1 or str(parsed) != version:
        raise ValueError("Evaluator version must be a canonical positive integer")
    return parsed


def _load_evaluator_spec(row: sqlite3.Row) -> EvaluatorSpec:
    spec = EvaluatorSpec.model_validate_json(row["payload"])
    if spec.version != str(row["version"]):
        raise ValueError("stored Evaluator version does not match its payload")
    if spec.content_sha256 != row["content_sha256"]:
        raise ValueError("stored Evaluator content hash does not match its payload")
    return spec
