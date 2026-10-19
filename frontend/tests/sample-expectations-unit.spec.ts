import { expect, test } from '@playwright/test';
import type { Expectation } from '../src/views/datasets/types';
import {
  expectationFieldsFromText,
  expectationFieldsText,
} from '../src/views/datasets/utils/sample-expectations';

type StateRule = Extract<Expectation, { kind: 'state' }>;
type ToolRule = Extract<Expectation, { kind: 'tool_argument' }>;
const state: StateRule = {
  id: 'state-one', name: '保留检查名称', kind: 'state', path: 'status',
  condition: { kind: 'equals', expected: 'done' },
};
const tool: ToolRule = {
  id: 'tool-one', name: '保留工具检查', kind: 'tool_argument', tool: 'lookup',
  path: 'arguments.limit', occurrence: 'any', condition: { kind: 'equals', expected: 10 },
};

test('state maps preserve metadata and support nested expected JSON values', () => {
  expect(JSON.parse(expectationFieldsText([state]))).toEqual({ status: 'done' });
  const result = expectationFieldsFromText(
    '{"status":"pending","user.profile":{"tier":"gold"}}', [state], () => 'new-rule',
  );
  expect(result[0]).toEqual({ ...state, condition: { kind: 'equals', expected: 'pending' } });
  expect(result[1]).toEqual({
    id: 'new-rule', name: null, path: 'user.profile',
    condition: { kind: 'equals', expected: { tier: 'gold' } },
  });
});

test('tool maps resolve fields under arguments and retain occurrence and identity', () => {
  expect(JSON.parse(expectationFieldsText([tool], 'arguments.'))).toEqual({ limit: 10 });
  const result = expectationFieldsFromText(
    '{"limit":20,"filter":{"status":"active"}}', [tool], () => 'new-rule', 'arguments.',
  );
  expect(result[0]).toEqual({ ...tool, condition: { kind: 'equals', expected: 20 } });
  expect(result[1].path).toBe('arguments.filter');
  expect(result[1].condition).toEqual({ kind: 'equals', expected: { status: 'active' } });
});

test('non-equality, duplicate paths, and nonstandard tool paths roundtrip without conversion', () => {
  const rules: StateRule[] = [
    state,
    { ...state, id: 'state-two', name: '范围检查', condition: { kind: 'within_range', minimum: 1, maximum: 10 } },
    { ...state, id: 'state-three', name: '另一个等值检查' },
  ];
  const text = expectationFieldsText(rules);
  expect(Array.isArray(JSON.parse(text))).toBe(true);
  expect(expectationFieldsFromText(text, rules, () => 'unused')).toEqual(rules);
  const legacyPath = { ...tool, path: 'status' };
  const toolText = expectationFieldsText([legacyPath], 'arguments.');
  expect(expectationFieldsFromText(toolText, [legacyPath], () => 'unused', 'arguments.')).toEqual([legacyPath]);
});

test('blank clears rules while invalid JSON, paths, and conditions reject saving', () => {
  expect(expectationFieldsFromText('  ', [state], () => 'unused')).toEqual([]);
  expect(expectationFieldsFromText('{}', [state], () => 'unused')).toEqual([]);
  for (const text of ['{', 'null', 'true', '"done"', '{"a..b":1}', '[{"path":"status"}]'])
    expect(() => expectationFieldsFromText(text, [state], () => 'unused')).toThrow();
  expect(() => expectationFieldsFromText('{"":10}', [tool], () => 'unused', 'arguments.')).toThrow();
  expect(() => expectationFieldsFromText('[{"path":"score","condition":{"kind":"within_range","minimum":10,"maximum":1}}]', [], () => 'new')).toThrow();
});
