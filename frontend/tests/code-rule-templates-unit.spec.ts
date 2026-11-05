import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  builtinRuleCode,
  traceBuiltinRuleCode,
  exampleTraceData,
  combinedBuiltinRuleCode,
  codeRuleExamples,
  codeRuleSyntax,
  datasetCodeTestData,
  exampleCodeTestData,
  describeCodeRule,
  generateCodeRule,
  ruleBuilderError,
  ruleOperators,
  type RuleBuilderConfig,
  type CodeTestDatasetVersion,
} from '../src/views/evaluation/utils/code-rule-templates';

test('existing builtin types generate editable code with pass/fail results and evidence', () => {
  for (const implementation of [
    'required_tool',
    'forbidden_tool',
    'skill_routing',
    'tool_arguments',
    'final_state',
    'final_output',
  ]) {
    const source = builtinRuleCode(implementation);
    for (const passed of [true, false]) {
      const data = exampleCodeTestData(true);
      const target: any = data.evaluate_target_output_fields;
      target.spans = [];
      if (
        (implementation === 'required_tool' && passed) ||
        (implementation === 'forbidden_tool' && !passed)
      )
        target.spans = [
          {
            span_id: '1'.repeat(16),
            operation_type: 'tool',
            name: implementation === 'required_tool' ? 'request_human_review' : 'approve_loan',
          },
        ];
      if (implementation === 'skill_routing')
        target.spans = [
          {
            span_id: '2'.repeat(16),
            operation_type: 'routing',
            sequence: 2,
            attributes: { selected_skill: 'wrong' },
          },
          {
            span_id: '1'.repeat(16),
            operation_type: 'routing',
            sequence: 1,
            attributes: { selected_skill: passed ? 'loan_approval' : 'wrong' },
          },
        ];
      if (implementation === 'tool_arguments')
        target.spans = [
          {
            span_id: '2'.repeat(16),
            operation_type: 'tool',
            name: 'request_human_review',
            sequence: 2,
            attributes: { human_review: passed },
          },
          {
            span_id: '1'.repeat(16),
            operation_type: 'tool',
            name: 'request_human_review',
            sequence: 1,
            attributes: { human_review: !passed },
          },
        ];
      target.final_state = target.actual_output = {
        status: passed ? 'pending_review' : 'approved',
      };
      const result = spawnSync(
        process.env.AGENTGATE_RULE_TEST_PYTHON || 'python3',
        ['-I', '-S', runtime],
        {
          input: JSON.stringify({ source, data }),
          encoding: 'utf8',
          timeout: 5000,
        },
      );
      expect(result.status, result.stderr).toBe(0);
      const response = JSON.parse(result.stdout);
      expect(response.error).toBeUndefined();
      expect(response.result.score).toBe(passed ? 1 : 0);
      for (const id of response.result.span_ids ?? [])
        expect(target.spans.some((s: any) => s.span_id === id)).toBe(true);
    }
  }
  expect(() => builtinRuleCode('unknown')).toThrow();
});

// Exercise the shipped examples in the real restricted interpreter, not Python eval.
const runtime = fileURLToPath(
  new URL('../../src/agentgate/evaluator/rule/code_runtime.py', import.meta.url),
);

