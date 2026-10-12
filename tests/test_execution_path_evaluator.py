from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from agentgate.domain import Case, CaseTurn, ExecutionPathExpectation, EvaluatorSpec, FrozenJsonObject, Trace, TraceSpan
from agentgate.evaluator.executor import execute_evaluators
from agentgate.evaluator.rule.execution import ExecutionPathEvaluator

TID = "a" * 32
ROOT = "1" * 16
START = datetime(2026, 10, 7, tzinfo=timezone.utc)
SPEC = EvaluatorSpec(id="execution-path", name="Execution", implementation_id="execution_path", dimension="execution", metric="execution_path_accuracy")


def span(i, kind, name, parent=ROOT, status="ok", at=None):
    return TraceSpan(trace_id=TID, span_id=f"{i:016x}", parent_span_id=parent,
        name=name, operation_type=kind, sequence=i,
        started_at=START + timedelta(seconds=i if at is None else at),
        ended_at=START + timedelta(seconds=100), status=status,
        attributes={kind + ".id": name})


def root():
    return TraceSpan(trace_id=TID, span_id=ROOT, name="turn", operation_type="turn", sequence=0,
        started_at=START, ended_at=START + timedelta(seconds=100), status="ok", attributes={"agentgate.turn.id": "one"})


def check(scope, expected, spans, allowed=None):
    e=ExecutionPathExpectation(scope=scope, expected=expected, allowed_tools=allowed)
    turn=CaseTurn(id="one", input={"txt":"synthetic"}, expectations=(e,))
    trace=Trace(trace_id=TID, run_id="run", case_id="case", spans=tuple(spans))
    return ExecutionPathEvaluator().evaluate(SPEC,turn,trace,None).checks[0]


def test_workflow_success_and_completion_order_do_not_change_actual_start_order():
    a=span(9,"workflow","extract",at=1)
    b=span(2,"workflow","end",at=2)
    assert check("workflow",("extract","end"),[root(),a,b]).outcome=="pass"


@pytest.mark.parametrize("names", [("extract",), ("end","extract"), ("extract","extract","end"), ("extract","act","end")])
def test_workflow_missing_reordered_duplicate_extra_nodes_fail(names):
    result=check("workflow",("extract","end"),[root(),*[span(i+2,"workflow",name) for i,name in enumerate(names)]])
    assert result.outcome=="fail" and result.score==0 and result.failure is not None


@pytest.mark.parametrize("status", ["unset","error"])
def test_node_must_have_success_evidence(status):
    assert check("workflow",("extract",),[root(),span(2,"workflow","extract",status=status)]).outcome=="fail"


def test_empty_tool_path_requires_a_complete_turn_and_forbids_calls():
    assert check("tool",(),[root()]).outcome=="pass"
    assert check("tool",(),[]).outcome=="fail"
    assert check("tool",(),[root(),span(2,"tool","submit_application")]).outcome=="fail"


def test_skill_requires_actual_invocation_and_tool_ancestry():
    skill=span(2,"skill","loan_application")
    tool=span(3,"tool","submit_application",parent=skill.span_id)
    assert check("skill",("loan_application",),[root(),skill,tool],("submit_application",)).outcome=="pass"
    assert check("skill",("loan_application",),[root(),tool],("submit_application",)).outcome=="fail"
    assert check("skill",("general_help",),[root(),skill,tool],()).outcome=="fail"
    assert check("skill",("loan_application",),[root(),skill,tool],()).outcome=="fail"
    outside=tool.model_copy(update={"parent_span_id":ROOT})
    assert check("skill",("loan_application",),[root(),skill,outside],("submit_application",)).outcome=="fail"


def test_skill_accepts_nested_workflow_but_rejects_broken_or_cyclic_ancestry():
    skill=span(2,"skill","loan_application")
    workflow=span(3,"workflow","submit",parent=skill.span_id)
    tool=span(4,"tool","submit_application",parent=workflow.span_id)
    assert check("skill",("loan_application",),[root(),skill,workflow,tool],("submit_application",)).outcome=="pass"
    for parent in ("f"*16, workflow.span_id):
        broken=workflow.model_copy(update={"parent_span_id":parent})
        assert check("skill",("loan_application",),[root(),skill,broken,tool],("submit_application",)).outcome=="fail"


def test_turn_scope_does_not_mix_skill_paths_across_rounds():
    first=root()
    second=span(5,"turn","second",parent=None).model_copy(update={"attributes":FrozenJsonObject({"agentgate.turn.id":"two"})})
    spans=(first,span(2,"skill","loan_application"),second,span(6,"skill","application_status",parent=second.span_id))
    turns=tuple(CaseTurn(id=tid,input={"txt":"test"},expectations=(ExecutionPathExpectation(scope="skill",expected=(skill,),allowed_tools=()),))
                for tid,skill in (("one","loan_application"),("two","application_status")))
    case=Case(id="case",name="switch",turns=turns)
    trace=Trace(trace_id=TID,run_id="run",case_id="case",spans=spans,
                turn_outcomes={t.id:{"input":{},"output":{},"state":{}} for t in turns})
    result=execute_evaluators(case,trace,(SPEC,),{("execution_path","1"):ExecutionPathEvaluator()})
    assert result[0].outcome=="pass"
    assert len(result[0].checks)==2


@pytest.mark.parametrize("payload", [
    {"scope":"workflow","expected":[]}, {"scope":"tool","expected":[" "]},
    {"scope":"skill","expected":["a"]},
    {"scope":"skill","expected":["a","b"],"allowed_tools":[]},
    {"scope":"workflow","expected":["a"],"allowed_tools":[]},
])
def test_execution_expectation_rejects_invalid_contracts(payload):
    with pytest.raises(ValidationError): ExecutionPathExpectation(**payload)
