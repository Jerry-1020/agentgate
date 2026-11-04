"""Best-effort execution timing; diagnostics never replace the business outcome."""

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from agentgate.domain.base import utcnow
from agentgate.domain.run_event import RunEvent
from agentgate.storage.repository import AgentGateRepository

LOGGER = logging.getLogger(__name__)
# The HTTP request identity follows FastAPI's thread-pool context into submission.
request_id_context: ContextVar[str | None] = ContextVar("execution_request_id", default=None)
request_started_at_context: ContextVar[datetime | None] = ContextVar("execution_request_started_at", default=None)


def safe_diagnostic(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1***", text)
    text = re.sub(
        r'''(?i)(["']?(?:authorization|token|api[_-]?key|password|secret|credential)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''',
        r"\1***", text,
    )
    text = re.sub(r"https?://[^\s<>]+", "[URL omitted]", text)
    return " ".join(text.split())[:2000]


class RunEventRecorder:
    def __init__(self, repository: AgentGateRepository, run_id: str | None = None,
                 user_team_id: str = "", request_id: str | None = None) -> None:
        self.repository = repository
        self.run_id = run_id
        self.user_team_id = user_team_id
        self.request_id = request_id if request_id is not None else request_id_context.get()

    def start(self, stage: str, name: str, *, key: str | None = None, **fields) -> RunEvent:
        for field in ("agent_id", "pod_task_id", "pod_name"):
            if fields.get(field) is not None:
                fields[field] = safe_diagnostic(fields[field])
        if stage == "run" and request_started_at_context.get() is not None:
            fields["started_at"] = request_started_at_context.get()
        event = RunEvent(
            **({"id": uuid5(NAMESPACE_URL, f"agentgate:{self.run_id}:{key}").hex} if key else {}),
            request_id=self.request_id, run_id=self.run_id, user_team_id=self.user_team_id,
            stage=stage, name=safe_diagnostic(name), **fields,
        )
        self._write(event, insert=True)
        return event

    def finish(self, event: RunEvent, *, status="completed", error: Exception | None = None,
               error_code: str | None = None, message: str = "", ended_at: datetime | None = None,
               duration_ms: float | None = None, bjs_job_id: str | None = None,
               bjs_batch_number: str | None = None, pod_name: str | None = None) -> None:
        end = max(ended_at or utcnow(), event.started_at)
        self._write(event.model_copy(update={
            "status": status, "ended_at": end,
            "duration_ms": duration_ms if duration_ms is not None else (end - event.started_at).total_seconds() * 1000,
            "error_code": safe_diagnostic(error_code or getattr(error, "code", type(error).__name__)) if error_code or error else None,
            "message": safe_diagnostic(message or error or ""),
            "bjs_job_id": safe_diagnostic(bjs_job_id)[:128] if bjs_job_id else event.bjs_job_id,
            "bjs_batch_number": safe_diagnostic(bjs_batch_number)[:128] if bjs_batch_number else event.bjs_batch_number,
            "pod_name": safe_diagnostic(pod_name) if pod_name else event.pod_name,
        }))

    @contextmanager
    def operation(self, stage: str, name: str, **fields):
        event = self.start(stage, name, **fields)
        started = monotonic()
        try:
            yield event
        except Exception as exc:
            self.finish(event, status="cancelled" if getattr(exc, "code", None) == "cancelled" else "failed",
                        error=exc, duration_ms=(monotonic() - started) * 1000)
            raise
        else:
            self.finish(event, duration_ms=(monotonic() - started) * 1000)

    def finish_open(self, stage: str | None, *, status="completed", error_code=None, message="", ended_at=None) -> None:
        try:
            self.repository.finish_open_run_events(
                self.run_id, stage, status=status, ended_at=ended_at or utcnow(),
                error_code=error_code, message=safe_diagnostic(message),
            )
        except Exception:  # noqa: BLE001 -- Diagnostics must not replace execution outcomes.
            LOGGER.warning("Execution log update failed: run_id=%s stage=%s", self.run_id, stage)

    def record_trace(self, trace) -> None:
        try:
            events = []
            for span in trace.spans:
                if span.attributes.get("platform.simulated") is True:
                    continue
                failed = span.status.value == "error"
                turn_id = span.attributes.get("agentgate.turn.id")
                events.append(RunEvent(
                    id=uuid5(NAMESPACE_URL, f"agentgate:{self.run_id}:span:{trace.trace_id}:{span.span_id}").hex,
                    run_id=self.run_id, user_team_id=self.user_team_id, request_id=self.request_id,
                    stage="turn" if span.operation_type == "turn" else "node", name=safe_diagnostic(span.name),
                    case_id=trace.case_id, turn_id=turn_id if isinstance(turn_id, str) else None,
                    started_at=span.started_at, ended_at=span.ended_at,
                    duration_ms=(span.ended_at - span.started_at).total_seconds() * 1000,
                    status="failed" if failed else "completed", error_code="upstream_node_error" if failed else None,
                    message="上游执行轨迹报告异常" if failed else "来自上游 Trace；执行结束后采集",
                ))
            self.repository.save_run_events(events)
        except Exception:  # noqa: BLE001 -- Diagnostics must not replace execution outcomes.
            LOGGER.warning("Execution trace log persistence failed: run_id=%s", self.run_id)

    def _write(self, event: RunEvent, *, insert=False) -> None:
        try:
            if insert:
                self.repository.start_run_event(event)
            else:
                self.repository.finish_run_event(event)
        except Exception:  # noqa: BLE001 -- Diagnostics must not replace execution outcomes.
            LOGGER.warning("Execution log persistence failed: run_id=%s stage=%s", self.run_id, event.stage)