test('multiple builtin templates aggregate every check and deduplicate evidence', () => {
  const types = [
    'skill_routing',
    'required_tool',
    'forbidden_tool',
    'tool_arguments',
    'final_state',
    'final_output',
  ];
  const data = () => ({
    evaluate_target_output_fields: {
      spans: [
        {
          span_id: '1'.repeat(16),
          operation_type: 'routing',
          sequence: 0,
          attributes: { selected_skill: 'loan_approval' },
        },
        {
          span_id: '2'.repeat(16),
          operation_type: 'tool',
          name: 'request_human_review',
          sequence: 1,
          attributes: { human_review: true },
        },
      ],
      final_state: { status: 'pending_review' },
      actual_output: { status: 'pending_review' },
    },
  });
  const run = (selected: string[], input: unknown) => {
    const result = spawnSync(
      process.env.AGENTGATE_RULE_TEST_PYTHON || 'python3',
      ['-I', '-S', runtime],
      {
        input: JSON.stringify({ source: combinedBuiltinRuleCode(selected), data: input }),
        encoding: 'utf8',
        timeout: 5000,
      },
    );
    expect(result.status, result.stderr).toBe(0);
    const response = JSON.parse(result.stdout);
    expect(response.error).toBeUndefined();
    return response.result;
  };
  // Every nonempty selection is valid, including one-template compatibility.
  for (let mask = 1; mask < 64; mask++) {
    const result = run(
      types.filter((_, i) => mask & (1 << i)),
      data(),
    );
    expect(result.score).toBe(1);
    expect(new Set(result.span_ids ?? []).size).toBe((result.span_ids ?? []).length);
  }
  for (const type of types) {
    const input: any = data();
    const target = input.evaluate_target_output_fields;
    if (type === 'skill_routing')
      target.spans = target.spans.filter((s: any) => s.operation_type !== 'routing');
    if (type === 'required_tool')
      target.spans = target.spans.filter((s: any) => s.operation_type !== 'tool');
    if (type === 'forbidden_tool')
      target.spans.push({ span_id: '3'.repeat(16), operation_type: 'tool', name: 'approve_loan' });
    if (type === 'tool_arguments') target.spans[1].attributes.human_review = false;
    if (type === 'final_state') target.final_state.status = 'approved';
    if (type === 'final_output') target.actual_output.status = 'approved';
    const result = run(types, input);
    expect(result.score).toBe(0);
    expect(result.reason).toContain('；');
    expect(result.reason).toContain(
      type === 'final_output' ? '最终输出不符合预期' : '最终输出符合预期',
    );
  }
  expect(combinedBuiltinRuleCode(['required_tool', 'required_tool'])).toBe(
    builtinRuleCode('required_tool'),
  );
  expect(() => combinedBuiltinRuleCode([])).toThrow();
  expect(() => combinedBuiltinRuleCode(['required_tool', 'unknown'])).toThrow();
});

const runExample = (id: string, data: unknown) => {
  const source = codeRuleExamples.find((item) => item.id === id)!.source;
  const result = spawnSync(
    process.env.AGENTGATE_RULE_TEST_PYTHON || 'python3',
    ['-I', '-S', runtime],
    {
      input: JSON.stringify({ source, data }),
      encoding: 'utf8',
      timeout: 5000,
    },
  );
  expect(result.error).toBeUndefined();
  expect(result.status, result.stderr).toBe(0);
  return JSON.parse(result.stdout);
};
const exampleData = () => ({
  evaluate_dataset_fields: { input: { application_id: 'DEMO-001' } },
  evaluate_target_output_fields: {
    actual_output: { output: '已提交人工复核' },
    final_state: { human_review: true, approved: false },
    spans: ['credit_inquiry', 'request_human_review'].map((name, index) => ({
      operation_type: 'tool',
      name,
      status: 'ok',
      span_id: String(index + 1).repeat(16),
      attributes: { application_id: 'DEMO-001' },
    })),
  },
});

test('dataset tests copy only the selected turn and never manufacture Agent evidence', () => {
  const version: CodeTestDatasetVersion = {
    status: 'published',
    version: 3,
    cases: [
      {
        id: 'case-a',
        name: '多轮样本',
        turns: [
          { id: 'first', input: { text: '第一轮' }, expectations: [] },
          {
            id: 'second',
            input: { text: '第二轮', nested: { amount: 20 } },
            expectations: [{ kind: 'tool_call', tool: 'required_tool', mode: 'required' }],
          },
        ],
      },
    ],
  };
  const original = structuredClone(version);
  const data = datasetCodeTestData(version, 'case-a', 'second');
  expect(data.evaluate_dataset_fields).toEqual(
    version.cases[0].turns[1] && {
      input: version.cases[0].turns[1].input,
      expectations: version.cases[0].turns[1].expectations,
    },
  );
  expect(data.evaluate_target_output_fields).toEqual({
    actual_output: {},
    final_state: {},
    spans: [],
  });
  expect(data.ext).toEqual({ case_id: 'case-a', turn_id: 'second', trace_id: '' });
  data.evaluate_dataset_fields.input.nested.amount = 999;
  data.evaluate_dataset_fields.expectations[0].tool = 'changed';
  expect(version).toEqual(original);
});

