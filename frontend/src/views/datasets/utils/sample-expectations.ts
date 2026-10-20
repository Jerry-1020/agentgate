import type { Condition } from '../types';

type FieldRule = { id: string; name: string | null; path: string; condition: Condition };

export function expectationFieldsText(rules: readonly FieldRule[], prefix = ''): string {
  if (!rules.length) return '';
  const paths = rules.map((rule) => rule.path);
  const simple =
    rules.every((rule) => rule.condition.kind === 'equals' && rule.path.startsWith(prefix)) &&
    new Set(paths).size === paths.length;
  return JSON.stringify(
    simple
      ? Object.fromEntries(
          rules.map((rule) => [
            rule.path.slice(prefix.length),
            (rule.condition as Extract<Condition, { kind: 'equals' }>).expected,
          ]),
        )
      : rules.map(({ path, condition }) => ({ path, condition })),
    null,
    2,
  );
}

function isCondition(value: unknown): value is Condition {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value);
  switch (item.kind) {
    case 'equals':
      return Object.hasOwn(item, 'expected');
    case 'within_tolerance':
      return number(item.expected) && number(item.epsilon) && (item.epsilon as number) > 0;
    case 'within_range':
      return (
        (item.minimum === null || number(item.minimum)) &&
        (item.maximum === null || number(item.maximum)) &&
        (item.minimum !== null || item.maximum !== null) &&
        (item.minimum === null ||
          item.maximum === null ||
          Number(item.minimum) <= Number(item.maximum))
      );
    case 'matches_pattern':
      return typeof item.pattern === 'string' && Boolean(item.pattern.trim());
    case 'one_of':
      return Array.isArray(item.allowed) && item.allowed.length > 0;
    case 'must_be_missing':
      return true;
    case 'matches_json_schema':
      return (
        Boolean(item.json_schema) &&
        typeof item.json_schema === 'object' &&
        !Array.isArray(item.json_schema)
      );
    default:
      return false;
  }
}

export function expectationFieldsFromText(
  text: string,
  original: readonly FieldRule[],
  createId: () => string,
  prefix = '',
): FieldRule[] {
  if (!text.trim()) return [];
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw Error('请填写有效的 JSON');
  }
  if (!value || typeof value !== 'object') throw Error('请填写字段与期望值组成的 JSON 对象');
  const entries = Array.isArray(value)
    ? value
    : Object.entries(value).map(([path, expected]) => ({
        path: prefix + path,
        condition: { kind: 'equals', expected },
      }));
  const used = new Set<number>();
  return entries.map((entry) => {
    if (
      !entry ||
      typeof entry.path !== 'string' ||
      entry.path.split('.').some((part: string) => !part.trim()) ||
      !isCondition(entry.condition)
    )
      throw Error('规则需包含有效的字段路径和判定条件');
    const previousIndex = original.findIndex(
      (rule, index) =>
        !used.has(index) &&
        rule.path === entry.path &&
        rule.condition.kind === entry.condition.kind,
    );
    const fallback =
      previousIndex < 0
        ? original.findIndex((rule, index) => !used.has(index) && rule.path === entry.path)
        : previousIndex;
    if (fallback >= 0) used.add(fallback);
    return {
      ...(fallback >= 0 ? original[fallback] : { id: createId(), name: null }),
      path: entry.path,
      condition: entry.condition,
    };
  });
}
