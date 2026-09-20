"""Process-local execution shared by Celery workers and BJS jobs."""

from contextlib import closing

from agentgate.application import RunManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import RunStatus
from agentgate.integrations.model_providers.environment import load_judge_model_from_environment
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.integrations.targets.local_bank import LocalBankAdapter, resolve_local_bank_trace
from agentgate.storage.configuration import create_repository, load_database_config
from agentgate.storage.repository import AgentGateRepository


def execute_persisted_run(run_id: str) -> str:
    """Execute one pending Run; duplicate and cancelled deliveries are no-ops."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must not be blank")
    with closing(create_repository(load_database_config())) as repository:
        return _execute(repository, run_id)


def _execute(repository: AgentGateRepository, run_id: str) -> str:
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError(f"unknown EvaluationRun: {run_id}")
    if run.status is not RunStatus.PENDING:
        return run.status.value
    if run.manifest.target.adapter_type not in {
        DemoLoanTargetAdapter.adapter_type,
        LocalBankAdapter.adapter_type,
    }:
        raise ValueError("Worker does not support the Run Target adapter type")

    configured_judge = load_judge_model_from_environment()
    capture: InMemoryTraceCapture | None = None
    try:
        evaluator_management = (
            build_default_evaluator_management(repository)
            if configured_judge is None
            else build_default_evaluator_management(
                repository,
                judge_client=configured_judge.client,
                judge_model_id=configured_judge.model_id,
                judge_credential_ref=configured_judge.credential_ref,
            )
        )
        if run.manifest.target.adapter_type == LocalBankAdapter.adapter_type:
            if (
                run.manifest.max_retries != 0
                or run.manifest.max_parallel_cases != 1
                or run.case_max_parallel not in (None, 1)
            ):
                raise ValueError("local bank execution requires no retries and serial cases")
            completed = RunManagement(repository, evaluator_management).execute_run(
                run.id,
                LocalBankAdapter(),
                resolve_local_bank_trace,
            )
            return completed.status.value
        capture = InMemoryTraceCapture()
        completed = RunManagement(repository, evaluator_management).execute_run(
            run.id,
            DemoLoanTargetAdapter(capture),
            capture.resolve,
        )
    finally:
        try:
            if capture is not None:
                capture.shutdown()
        finally:
            if configured_judge is not None:
                configured_judge.client.close()
    return completed.status.value