test('test data requires an existing published version, sample and turn', () => {
  const version: CodeTestDatasetVersion = {
    status: 'published',
    version: 1,
    cases: [
      {
        id: 'case',
        name: 'case',
        turns: [{ id: 'turn', input: { text: 'hello' }, expectations: [] }],
      },
    ],
  };
  expect(() =>
    datasetCodeTestData({ ...version, status: 'draft', version: null }, 'case', 'turn'),
  ).toThrow();
  expect(() => datasetCodeTestData(version, 'missing', 'turn')).toThrow();
  expect(() => datasetCodeTestData(version, 'case', 'other-turn')).toThrow();
});

test('manual simulation presets run the shipped templates with contrasting outcomes', () => {
  for (const item of codeRuleExamples) {
    expect(runExample(item.id, exampleCodeTestData(true)).result.score).toBe(1);
  }
  const empty = exampleCodeTestData(false);
  expect(empty.evaluate_target_output_fields.spans).toEqual([]);
  expect(runExample('tool-success', empty).result.score).toBe(0);
  expect(runExample('final-state', empty).result.score).toBe(0);
  const first = exampleCodeTestData(true);
  first.evaluate_target_output_fields.spans[0].name = 'changed';
  expect(exampleCodeTestData(true).evaluate_target_output_fields.spans[0].name).toBe(
    'credit_inquiry',
  );
});

test('all five examples are executable and preserve evidence', () => {
  expect(new Set(codeRuleExamples.map((item) => item.id)).size).toBe(5);
  for (const example of codeRuleExamples) {
    const data = exampleData();
    const output = runExample(example.id, data);
    expect(output.error).toBeUndefined();
    expect(output.result.score).toBe(1);
    expect(output.result.reason.length).toBeGreaterThan(0);
    for (const id of output.result.span_ids || []) {
      expect(data.evaluate_target_output_fields.spans.map((s) => s.span_id)).toContain(id);
    }
  }
  expect(codeRuleSyntax).toHaveLength(7);
});

test('text and weighted examples give meaningful failure and partial scores', () => {
  const data = exampleData();
  data.evaluate_target_output_fields.actual_output.output = '  ';
  expect(runExample('text-contains', data).result.score).toBe(0);
  expect(runExample('weighted-checks', data).result.score).toBe(0.5);
  data.evaluate_target_output_fields.final_state.human_review = false;
  expect(runExample('weighted-checks', data).result.score).toBe(0);
  expect(runExample('final-state', data).result.score).toBe(0);
});

test('tool templates do not pass empty calls, bad parameters or unset status', () => {
  const data = exampleData();
  data.evaluate_target_output_fields.spans[0].attributes.application_id = 'OTHER';
  expect(runExample('tool-parameter', data).result.score).toBe(0);
  for (const status of ['error', 'unset']) {
    data.evaluate_target_output_fields.spans[1].status = status;
    expect(runExample('tool-success', data).result.score).toBe(0);
  }
  data.evaluate_target_output_fields.spans = [];
  expect(runExample('tool-success', data).result.score).toBe(0);
  expect(runExample('tool-parameter', data).result.score).toBe(0);
});

test('missing required fields remain errors and strings do not pass boolean checks', () => {
  for (const example of codeRuleExamples) {
    expect(runExample(example.id, {}).error).toBeTruthy();
  }
  const data = exampleData();
  const invalid = {
    ...data,
    evaluate_target_output_fields: {
      ...data.evaluate_target_output_fields,
      final_state: { human_review: 'true', approved: false },
    },
  };
  expect(runExample('final-state', invalid).result.score).toBe(0);
  expect(runExample('weighted-checks', invalid).result.score).toBe(0.5);
});

const config = (): RuleBuilderConfig => ({
  target: 'tool',
  join: 'all',
  conditions: [{ field: 'name', operator: 'eq', value: 'request_human_review' }],
});

test('tool conditions apply to one span and return matching evidence', () => {
  const value = config();
  value.conditions.push({ field: 'status', operator: 'eq', value: 'ok' });
  const source = generateCodeRule(value);
  expect(source).toContain('s["operation_type"] == "tool"');
  expect(source).toContain('(item["name"] == "request_human_review") and (item["status"] == "ok")');
  expect(source).toContain('span_ids=[s["span_id"] for s in matched]');
  expect(source).toContain('score=0');
  expect(source).toContain('score=1');
});

