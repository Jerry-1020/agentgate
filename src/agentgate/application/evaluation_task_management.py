"""Persist user-facing associations without executing or modifying referenced runs."""

from datetime import timedelta, timezone

from agentgate.application.result_reader import ResultReader
from agentgate.application.run_management import RunManagement
from agentgate.domain import EvaluationReport
from agentgate.domain.base import require_non_blank
from agentgate.domain.evaluation_task import EvaluationTask, EvaluationTaskKind
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.result.historical_comparison import (
    HistoricalComparison,
    compare_historical_reports,
)
from agentgate.server.user_context import get_user_info
from agentgate.storage.repository import AgentGateRepository


def _team_id() -> str:
    info = get_user_info()
    return info.user_team_id if info else ""


class EvaluationTaskManagement:
    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def create_history_comparison(
        self,
        comparison_id: str,
        *,
        baseline_task_id: str,
        baseline_run_id: str,
        candidate_task_id: str,
        candidate_run_id: str,
        name: str | None = None,
    ) -> EvaluationTask:
        """Compare two selected single-task executions and persist only their references."""
        for field, value in (
            ("comparison_id", comparison_id),
            ("baseline_task_id", baseline_task_id),
            ("baseline_run_id", baseline_run_id),
            ("candidate_task_id", candidate_task_id),
            ("candidate_run_id", candidate_run_id),
        ):
            require_non_blank(value, field)
        if baseline_task_id == candidate_task_id or baseline_run_id == candidate_run_id:
            raise ValueError("historical comparison requires two distinct single tasks and runs")
        if comparison_id in {baseline_task_id, candidate_task_id}:
            raise ValueError("comparison identity must differ from its source tasks")

        team_id = _team_id()
        reader = ResultReader(self.repository)
        baseline, baseline_report = self._single_comparison_source(
            baseline_task_id,
            baseline_run_id,
            team_id,
            reader,
        )
        candidate, candidate_report = self._single_comparison_source(
            candidate_task_id,
            candidate_run_id,
            team_id,
            reader,
        )
        compare_historical_reports(baseline_report, candidate_report)

        if name is None:
            a = baseline.name or baseline_report.run.manifest.target.display_name
            b = candidate.name or candidate_report.run.manifest.target.display_name
            name = f"A/B历史结果对比：{a[:48]} / {b[:48]}"
        cleaned_name = name.strip()
        if cleaned_name:
            for task in self._accessible_tasks(team_id):
                if (
                    task.id != comparison_id
                    and (task.name or "").strip() == cleaned_name
                ):
                    raise ValueError(f"任务名称已存在：{cleaned_name}，请修改名称后重试。")
        task = EvaluationTask(
            id=comparison_id,
            kind=EvaluationTaskKind.AB,
            name=cleaned_name,
            run_ids=(baseline_run_id, candidate_run_id),
        )
        # Storage rechecks ownership and access atomically, and returns an identical prior save.
        return self.repository.save_historical_comparison(
            task,
            baseline_task_id=baseline_task_id,
            candidate_task_id=candidate_task_id,
            user_team_id=team_id,
        )

    def compare_task_results(self, task_id: str) -> HistoricalComparison:
        """Read the exact A/B run pair without following source-task reruns or writing names."""
        require_non_blank(task_id, "task_id")
        task = self._read_accessible_task(task_id, _team_id())
        if task.kind != EvaluationTaskKind.AB:
            raise ValueError("result comparison requires an A/B task")
        reader = ResultReader(self.repository)
        return compare_historical_reports(
            reader.get_report(task.run_ids[0]),
            reader.get_report(task.run_ids[1]),
        )

    def _read_accessible_task(self, task_id: str, team_id: str) -> EvaluationTask:
        task = self.repository.get_evaluation_task(task_id)
        if task is None or any(
            self.repository.get_run(run_id, user_team_id=team_id) is None for run_id in task.run_ids
        ):
            raise LookupError("unknown evaluation task")
        return task

    def _single_comparison_source(
        self,
        task_id: str,
        run_id: str,
        team_id: str,
        reader: ResultReader,
    ) -> tuple[EvaluationTask, EvaluationReport]:
        task = self._read_accessible_task(task_id, team_id)
        if task.kind != EvaluationTaskKind.SINGLE:
            raise ValueError("historical comparison sources must be single tasks")
        if run_id not in task.run_ids + task.previous_run_ids:
            raise ValueError("selected execution does not belong to its source task")
        return task, reader.get_report(run_id)

    def save(self, task: EvaluationTask) -> EvaluationTask:
        runs = [self.repository.get_run(run_id, user_team_id=_team_id()) for run_id in task.run_ids]
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
        if task is None or any(self.repository.get_run(run_id, user_team_id=_team_id()) is None for run_id in task.run_ids):
            raise LookupError("unknown evaluation task")
        return self._with_name(task)

    def rerun(
        self, task_id: str, source_run_id: str, runs: RunManagement, dispatcher: JobDispatcher,
    ) -> EvaluationTask:
        task = self.get(task_id)
        if task.kind != EvaluationTaskKind.SINGLE:
            raise ValueError("only single tasks can be rerun")
        if task.run_ids != (source_run_id,):
            raise ValueError("task execution changed; refresh before rerunning")
        new_run = runs.create_rerun(source_run_id, persist=False)
        updated = self.repository.save_task_rerun(
            task.id, source_run_id, new_run, user_team_id=_team_id(),
        )
        runs.dispatch_run(new_run.id, dispatcher)
        return updated

    def _with_name(self, task: EvaluationTask) -> EvaluationTask:
        if task.name is not None:
            return task
        run = self.repository.get_run(task.run_ids[0], user_team_id=_team_id())
        agent = run.manifest.target.display_name
        if agent == "Loan Agent":
            agent = "贷款智能体"
        date = task.created_at.astimezone(timezone(timedelta(hours=8)))
        suffix = f"{date.month}{date.day:02d}"
        named = EvaluationTask.model_validate({
            **task.model_dump(), "name": agent[:128 - len(suffix)] + suffix,
        })
        return self.repository.save_evaluation_task(named)

    def _accessible_tasks(self, team_id: str) -> list[EvaluationTask]:
        return [
            task
            for task in self.repository.list_evaluation_tasks()
            if all(
                self.repository.get_run(run_id, user_team_id=team_id) is not None
                for run_id in task.run_ids
            )
        ]

    def list(self) -> list[EvaluationTask]:
        return [self._with_name(task) for task in self._accessible_tasks(_team_id())]
