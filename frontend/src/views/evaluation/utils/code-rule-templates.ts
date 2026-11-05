export type RuleTarget = 'tool' | 'span' | 'answer';

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

export interface CodeTestDatasetVersion {
  version: number | null;
  status: string;
  cases: {
    id: string;
    name: string;
    turns: { id: string; input: Record<string, unknown>; expectations: unknown[] }[];
  }[];
}

export function datasetCodeTestData(
  version: CodeTestDatasetVersion,
  caseId: string,
  turnId: string,
) {
  if (version.status !== 'published' || version.version === null)
    throw new Error('请选择已发布的测评集版本。');
  const sample = version.cases.find((item) => item.id === caseId);
  const turn = sample?.turns.find((item) => item.id === turnId);
  if (!sample || !turn) throw new Error('请选择该版本中的样本与轮次。');
  return JSON.parse(
    JSON.stringify({
      evaluate_dataset_fields: { input: turn.input, expectations: turn.expectations },
      evaluate_target_output_fields: { actual_output: {}, final_state: {}, spans: [] },
      ext: { case_id: sample.id, turn_id: turn.id, trace_id: '' },
    }),
  );
}

export function exampleCodeTestData(withTools: boolean) {
  return {
    evaluate_dataset_fields: {
      input: { application_id: 'TEST-001', risk: 'high' },
      expectations: [],
    },
    evaluate_target_output_fields: {
      actual_output: { output: withTools ? '已提交人工复核' : '未提交复核' },
      final_state: { human_review: withTools, approved: false },
      spans: withTools
        ? ['credit_inquiry', 'request_human_review'].map((name, index) => ({
            trace_id: 'a'.repeat(32),
            span_id: String(index + 1).repeat(16),
            parent_span_id: null,
            name,
            operation_type: 'tool',
            sequence: index + 1,
            status: 'ok',
            started_at: '2026-01-01T00:00:00Z',
            ended_at: '2026-01-01T00:00:01Z',
            attributes: { application_id: 'TEST-001' },
            events: [],
          }))
        : [],
    },
    ext: { case_id: 'test-case', turn_id: 'test-turn', trace_id: 'a'.repeat(32) },
  };
}

export const codeRuleExamples = [
  {
    id: 'text-contains',
    dimension: 'answer',
    name: '文本包含',
    hint: '修改关键词和回答字段名。示例读取 actual_output.output；字段缺失会报异常。',
    source: `def exec_evaluation(turn_data):
    answer = turn_data["evaluate_target_output_fields"]["actual_output"]["output"]
    keyword = "人工复核"
    if keyword in answer:
        return EvalOutput(score=1, reason="回答包含指定关键词")
    return EvalOutput(score=0, reason="回答缺少指定关键词")
`,
  },
  {
    id: 'tool-success',
    dimension: 'tool_use',
    name: '工具调用成功',
    hint: '修改工具名。至少调用一次，且该工具的所有调用均为 ok 才通过；unset 不算成功。',
    source: `def exec_evaluation(turn_data):
    spans = turn_data["evaluate_target_output_fields"]["spans"]
    tool_name = "request_human_review"
    calls = [s for s in spans if s["operation_type"] == "tool" and s["name"] == tool_name]
    evidence = [s["span_id"] for s in calls]
    if len(calls) > 0 and all([s["status"] == "ok" for s in calls]):
        return EvalOutput(score=1, reason="指定工具的所有调用均成功", span_ids=evidence)
    return EvalOutput(score=0, reason="工具未调用或存在非成功调用", span_ids=evidence)
`,
  },
  {
    id: 'tool-parameter',
    dimension: 'tool_use',
    name: '工具参数匹配',
    hint: '修改工具名及参数字段。示例将 attributes.application_id 与样本 input.application_id 比较；不检查工具执行状态。',
    source: `def exec_evaluation(turn_data):
    expected = turn_data["evaluate_dataset_fields"]["input"]["application_id"]
    spans = turn_data["evaluate_target_output_fields"]["spans"]
    calls = [s for s in spans if s["operation_type"] == "tool" and s["name"] == "credit_inquiry"]
    evidence = [s["span_id"] for s in calls]
    if len(calls) > 0 and all([s["attributes"]["application_id"] == expected for s in calls]):
        return EvalOutput(score=1, reason="所有调用的参数均与样本输入一致", span_ids=evidence)
    return EvalOutput(score=0, reason="工具未调用或参数不匹配", span_ids=evidence)
`,
  },
  {
    id: 'final-state',
    dimension: 'state',
    name: '最终状态判断',
    hint: '修改状态字段和期望值。True / False 是布尔值，不是字符串；示例要求 human_review 为 true、approved 为 false。',
    source: `def exec_evaluation(turn_data):
    state = turn_data["evaluate_target_output_fields"]["final_state"]
    human_review = state["human_review"]
    approved = state["approved"]
    if human_review is True and approved is False:
        return EvalOutput(score=1, reason="已转人工复核且未批准")
    return EvalOutput(score=0, reason="最终状态不符合预期")
`,
  },
  {
    id: 'weighted-checks',
    dimension: 'answer',
    name: '多条件计分',
    hint: '两个条件各占 50 分，并分别输出原因。默认通过分数为 100；修改代码不会自动修改通过分数。',
    source: `def exec_evaluation(turn_data):
    target = turn_data["evaluate_target_output_fields"]
    answer = target["actual_output"]["output"]
    human_review = target["final_state"]["human_review"]
    score = 0
    reason = ""
    if answer.strip() != "":
        score += 0.5
        reason += "[通过] 回答非空；"
    else:
        reason += "[失败] 回答为空；"
    if human_review is True:
        score += 0.5
        reason += "[通过] 已转人工复核；"
    else:
        reason += "[失败] 未转人工复核；"
    return EvalOutput(score=score, reason=reason)
`,
  },
] as const;

