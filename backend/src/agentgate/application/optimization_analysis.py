"""Application workflow for analysis of completed evaluation Runs."""

from __future__ import annotations

from agentgate.domain import (
    EvaluationRun,
    OptimizationReport,
    ReviewDecision,
    RunStatus,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisStatus,
)
from agentgate.domain.base import require_non_blank, content_sha256
from agentgate.optimizer.pipeline import ANALYZER_VERSION
from agentgate.evaluator.judge.model_protocol import JudgeModelClient
from agentgate.optimizer import build_optimization_report
from agentgate.storage.repository import AgentGateRepository


class OptimizationRunNotFound(LookupError):
    """The requested EvaluationRun does not exist."""


class OptimizationRunNotCompleted(ValueError):
    """The requested EvaluationRun has not completed successfully."""


class OptimizationSkillAnalysisReportNotFound(LookupError):
    """The explicitly requested Skill-analysis report does not exist."""


class OptimizationSkillAnalysisMismatch(ValueError):
    """The selected Skill-analysis report belongs to another Target version."""


class OptimizationSkillAnalysisNotUsable(ValueError):
    """The selected Skill-analysis report has no usable analysis output."""


class OptimizationAnalysis:
    """Load persisted evidence and invoke the optimizer pipeline."""

    __slots__ = (
        "repository",
        "root_cause_model_client",
        "root_cause_model_id",
        "root_cause_timeout_seconds",
    )

    def __init__(
        self,
        repository: AgentGateRepository,
        *,
        root_cause_model_client: JudgeModelClient | None = None,
        root_cause_model_id: str | None = None,
        root_cause_timeout_seconds: float = 60,
    ) -> None:
        if (root_cause_model_client is None) != (root_cause_model_id is None):
            raise ValueError(
                "root-cause model client and model id must be configured together"
            )
        if root_cause_model_id is not None:
            root_cause_model_id = require_non_blank(
                root_cause_model_id,
                "root-cause model_id",
            )
        if (
            isinstance(root_cause_timeout_seconds, bool)
            or not isinstance(root_cause_timeout_seconds, (int, float))
            or root_cause_timeout_seconds <= 0
        ):
            raise ValueError("root_cause_timeout_seconds must be positive")
        self.repository = repository
        self.root_cause_model_client = root_cause_model_client
        self.root_cause_model_id = root_cause_model_id
        self.root_cause_timeout_seconds = float(root_cause_timeout_seconds)

    def analyze_run(
        self,
        run_id: str,
        skill_analysis_report_id: str | None = None,
    ) -> OptimizationReport:
        identifier = require_non_blank(run_id, "EvaluationRun id")
        run = self.repository.get_run(identifier)
        if run is None:
            raise OptimizationRunNotFound(
                f"unknown EvaluationRun: {identifier}"
            )
        if run.status != RunStatus.COMPLETED:
            raise OptimizationRunNotCompleted(
                f"EvaluationRun is not completed: {identifier}"
            )

        findings: tuple[SkillAnalysisFinding, ...] = ()
        if skill_analysis_report_id is not None:
            report = self._skill_analysis_report(skill_analysis_report_id)
            self._validate_skill_analysis_report(run, report)
            dismissed = {
                review.finding_id
                for review in self.repository.list_skill_analysis_reviews(report.id)
                if review.decision == ReviewDecision.DISMISSED
            }
            findings = tuple(
                finding
                for finding in sorted(report.findings, key=lambda item: item.id)
                if finding.id not in dismissed
            )
        results = self.repository.list_results(run.id)
        traces = self.repository.list_traces(run.id)
        evidence_key = content_sha256({
            "run": run.model_dump(mode="json"),
            "results": [r.model_dump(mode="json") for r in sorted(results, key=lambda r: r.id)],
            "traces": [t.model_dump(mode="json") for t in sorted(traces, key=lambda t: t.trace_id)],
            "findings": [f.model_dump(mode="json") for f in findings],
            "model_id": self.root_cause_model_id,
            "provider_id": self.root_cause_model_client.provider_id if self.root_cause_model_client else None,
            "analyzer_version": ANALYZER_VERSION,
        })
        cached = self.repository.get_optimization_report(evidence_key)
        if cached is not None:
            return cached
        report = build_optimization_report(
            run,
            results,
            traces,
            findings,
            model_client=self.root_cause_model_client,
            model_id=self.root_cause_model_id,
            root_cause_timeout_seconds=self.root_cause_timeout_seconds,
        )
        return self.repository.save_optimization_report(evidence_key, report)

    def _skill_analysis_report(
        self,
        report_id: str,
    ) -> SkillAnalysisReport:
        identifier = require_non_blank(report_id, "SkillAnalysisReport id")
        report = self.repository.get_skill_analysis_report(identifier)
        if report is None:
            raise OptimizationSkillAnalysisReportNotFound(
                f"unknown SkillAnalysisReport: {identifier}"
            )
        return report

    @staticmethod
    def _validate_skill_analysis_report(
        run: EvaluationRun,
        report: SkillAnalysisReport,
    ) -> None:
        if report.status == SkillAnalysisStatus.FAILED:
            raise OptimizationSkillAnalysisNotUsable(
                f"SkillAnalysisReport has no usable output: {report.id}"
            )
        if (
            report.target_ref != run.manifest.target.ref
            or report.target_descriptor_sha256
            != run.manifest.target.descriptor_sha256
        ):
            raise OptimizationSkillAnalysisMismatch(
                "SkillAnalysisReport does not match the Run Target version"
            )


__all__ = [
    "OptimizationAnalysis",
    "OptimizationRunNotCompleted",
    "OptimizationRunNotFound",
    "OptimizationSkillAnalysisMismatch",
    "OptimizationSkillAnalysisNotUsable",
    "OptimizationSkillAnalysisReportNotFound",
]
