"""Read-only Target-version discovery for the AgentGate demo interface."""

from fastapi import APIRouter, Depends
from typing import Annotated

from agentgate.demo.targets import LOAN_AGENT_DESCRIPTORS
from agentgate.integrations.targets.local_bank import LocalBankClient, local_bank_target
from agentgate.run.target_protocol import TargetExecutionError
from agentgate.server.dependencies import ServerDependencies, get_dependencies

from agentgate.demo.loan import LoanAgent


router = APIRouter(prefix="/api", tags=["catalogs"])

_TARGET_VERSION_LABELS = {
    "loan-agent-v1-risky": "Risky version",
    "loan-agent-v2-fixed": "Fixed version",
}


@router.get("/versions")
def target_versions() -> list[dict[str, str]]:
    return [
        {"id": version, "label": _TARGET_VERSION_LABELS[version]}
        for version in LoanAgent.versions
    ]


@router.get("/local-targets")
def local_targets(dependencies: Annotated[ServerDependencies, Depends(get_dependencies)]):
    """Local execution targets; offline runtimes remain visible but unselectable."""
    records = [{"descriptor": d, "adapter_type": "demo_loan", "mode": None}
               for d in LOAN_AGENT_DESCRIPTORS]
    unavailable = []
    for mode, name in (("base", "基础编排"), ("workflow", "工作流"), ("cloudshrimp", "云虾")):
        try:
            descriptor, snapshot = local_bank_target(LocalBankClient(), mode)
            dependencies.targets.register_descriptor(descriptor)
            records.append({"descriptor": descriptor, "adapter_type": snapshot.adapter_type, "mode": mode})
        except (TargetExecutionError, ValueError):
            unavailable.append({"agent_id": "loan-" + mode, "name": "贷款智能体 · " + name, "mode": mode})
    return {"targets": records, "unavailable": unavailable}
