"""Compose Target execution components with caller-owned resource cleanup."""

from contextlib import ExitStack

from agentgate.domain import TargetSnapshot
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets.demo_loan import DemoLoanTargetAdapter
from agentgate.integrations.targets.inbank.chatabc import (
    InbankChatABCTargetAdapter,
    load_chatabc_settings,
    resolve_chatabc_trace,
)
from agentgate.integrations.targets.inbank.yunxia import (
    InbankYunxiaTargetAdapter,
    load_yunxia_settings,
    resolve_yunxia_trace,
)
from agentgate.integrations.targets.local_bank import LocalBankAdapter, resolve_local_bank_trace
from agentgate.run.engine import TraceResolver
from agentgate.run.target_protocol import TargetAdapterProtocol


class TargetExecutionFactory:
    """Create one Run's adapter and Trace resolver without starting the Target."""

    @staticmethod
    def create(
        target: TargetSnapshot,
        resources: ExitStack,
    ) -> tuple[TargetAdapterProtocol, TraceResolver]:
        adapter: TargetAdapterProtocol
        resolver: TraceResolver
        if target.adapter_type == DemoLoanTargetAdapter.adapter_type:
            capture = InMemoryTraceCapture()
            resources.callback(capture.shutdown)
            adapter = DemoLoanTargetAdapter(capture)
            resolver = capture.resolve
        elif target.adapter_type == LocalBankAdapter.adapter_type:
            adapter = LocalBankAdapter()
            resolver = resolve_local_bank_trace
        elif target.adapter_type == InbankChatABCTargetAdapter.adapter_type:
            chatabc = InbankChatABCTargetAdapter(load_chatabc_settings())
            resources.callback(chatabc.close)
            adapter = chatabc
            resolver = resolve_chatabc_trace
        elif target.adapter_type == InbankYunxiaTargetAdapter.adapter_type:
            yunxia = InbankYunxiaTargetAdapter(load_yunxia_settings())
            resources.callback(yunxia.close)
            adapter = yunxia
            resolver = resolve_yunxia_trace
        else:
            raise ValueError("Worker does not support the Run Target adapter type")

        if adapter.adapter_version != target.adapter_version:
            raise ValueError("Target adapter_version does not match RunManifest")
        return adapter, resolver
