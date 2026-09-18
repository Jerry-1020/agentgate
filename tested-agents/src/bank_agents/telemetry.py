"""Per-request Collector instances use the customer's actual SDK file exporter."""
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

from trace_sdk.client import Collector
from trace_sdk.config import SDKConfig


PROJECT = "bank-tested-agents"
# SDK defaults can mistake an eleven-digit substring of a UUID for a phone.
# Use the SDK's public rule override. Only complete UUIDs are exempted;
# real phones still mask even when adjacent to a label such as "phone138...".
def _phone_or_uuid(match):
    return match.group("uuid") or f"{match.group('prefix')}****{match.group('suffix')}"


MASK_RULES = {
    "phone": (r"(?P<uuid>(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
              r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F]))|"
              r"(?<!\d)(?P<prefix>1[3-9]\d)\d{4}(?P<suffix>\d{4})(?!\d)", _phone_or_uuid),
}


class Evidence:
    def __init__(self, directory: Path, trace_id: str, session_id: str, mode: str, text: str):
        self.collector = Collector(SDKConfig(backend="file", project_id=PROJECT,
            agent_name=f"loan-{mode}-v1", output_file=str(directory),
            discard_on_overflow=False, flush_interval=1, mask_enabled=True,
            mask_rules=MASK_RULES))
        self.collector.start_trace(trace_id=trace_id, session_id=session_id,
            name=f"loan.{mode}", agent_name=f"loan-{mode}-v1", input={"txt": text},
            tags=["test-only", "test-policy-v1"])
        self.start = monotonic()
        self.path = directory / PROJECT / session_id / f"{trace_id}.jsonl"

    @contextmanager
    def span(self, name, kind="chain", inputs=None, **kwargs):
        meta = self.collector.start_span(name=name, span_type=kind, input=inputs, **kwargs)
        result = {"output": None, "meta": meta}
        start = monotonic()
        try:
            yield result
        except Exception as exc:
            self.collector.end_span(meta, duration_ms=int((monotonic()-start)*1000), status="error",
                                    error_info={"type": type(exc).__name__})
            raise
        else:
            self.collector.end_span(meta, output=result["output"], duration_ms=int((monotonic()-start)*1000),
                                    status="error" if result.get("failed") else "success")

    def finish(self, output=None, failed=False):
        counts = self.collector.stats_snapshot()
        self.collector.end_trace(output=output, duration_ms=int((monotonic()-self.start)*1000),
            span_count=counts["spans"], tool_count=counts["tool_calls"],
            prompt_tokens=counts["prompt_tokens"], completion_tokens=counts["completion_tokens"],
            status="error" if failed else "success")
        self.collector.shutdown()
        if not self.path.is_file():
            raise RuntimeError("SDK evidence export is missing")
