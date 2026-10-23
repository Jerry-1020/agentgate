"""Explicit SQL projection operations shared by the two storage adapters.

Callers own the transaction. No connection, configuration or scoring side effects.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC
from zoneinfo import ZoneInfo

from sqlalchemy import text

from agentgate.domain import RunStatus, content_sha256

from .evaluation_query_models import (
    SUMMARY_VERSION,
    OverviewSummary,
    RunListSummary,
    SummarySourceChanged,
    TaskListSummary,
    TaskSummaryPage,
)

LOGGER = logging.getLogger(__name__)


def mysql(db):
    return not isinstance(db, sqlite3.Connection)


def execute(db, sql, params=None):
    return db.execute(text(sql) if mysql(db) else sql, params or {})


def rows(db, sql, params=None):
    result = execute(db, sql, params)
    return list(result.mappings()) if mysql(db) else [dict(r) for r in result.fetchall()]


def keys(db):
    return (
        ("id_key", "run_key", "task_key", "case_key", "evaluator_key", "user_team_key")
        if mysql(db)
        else ("id", "run_id", "task_id", "case_id", "evaluator_id", "user_team_id")
    )


def key(db, identifier):
    if not mysql(db):
        return identifier
    # Keep exactly the digest algorithm used by the existing MySQL adapter.
    from .mysql import _digest

    return _digest(identifier)


def stamp(db, value):
    utc = value.astimezone(UTC)
    return utc.replace(tzinfo=None) if mysql(db) else utc.isoformat()


def put_run(db, run):
    _, rk, _, ck, ek, _ = keys(db)
    k = key(db, run.id)
    if rows(db, f"SELECT {rk} FROM agentgate_run_summaries WHERE {rk}=:k", {"k": k}):
        return
    manifest = run.manifest
    date = run.created_at.astimezone(ZoneInfo("Asia/Shanghai"))
    name = manifest.target.display_name
    name = "贷款智能体" if name == "Loan Agent" else name
    fallback = f"{name}{date.month}{date.day:02d}"
    primary = set(manifest.primary_evaluator_ids)
    display = {
        "target_name": manifest.target.display_name,
        "target_version": manifest.target.ref.external_version_id,
        "dataset_name": manifest.dataset.dataset_name,
        "dataset_version": manifest.dataset.version,
        "evaluator_kinds": list(
            dict.fromkeys(s.kind.value for s in manifest.evaluator_specs if s.id in primary)
        ),
        "scoring_mode": manifest.metric_plan.id,
    }
    p = {
        "k": k,
        "rid": run.id,
        "digest": content_sha256(manifest),
        "display": json.dumps(display, ensure_ascii=False),
        "total": len(manifest.execution_cases),
        "name": fallback,
    }
    extra_column, extra_value = (",run_id", ",:rid") if mysql(db) else ("", "")
    execute(
        db,
        f"""INSERT INTO agentgate_run_summaries
        ({rk}{extra_column},manifest_sha256,display_payload,total_cases,fallback_name)
        VALUES (:k{extra_value},:digest,:display,:total,:name)""",
        p,
    )
    expected = {spec.id for spec in manifest.evaluator_specs}
    for case in manifest.execution_cases:
        execute(
            db,
            f"INSERT INTO agentgate_run_case_progress ({rk},{ck},completed) VALUES (:r,:c,:done)",
            {"r": k, "c": key(db, case.id), "done": int(not expected)},
        )
    for evaluator in sorted(expected):
        execute(
            db,
            f"INSERT INTO agentgate_run_expected_evaluators ({rk},{ek}) VALUES (:r,:e)",
            {"r": k, "e": key(db, evaluator)},
        )


def put_task(db, task):
    pk, rk, tk, _, _, _ = keys(db)
    first = "first_run_key" if mysql(db) else "first_run_id"
    execute(
        db,
        f"UPDATE agentgate_evaluation_tasks SET name=:n,kind=:kind,{first}=:r WHERE {pk}=:t",
        {
            "n": task.name,
            "kind": task.kind.value,
            "r": key(db, task.run_ids[0]),
            "t": key(db, task.id),
        },
    )
    for current, ids in ((1, task.run_ids), (0, task.previous_run_ids)):
        for position, rid in enumerate(ids):
            execute(
                db,
                f"""UPDATE agentgate_evaluation_task_runs
                SET is_current=:current,position=:pos WHERE {rk}=:r AND {tk}=:t""",
                {"current": current, "pos": position, "r": key(db, rid), "t": key(db, task.id)},
            )


def update_progress(db, run_id):
    _, rk, _, ck, ek, _ = keys(db)
    k = key(db, run_id)
    execute(
        db,
        f"""UPDATE agentgate_run_case_progress SET completed = CASE WHEN NOT EXISTS (
        SELECT 1 FROM agentgate_run_expected_evaluators e
        WHERE e.{rk}=agentgate_run_case_progress.{rk} AND NOT EXISTS (
            SELECT 1 FROM agentgate_results r WHERE r.{rk}=e.{rk} AND r.{ek}=e.{ek}
                AND r.{ck}=agentgate_run_case_progress.{ck}
        )) THEN 1 ELSE 0 END WHERE {rk}=:k""",
        {"k": k},
    )
    execute(
        db,
        f"""UPDATE agentgate_run_summaries SET summary_version=NULL,
        overall_score=NULL,gate_reason=NULL,source_results_sha256=NULL,result_count=NULL
        WHERE {rk}=:k""",
        {"k": k},
    )


def put_completed(db, run, summary, results):
    from agentgate.result.summary import result_source_digest

    if run.status != RunStatus.COMPLETED or summary.run_id != run.id:
        raise ValueError("invalid completed summary identity")
    if (
        summary.manifest_sha256 != content_sha256(run.manifest)
        or summary.result_count != len(results)
        or summary.source_results_sha256 != result_source_digest(results)
    ):
        raise SummarySourceChanged("completion source changed")
    _, rk, _, _, _, _ = keys(db)
    put_run(db, run)
    update_progress(db, run.id)
    execute(
        db,
        f"""UPDATE agentgate_run_summaries SET overall_score=:score,
        gate_reason=:reason,summary_version=:version,result_count=:count,
        source_results_sha256=:digest WHERE {rk}=:k""",
        {
            "score": summary.overall_score,
            "reason": summary.gate_reason,
            "version": summary.summary_version,
            "count": len(results),
            "digest": summary.source_results_sha256,
            "k": key(db, run.id),
        },
    )


def remove_run(db, run_id):
    _, rk, _, _, _, _ = keys(db)
    for table in ("run_case_progress", "run_expected_evaluators", "run_summaries"):
        execute(db, f"DELETE FROM agentgate_{table} WHERE {rk}=:k", {"k": key(db, run_id)})


def valid_summary(db, run="r", summary="s"):
    """Validate compact projection fields in SQL before aggregation, without reports."""

    def kind(field):
        path = "$." + field
        if mysql(db):
            return f"LOWER(JSON_TYPE(JSON_EXTRACT({summary}.display_payload,'{path}')))"
        return f"json_type({summary}.display_payload,'{path}')"

    string_type = "string" if mysql(db) else "text"
    fields = [
        f"{kind(field)}='{string_type}'"
        for field in ("target_name", "target_version", "dataset_name", "scoring_mode")
    ]
    fields.extend(
        [
            f"{kind('evaluator_kinds')}='array'",
            f"{kind('dataset_version')} IN ('integer','null')",
            f"{summary}.total_cases>=0",
            f"({summary}.overall_score IS NULL OR {summary}.overall_score BETWEEN 0 AND 1)",
            f"({run}.status<>'completed' OR {summary}.summary_version={SUMMARY_VERSION})",
        ]
    )
    # CASE guards JSON extraction on malformed text on both supported databases.
    return (
        f"CASE WHEN JSON_VALID({summary}.display_payload)=1 THEN "
        f"CASE WHEN {' AND '.join(fields)} THEN 1 ELSE 0 END ELSE 0 END"
    )


def run_relation(db):
    pk, rk, _, _, _, team = keys(db)
    return f"""SELECT r.{pk} AS k,r.id AS run_id,r.{team} AS team,r.status,r.created_at,
        s.display_payload,s.fallback_name,s.total_cases,s.overall_score,s.gate_reason,
        s.summary_version,{valid_summary(db)} AS summary_valid,
        COALESCE(p.completed_cases,0) AS completed_cases
        FROM agentgate_runs r LEFT JOIN agentgate_run_summaries s ON s.{rk}=r.{pk}
        LEFT JOIN (SELECT {rk},SUM(completed) AS completed_cases
                   FROM agentgate_run_case_progress GROUP BY {rk}) p ON p.{rk}=r.{pk}"""


def task_relation(db):
    pk, rk, tk, _, _, team = keys(db)
    first = "first_run_key" if mysql(db) else "first_run_id"
    return f"""SELECT t.{pk} AS k,t.id,t.id AS task_id,COALESCE(t.name,s.fallback_name,t.id) AS name,
        t.kind,t.created_at,first_run.id AS search_run_id,
        MAX(1-({valid_summary(db, "r", "member_summary")})) AS summary_pending,
        CASE WHEN SUM(CASE WHEN r.status='failed' THEN 1 ELSE 0 END)>0 THEN 'failed'
             WHEN SUM(CASE WHEN r.status='cancelled' THEN 1 ELSE 0 END)>0 THEN 'cancelled'
             WHEN MIN(CASE WHEN r.status='completed' THEN 1 ELSE 0 END)=1 THEN 'completed'
             WHEN SUM(CASE WHEN r.status IN ('running','completed') THEN 1 ELSE 0 END)>0 THEN 'running'
             ELSE first_run.status END AS status
        FROM agentgate_evaluation_tasks t
        JOIN agentgate_evaluation_task_runs a ON a.{tk}=t.{pk} AND a.is_current=1
        JOIN agentgate_runs r ON r.{pk}=a.{rk}
        LEFT JOIN agentgate_run_summaries member_summary ON member_summary.{rk}=r.{pk}
        JOIN agentgate_runs first_run ON first_run.{pk}=t.{first}
        LEFT JOIN agentgate_run_summaries s ON s.{rk}=t.{first}
        WHERE NOT EXISTS (
            SELECT 1 FROM agentgate_evaluation_task_runs bad
            LEFT JOIN agentgate_runs br ON br.{pk}=bad.{rk}
            WHERE bad.{tk}=t.{pk} AND bad.is_current=1
                AND (br.{pk} IS NULL OR br.{team}<>:team))
        GROUP BY t.{pk},t.id,t.name,s.fallback_name,t.kind,t.created_at,first_run.status,first_run.id
        UNION ALL
        SELECT r.{pk},r.id,NULL,COALESCE(s.fallback_name,r.id),'single',r.created_at,r.id,
        1-({valid_summary(db)}),r.status
        FROM agentgate_runs r LEFT JOIN agentgate_run_summaries s ON s.{rk}=r.{pk}
        WHERE r.{team}=:team AND NOT EXISTS (
            SELECT 1 FROM agentgate_evaluation_task_runs a WHERE a.{rk}=r.{pk})"""


def filters(db, query, alias="q"):
    clauses, params = [], {}
    for field, op in (("start_at", ">="), ("end_at", "<")):
        value = getattr(query, field)
        if value is not None:
            clauses.append(f"{alias}.created_at {op} :{field}")
            params[field] = stamp(db, value)
    if hasattr(query, "kind"):
        if query.kind:
            clauses.append(f"{alias}.kind=:kind")
            params["kind"] = query.kind.value
        if query.status:
            if query.status == RunStatus.PENDING:
                clauses.append(f"{alias}.status IN ('pending','scheduled')")
            else:
                clauses.append(f"{alias}.status=:status")
                params["status"] = query.status.value
        if query.keyword:
            # Literal substring search; percent/underscore are not wildcard operators.
            needle = query.keyword.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            concat = (
                f"CONCAT({alias}.name,' ',{alias}.id)"
                if mysql(db)
                else f"({alias}.name || ' ' || {alias}.id)"
            )
            clauses.append(
                f"(LOWER({concat}) LIKE :keyword ESCAPE '!' OR LOWER({alias}.search_run_id) LIKE :keyword ESCAPE '!')"
            )
            params["keyword"] = f"%{needle}%"
    return " AND ".join(clauses) or "1=1", params


def task_page(db, query, team):
    condition, p = filters(db, query)
    p["team"] = key(db, team)
    relation = task_relation(db)
    total = rows(db, f"SELECT COUNT(*) AS n FROM ({relation}) q WHERE {condition}", p)[0]["n"]
    p.update(limit=query.page_size, offset=(query.page - 1) * query.page_size)
    page = rows(
        db,
        f"""SELECT * FROM ({relation}) q WHERE {condition}
        ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset""",
        p,
    )
    if not page:
        return TaskSummaryPage(items=(), total=total, page=query.page, page_size=query.page_size)
    _, rk, tk, _, _, _ = keys(db)
    tokens = ",".join(f":k{i}" for i in range(len(page)))
    ids = {f"k{i}": row["k"] for i, row in enumerate(page)}
    members = rows(
        db,
        f"""SELECT {tk} AS task_key,{rk} AS run_key,position
        FROM agentgate_evaluation_task_runs WHERE is_current=1 AND {tk} IN ({tokens}) ORDER BY position""",
        ids,
    )
    historical = {
        item["task_key"]: item["n"]
        for item in rows(
            db,
            f"SELECT {tk} AS task_key,COUNT(*) AS n FROM agentgate_evaluation_task_runs "
            f"WHERE is_current=0 AND {tk} IN ({tokens}) GROUP BY {tk}",
            ids,
        )
    }
    run_keys = list(
        dict.fromkeys(
            [m["run_key"] for m in members] + [r["k"] for r in page if r["task_id"] is None]
        )
    )
    placeholders = ",".join(f":r{i}" for i in range(len(run_keys)))
    rparams = {f"r{i}": k for i, k in enumerate(run_keys)}
    run_rows = rows(
        db, f"SELECT * FROM ({run_relation(db)}) q WHERE k IN ({placeholders})", rparams
    )
    bykey = {}
    for r in run_rows:
        valid = bool(r["summary_valid"])
        display = json.loads(r["display_payload"]) if valid else {}
        bykey[r["k"]] = RunListSummary(
            target_name=display.get("target_name"),
            target_version=display.get("target_version"),
            dataset_name=display.get("dataset_name"),
            dataset_version=display.get("dataset_version"),
            evaluator_kinds=tuple(
                k for k in display.get("evaluator_kinds", []) if isinstance(k, str)
            ),
            scoring_mode=display.get("scoring_mode"),
            run_id=r["run_id"],
            status=r["status"],
            summary_pending=not valid,
            total_cases=r["total_cases"] if valid else None,
            completed_cases=r["completed_cases"] if valid else None,
            overall_score=r["overall_score"] if valid and r["status"] == "completed" else None,
            gate_reason=r["gate_reason"] if valid else None,
        )
    items = []
    for row in page:
        associated = (
            [m["run_key"] for m in members if m["task_key"] == row["k"]]
            if row["task_id"]
            else [row["k"]]
        )
        children = tuple(bykey[k] for k in associated)
        if mysql(db):
            row = dict(row)
            row["created_at"] = row["created_at"].replace(tzinfo=UTC)
        items.append(
            TaskListSummary(
                **{k: row[k] for k in ("id", "task_id", "name", "kind", "created_at", "status")},
                previous_run_count=historical.get(row["k"], 0) if row["task_id"] else 0,
                runs=children,
                summary_pending=any(r.summary_pending for r in children),
                total_cases=None
                if any(r.summary_pending for r in children)
                else sum(r.total_cases for r in children),
                completed_cases=None
                if any(r.summary_pending for r in children)
                else sum(r.completed_cases for r in children),
            )
        )
    pending_ids = [item.id for item in items if item.summary_pending]
    if pending_ids:
        LOGGER.warning(
            "Evaluation summaries pending: scope=task_page count=%d task_ids=%s reason=missing_or_invalid_summary",
            len(pending_ids),
            pending_ids[:10],
        )
    return TaskSummaryPage(
        items=tuple(items), total=total, page=query.page, page_size=query.page_size
    )


def overview(db, query, team):
    condition, p = filters(db, query)
    p["team"] = key(db, team)
    tasks = rows(
        db,
        f"SELECT COUNT(*) AS n,COALESCE(SUM(summary_pending),0) AS pending FROM ({task_relation(db)}) q WHERE {condition}",
        p,
    )[0]
    pk, rk, tk, _, _, _ = keys(db)
    stats = rows(
        db,
        f"""SELECT AVG(overall_score) AS score,COUNT(overall_score) AS scored,
        COALESCE(SUM(total_cases),0) AS samples FROM ({run_relation(db)}) q
        WHERE team=:team AND status='completed' AND summary_valid=1 AND {condition}
        AND NOT EXISTS (
            SELECT 1 FROM agentgate_evaluation_task_runs own
            JOIN agentgate_evaluation_task_runs member ON member.{tk}=own.{tk} AND member.is_current=1
            LEFT JOIN agentgate_runs mr ON mr.{pk}=member.{rk}
            LEFT JOIN agentgate_run_summaries ms ON ms.{rk}=member.{rk}
            WHERE own.{rk}=q.k AND (mr.{pk} IS NULL OR {valid_summary(db, "mr", "ms")}=0))""",
        p,
    )[0]
    pk, _, _, _, _, tc = keys(db)
    dk = "dataset_key" if mysql(db) else "dataset_id"
    datasets = rows(
        db,
        f"""SELECT COUNT(*) AS n,SUM(CASE WHEN v.id IS NOT NULL AND v.sample_count IS NULL THEN 1 ELSE 0 END) AS missing,
        COALESCE(SUM(v.sample_count),0) AS samples FROM agentgate_datasets d
        LEFT JOIN agentgate_dataset_versions v ON v.{dk}=d.{pk} AND v.status='published'
          AND v.{tc}=:team AND NOT EXISTS (SELECT 1 FROM agentgate_dataset_versions newer
              WHERE newer.{dk}=v.{dk} AND newer.status='published' AND newer.{tc}=:team AND newer.version>v.version)
        WHERE d.{tc}=:team AND d.archived=0""",
        p,
    )[0]
    if tasks["pending"] or datasets["missing"]:
        LOGGER.warning(
            "Evaluation summaries pending: scope=overview task_count=%d dataset_count=%d reason=missing_or_invalid_summary",
            tasks["pending"],
            datasets["missing"] or 0,
        )
    return OverviewSummary(
        task_count=tasks["n"],
        pending_summary_task_count=tasks["pending"],
        pending_dataset_count=datasets["missing"] or 0,
        average_score=stats["score"],
        scored_run_count=stats["scored"],
        completed_sample_count=stats["samples"],
        dataset_count=datasets["n"] - (datasets["missing"] or 0),
        dataset_sample_count=datasets["samples"],
    )


def backfill_ids(db, entity, after_id, limit):
    if entity not in {"run", "task", "dataset_version"} or not 1 <= limit <= 1000:
        raise ValueError("invalid backfill selection")
    table = {
        "run": "agentgate_runs",
        "task": "agentgate_evaluation_tasks",
        "dataset_version": "agentgate_dataset_versions",
    }[entity]
    return [
        r["id"]
        for r in rows(
            db,
            f"SELECT id FROM {table} WHERE id>:cursor ORDER BY id LIMIT :limit",
            {"cursor": after_id or "", "limit": limit},
        )
    ]


def source(db, run_id, *, lock=False):
    from agentgate.domain import EvaluationResult, EvaluationRun

    from .evaluation_query_models import RunSummarySource

    pk, rk, _, _, _, _ = keys(db)
    suffix = " FOR UPDATE" if mysql(db) and lock else ""
    found = rows(
        db, f"SELECT payload FROM agentgate_runs WHERE {pk}=:k" + suffix, {"k": key(db, run_id)}
    )
    if not found:
        return None
    result_rows = rows(
        db, f"SELECT payload FROM agentgate_results WHERE {rk}=:k", {"k": key(db, run_id)}
    )
    return RunSummarySource(
        run=EvaluationRun.model_validate_json(found[0]["payload"]),
        results=tuple(
            sorted(
                (EvaluationResult.model_validate_json(r["payload"]) for r in result_rows),
                key=lambda r: r.id,
            )
        ),
    )


def rebuild_run(db, expected, summary):
    actual = source(db, expected.run.id, lock=True)
    if actual is None:
        return False
    if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise SummarySourceChanged("backfill source changed")
    _, rk, _, _, _, _ = keys(db)
    existing = rows(
        db,
        f"SELECT summary_version FROM agentgate_run_summaries WHERE {rk}=:k",
        {"k": key(db, actual.run.id)},
    )
    if existing and (existing[0]["summary_version"] or 0) > SUMMARY_VERSION:
        raise SummarySourceChanged("newer summary version exists")
    remove_run(db, actual.run.id)
    put_run(db, actual.run)
    update_progress(db, actual.run.id)
    if actual.run.status == RunStatus.COMPLETED:
        if summary is None:
            raise ValueError("completed run requires a score projection")
        put_completed(db, actual.run, summary, actual.results)
    return True


def rebuild_entity(db, entity, identifier):
    from agentgate.domain import DatasetVersion
    from agentgate.domain.evaluation_task import EvaluationTask

    if entity not in {"task", "dataset_version"}:
        raise ValueError("invalid entity")
    pk, _, _, _, _, _ = keys(db)
    table = "agentgate_evaluation_tasks" if entity == "task" else "agentgate_dataset_versions"
    suffix = " FOR UPDATE" if mysql(db) else ""
    found = rows(
        db, f"SELECT payload FROM {table} WHERE {pk}=:k" + suffix, {"k": key(db, identifier)}
    )
    if not found:
        return False
    if entity == "task":
        put_task(db, EvaluationTask.model_validate_json(found[0]["payload"]))
    else:
        version = DatasetVersion.model_validate_json(found[0]["payload"])
        execute(
            db,
            f"UPDATE {table} SET sample_count=:n WHERE {pk}=:k",
            {"n": len(version.cases), "k": key(db, identifier)},
        )
    return True


def audit(db):
    pk, rk, tk, _, _, _ = keys(db)
    issues = []
    queries = {
        "run": f"""SELECT r.id FROM agentgate_runs r LEFT JOIN agentgate_run_summaries s ON s.{rk}=r.{pk}
            LEFT JOIN (SELECT {rk},COUNT(*) AS n FROM agentgate_run_case_progress GROUP BY {rk}) p ON p.{rk}=r.{pk}
            WHERE s.{rk} IS NULL OR COALESCE(p.n,0)<>s.total_cases OR
            (r.status='completed' AND (s.summary_version IS NULL OR s.summary_version<>:v))""",
        "task": f"""SELECT DISTINCT t.id FROM agentgate_evaluation_tasks t
            LEFT JOIN agentgate_evaluation_task_runs a ON a.{tk}=t.{pk}
            WHERE t.kind IS NULL OR a.{rk} IS NULL OR a.is_current IS NULL OR a.position IS NULL""",
        "dataset_version": "SELECT id FROM agentgate_dataset_versions WHERE sample_count IS NULL",
    }
    for entity, sql in queries.items():
        issues.extend(
            {"entity": entity, "id": r["id"], "error_type": "SummaryNotReady"}
            for r in rows(db, sql, {"v": SUMMARY_VERSION})
        )
    return issues
