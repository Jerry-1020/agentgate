"""Versioned Code rules with native whole-Trace and legacy turn-scoped inputs."""

import json
import math
import subprocess
import sys
from pathlib import Path

from agentgate.domain import EvaluatorKind, FailureStage, MethodRef, Outcome
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate
from agentgate.evaluator.rule.code_runtime import MAX_INPUT, parse_source


def validate_code_config(config):
    if set(config) - {"input_format"} != {"language", "source", "pass_threshold"}:
        raise ValueError("Code 配置必须包含 language、source、pass_threshold")
    if config["language"] != "python-subset-v1":
        raise ValueError("首版仅支持受限 Python（python-subset-v1）")
    threshold = config["pass_threshold"]
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("通过阈值必须为 0 到 1 的数字")
    function = parse_source(config["source"])
    if config.get("input_format") not in (None, "trace-v1"):
        raise ValueError("不支持的 Code 输入格式")
    if config.get("input_format") == "trace-v1" and function.args.args[0].arg != "trace":
        raise ValueError("Trace 规则函数签名必须为 def exec_evaluation(trace):")


def run_code(source, data):
    payload = json.dumps({"source": source, "data": data}, ensure_ascii=True, allow_nan=False)
    if len(payload.encode()) > MAX_INPUT:
        raise ValueError("Code 评估输入超过 1 MB，未截断证据")
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(Path(__file__).with_name("code_runtime.py"))],
            input=payload, text=True, capture_output=True, timeout=3,
            env={"PYTHONIOENCODING": "utf-8"}, cwd=Path(__file__).parent,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Code 规则执行超时（3 秒）") from exc
    if result.returncode != 0:
        raise RuntimeError("Code 执行进程异常退出或超出资源限制")
    response = json.loads(result.stdout)
    if "error" in response:
        raise ValueError(response["error"])
    output = response.get("result")
    if not isinstance(output, dict) or set(output) - {"score", "reason", "span_ids"}:
        raise ValueError("规则需返回 EvalOutput(score=..., reason=..., span_ids=[...])")
    score, reason = output.get("score"), output.get("reason")
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("规则 score 必须为 0 到 1 的有限数字")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("规则 reason 必须为 1 到 2000 字符的说明")
    span_ids = output.get("span_ids", [])
    if not isinstance(span_ids, list) or any(not isinstance(s, str) for s in span_ids):
        raise ValueError("span_ids 必须为字符串列表")
    return output


def run_code_with_evidence(source, data):
    """Use the same output and evidence validation for tasks and manual trials."""
    output = run_code(source, data)
    span_ids = output.get("span_ids", [])
    known_ids = {span["span_id"] for span in (data["spans"] if "spans" in data else data["evaluate_target_output_fields"]["spans"])}
    if set(span_ids) - known_ids:
        raise ValueError("规则返回了不属于当前 Trace 的证据")
    return output


def trace_code_data(trace):
    """Whole-case native Trace, enriching recorded per-turn inputs for SDK traces."""
    data = trace.model_dump(mode="json")
    outcomes = data["turn_outcomes"]
    for span in trace.spans:
        turn_id = span.attributes.get("agentgate.turn.id")
        if span.operation_type != "turn" or not isinstance(turn_id, str):
            continue
        outcome = outcomes.setdefault(turn_id, {})
        if not isinstance(outcome, dict):
            raise ValueError("Trace turn_outcomes 必须为轮次对象")
        input_data = outcome.get("input")
        if input_data is None:
            attributes = span.attributes.to_dict()
            input_data = attributes.get("trace_sdk.input", attributes.get("agentgate.turn.input"))
            if isinstance(input_data, str):
                try:
                    input_data = json.loads(input_data)
                except ValueError:
                    input_data = None
        outcome["input"] = input_data if isinstance(input_data, dict) else None
    return data


class CodeRuleEvaluator:
    kind = EvaluatorKind.RULE
    implementation_id = "code_rule"
    implementation_version = "1"

    def validate_spec(self, spec):
        validate_code_config(spec.config)

    def applies_to(self, _spec, _turn):
        return True

    def evaluate(self, spec, turn, trace, _resolve):
        self.validate_spec(spec)
        data = {
            "evaluate_dataset_fields": {
                "input": turn.input.to_dict(),
                "expectations": [e.model_dump(mode="json") for e in turn.expectations],
            },
            "evaluate_target_output_fields": {
                "actual_output": trace.final_output.to_dict(),
                "final_state": trace.final_state.to_dict(),
                "spans": [s.model_dump(mode="json") for s in trace.spans],
            },
            "ext": {"turn_id": turn.id, "case_id": trace.case_id, "trace_id": trace.trace_id},
        }
        return self._evaluate_data(spec, data, turn.id)

    def evaluate_case(self, spec, _case, trace, _resolve):
        self.validate_spec(spec)
        return self._evaluate_data(spec, trace_code_data(trace), None)

    def _evaluate_data(self, spec, data, turn_id):
        output = run_code_with_evidence(spec.config["source"], data)
        span_ids = tuple(output.get("span_ids", []))
        passed = output["score"] >= spec.config["pass_threshold"]
        return Evaluation(checks=(CheckDraft(
            name=spec.name, turn_id=turn_id,
            outcome=Outcome.PASS if passed else Outcome.FAIL,
            score=output["score"], reason=output["reason"],
            expected={"minimum_score": spec.config["pass_threshold"]},
            actual={"score": output["score"]}, span_ids=span_ids,
            methods=(MethodRef(implementation_id=self.implementation_id, implementation_version="1"),),
            failure=None if passed else FailureCandidate(
                stage=FailureStage.RESULT_INTERPRETATION, at_trace_completion=True,
            ),
        ),))