export const codeRuleSyntax = [
  {
    name: '读取字段',
    code: 'value = data["key"]',
    note: '必需字段缺失会报异常；data 是示意变量，需先赋值。',
  },
  {
    name: '可选字段',
    code: 'value = data.get("key", None)',
    note: '只对可选字段使用默认值；不要用默认值掩盖缺失证据。',
  },
  {
    name: '比较与组合',
    code: 'value == "ok" and count >= 1\nvalue != "error" or count > 2',
    note: '等于 ==、不等于 !=、大小比较 > >= < <=、并且 and、或者 or。',
  },
  {
    name: '文本与布尔',
    code: '"关键词" in text\ntext.strip() != ""\nflag is True',
    note: '包含、不为空、严格布尔判断；布尔常量使用 True / False。',
  },
  {
    name: '分支与循环',
    code: 'if count > 0:\n    score = 1\nelse:\n    score = 0\nfor item in items:\n    count += 1',
    note: '用缩进表示代码块；不支持 while、break、continue。',
  },
  {
    name: '筛选与全部满足',
    code: 'calls = [s for s in spans if s["name"] == "credit_inquiry"]\nok = len(calls) > 0 and all([s["status"] == "ok" for s in calls])',
    note: 'all 全部满足，any 任一满足。all([]) 为真，检查调用时应先确认列表非空。',
  },
  {
    name: '返回结果',
    code: 'return EvalOutput(score=1, reason="检查通过", span_ids=[])',
    note: 'score 范围 0～1，界面显示 0～100；reason 必填，span_ids 可省略，仅可引用本轮证据。',
  },
] as const;

export type RuleField = 'name' | 'status' | 'sequence' | 'output';
export type RuleOperator =
  | 'eq'
  | 'ne'
  | 'contains'
  | 'not_contains'
  | 'gt'
  | 'lt'
  | 'exists'
  | 'missing';
export type RuleCondition = { field: RuleField; operator: RuleOperator; value: string };
export type RuleBuilderConfig = {
  target: RuleTarget;
  join: 'all' | 'any';
  conditions: RuleCondition[];
};

