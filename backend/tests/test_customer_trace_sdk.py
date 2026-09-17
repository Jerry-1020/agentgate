from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from agentgate.application import RunManagement, ResultReader
from agentgate.application.dataset_management import DatasetManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import Case, CaseTurn, TargetDescriptor, TargetRef, TargetSnapshot
from agentgate.integrations.observability.trace_sdk import normalize_sdk_exports
from agentgate.integrations.targets.trace_sdk_replay import TraceSDKReplayAdapter, resolve_sdk_replay
from agentgate.run.target_protocol import CaseExecutionRequest, TargetExecutionError
from agentgate.storage.sqlite import SQLiteRepository


def events():
    common = dict(project_id="project", trace_id="external-trace", started_at="2026-08-30T03:12:54Z",
                  duration_ms=10, status="success")
    return [dict(common, event_type="span", event_id="span-event", span_id="external-span",
                 parent_span_id=None, span_type="tool", name="tool.check", tool_name="check",
                 input={"city": "深圳"}, output={"ok": True}),
            dict(common, event_type="trace", event_id="trace-event", output={"text": "done"})]


def encode(items):
    return "\n".join(json.dumps(e) for e in items).encode()


def request(raw=None, source="external-trace", project="project", case=None):
    raw = raw if raw is not None else encode(events())
    case = case or Case(id="case", name="Case", turns=(CaseTurn(id="turn", input={"txt": "hello"}),))
    descriptor = TargetDescriptor(ref=TargetRef(source_id="trace-sdk", target_type="agent",
        external_target_id="archive", external_version_id="archive-sha256-" + hashlib.sha256(raw).hexdigest()),
        display_name="Historical SDK export")
    snapshot = TargetSnapshot(ref=descriptor.ref, display_name=descriptor.display_name,
        descriptor_sha256=descriptor.content_sha256, adapter_type="trace_sdk_replay", adapter_version="1",
        invocation_config={"project_id": project, "exports": {case.id: {
            case.turns[0].id: {"trace_id": source, "sha256": hashlib.sha256(raw).hexdigest()}}}})
    return CaseExecutionRequest("execution", "run", case, snapshot, 30, "00-" + "1" * 32 + "-" + "2" * 16 + "-01"), descriptor


def test_sdk_mapping_preserves_real_tools_but_does_not_invent_routing_or_state():
    req, _ = request()
    trace = normalize_sdk_exports(req, {"turn": ("external-trace", encode(events()))}, project_id="project")
    assert len(trace.spans) == 2
    assert trace.for_turn("turn").spans[1].name == "check"
    assert trace.spans[1].attributes["arguments"]["city"] == "深圳"
    assert trace.spans[1].attributes["trace_sdk.span_id"] == "external-span"
    assert trace.final_state == {}
    assert not any(s.operation_type == "routing" for s in trace.spans)


@pytest.mark.parametrize("mutation", ["project", "trace", "parent", "cycle", "duplicate", "missing_root",
                                    "failed", "duration", "timezone", "tool_name", "observation"])
def test_invalid_evidence_is_rejected(mutation):
    rows = events()
    if mutation == "project": rows[0]["project_id"] = "other"
    if mutation == "trace": rows[0]["trace_id"] = "other"
    if mutation == "parent": rows[0]["parent_span_id"] = "missing"
    if mutation == "cycle": rows[0]["parent_span_id"] = "external-span"
    if mutation == "duplicate": rows.append(dict(rows[0], name="different"))
    if mutation == "missing_root": rows.pop()
    if mutation == "failed": rows[-1]["status"] = "error"
    if mutation == "duration": rows[0]["duration_ms"] = -1
    if mutation == "timezone": rows[0]["started_at"] = "2026-08-30T03:12:54"
    if mutation == "tool_name": rows[0].pop("tool_name")
    if mutation == "observation": rows.append(dict(rows[0], event_type="observation", span_id="missing"))
    req, _ = request()
    with pytest.raises(ValueError):
        normalize_sdk_exports(req, {"turn": ("external-trace", encode(rows))}, project_id="project")


def test_exact_event_duplicates_are_idempotent_and_export_hash_is_enforced():
    raw = encode(events() + [events()[0]])
    req, _ = request(raw)
    adapter = TraceSDKReplayAdapter({"case": {"turn": ("external-trace", raw)}})
    handle = adapter.start(req)
    assert len(adapter.wait(handle, 1).inline_trace.spans) == 2
    with pytest.raises(TargetExecutionError): adapter.start(req)
    changed = TraceSDKReplayAdapter({"case": {"turn": ("external-trace", raw + b"\n")}})
    with pytest.raises(TargetExecutionError): changed.start(req)


def execute_archive(tmp_path, raw, source, project, tool):
    case = Case(id="archive-case", name="SDK evidence replay; not a live loan acceptance test",
                turns=(CaseTurn(id="archive-turn", input={"txt": "Archive contract test"}, expectations=(
                    {"kind": "tool_call", "mode": "required", "tool": tool},
                    {"kind": "tool_call", "mode": "required", "tool": "deliberately_absent_tool"},
                )),))
    req, descriptor = request(raw, source, project, case)
    repo = SQLiteRepository(tmp_path / "sdk-replay.db")
    repo.save_target_descriptor(descriptor)
    datasets = DatasetManagement(repo)
    dataset = datasets.create_dataset("SDK contract verification")
    datasets.create_draft(dataset.id)
    datasets.save_case(dataset.id, case)
    datasets.publish_draft(dataset.id)
    runs = RunManagement(repo, build_default_evaluator_management(repo))
    run = runs.create_run(req.target, dataset_id=dataset.id, evaluator_ids=["required-tool"])
    completed = runs.execute_run(run.id, TraceSDKReplayAdapter({case.id: {
        case.turns[0].id: (source, raw)}}), resolve_sdk_replay)
    report = ResultReader(repo).get_report(completed.id)
    assert completed.status.value == "completed"
    checks = report.results[0].checks
    assert [c.outcome.value for c in checks] == ["pass", "fail"]
    assert checks[0].span_ids
    reopened = SQLiteRepository(tmp_path / "sdk-replay.db")
    assert ResultReader(reopened).get_report(completed.id).results == report.results


def test_replay_through_real_engine_evaluators_and_sqlite(tmp_path):
    execute_archive(tmp_path, encode(events()), "external-trace", "project", "check")


@pytest.mark.skipif(not os.environ.get("AGENTGATE_SDK_SAMPLE"), reason="private customer archive not in repository")
def test_supplied_customer_archive_through_real_engine(tmp_path):
    raw = Path(os.environ["AGENTGATE_SDK_SAMPLE"]).read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    root = next(e for e in rows if e["event_type"] == "trace")
    assert len([e for e in rows if e["event_type"] == "span"]) == 20
    execute_archive(tmp_path, raw, root["trace_id"], root["project_id"], "city_research_skill")
