// Editable starting rules for the implementations in the existing builtin catalog.
// These explicit checks do not reproduce every builtin expectation/operator.
export function builtinRuleCode(implementation: string): string {
  const header =
    'def exec_evaluation(turn_data):\n    target = turn_data["evaluate_target_output_fields"]\n';
  if (implementation === 'required_tool' || implementation === 'forbidden_tool') {
    const required = implementation === 'required_tool';
    return (
      header +
      `    # 修改工具名；按本轮实际工具调用判断，不以回答文本替代证据。
    tool_name = "${required ? 'request_human_review' : 'approve_loan'}"
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == tool_name]
    passed = len(calls) ${required ? '>' : '=='} 0
    reason = "${required ? '已调用必需工具' : '未调用禁止工具'}" if passed else "${required ? '未调用必需工具' : '调用了禁止工具'}"
    return EvalOutput(score=1 if passed else 0, reason=reason, span_ids=[s["span_id"] for s in calls])
`
    );
  }
  if (implementation === 'skill_routing')
    return (
      header +
      `    # 修改期望技能；检查 sequence 最小的路由节点。
    expected_skill = "loan_approval"
    routes = [s for s in target["spans"] if s.get("operation_type") == "routing"]
    if len(routes) == 0:
        return EvalOutput(score=0, reason="未产生路由决策")
    else:
        first = routes[0]
        for span in routes:
            if span["sequence"] < first["sequence"]:
                first = span
        passed = first["attributes"]["selected_skill"] == expected_skill
        return EvalOutput(score=1 if passed else 0, reason="路由正确" if passed else "路由与期望不符", span_ids=[first["span_id"]])
`
    );
  if (implementation === 'tool_arguments')
    return (
      header +
      `    # 修改工具名、参数字段与期望值；示例检查最后一次调用。
    tool_name = "request_human_review"
    parameter = "human_review"
    expected = True
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == tool_name]
    if len(calls) == 0:
        return EvalOutput(score=0, reason="未调用指定工具，无法验证参数")
    else:
        last = calls[0]
        for span in calls:
            if span["sequence"] >= last["sequence"]:
                last = span
        actual = last["attributes"][parameter]
        passed = actual == expected
        return EvalOutput(score=1 if passed else 0, reason="工具参数符合预期" if passed else "工具参数不符合预期", span_ids=[last["span_id"]])
`
    );
  if (implementation === 'final_state' || implementation === 'final_output') {
    const field = implementation === 'final_state' ? 'final_state' : 'actual_output';
    const label = implementation === 'final_state' ? '最终状态' : '最终输出';
    return (
      header +
      `    # 修改字段和期望值；嵌套字段可继续使用字典下标读取。
    field = "status"
    expected = "pending_review"
    actual = target["${field}"][field]
    passed = actual == expected
    return EvalOutput(score=1 if passed else 0, reason="${label}符合预期" if passed else "${label}不符合预期")
`
    );
  }
  throw new Error('该预置规则尚无可编辑的 Python 模板，请选择不使用预置模板。');
}

export function combinedBuiltinRuleCode(implementations: string[]): string {
  const selected = [...new Set(implementations)];
  if (!selected.length) throw new Error('请至少选择一个预置模板。');
  if (selected.length === 1) return builtinRuleCode(selected[0]);
  // Builtin template branches are exhaustive: capture each result without returning
  // early, so a failed check cannot skip the remaining selected checks.
  const blocks = selected.map((implementation, index) => {
    const body = builtinRuleCode(implementation).split('\n').slice(1).join('\n');
    return (
      `    # 检查 ${index + 1}：${implementation}\n` +
      body.replace(/^(\s*)return EvalOutput\(/gm, `$1check${index + 1} = EvalOutput(`)
    );
  });
  return (
    'def exec_evaluation(turn_data):\n' +
    blocks.join('\n') +
    `\n    checks = [${selected.map((_, index) => `check${index + 1}`).join(', ')}]
    passed = all([check["score"] == 1 for check in checks])
    reason = ""
    for check in checks:
        reason = reason + check["reason"] + "；"
    evidence = [s["span_id"] for s in target["spans"] if any([s["span_id"] in check.get("span_ids", []) for check in checks])]
    return EvalOutput(score=1 if passed else 0, reason=reason, span_ids=evidence)
`
  );
}

// New rules use AgentGate's native Trace names. Existing published rules keep their format.
export function traceBuiltinRuleCode(implementations: string[]): string {
  return combinedBuiltinRuleCode(implementations)
    .replace('def exec_evaluation(turn_data):', 'def exec_evaluation(trace):')
    .replaceAll('target = turn_data["evaluate_target_output_fields"]', 'target = trace')
    .replaceAll('["actual_output"]', '["final_output"]')
    .replaceAll('本轮', '整条 Trace');
}

export interface CodeTraceData {
  trace_id: string;
  run_id: string;
  case_id: string;
  turn_outcomes: Record<
    string,
    {
      input?: Record<string, unknown> | null;
      output?: Record<string, unknown>;
      state?: Record<string, unknown>;
    }
  >;
  final_output: Record<string, unknown>;
  final_state: Record<string, unknown>;
  spans: Record<string, unknown>[];
}

export function traceDataForLegacyRule(trace: CodeTraceData) {
  const turns = Object.entries(trace.turn_outcomes);
  if (turns.length > 1)
    throw new Error(
      '此旧版规则按轮评估，不能直接使用多轮完整 Trace。请使用单轮 Trace 或自定义 JSON；新建规则支持整条 Trace。',
    );
  const [turnId, turn] = turns[0] ?? ['', {}];
  return {
    evaluate_dataset_fields: { input: turn.input ?? {}, expectations: [] },
    evaluate_target_output_fields: {
      actual_output: trace.final_output,
      final_state: trace.final_state,
      spans: trace.spans,
    },
    ext: {
      trace_id: trace.trace_id,
      run_id: trace.run_id,
      case_id: trace.case_id,
      turn_id: turnId,
    },
  };
}
