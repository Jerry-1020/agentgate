"""Process-local execution shared by Celery workers and BJS jobs."""

import logging
import os
from contextlib import ExitStack, closing
from socket import gethostname

from agentgate.application import RunManagement
from agentgate.application.credential_management import ApiKeyManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import EvaluationRun, RunStatus, transition_run
from agentgate.integrations.credentials.encryption import ApiKeyEncryptionError
from agentgate.integrations.credentials.environment import load_api_key_encryptor
from agentgate.integrations.model_providers.environment import load_judge_model_from_environment
from agentgate.integrations.targets.agent_platform import (
    PlatformAdapter,
    PlatformClient,
    resolve_platform_trace,
)
from agentgate.integrations.targets.execution_factory import TargetExecutionFactory
from agentgate.run.events import RunEventRecorder
from agentgate.storage.configuration import create_repository, load_database_config
from agentgate.storage.repository import AgentGateRepository

LOGGER = logging.getLogger(__name__)


def _inbank_init_context(run: EvaluationRun) -> str:
    """Log only identifiers; never credentials, full configuration, or exception text."""
    target = run.manifest.target
    version = target.invocation_config.get("agent_version")
    try:
        hostname = gethostname()
    except OSError:
        hostname = "unavailable"
    return (
        f"run_id={run.id!r} agent_id={target.ref.external_target_id!r} "
        f"agent_version={target.ref.external_version_id!r} "
        f"invocation_agent_version={version if isinstance(version, str) else None!r} "
        f"adapter_type={target.adapter_type!r} adapter_version={target.adapter_version!r} "
        f"credential_ref={target.credential_ref!r} hostname={hostname!r} pid={os.getpid()}"
    )


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
    recorder = RunEventRecorder(repository, run.id, run.user_team_id)
    recorder.finish_open("worker_wait")
    event = recorder.start("worker", "Worker 处理任务")
    try:
        status = _execute_initialized(repository, run_id, recorder)
    except Exception as exc:
        recorder.finish(event, status="failed", error=exc)
        recorder.finish_open("initialization", status="failed", error_code=type(exc).__name__,
                             message=str(exc))
        raise
    else:
        recorder.finish(event, status="failed" if status == "failed" else "cancelled" if status == "cancelled" else "completed",
                        message="Worker 执行结束")
        if status in {"failed", "cancelled"}:
            recorder.finish_open(None, status="failed" if status == "failed" else "cancelled",
                                 message="Worker 执行结束")
        return status


def _execute_initialized(repository: AgentGateRepository, run_id: str, recorder: RunEventRecorder) -> str:
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError(f"unknown EvaluationRun: {run_id}")
    if run.status is not RunStatus.PENDING:
        return run.status.value
    target = run.manifest.target
    if target.adapter_type == "local_bank" and (
        run.manifest.max_retries != 0
    ):
        raise ValueError(f"{target.adapter_type} execution requires no retries")
    if target.adapter_type in {"inbank_chatabc", "inbank_yunxia"} and run.manifest.max_retries != 0:
        raise ValueError(f"{target.adapter_type} execution requires no retries")

    init_event = recorder.start("initialization", "初始化执行环境与凭据")
    with ExitStack() as resources:
        if target.adapter_type in {
            PlatformAdapter.adapter_type, "inbank_chatabc", "inbank_yunxia",
        }:
            token = ""
            label = "Platform" if target.adapter_type == PlatformAdapter.adapter_type else "In-bank"
            diagnostic_context = _inbank_init_context(run) if label == "In-bank" else ""
            if diagnostic_context:
                LOGGER.info("inbank_execution_init_started %s", diagnostic_context)
            stage = "credential_reference"
            try:
                reference = target.credential_ref
                if reference is None:
                    raise ValueError("task credential reference is missing")
                stage = "encryption_key"
                credentials = ApiKeyManagement(repository, load_api_key_encryptor())
                stage = "credential_resolve"
                token = credentials.resolve_api_key(reference)
                stage = "adapter_configuration"
                if target.adapter_type == PlatformAdapter.adapter_type:
                    adapter = PlatformAdapter(PlatformClient.from_environment(), token)
                    trace_resolver = resolve_platform_trace
                    resources.callback(setattr, adapter, "token", "")
                    resources.callback(adapter.close)
                else:
                    adapter, trace_resolver = TargetExecutionFactory.create(
                        target, resources, trace_token=token, event_recorder=recorder,
                    )
            except (ValueError, LookupError, ConnectionError) as exc:
                recorder.finish(init_event, status="failed", error=exc)
                if diagnostic_context:
                    if stage == "credential_resolve":
                        reason = (
                            "credential_decryption_failed" if isinstance(exc, ApiKeyEncryptionError)
                            else "credential_not_found" if isinstance(exc, LookupError)
                            else "credential_resolution_failed"
                        )
                    else:
                        reason = {
                            "credential_reference": "credential_reference_missing",
                            "encryption_key": "encryption_key_unavailable",
                            "adapter_configuration": "adapter_configuration_unavailable",
                        }[stage]
                    LOGGER.error(
                        "In-bank credential or configuration unavailable: "
                        "event=inbank_execution_init_failed %s "
                        "stage=%s reason_code=%s error_type=%s",
                        diagnostic_context, stage, reason, type(exc).__name__,
                    )
                else:
                    LOGGER.error(
                        "%s credential or configuration unavailable: run_id=%s", label, run.id,
                    )
                failed = transition_run(
                    run,
                    RunStatus.FAILED,
                    error=f"{label} execution configuration or credential is unavailable",
                )
                repository.save_run(failed)
                return failed.status.value
            finally:
                token = ""
            if diagnostic_context:
                LOGGER.info("inbank_execution_init_ready %s", diagnostic_context)
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
        recorder.finish(init_event)
        completed = RunManagement(repository, evaluator_management).execute_run(
            run.id,
            adapter,
            trace_resolver,
        )
        return completed.status.value