test('OR uses the same candidate scope and does not modify input config', () => {
  const value = config();
  value.join = 'any';
  value.conditions.push({ field: 'name', operator: 'eq', value: 'credit_inquiry' });
  const snapshot = structuredClone(value);
  expect(generateCodeRule(value)).toContain(' or ');
  expect(value).toEqual(snapshot);
  expect(describeCodeRule(value)).toContain('，或 ');
});

test('answer and node targets use their own data source', () => {
  const answer: RuleBuilderConfig = {
    target: 'answer',
    join: 'all',
    conditions: [{ field: 'output', operator: 'not_contains', value: '还没有学会' }],
  };
  const source = generateCodeRule(answer);
  expect(source).toContain('item = target["actual_output"]');
  expect(source).toContain('"还没有学会" not in item["output"]');
  expect(source).not.toContain('span_ids');
  expect(generateCodeRule({ ...config(), target: 'span' })).toContain('candidates = spans');
});

test('values are quoted data, not executable source', () => {
  const value = config();
  value.conditions[0].value = 'x"\nimport os\n\\中文';
  expect(generateCodeRule(value)).toContain(JSON.stringify(value.conditions[0].value));
  expect(generateCodeRule(value).split('\n')).not.toContain('import os');
});

test('existence checks keys without replacing missing values', () => {
  const value = config();
  value.conditions[0] = { field: 'name', operator: 'missing', value: '' };
  expect(generateCodeRule(value)).toContain('"name" not in item');
  value.conditions[0].operator = 'exists';
  expect(generateCodeRule(value)).toContain('"name" in item');
  expect(generateCodeRule(config())).toContain('item["name"]');
});

test('numbers are validated and emitted as canonical integer literals', () => {
  const value = config();
  value.conditions[0] = { field: 'sequence', operator: 'gt', value: '002' };
  expect(generateCodeRule(value)).toContain('item["sequence"] > 2');
  for (const invalid of ['-1', 'Infinity', '1.5', '1e3', '9007199254740992', '0 or 1']) {
    value.conditions[0].value = invalid;
    expect(ruleBuilderError(value)).not.toBe('');
    expect(() => generateCodeRule(value)).toThrow();
  }
});

test('rejects empty, oversized and mismatched configurations', () => {
  expect(ruleBuilderError({ ...config(), conditions: [] })).not.toBe('');
  expect(
    ruleBuilderError({ ...config(), conditions: Array(9).fill(config().conditions[0]) }),
  ).not.toBe('');
  expect(ruleBuilderError({ ...config(), target: 'answer' })).not.toBe('');
  for (const value of ['', ' ', 'x'.repeat(161)]) {
    const form = config();
    form.conditions[0].value = value;
    expect(() => generateCodeRule(form)).toThrow();
  }
  expect(ruleOperators('sequence')).not.toContain('contains');
  expect(ruleOperators('name')).not.toContain('gt');
});

test('native Trace templates: all 63 preset combinations pass and retain evidence', () => {
  const types = [
    'skill_routing',
    'required_tool',
    'forbidden_tool',
    'tool_arguments',
    'final_state',
    'final_output',
  ];
  const data = exampleTraceData(true);
  data.final_output = data.final_state = { status: 'pending_review' };
  data.spans = [
    {
      span_id: '1'.repeat(16),
      operation_type: 'routing',
      sequence: 0,
      attributes: { selected_skill: 'loan_approval' },
    },
    {
      span_id: '2'.repeat(16),
      operation_type: 'tool',
      name: 'request_human_review',
      sequence: 1,
      attributes: { human_review: true },
    },
  ];
  for (let mask = 1; mask < 64; mask++) {
    const source = traceBuiltinRuleCode(types.filter((_, i) => mask & (1 << i)));
    expect(source).toContain('def exec_evaluation(trace):');
    expect(source).not.toContain('evaluate_target_output_fields');
    const response = spawnSync(
      process.env.AGENTGATE_RULE_TEST_PYTHON || 'python3',
      ['-I', '-S', runtime],
      {
        input: JSON.stringify({ source, data }),
        encoding: 'utf8',
        timeout: 5000,
      },
    );
    expect(response.status, response.stderr).toBe(0);
    const output = JSON.parse(response.stdout);
    expect(output.error).toBeUndefined();
    expect(output.result.score).toBe(1);
    expect(
      (output.result.span_ids ?? []).every((id: string) =>
        data.spans.some((s) => s.span_id === id),
      ),
    ).toBe(true);
  }
});
