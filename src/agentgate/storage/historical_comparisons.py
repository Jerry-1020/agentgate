"""Historical result references in existing task payloads; callers own transactions."""

from agentgate.domain import EvaluationRun, RunStatus, canonical_json
from agentgate.domain.evaluation_task import EvaluationTask, EvaluationTaskKind

from . import evaluation_projection as sql


class TaskReferencedError(ValueError):
    """Deleting an owning task would invalidate a saved comparison."""


def _task(db, task_id: str, *, lock: bool = False) -> EvaluationTask | None:
    pk, *_ = sql.keys(db)
    suffix = " FOR UPDATE" if lock and sql.mysql(db) else ""
    found = sql.rows(
        db,
        f"SELECT id,payload FROM agentgate_evaluation_tasks WHERE {pk}=:id{suffix}",
        {"id": sql.key(db, task_id)},
    )
    if not found or found[0]["id"] != task_id:
        return None
    return EvaluationTask.model_validate_json(found[0]["payload"])


def _run(db, run_id: str, team_id: str) -> EvaluationRun:
    pk, _, _, _, _, team = sql.keys(db)
    found = sql.rows(
        db,
        f"SELECT id,payload FROM agentgate_runs WHERE {pk}=:id AND {team}=:team",
        {"id": sql.key(db, run_id), "team": sql.key(db, team_id)},
    )
    if not found or found[0]["id"] != run_id:
        raise LookupError("unknown evaluation task")
    run = EvaluationRun.model_validate_json(found[0]["payload"])
    if run.user_team_id != team_id:
        raise LookupError("unknown evaluation task")
    return run


def is_reference(db, task_id: str) -> bool:
    pk, *_ = sql.keys(db)
    return bool(
        sql.rows(
            db,
            f"""SELECT t.id FROM agentgate_evaluation_tasks t
        WHERE t.{pk}=:id AND {sql.reference_task_condition(db)}""",
            {"id": sql.key(db, task_id)},
        )
    )


def accessible_reference(db, task_id: str, team_id: str) -> bool:
    task = _task(db, task_id)
    if task is None:
        raise LookupError("unknown evaluation task")
    for run_id in task.run_ids:
        _run(db, run_id, team_id)
    return is_reference(db, task_id)


def ensure_unreferenced(db, run_ids: tuple[str, ...]) -> None:
    if not run_ids:
        return
    _, rk, _, _, _, _ = sql.keys(db)
    params = {f"r{i}": sql.key(db, run_id) for i, run_id in enumerate(run_ids)}
    tokens = ",".join(f":{name}" for name in params)
    if sql.rows(
        db,
        f"""SELECT 1 FROM ({sql.historical_task_members(db)}) refs
        WHERE refs.{rk} IN ({tokens}) LIMIT 1""",
        params,
    ):
        raise TaskReferencedError("该单任务的结果已被历史对比任务引用，请先删除关联的对比任务。")


def save_reference(
    db,
    task: EvaluationTask,
    *,
    baseline_task_id: str,
    candidate_task_id: str,
    user_team_id: str,
) -> EvaluationTask:
    if task.kind != EvaluationTaskKind.AB or any(
        (
            task.previous_run_ids,
            task.static_report_ids,
            task.git_commit_refs,
            task.credential_id,
        )
    ):
        raise ValueError("historical comparisons contain only two run references")
    source_ids = (baseline_task_id, candidate_task_id)
    if len(set(source_ids)) != 2 or task.id in source_ids:
        raise ValueError("historical comparisons require distinct source task identities")
    # Lock owning tasks before checking runs; delete and rerun use the same owner lock.
    sources = {identity: _task(db, identity, lock=True) for identity in sorted(source_ids)}
    _, rk, tk, _, _, _ = sql.keys(db)
    for source_id, run_id in zip(source_ids, task.run_ids, strict=True):
        source = sources[source_id]
        if source is None:
            raise LookupError("unknown evaluation task")
        for current_id in source.run_ids:
            _run(db, current_id, user_team_id)
        run = _run(db, run_id, user_team_id)
        if source.kind != EvaluationTaskKind.SINGLE:
            raise ValueError("historical comparison sources must be single tasks")
        if run_id not in source.run_ids + source.previous_run_ids or not sql.rows(
            db,
            f"SELECT 1 FROM agentgate_evaluation_task_runs WHERE {rk}=:run AND {tk}=:task",
            {"run": sql.key(db, run_id), "task": sql.key(db, source_id)},
        ):
            raise ValueError("selected execution does not belong to its source task")
        if run.status != RunStatus.COMPLETED:
            raise ValueError("historical comparisons require completed runs")

    columns, values = "id,created_at,payload", ":id,:created,:payload"
    params = {
        "id": task.id,
        "created": sql.stamp(db, task.created_at),
        "payload": canonical_json(task),
    }
    if sql.mysql(db):
        columns, values = "id_key," + columns, ":key," + values
        params["key"] = sql.key(db, task.id)
        conflict = "ON DUPLICATE KEY UPDATE id=id"
    else:
        conflict = "ON CONFLICT(id) DO NOTHING"
    sql.execute(
        db,
        f"INSERT INTO agentgate_evaluation_tasks ({columns}) VALUES ({values}) {conflict}",
        params,
    )
    stored = _task(db, task.id, lock=True)
    if stored is None:
        raise ValueError("comparison identity conflict")
    for run_id in stored.run_ids:
        _run(db, run_id, user_team_id)
    if (
        stored.kind != EvaluationTaskKind.AB
        or stored.run_ids != task.run_ids
        or sql.rows(
            db,
            f"SELECT 1 FROM agentgate_evaluation_task_runs WHERE {tk}=:task",
            {"task": sql.key(db, stored.id)},
        )
    ):
        raise ValueError("comparison identity already has different references")
    # A new row has no projected kind yet. Classify it from its validated payload, not its name.
    sql.put_task(db, stored)
    return stored
