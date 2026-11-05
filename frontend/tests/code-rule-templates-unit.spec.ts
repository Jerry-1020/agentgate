import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  builtinRuleCode,
  combinedBuiltinRuleCode,
  traceBuiltinRuleCode,
  traceDataForLegacyRule,
  type CodeTraceData,
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
      const data = {
        evaluate_target_output_fields: { actual_output: {}, final_state: {}, spans: [] },
      };
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

// Execute generated production templates in the restricted interpreter.
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

test('native Trace templates: all 63 preset combinations pass and retain evidence', () => {
  const types = [
    'skill_routing',
    'required_tool',
    'forbidden_tool',
    'tool_arguments',
    'final_state',
    'final_output',
  ];
  const data: CodeTraceData = {
    trace_id: 'a'.repeat(32),
    run_id: 'test-run',
    case_id: 'test-case',
    turn_outcomes: {},
    final_output: {},
    final_state: {},
    spans: [],
  };
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

test('legacy rules retain single-turn input and reject ambiguous multi-turn copies', () => {
  const trace: CodeTraceData = {
    trace_id: 'a'.repeat(32),
    run_id: 'test-run',
    case_id: 'test-case',
    turn_outcomes: { first: { input: { text: 'first' } } },
    final_output: { text: 'answer' },
    final_state: {},
    spans: [],
  };
  const result = traceDataForLegacyRule(trace);
  expect(result.evaluate_dataset_fields).toEqual({ input: { text: 'first' }, expectations: [] });
  expect(result.evaluate_target_output_fields.actual_output).toEqual(trace.final_output);
  expect(result.ext.turn_id).toBe('first');
  expect(() =>
    traceDataForLegacyRule({
      ...trace,
      turn_outcomes: { ...trace.turn_outcomes, second: { input: { text: 'second' } } },
    }),
  ).toThrow('不能直接使用多轮完整 Trace');
});
