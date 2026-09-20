import type { EvaluationResult } from '../../../api/client';

export const needsAttention = (result: Pick<EvaluationResult, 'outcome'>) =>
  ['fail', 'error', 'review'].includes(result.outcome);

// Compare JSON values without treating absent evidence as an empty value.
export function sameJson(left: unknown, right: unknown): boolean {
  if (left === undefined || right === undefined) return false;
  if (left === right) return true;
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object')
    return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  }
  const a = left as Record<string, unknown>,
    b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(b, key) && sameJson(a[key], b[key]))
  );
}

export function equalsCondition(value: unknown): value is { kind: 'equals'; expected: unknown } {
  return (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    (value as Record<string, unknown>).kind === 'equals' &&
    Object.prototype.hasOwnProperty.call(value, 'expected') &&
    Object.keys(value).every((key) => key === 'kind' || key === 'expected')
  );
}
