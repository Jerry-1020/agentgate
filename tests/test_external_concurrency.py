"""Bounded external execution through injected providers and HTTP boundaries."""

from dataclasses import replace
from threading import Barrier, Event, Lock, Thread

import pytest
from test_demo_loan_target import request as demo_request
from test_local_bank_adapter import Client

from agentgate.demo.provider import DeterministicProvider
from agentgate.domain import Case, CaseTurn
from agentgate.integrations.targets.demo_loan import DemoLoanTargetAdapter, resolve_demo_trace
from agentgate.integrations.targets.local_bank import LocalBankAdapter, local_bank_target
from agentgate.run.target_protocol import (
    CaseExecutionPending,
    CaseExecutionStatus,
    TargetExecutionError,
)


def completed(adapter, handle):
    for _ in range(100):
        try:
            return adapter.wait(handle, 5)
        except CaseExecutionPending:
            pass
    raise AssertionError("Case did not finish")


@pytest.mark.parametrize("limit", [1, 2, 3, 30])
def test_demo_bounded_overlap_keeps_turn_order_and_separate_trace_captures(limit):
    gate, lock = Barrier(limit), Lock()
    active = peak = 0
    observed = {}

    class Provider(DeterministicProvider):
        def choose_action(self, values, version):
            nonlocal active, peak
            with lock:
                observed.setdefault(values["application_id"], []).append(values["turn"])
                active += 1
                peak = max(peak, active)
            try:
                gate.wait(5)
                return super().choose_action(values, version)
            finally:
                with lock:
                    active -= 1

    adapter = DemoLoanTargetAdapter(provider=Provider())
    requests = []
    try:
        for index in range(limit * 2):
            identity = str(index)
            case = Case(
                id=identity,
                name=identity,
                turns=[
                    CaseTurn(
                        id=f"{identity}-{turn}",
                        input={
                            "application_id": identity,
                            "skill": "loan_approval",
                            "risk": "low",
                            "amount": 100,
                            "turn": turn,
                        },
                    )
                    for turn in (0, 1)
                ],
            )
            requests.append(
                replace(
                    demo_request(case),
                    execution_id=identity,
                    traceparent=f"00-{index + 1:032x}-{'b' * 16}-01",
                    max_parallel_cases=limit,
                )
            )
        handles = [adapter.start(req) for req in requests]
        for req, handle in zip(requests, handles, strict=True):
            trace = resolve_demo_trace(req, completed(adapter, handle))
            assert adapter.get_status(handle) == CaseExecutionStatus.COMPLETED
            assert trace.case_id == req.case.id and trace.run_id == req.run_id
            assert trace.trace_id == req.traceparent.split("-")[1]
            assert set(trace.turn_outcomes) == {turn.id for turn in req.case.turns}
            assert trace.final_state["application_id"] == req.case.id
        assert peak == limit
        assert observed == {req.case.id: [0, 1] for req in requests}
    finally:
        adapter.close()
        adapter.close()
    with pytest.raises(TargetExecutionError, match="closed"):
        adapter.start(replace(requests[0], execution_id="after-close"))


@pytest.mark.parametrize("mode", ["base", "workflow", "cloudshrimp"])
@pytest.mark.parametrize("limit", [1, 2, 3, 30])
def test_local_bank_bounded_overlap_keeps_actual_sessions_and_evidence_separate(mode, limit):
    gate, lock = Barrier(limit), Lock()
    active = peak = 0

    class ConcurrentClient(Client):
        def call(self, path, payload=None, **kwargs):
            nonlocal active, peak
            if not payload or path.endswith("init_session"):
                return super().call(path, payload, **kwargs)
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                gate.wait(5)
                return super().call(path, payload, **kwargs)
            finally:
                with lock:
                    active -= 1

    client = ConcurrentClient(mode)
    _, target = local_bank_target(client, mode)
    adapter = LocalBankAdapter(client, client.trace_server)
    requests = [
        replace(
            demo_request(
                Case(
                    id=str(i),
                    name="c",
                    turns=[
                        CaseTurn(id=f"{i}-{turn}", input={"txt": f"case{i}-turn{turn}"})
                        for turn in range(2)
                    ],
                )
            ),
            target=target,
            execution_id=str(i),
            max_parallel_cases=limit,
            traceparent=f"00-{i + 1:032x}-{'b' * 16}-01",
        )
        for i in range(limit * 2)
    ]
    try:
        handles = [adapter.start(req) for req in requests]
        results = [completed(adapter, handle) for handle in handles]
        assert peak == limit
        assert len({r.trace_id for r in results}) == len(requests)
        sessions = {}
        for rid, record in client.requests.items():
            sessions.setdefault(record["session_id"], []).append(client.inputs[rid]["txt"])
        assert len(sessions) == len(requests)
        assert sorted(sessions.values()) == sorted(
            [[turn.input["txt"] for turn in req.case.turns] for req in requests]
        )
        for req, result in zip(requests, results, strict=True):
            assert result.inline_trace.case_id == req.case.id
            for turn in req.case.turns:
                assert result.inline_trace.turn_outcomes[turn.id]["input"] == turn.input
    finally:
        adapter.close()


def cancel_and_close_inflight(adapter, request, entered, release):
    handle = adapter.start(request)
    closing, closed = Event(), Event()

    def close():
        closing.set()
        adapter.close()
        closed.set()

    closer = Thread(target=close)
    try:
        assert entered.wait(5)
        with pytest.raises(CaseExecutionPending):
            adapter.wait(handle, 0.001)
        adapter.cancel(handle)
        assert adapter.get_status(handle) == CaseExecutionStatus.CANCELLED
        with pytest.raises(TargetExecutionError, match="cancelled"):
            adapter.wait(handle, 1)
        closer.start()
        assert closing.wait(5)
        assert not closed.wait(0.05)
    finally:
        release.set()
        if closer.ident is not None:
            closer.join(5)
        adapter.close()
    assert closed.is_set()


def test_demo_cancellation_stops_later_turn_and_cleanup_waits_for_provider():
    entered, release = Event(), Event()
    calls = []

    class Provider(DeterministicProvider):
        def choose_action(self, values, version):
            calls.append(values["turn"])
            entered.set()
            assert release.wait(5)
            return super().choose_action(values, version)

    case = Case(
        name="cancel",
        turns=[
            CaseTurn(
                input={
                    "application_id": "cancel",
                    "skill": "loan_approval",
                    "amount": 100,
                    "risk": "low",
                    "turn": i,
                }
            )
            for i in range(2)
        ],
    )
    cancel_and_close_inflight(
        DemoLoanTargetAdapter(provider=Provider()),
        replace(demo_request(case), max_parallel_cases=2),
        entered,
        release,
    )
    assert calls == [0]


@pytest.mark.parametrize("mode", ["base", "workflow", "cloudshrimp"])
def test_local_bank_cancellation_stops_later_turn_and_cleanup_waits_for_http(mode):
    entered, release = Event(), Event()
    calls = []

    class BlockingClient(Client):
        def call(self, path, payload=None, **kwargs):
            if payload and not path.endswith("init_session"):
                calls.append(path)
                entered.set()
                assert release.wait(5)
            return super().call(path, payload, **kwargs)

    client = BlockingClient(mode)
    _, target = local_bank_target(client, mode)
    case = Case(name="cancel", turns=[CaseTurn(input={"txt": str(i)}) for i in range(2)])
    cancel_and_close_inflight(
        LocalBankAdapter(client, client.trace_server),
        replace(demo_request(case), target=target, max_parallel_cases=2),
        entered,
        release,
    )
    assert len(calls) == 1
