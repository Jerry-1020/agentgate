"""Explicitly synthetic execution evidence; never invent model or tool calls."""

from datetime import UTC, datetime
from uuid import uuid4


def simulated_events(agent_id, kind, session, text, output, *, failed=False):
    project, trace = "agent-platform-mock", str(uuid4())
    now = datetime.now(UTC).isoformat()
    common = {
        "project_id": project,
        "trace_id": trace,
        "session_id": session,
        "started_at": now,
        "duration_ms": 0,
        "status": "error" if failed else "success",
        "agent_name": agent_id,
    }
    root_id = uuid4().hex
    steps = {
        "base": ["mock.reply"],
        "workflow": ["mock.workflow.start", "mock.workflow.echo", "mock.workflow.end"],
        "abcclaw": ["mock.skill.route", "mock.skill.echo"],
    }[kind]
    spans = [
        dict(
            common,
            event_type="span",
            event_id=uuid4().hex,
            span_id=root_id,
            parent_span_id=None,
            name="mock.agent." + kind,
            span_type="agent",
            input={"txt": text},
            output={"output": output},
            metadata={"simulated": True},
        )
    ]
    for name in steps:
        spans.append(
            dict(
                common,
                event_type="span",
                event_id=uuid4().hex,
                span_id=uuid4().hex,
                parent_span_id=root_id,
                name=name,
                started_at=datetime.now(UTC).isoformat(),
                span_type="chain",
                input={"txt": text},
                output={"output": output},
                metadata={"simulated": True},
            )
        )
    for span in spans:
        span["id"] = span["span_id"]
    return [
        *spans,
        dict(
            common,
            event_type="trace",
            event_id=uuid4().hex,
            name="mock." + kind,
            input={"txt": text},
            output={"output": output},
            tags=["simulated", "protocol-echo-only"],
            span_count=len(spans),
            tool_count=0,
            prompt_tokens=0,
            completion_tokens=0,
        ),
    ]


def report_simulated(agent_id, kind, session, text, output, *, failed=False):
    import json
    import os
    from pathlib import Path

    from bank_agents.reporting import report_events

    events = simulated_events(agent_id, kind, session, text, output, failed=failed)
    directory = Path(os.getenv("MOCK_TRACE_SPOOL_DIR", "runtime/platform-mock/traces"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (events[-1]["trace_id"] + ".jsonl")).write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    )
    return report_events(events, simulated=True)
