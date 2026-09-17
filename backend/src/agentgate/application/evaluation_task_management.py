"""Persist user-facing associations without executing or modifying referenced runs."""

from agentgate.domain.evaluation_task import EvaluationTask, EvaluationTaskKind
from agentgate.storage.repository import AgentGateRepository


class EvaluationTaskManagement:
    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def save(self, task: EvaluationTask) -> EvaluationTask:
        runs = [self.repository.get_run(run_id) for run_id in task.run_ids]
        if any(run is None for run in runs):
            raise LookupError("task references an unknown run")
        if task.kind == EvaluationTaskKind.STABILITY and any(run.manifest != runs[0].manifest for run in runs):
            raise ValueError("stability requires identical run manifests")
        if task.kind == EvaluationTaskKind.AB:
            left, right = (run.manifest for run in runs)
            a, b = left.target.ref, right.target.ref
            if (a.source_id, a.target_type, a.external_target_id) != (b.source_id, b.target_type, b.external_target_id):
                raise ValueError("A/B must evaluate the same target")
            if a.external_version_id == b.external_version_id:
                raise ValueError("A/B requires distinct target versions")
            for field in ("dataset", "selected_case_ids", "evaluator_specs", "primary_evaluator_ids",
                          "metric_plan", "gate_spec", "timeout_seconds", "max_retries", "max_parallel_cases"):
                if getattr(left, field) != getattr(right, field):
                    raise ValueError(f"A/B conditions differ: {field}")
        for report_id in task.static_report_ids:
            report = self.repository.get_skill_analysis_report(report_id)
            if report is None:
                raise LookupError("task references an unknown static report")
            if not any(report.target_ref == run.manifest.target.ref
                       and report.target_descriptor_sha256 == run.manifest.target.descriptor_sha256
                       for run in runs):
                raise ValueError("static report does not match the task target snapshot")
        return self.repository.save_evaluation_task(task)

    def get(self, task_id: str) -> EvaluationTask:
        task = self.repository.get_evaluation_task(task_id)
        if task is None:
            raise LookupError("unknown evaluation task")
        return task

    def list(self) -> list[EvaluationTask]:
        return self.repository.list_evaluation_tasks()
