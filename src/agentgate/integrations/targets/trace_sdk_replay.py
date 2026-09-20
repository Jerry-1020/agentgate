"""Replay explicitly pinned SDK evidence without invoking a customer Agent."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from agentgate.integrations.observability.trace_sdk import normalize_sdk_exports
from agentgate.run.target_protocol import (
    CaseExecutionRequest, CaseExecutionResult, CaseExecutionStatus, TargetExecutionError,
)


class TraceSDKReplayAdapter:
    adapter_type = "trace_sdk_replay"
    adapter_version = "1"

    def __init__(self, exports: Mapping[str, Mapping[str, tuple[str, bytes]]]) -> None:
        self.exports = {case: dict(turns) for case, turns in exports.items()}
        self.results: dict[str, CaseExecutionResult] = {}
        self.statuses: dict[str, CaseExecutionStatus] = {}

    def start(self, request: CaseExecutionRequest) -> str:
        handle = request.execution_id
        if handle in self.statuses:
            raise TargetExecutionError("invalid_request", "duplicate execution_id")
        if (request.target.adapter_type, request.target.adapter_version) != (self.adapter_type, self.adapter_version):
            raise TargetExecutionError("invalid_request", "replay adapter snapshot mismatch")
        self.statuses[handle] = CaseExecutionStatus.RUNNING
        try:
            config = request.target.invocation_config
            exports = self.exports[request.case.id]
            pins = config["exports"][request.case.id]
            if set(pins) != set(exports):
                raise ValueError("Trace SDK export pins do not match turns")
            for turn_id, (source_id, raw) in exports.items():
                pin = pins[turn_id]
                if pin["trace_id"] != source_id or pin["sha256"] != hashlib.sha256(raw).hexdigest():
                    raise ValueError("Trace SDK export differs from frozen snapshot")
            trace = normalize_sdk_exports(request, exports, project_id=config["project_id"])
            self.results[handle] = CaseExecutionResult(handle, trace.trace_id, trace)
            self.statuses[handle] = CaseExecutionStatus.COMPLETED
        except (KeyError, TypeError, ValueError) as exc:
            self.statuses[handle] = CaseExecutionStatus.FAILED
            # Never include payloads or file paths in persisted execution errors.
            raise TargetExecutionError("protocol_error", "invalid or mismatched SDK replay evidence") from exc
        return handle

    def get_status(self, handle: str) -> CaseExecutionStatus:
        if handle not in self.statuses:
            raise TargetExecutionError("invalid_request", "unknown execution handle")
        return self.statuses[handle]

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        if timeout_seconds <= 0:
            raise TargetExecutionError("invalid_request", "timeout must be positive")
        if self.get_status(handle) != CaseExecutionStatus.COMPLETED:
            raise TargetExecutionError("protocol_error", "replay has not completed")
        return self.results[handle]

    def cancel(self, handle: str) -> None:
        if self.get_status(handle) in {CaseExecutionStatus.PENDING, CaseExecutionStatus.RUNNING}:
            self.statuses[handle] = CaseExecutionStatus.CANCELLED


def resolve_sdk_replay(request: CaseExecutionRequest, result: CaseExecutionResult):
    trace = result.inline_trace
    if trace is None or trace.run_id != request.run_id or trace.case_id != request.case.id:
        raise TargetExecutionError("protocol_error", "missing or mismatched inline Trace")
    return trace
