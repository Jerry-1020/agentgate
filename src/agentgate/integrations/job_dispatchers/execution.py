"""Process-local execution shared by Celery workers and BJS jobs."""

import logging
from contextlib import ExitStack, closing

from agentgate.application import RunManagement
from agentgate.application.credential_management import ApiKeyManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import RunStatus, transition_run
from agentgate.integrations.credentials.environment import load_api_key_encryptor
from agentgate.integrations.model_providers.environment import load_judge_model_from_environment
from agentgate.integrations.targets.agent_platform import (
    PlatformAdapter,
    PlatformClient,
    resolve_platform_trace,
)
from agentgate.integrations.targets.execution_factory import TargetExecutionFactory
from agentgate.storage.configuration import create_repository, load_database_config
from agentgate.storage.repository import AgentGateRepository

LOGGER = logging.getLogger(__name__)


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
    target = run.manifest.target
    if target.adapter_type == "local_bank" and (
        run.manifest.max_retries != 0 or run.manifest.max_parallel_cases != 1
    ):
        raise ValueError(f"{target.adapter_type} execution requires no retries and serial cases")
    if target.adapter_type in {"inbank_chatabc", "inbank_yunxia"} and run.manifest.max_retries != 0:
        raise ValueError(f"{target.adapter_type} execution requires no retries")

    with ExitStack() as resources:
        if target.adapter_type in {
            PlatformAdapter.adapter_type, "inbank_chatabc", "inbank_yunxia",
        }:
            token = ""
            label = "Platform" if target.adapter_type == PlatformAdapter.adapter_type else "In-bank"
            try:
                reference = target.credential_ref
                if reference is None:
                    raise ValueError("task credential reference is missing")
                credentials = ApiKeyManagement(repository, load_api_key_encryptor())
                token = credentials.resolve_api_key(reference)
                if target.adapter_type == PlatformAdapter.adapter_type:
                    adapter = PlatformAdapter(PlatformClient.from_environment(), token)
                    trace_resolver = resolve_platform_trace
                    resources.callback(setattr, adapter, "token", "")
                else:
                    adapter, trace_resolver = TargetExecutionFactory.create(
                        target, resources, trace_token=token,
                    )
            except (ValueError, LookupError, ConnectionError):
                LOGGER.error("%s credential or configuration unavailable: run_id=%s", label, run.id)
                failed = transition_run(
                    run,
                    RunStatus.FAILED,
                    error=f"{label} execution configuration or credential is unavailable",
                )
                repository.save_run(failed)
                return failed.status.value
            finally:
                token = ""
        else:
            adapter, trace_resolver = TargetExecutionFactory.create(target, resources)
        configured_judge = load_judge_model_from_environment()
        if configured_judge is not None:
            resources.callback(configured_judge.client.close)
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
        completed = RunManagement(repository, evaluator_management).execute_run(
            run.id,
            adapter,
            trace_resolver,
        )
        return completed.status.value
