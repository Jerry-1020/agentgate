"""Create exact-target platform tasks using existing persistence and dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from agentgate.application.credential_management import ApiKeyManagement
from agentgate.application.evaluator_management import EvaluatorManagement
from agentgate.application.run_management import RunManagement
from agentgate.domain import EvaluationRun, TargetSnapshot, utcnow
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.integrations.targets.agent_platform import PlatformClient, resolve_platform_target
from agentgate.storage.repository import AgentGateRepository


def submit_platform_evaluation(
    *,
    repository: AgentGateRepository,
    evaluators: EvaluatorManagement,
    credentials: ApiKeyManagement | None,
    dispatcher: JobDispatcher,
    team_id: str | None,
    agent_id: str,
    type_group: Literal["base/workflow", "abcclaw"],
    agent_version: str,
    branch_id: str | None,
    dataset_id: str,
    dataset_version: int,
    case_ids: tuple[str, ...] | None,
    evaluator_ids: tuple[str, ...],
    max_parallel_cases: int,
    timeout_seconds: int,
    max_retries: int,
    repetitions: int,
    scheduled_for: datetime | None,
    token: str,
    user_team_id: str,
    user_id: str,
    user_name: str,
) -> EvaluationTask:
    if credentials is None:
        raise ConnectionError("platform credential encryption is not configured")
    if scheduled_for is not None and (scheduled_for <= utcnow() or repetitions != 1):
        raise ValueError("invalid reservation")
    if not 1 <= repetitions <= 20:
        raise ValueError("invalid repetitions")
    if repository.get_dataset(dataset_id, user_team_id=user_team_id) is None:
        raise LookupError("dataset unavailable to caller")
    client = PlatformClient.from_environment()
    descriptor = resolve_platform_target(
        client,
        token,
        team_id=team_id,
        agent_id=agent_id,
        type_group=type_group,
        agent_version=agent_version,
        branch_id=branch_id,
    )
    repository.save_target_descriptor(descriptor)
    task_id = str(uuid4())
    metadata = credentials.create_api_key(
        name="Platform task " + task_id,
        provider_id="agent-platform-mock",
        scope="private",
        plaintext=token,
    )
    try:
        snapshot = TargetSnapshot(
            ref=descriptor.ref,
            display_name=descriptor.display_name,
            descriptor_sha256=descriptor.content_sha256,
            adapter_type="agent_platform_mock",
            adapter_version="1",
            invocation_config=descriptor.metadata,
            credential_ref=metadata.id,
        )
        management = RunManagement(repository, evaluators)
        run = management.create_run(
            snapshot,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            case_ids=case_ids,
            evaluator_ids=evaluator_ids,
            max_parallel_cases=max_parallel_cases,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            scheduled_for=scheduled_for,
            persist=False,
        )
        for case in run.manifest.execution_cases:
            if case.initial_state:
                raise ValueError("platform mock has no mutable initial business state")
            for turn in case.turns:
                if (
                    set(turn.input) != {"txt"}
                    or not isinstance(turn.input["txt"], str)
                    or not turn.input["txt"].strip()
                ):
                    raise ValueError("platform case input requires nonblank txt only")
        runs = [
            EvaluationRun(
                id=task_id if index == 0 else str(uuid4()),
                manifest=run.manifest,
                status=run.status,
                scheduled_for=run.scheduled_for,
                user_team_id=user_team_id,
                user_id=user_id,
                user_name=user_name,
            )
            for index in range(repetitions)
        ]
        task = EvaluationTask(
            id=task_id,
            kind="single" if repetitions == 1 else "stability",
            run_ids=tuple(r.id for r in runs),
            credential_id=metadata.id,
        )
    except Exception:
        credentials.delete_api_key(metadata.id)
        raise
    try:
        repository.save_task_runs(task, runs)
    except Exception:  # noqa: BLE001 -- Persistence outcome must never become a 4xx rejection.
        # A commit error may be ambiguous: retain the encrypted credential for reconciliation.
        raise RuntimeError("task persistence outcome is uncertain") from None
    for item in runs:
        if item.status == "scheduled":
            continue
        try:
            management.dispatch_run(item.id, dispatcher)
        except RuntimeError:
            # Existing RunManagement records dispatch failure. The created task still exists.
            continue
        except Exception:  # noqa: BLE001 -- Dispatch after commit has an uncertain outcome.
            raise RuntimeError("task exists but dispatch outcome is uncertain") from None
    return task
