"""Target adapter for the in-process deterministic Loan Agent demo."""

from __future__ import annotations

import time
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from threading import Event
from typing import Any

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from agentgate.demo.loan import LoanAgent
from agentgate.demo.provider import AgentProvider
from agentgate.domain import TargetType, Trace, canonical_json
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.run.target_protocol import (
    CaseExecutionPending,
    CaseExecutionRequest,
    CaseExecutionResult,
    CaseExecutionStatus,
    TargetExecutionError,
)


class DemoLoanTargetAdapter:
    """Translate one evaluation Case into Loan Agent invocations."""

    adapter_type = "demo_loan"
    adapter_version = "1"

    def __init__(
        self,
        *,
        provider: AgentProvider | None = None,
        state_store: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.provider = provider
        self.state_store = state_store if state_store is not None else {}
        self._pool: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[CaseExecutionResult]] = {}
        self._cancelled: dict[str, Event] = {}
        self._run_id: str | None = None
        self._parallelism: int | None = None
        self._closed = False

    def start(self, request: CaseExecutionRequest) -> str:
        self._validate_request(request)
        handle = request.execution_id
        if self._closed or handle in self._futures:
            raise TargetExecutionError("invalid_request", "adapter closed or duplicate execution")
        if self._run_id is not None and (
            request.run_id != self._run_id or request.max_parallel_cases != self._parallelism
        ):
            raise TargetExecutionError(
                "invalid_request", "adapter belongs to one Run and concurrency limit"
            )
        if self._run_id is None:
            self._run_id, self._parallelism = request.run_id, request.max_parallel_cases
            if request.max_parallel_cases > 1:
                self._pool = ThreadPoolExecutor(max_workers=request.max_parallel_cases)
        self._cancelled[handle] = Event()

        def execute() -> CaseExecutionResult:
            self._check_cancelled(handle)
            try:
                result = self._execute(request)
                self._check_cancelled(handle)
                return result
            except TargetExecutionError:
                raise
            except Exception as exc:  # noqa: BLE001 - sanitize at the Target boundary.
                raise TargetExecutionError("rejected", type(exc).__name__) from None

        if self._pool is None:
            future: Future[CaseExecutionResult] = Future()
            self._futures[handle] = future
            try:
                future.set_result(execute())
            except Exception as exc:
                future.set_exception(exc)
                raise
        else:
            self._futures[handle] = self._pool.submit(execute)
        return handle

    def _execute(self, request: CaseExecutionRequest) -> CaseExecutionResult:
        capture = InMemoryTraceCapture()
        try:
            self._execute_case(request, capture)
            result = CaseExecutionResult(request.execution_id, request.traceparent.split("-")[1])
            trace = capture.resolve(request, result)
            return CaseExecutionResult(request.execution_id, result.trace_id, trace)
        finally:
            capture.shutdown()

    def _future(self, handle: str) -> Future[CaseExecutionResult]:
        try:
            return self._futures[handle]
        except KeyError:
            raise TargetExecutionError("invalid_request", "unknown execution") from None

    def _check_cancelled(self, handle: str) -> None:
        if self._cancelled[handle].is_set():
            raise TargetExecutionError("cancelled", "Case execution was cancelled")

    def get_status(self, handle: str) -> CaseExecutionStatus:
        future = self._future(handle)
        if self._cancelled[handle].is_set() or future.cancelled():
            return CaseExecutionStatus.CANCELLED
        if not future.done():
            return CaseExecutionStatus.RUNNING
        return CaseExecutionStatus.FAILED if future.exception() else CaseExecutionStatus.COMPLETED

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        if timeout_seconds <= 0:
            raise TargetExecutionError("invalid_request", "timeout must be positive")
        future = self._future(handle)
        self._check_cancelled(handle)
        try:
            return future.result(timeout=min(timeout_seconds, 0.1))
        except TimeoutError:
            raise CaseExecutionPending() from None
        except CancelledError:
            raise TargetExecutionError("cancelled", "Case execution was cancelled") from None

    def cancel(self, handle: str) -> None:
        future = self._future(handle)
        if not future.done():
            self._cancelled[handle].set()
            future.cancel()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in self._futures:
            self.cancel(handle)
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)

    def _execute_case(self, request: CaseExecutionRequest, capture: InMemoryTraceCapture) -> None:
        tracer = capture.get_tracer("agentgate.demo.loan_adapter", self.adapter_version)
        parent = TraceContextTextMapPropagator().extract({"traceparent": request.traceparent})
        root_attributes = {
            "agentgate.run.id": request.run_id,
            "agentgate.case.id": request.case.id,
            "agentgate.execution.id": request.execution_id,
            "agentgate.operation.type": "case",
        }
        agent = LoanAgent(
            version=request.target.ref.external_version_id,
            tracer=capture.get_tracer("agentgate.demo.loan", "1"),
            provider=self.provider,
            state_store=self.state_store,
        )
        deadline = time.monotonic() + request.timeout_seconds
        conversation_id: str | None = None
        final_output: dict[str, Any] = {}
        final_state: dict[str, Any] = {}

        with tracer.start_as_current_span(
            "case.execute", context=parent, attributes=root_attributes
        ) as case_span:
            for turn in request.case.turns:
                self._check_cancelled(request.execution_id)
                if time.monotonic() >= deadline:
                    raise TargetExecutionError("timeout", "Case deadline exceeded")
                turn_input = turn.input.to_dict()
                with tracer.start_as_current_span(
                    "turn.execute",
                    attributes={
                        "agentgate.operation.type": "turn",
                        "agentgate.turn.id": turn.id,
                    },
                ) as turn_span:
                    response = agent.invoke(turn_input, conversation_id)
                    conversation_id = response.conversation_id
                    final_output = response.output
                    final_state = response.state
                    turn_span.set_attribute("agentgate.turn.complete", True)
                    turn_span.set_attribute("agentgate.turn.input", canonical_json(turn_input))
                    turn_span.set_attribute("agentgate.turn.output", canonical_json(final_output))
                    turn_span.set_attribute("agentgate.turn.state", canonical_json(final_state))

            case_span.set_attribute("agentgate.trace.complete", True)
            case_span.set_attribute("agentgate.final.output", canonical_json(final_output))
            case_span.set_attribute("agentgate.final.state", canonical_json(final_state))

    def _validate_request(self, request: CaseExecutionRequest) -> None:
        if request.target.ref.target_type is not TargetType.AGENT:
            raise TargetExecutionError("invalid_request", "demo target must be an Agent")
        if request.target.adapter_type != self.adapter_type:
            raise TargetExecutionError("invalid_request", "adapter_type does not match")
        if request.target.adapter_version != self.adapter_version:
            raise TargetExecutionError("invalid_request", "adapter_version does not match")
        if request.case.initial_state:
            raise TargetExecutionError(
                "invalid_request", "demo target does not support initial state seeding"
            )


def resolve_demo_trace(request: CaseExecutionRequest, result: CaseExecutionResult) -> Trace:
    if result.inline_trace is None:
        raise TargetExecutionError("protocol_error", "Demo execution returned no trace")
    return result.inline_trace
