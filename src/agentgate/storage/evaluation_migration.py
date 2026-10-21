"""Additive, inspected evaluation projection upgrade; no import-time effects."""

from .evaluation_projection import execute

SQLITE_TABLES = (
    """CREATE TABLE IF NOT EXISTS agentgate_run_summaries (
        run_id TEXT PRIMARY KEY REFERENCES agentgate_runs(id) ON DELETE CASCADE,
        manifest_sha256 TEXT NOT NULL, display_payload TEXT NOT NULL,
        fallback_name TEXT NOT NULL,total_cases INTEGER NOT NULL CHECK(total_cases>=0),
        overall_score REAL,gate_reason TEXT,summary_version INTEGER,result_count INTEGER,
        source_results_sha256 TEXT)""",
    """CREATE TABLE IF NOT EXISTS agentgate_run_case_progress (
        run_id TEXT NOT NULL REFERENCES agentgate_runs(id) ON DELETE CASCADE,
        case_id TEXT NOT NULL,completed INTEGER NOT NULL CHECK(completed IN (0,1)),
        PRIMARY KEY(run_id,case_id))""",
    """CREATE TABLE IF NOT EXISTS agentgate_run_expected_evaluators (
        run_id TEXT NOT NULL REFERENCES agentgate_runs(id) ON DELETE CASCADE,
        evaluator_id TEXT NOT NULL,PRIMARY KEY(run_id,evaluator_id))""",
)
SQLITE_COLUMNS = {
    "agentgate_evaluation_tasks": {"name": "TEXT", "kind": "TEXT", "first_run_id": "TEXT"},
    "agentgate_evaluation_task_runs": {"is_current": "INTEGER", "position": "INTEGER"},
    "agentgate_dataset_versions": {"sample_count": "INTEGER"},
}


def upgrade_sqlite(db):
    for statement in SQLITE_TABLES:
        db.execute(statement)
    expected_tables = {
        "agentgate_run_summaries": {
            "run_id": "TEXT",
            "manifest_sha256": "TEXT",
            "display_payload": "TEXT",
            "fallback_name": "TEXT",
            "total_cases": "INTEGER",
            "overall_score": "REAL",
            "gate_reason": "TEXT",
            "summary_version": "INTEGER",
            "result_count": "INTEGER",
            "source_results_sha256": "TEXT",
        },
        "agentgate_run_case_progress": {
            "run_id": "TEXT",
            "case_id": "TEXT",
            "completed": "INTEGER",
        },
        "agentgate_run_expected_evaluators": {"run_id": "TEXT", "evaluator_id": "TEXT"},
    }
    for table, expected in expected_tables.items():
        actual = {row[1]: row[2].upper() for row in db.execute(f"PRAGMA table_info({table})")}
        if actual != expected:
            raise ValueError(f"incompatible projection table: {table}")
    for table, columns in SQLITE_COLUMNS.items():
        existing = {r[1]: r[2].upper() for r in db.execute(f"PRAGMA table_info({table})")}
        for column, kind in columns.items():
            if column not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind} NULL")
            elif existing[column] != kind:
                raise ValueError(f"incompatible column: {table}.{column}")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_runs_current_position ON agentgate_evaluation_task_runs(task_id,is_current,position)"
    )


def inspect_or_upgrade_mysql(engine, *, apply=False):
    from sqlalchemy import inspect

    from . import mysql_schema as s

    inspector = inspect(engine)
    additions = {
        "agentgate_evaluation_tasks": {
            "name": "LONGTEXT NULL",
            "kind": "VARCHAR(16) NULL",
            "first_run_key": "BINARY(32) NULL",
        },
        "agentgate_evaluation_task_runs": {
            "is_current": "SMALLINT NULL",
            "position": "INTEGER NULL",
        },
        "agentgate_dataset_versions": {"sample_count": "BIGINT NULL"},
    }
    pending = []
    for table in (s.run_summaries, s.run_case_progress, s.run_expected_evaluators):
        if not inspector.has_table(table.name):
            pending.append("create " + table.name)
            if apply:
                table.create(engine)
        else:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            if existing != set(table.c.keys()):
                raise ValueError("incompatible projection table: " + table.name)
            for column in inspector.get_columns(table.name):
                expected = table.c[column["name"]]
                actual_type = str(column["type"].compile(dialect=engine.dialect)).upper()
                expected_type = str(expected.type.compile(dialect=engine.dialect)).upper()
                if (
                    actual_type.split()[0] != expected_type.split()[0]
                    or column["nullable"] != expected.nullable
                ):
                    raise ValueError(
                        "incompatible projection column: " + table.name + "." + column["name"]
                    )
    with engine.begin() as db:
        for table, cols in additions.items():
            existing = {c["name"]: c for c in inspector.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing:
                    pending.append(f"add {table}.{col}")
                    if apply:
                        execute(db, f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                else:
                    expected_column = s.metadata.tables[table].c[col]
                    actual_type = str(existing[col]["type"].compile(dialect=engine.dialect)).upper()
                    expected_type = str(
                        expected_column.type.compile(dialect=engine.dialect)
                    ).upper()
                    if (
                        actual_type.split()[0] != expected_type.split()[0]
                        or not existing[col]["nullable"]
                    ):
                        raise ValueError("incompatible query column: " + table + "." + col)
        if "ix_task_runs_current_position" not in {
            i["name"] for i in inspector.get_indexes("agentgate_evaluation_task_runs")
        }:
            pending.append("index ix_task_runs_current_position")
            if apply:
                execute(
                    db,
                    "CREATE INDEX ix_task_runs_current_position ON agentgate_evaluation_task_runs(task_key,is_current,position)",
                )
    return pending
