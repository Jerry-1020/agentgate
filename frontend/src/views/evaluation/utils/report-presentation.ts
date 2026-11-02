import type { CheckResult, EvaluationResult } from '../../../api/client';
import { chineseEvaluatorText, dimensionNames } from './evaluator-display';
import type { EvaluatorSnapshot } from './task-report';

function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const textValue = (value: unknown) => (typeof value === 'string' ? value : '');
const fraction = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
const criterionName = (name: string) =>
  dimensionNames[name] ?? (name === 'overall' ? '整体评分' : name);

export function llmScoringBasis(result: EvaluationResult, specs: EvaluatorSnapshot[] = []) {
  // Historical results must use the exact evaluator version frozen into this run.
  const spec = specs.find(
    (item) =>
      item.id === result.evaluator_id &&
      item.version === result.evaluator_version &&
      item.kind === result.evaluator_kind,
  );
  const config = spec?.config;
  const usesDefaultThreshold =
    !!config &&
    config.pass_threshold === undefined &&
    ((spec.implementation_id === 'answer_quality' &&
      ['1', '2'].includes(spec.implementation_version ?? '')) ||
      (spec.implementation_id === 'llm_group' && spec.implementation_version === '1'));
  const criteria = Array.isArray(config?.dimensions)
    ? config.dimensions.map((value) => {
        const dimension = objectValue(value);
        return {
          name: textValue(dimension.name) || criterionName(textValue(dimension.id)),
          description: [textValue(dimension.description), textValue(dimension.prompt)]
            .filter(Boolean)
            .join('\n'),
          weight: typeof dimension.weight === 'number' ? dimension.weight : null,
        };
      })
    : Object.entries(objectValue(config?.rubric)).map(([name, value]) => ({
        name: criterionName(name),
        description:
          typeof value === 'string' ? chineseEvaluatorText(value) : JSON.stringify(value, null, 2),
        weight: null,
      }));
  return {
    instruction: chineseEvaluatorText(textValue(config?.instruction ?? config?.description)),
    criteria,
    passThreshold: usesDefaultThreshold ? 0.8 : fraction(config?.pass_threshold),
    usesDefaultThreshold,
    minConfidence: fraction(config?.min_confidence),
    combination:
      spec?.kind === 'llm_group'
        ? ({
            weighted_score: '按子评估器权重汇总得分，具体评分标准见下方子评估器。',
            all: '所有适用的子评估器均通过时通过，具体评分标准见下方子评估器。',
            any: '任一适用的子评估器通过时通过，具体评分标准见下方子评估器。',
          }[spec.combination ?? ''] ?? '')
        : '',
  };
}

export function llmCheckDetails(check: CheckResult) {
  const actual = check.actual_missing ? {} : objectValue(check.actual);
  return {
    confidence: fraction(actual.confidence),
    violations: (Array.isArray(actual.violations) ? actual.violations : []).map((value) => {
      const violation = objectValue(value);
      return {
        criterion: criterionName(textValue(violation.criterion)),
        detail: textValue(violation.detail),
      };
    }),
    dimensions: (Array.isArray(actual.dimensions) ? actual.dimensions : []).map((value) => {
      const dimension = objectValue(value);
      return {
        name: textValue(dimension.name) || criterionName(textValue(dimension.id)),
        score: fraction(dimension.score),
        reason: textValue(dimension.reason),
        review: dimension.review === true,
      };
    }),
  };
}

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
