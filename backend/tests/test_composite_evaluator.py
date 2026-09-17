from types import SimpleNamespace

import pytest

from agentgate.domain import EvaluatorSpec, EvaluatorRef, Outcome
from agentgate.evaluator.hybrid import CompositeEvaluator


def spec(policy="all", threshold=0.8):
    return EvaluatorSpec(id="combined", name="Combined", kind="hybrid", dimension="answer",
                         metric="combined", implementation_id="composite", combination=policy,
                         config={"pass_threshold": threshold}, children=tuple(
                             EvaluatorRef(evaluator_id=id, evaluator_version="1", weight=0.5 if policy == "weighted_score" else None)
                             for id in ("rule", "judge")))


def result(id, outcome, score, severity="standard"):
    return SimpleNamespace(id="result-"+id, evaluator_id=id, evaluator_version="1",
                           outcome=Outcome(outcome), score=score, severity=severity)


@pytest.mark.parametrize("policy,left,right,expected", [
    ("all", "pass", "pass", "pass"), ("all", "pass", "fail", "fail"),
    ("any", "pass", "fail", "pass"), ("any", "fail", "fail", "fail"),
    ("any", "pass", "review", "review"), ("weighted_score", "pass", "fail", "fail"),
    ("all", "not_applicable", "not_applicable", "not_applicable"),
    ("weighted_score", "not_applicable", "pass", "pass"),
])
def test_composition(policy, left, right, expected):
    values = {id: result(id, outcome, None if outcome == "not_applicable" else 1 if outcome == "pass" else 0)
              for id, outcome in (("rule", left), ("judge", right))}
    check = CompositeEvaluator().evaluate_case(spec(policy), None, None, values.__getitem__).checks[0]
    assert check.outcome == expected
    assert len(check.actual) == 2
    if expected == "not_applicable":
        assert check.score is None


def test_blocking_and_error_are_not_passes():
    values = {"rule": result("rule", "fail", 0, "blocking"), "judge": result("judge", "pass", 1)}
    evaluator = CompositeEvaluator()
    assert evaluator.evaluate_case(spec("any"), None, None, values.__getitem__).checks[0].outcome == "fail"
    values["rule"] = result("rule", "error", None)
    with pytest.raises(ValueError, match="child evaluation failed"):
        evaluator.evaluate_case(spec("any"), None, None, values.__getitem__)


@pytest.mark.parametrize("threshold", [-1, 2, True, "0.8"])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        CompositeEvaluator().validate_spec(spec(threshold=threshold))
