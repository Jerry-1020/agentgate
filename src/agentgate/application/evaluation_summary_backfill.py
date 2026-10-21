"""Bounded, restartable rebuild of disposable evaluation read projections."""

import logging

from agentgate.domain import RunStatus
from agentgate.result.summary import build_completed_run_summary
from agentgate.storage.evaluation_query_models import SummarySourceChanged

LOGGER = logging.getLogger(__name__)


def backfill(repository, *, batch_size=50, apply=False):
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    report = {"applied": apply, "scanned": 0, "rebuilt": 0, "deleted": 0, "failures": []}
    LOGGER.info("Evaluation summary backfill started: apply=%s batch_size=%d", apply, batch_size)
    for entity in ("dataset_version", "run", "task"):
        cursor = None
        while True:
            ids = repository.list_summary_backfill_ids(
                entity=entity, after_id=cursor, limit=batch_size
            )
            if not ids:
                break
            for identifier in ids:
                report["scanned"] += 1
                if not apply:
                    continue
                try:
                    for attempt in range(3):
                        try:
                            if entity == "run":
                                source = repository.read_run_summary_source(identifier)
                                if source is None:
                                    report["deleted"] += 1
                                    break
                                summary = (
                                    build_completed_run_summary(source.run, source.results)
                                    if source.run.status == RunStatus.COMPLETED
                                    else None
                                )
                                changed = repository.rebuild_run_summary(source, summary)
                            elif entity == "task":
                                changed = repository.rebuild_task_query_fields(identifier)
                            else:
                                changed = repository.rebuild_dataset_version_query_fields(
                                    identifier
                                )
                            report["rebuilt" if changed else "deleted"] += 1
                            break
                        except SummarySourceChanged:
                            if attempt == 2:
                                raise
                            LOGGER.warning(
                                "Summary backfill source changed; retrying: entity=%s id=%s",
                                entity,
                                identifier,
                            )
                except Exception as exc:
                    LOGGER.exception("Summary backfill failed: entity=%s id=%s", entity, identifier)
                    report["failures"].append(
                        {"entity": entity, "id": identifier, "error_type": type(exc).__name__}
                    )
            cursor = ids[-1]
    report["failures"].extend(repository.audit_evaluation_summaries())
    LOGGER.info(
        "Evaluation summary backfill finished: scanned=%d failures=%d",
        report["scanned"],
        len(report["failures"]),
    )
    return report
