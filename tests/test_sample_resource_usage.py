from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentgate.application.sample_resource_usage import summarize_sample
from agentgate.domain import Trace, TraceSpan
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.results import router
from agentgate.server.user_context import UserInfo, reset_user_info, set_user_info

START = datetime(2026, 1, 1, tzinfo=UTC)


def span(n=1, kind="llm", events=(), start=0, end=1, attrs=None):
    return TraceSpan(
        trace_id="a" * 32,
        span_id=f"{n:016x}",
        sequence=n,
        name=kind,
        operation_type=kind,
        events=events,
        started_at=START + timedelta(seconds=start),
        ended_at=START + timedelta(seconds=end),
        attributes=attrs or {},
    )


def trace(*spans):
    return Trace(trace_id="a" * 32, run_id="run", case_id="case", spans=spans)


def obs(identity="o1", prompt=6941, completion=93, source="source"):
    return {
        "event_type": "observation",
        "event_id": identity,
        "trace_id": source,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }


def test_realistic_usage_and_duplicate_observations_do_not_count_message_usage():
    t = trace(
        span(1, events=(obs(),)),
        span(2, events=(obs(), obs("o2", 7171, 146))),
        span(3, "turn", start=0, end=5.85, attrs={"agentgate.turn.id": "turn"}),
        span(4, "tool", events=({"event_type": "llm_request", "prompt_tokens": 999},)),
    )
    actual = summarize_sample("case", t, ["turn"])
    assert actual.total_tokens == 14351
    assert actual.token_status == "available"
    assert actual.duration_ms == 5850
    assert actual.duration_source == "turn_bounds"


@pytest.mark.parametrize("value", [None, -1, True, 1.5, "32", 2**53])
def test_invalid_counts_are_missing_not_zero(value):
    actual = summarize_sample("case", trace(span(events=(obs(prompt=value),))))
    assert actual.total_tokens == 93
    assert actual.token_status == "partial"


def test_zero_unknown_empty_and_non_observations():
    assert (
        summarize_sample("case", trace(span(events=(obs(prompt=0, completion=0),)))).total_tokens
        == 0
    )
    for evidence in [
        None,
        trace(),
        trace(span()),
        trace(span(events=({"event_type": "llm_request"},))),
        trace(span(events=(obs(prompt=None, completion=None),))),
    ]:
        actual = summarize_sample("case", evidence)
        assert actual.total_tokens is None
        assert actual.token_status == "unavailable"


def test_conflicting_duplicate_is_excluded_and_missing_ids_are_partial():
    actual = summarize_sample("case", trace(span(events=(obs(), obs(prompt=5), obs("o2", 1, 2)))))
    assert (actual.total_tokens, actual.token_status) == (3, "partial")
    actual = summarize_sample(
        "case", trace(span(events=(obs(identity=None, prompt=1, completion=2),) * 2))
    )
    assert (actual.total_tokens, actual.token_status) == (3, "partial")


def test_source_identity_and_missing_llm_observation():
    actual = summarize_sample("case", trace(span(events=(obs(), obs(source="other"))), span(2)))
    assert actual.total_tokens == 14068
    assert actual.token_status == "partial"


def test_output_only_and_missing_turns_do_not_claim_complete():
    t = trace(
        span(events=(obs(),)),
        span(2, "turn", attrs={"agentgate.turn.id": "t1", "inbank.evidence_mode": "output_only"}),
    )
    actual = summarize_sample("case", t, (x for x in ["t1", "t2"]))
    assert actual.token_status == "partial"
    assert actual.duration_ms is None


def test_duration_uses_case_else_turn_bounds_not_sum_of_children():
    t = trace(
        span(1, "turn", start=1, end=4),
        span(2, "turn", start=3, end=5),
        span(3, "tool", start=1, end=10),
    )
    assert summarize_sample("case", t).duration_ms == 4000
    actual = summarize_sample("case", trace(*t.spans, span(4, "case", start=0, end=6)))
    assert (actual.duration_ms, actual.duration_source) == (6000, "case_span")
    assert summarize_sample("case", trace(span(1, "case", end=0))).duration_ms == 0


def test_default_timestamps_are_not_observed_execution_time():
    s = TraceSpan(
        trace_id="a" * 32, span_id="b" * 16, sequence=1, name="case", operation_type="case"
    )
    assert summarize_sample("case", trace(s)).duration_ms is None
    s = s.model_copy(update={"operation_type": "turn"})
    assert summarize_sample("case", trace(s)).duration_ms is None


def test_resource_route_is_team_scoped_and_reads_traces_once(tmp_path, monkeypatch):
    deps = build_dependencies(tmp_path / "resources.db")
    run = deps.execute_demo_run("loan-agent-v2-fixed")
    stored = deps.repository.get_trace(run.id, "high-risk-approval")
    assert stored is not None
    # Native persisted trace read, not a JSON fixture returned by the API.
    listed = Mock(wraps=deps.repository.list_traces)
    monkeypatch.setattr(deps.repository, "list_traces", listed)
    app = FastAPI()
    app.state.dependencies = deps

    @app.middleware("http")
    async def identity(request: Request, call_next):
        token = set_user_info(
            UserInfo(
                user_team_id=request.headers.get("X-Team-Id", ""), user_id="test", user_name="test"
            )
        )
        try:
            return await call_next(request)
        finally:
            reset_user_info(token)

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        url = f"/api/runs/{run.id}/sample-resource-usage"
        assert client.get(url, headers={"X-Team-Id": "other-team"}).status_code == 404
        listed.assert_not_called()
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.json()["items"]) == len(run.manifest.execution_cases)
        listed.assert_called_once_with(run.id)
        assert "spans" not in response.text
        assert client.get("/api/runs/missing/sample-resource-usage").status_code == 404
        listed.side_effect = RuntimeError("storage unavailable")
        assert client.get(url).status_code == 500
        # Resource failure cannot break the existing score report.
        assert client.get(f"/api/runs/{run.id}").status_code == 200
