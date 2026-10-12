"""Check exact executed paths and Skill ownership from normalized Trace spans."""
from agentgate.domain import ExecutionPathExpectation, EvaluatorKind, Outcome, FailureStage, SpanStatus
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate


def _descends_from(span, ancestor, spans):
    seen = {span.span_id}
    parent = span.parent_span_id
    while parent and parent not in seen:
        if parent == ancestor.span_id:
            return True
        seen.add(parent)
        item = spans.get(parent)
        if item is None:
            return False
        parent = item.parent_span_id
    return False


class ExecutionPathEvaluator:
    kind = EvaluatorKind.RULE
    implementation_id = "execution_path"
    implementation_version = "1"

    def applies_to(self, _spec, turn):
        return any(isinstance(e, ExecutionPathExpectation) for e in turn.expectations)

    def evaluate(self, _spec, turn, trace, _resolve):
        checks = []
        by_id = {s.span_id: s for s in trace.spans}
        # SDK completion events may be emitted after children; order by actual start.
        ordered = sorted(trace.spans, key=lambda s: (s.started_at, s.sequence))
        tools = [s for s in ordered if s.operation_type == "tool"]
        for e in turn.expectations:
            if not isinstance(e, ExecutionPathExpectation):
                continue
            selected = [s for s in ordered if s.operation_type == e.scope]
            actual = [s.name if e.scope == "tool" else s.attributes.get(e.scope + ".id") for s in selected]
            problems = []
            if actual != list(e.expected):
                problems.append("实际执行路径与期望不一致（包含顺序、遗漏或额外执行）")
            if any(s.status != SpanStatus.OK for s in selected):
                problems.append("执行节点未成功完成")
            roots = [s for s in ordered if s.operation_type == "turn"]
            if len(roots) != 1 or roots[0].status != SpanStatus.OK:
                problems.append("缺少本轮成功完成的 Trace 证据")
            elif any(not _descends_from(s, roots[0], by_id) for s in selected):
                problems.append("执行节点不属于本轮 Trace")
            if e.scope == "skill":
                if len(selected) != 1 or any(not _descends_from(t, selected[0], by_id) for t in tools):
                    problems.append("工具调用不属于期望 Skill 的执行范围")
                if any(t.name not in e.allowed_tools for t in tools):
                    problems.append("Skill 调用了职责范围外的工具")
                if any(t.status != SpanStatus.OK for t in tools):
                    problems.append("Skill 内工具调用未成功完成")
            passed = not problems
            evidence = list(dict.fromkeys(s.span_id for s in [*selected, *(tools if e.scope == "skill" else [])]))
            checks.append(CheckDraft(
                name=e.name or {"workflow": "完整工作流路径", "skill": "Skill 实际执行与工具归属", "tool": "工具调用顺序与次数"}[e.scope],
                expectation_id=e.id, outcome=Outcome.PASS if passed else Outcome.FAIL,
                score=1.0 if passed else 0.0,
                reason="执行路径、节点状态及所属范围符合期望" if passed else "；".join(problems),
                expected={"path": e.expected, "allowed_tools": e.allowed_tools},
                actual={"path": actual, "tools": [t.name for t in tools] if e.scope == "skill" else None},
                span_ids=tuple(evidence),
                failure=None if passed else FailureCandidate(stage=FailureStage.PLANNING, at_trace_completion=True),
            ))
        return Evaluation(checks=tuple(checks))
