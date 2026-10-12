import type { Condition } from '../types';
export function outputEditorValue(condition: Condition): { text: string; json: boolean } {
  let value: unknown;
  switch (condition.kind) {
    case 'equals':
    case 'within_tolerance':
      value = condition.expected;
      break;
    case 'matches_pattern':
      value = condition.pattern;
      break;
    case 'one_of':
      value = condition.allowed;
      break;
    default:
      return { text: '', json: false };
  }
  return {
    text: typeof value === 'string' ? value : JSON.stringify(value),
    json: typeof value !== 'string',
  };
}
export function outputCondition(text: string, json: boolean, current: Condition): Condition | null {
  if (
    current.kind === 'must_be_missing' ||
    current.kind === 'within_range' ||
    current.kind === 'matches_json_schema'
  )
    return { ...current };
  if (!text.trim()) return null;
  if (current.kind === 'matches_pattern') {
    new RegExp(text);
    return { kind: current.kind, pattern: text };
  }
  const value = json ? JSON.parse(text) : text;
  if (current.kind === 'within_tolerance') {
    const expected = Number(value);
    if ((typeof value !== 'number' && typeof value !== 'string') || !Number.isFinite(expected))
      throw Error('数值容差的期望输出必须为数字');
    return { ...current, expected };
  }
  if (current.kind === 'one_of') {
    const allowed = json
      ? value
      : text
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean);
    if (!Array.isArray(allowed) || !allowed.length)
      throw Error('属于集合的期望输出需为非空 JSON 数组或逗号分隔的值');
    return { kind: current.kind, allowed };
  }
  return { kind: 'equals', expected: value };
}
