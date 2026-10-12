import { test, expect } from '@playwright/test';
import { outputEditorValue, outputCondition } from '../src/views/datasets/utils/sample-output';
import type { Condition } from '../src/views/datasets/types';

test('expected output round-trips strings and structured values', () => {
  for (const expected of ['hello', '', 0, false, null, { answer: 'yes' }]) {
    const original: Condition = { kind: 'equals', expected };
    const value = outputEditorValue(original);
    expect(outputCondition(value.text, value.json, original)).toEqual(
      expected === '' ? null : original,
    );
  }
});
test('regex uses the main expected output and rejects invalid patterns', () => {
  const condition: Condition = { kind: 'matches_pattern', pattern: 'old' };
  expect(outputCondition('.*你好.*', false, condition)).toEqual({
    kind: 'matches_pattern',
    pattern: '.*你好.*',
  });
  expect(() => outputCondition('[', false, condition)).toThrow();
  expect(condition.pattern).toBe('old');
});
test('numeric tolerance uses the main expected output while retaining epsilon', () => {
  const condition: Condition = { kind: 'within_tolerance', expected: 1, epsilon: 0.1 };
  expect(outputCondition('0', false, condition)).toEqual({ ...condition, expected: 0 });
  for (const value of ['hello', 'null', 'false', '[]'])
    expect(() => outputCondition(value, true, condition)).toThrow();
});
test('set membership accepts JSON arrays and comma separated values', () => {
  const condition: Condition = { kind: 'one_of', allowed: [] };
  expect(outputCondition('yes，no', false, condition)).toEqual({
    kind: 'one_of',
    allowed: ['yes', 'no'],
  });
  expect(outputCondition('[0,false,"yes"]', true, condition)).toEqual({
    kind: 'one_of',
    allowed: [0, false, 'yes'],
  });
  expect(() => outputCondition('{}', true, condition)).toThrow();
  expect(() => outputCondition('[]', true, condition)).toThrow();
});
test('range and missing-field checks survive an empty expected output', () => {
  const checks: Condition[] = [
    { kind: 'within_range', minimum: 0, maximum: 100 },
    { kind: 'must_be_missing' },
  ];
  for (const check of checks) expect(outputCondition('', false, check)).toEqual(check);
  expect(outputCondition(' ', false, { kind: 'equals', expected: '' })).toBeNull();
});