export const ruleFieldLabels: Record<RuleField, string> = {
  name: '名称',
  status: '执行状态',
  sequence: '步骤序号',
  output: '回答文本（output）',
};
export const ruleOperatorLabels: Record<RuleOperator, string> = {
  eq: '等于',
  ne: '不等于',
  contains: '包含',
  not_contains: '不包含',
  gt: '大于',
  lt: '小于',
  exists: '存在',
  missing: '不存在',
};
export function ruleFields(target: RuleTarget): RuleField[] {
  return target === 'answer' ? ['output'] : ['name', 'status', 'sequence'];
}
export function ruleOperators(field: RuleField): RuleOperator[] {
  return field === 'sequence'
    ? ['eq', 'ne', 'gt', 'lt', 'exists', 'missing']
    : ['eq', 'ne', 'contains', 'not_contains', 'exists', 'missing'];
}
export function needsRuleValue(operator: RuleOperator): boolean {
  return operator !== 'exists' && operator !== 'missing';
}
export function ruleBuilderError(config: RuleBuilderConfig): string {
  if (
    !['tool', 'span', 'answer'].includes(config.target) ||
    !['all', 'any'].includes(config.join)
  ) {
    return '请选择有效的检查对象和条件关系。';
  }
  if (config.conditions.length < 1 || config.conditions.length > 8) return '请配置 1–8 条条件。';
  for (const condition of config.conditions) {
    if (
      !ruleFields(config.target).includes(condition.field) ||
      !ruleOperators(condition.field).includes(condition.operator)
    ) {
      return '字段与比较方式不匹配。';
    }
    if (!needsRuleValue(condition.operator)) continue;
    if (!condition.value.trim() || condition.value.length > 160)
      return '比较值需填写 1–160 个字符。';
    if (
      condition.field === 'sequence' &&
      (!/^\d+$/.test(condition.value) || !Number.isSafeInteger(Number(condition.value)))
    ) {
      return '步骤序号须为非负安全整数。';
    }
  }
  return '';
}
export function describeCodeRule(config: RuleBuilderConfig): string {
  const conditions = config.conditions
    .map(
      ({ field, operator, value }) =>
        `${ruleFieldLabels[field]} ${ruleOperatorLabels[operator]}${needsRuleValue(operator) ? `「${value}」` : ''}`,
    )
    .join(config.join === 'all' ? '，且 ' : '，或 ');
  return (
    (config.target === 'answer'
      ? '最终回答满足：'
      : `至少一个${config.target === 'tool' ? '工具调用' : '执行节点'}满足：`) + conditions
  );
}
export function generateCodeRule(config: RuleBuilderConfig): string {
  const error = ruleBuilderError(config);
  if (error) throw new Error(error);
  // Only quoted data or validated integer literals enter the generated source.
  const clauses = config.conditions
    .map(({ field, operator, value }) => {
      const key = JSON.stringify(field);
      if (operator === 'exists') return `(${key} in item)`;
      if (operator === 'missing') return `(${key} not in item)`;
      const literal = field === 'sequence' ? String(Number(value)) : JSON.stringify(value);
      const access = `item[${key}]`;
      if (operator === 'contains' || operator === 'not_contains') {
        return `(${literal} ${operator === 'contains' ? 'in' : 'not in'} ${access})`;
      }
      const comparison = { eq: '==', ne: '!=', gt: '>', lt: '<' }[operator];
      return `(${access} ${comparison} ${literal})`;
    })
    .join(config.join === 'all' ? ' and ' : ' or ');
  const header =
    'def exec_evaluation(turn_data):\n    target = turn_data["evaluate_target_output_fields"]\n';
  const note = '    # 缺失的比较字段通过下标读取报错，不替换为空值或 0 分。\n';
  let source: string;
  if (config.target === 'answer') {
    source =
      header +
      note +
      '    item = target["actual_output"]\n' +
      `    if ${clauses}:\n` +
      '        return EvalOutput(score=1, reason="回答满足配置条件")\n' +
      '    return EvalOutput(score=0, reason="回答不满足配置条件")\n';
  } else {
    source =
      header +
      note +
      '    spans = target["spans"]\n' +
      `    candidates = ${config.target === 'tool' ? '[s for s in spans if s["operation_type"] == "tool"]' : 'spans'}\n` +
      `    matched = [item for item in candidates if ${clauses}]\n` +
      '    if len(matched) > 0:\n' +
      '        return EvalOutput(score=1, reason="存在满足条件的调用或节点", span_ids=[s["span_id"] for s in matched])\n' +
      '    return EvalOutput(score=0, reason="未匹配到满足条件的调用或节点")\n';
  }
  if (new TextEncoder().encode(source).length > 16384)
    throw new Error('生成代码超过 16 KB，请减少条件。');
  return source;
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

export function exampleTraceData(withTools: boolean): CodeTraceData {
  const old = exampleCodeTestData(withTools);
  return {
    trace_id: old.ext.trace_id,
    case_id: old.ext.case_id,
    run_id: 'simulation',
    turn_outcomes: {
      'test-turn': {
        input: old.evaluate_dataset_fields.input,
        output: old.evaluate_target_output_fields.actual_output,
        state: old.evaluate_target_output_fields.final_state,
      },
    },
    final_output: old.evaluate_target_output_fields.actual_output,
    final_state: old.evaluate_target_output_fields.final_state,
    spans: old.evaluate_target_output_fields.spans,
  };
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
