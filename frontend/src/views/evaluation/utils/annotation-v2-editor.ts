import type { AnnotationTask, ObjectAnnotation } from '../../../stores/modules/review';
import type { CaseTurn } from '../../datasets/types';
import { displayValue } from './task-report';

export const annotationObjects = [
  { key: 'dataset', title: '测评集人工标注' },
  { key: 'evaluator', title: '评估器人工标注' },
] as const;
export function originalExpectedAnswer(turn?: CaseTurn): string {
  const expectations = (turn?.original_expectations ?? turn?.expectations ?? []).filter(
    (e) => e.kind === 'output',
  );
  if (!expectations.length) return '未配置';
  return expectations
    .map((e) => {
      if (e.kind !== 'output') return '';
      const c = e.condition;
      if (c.kind === 'equals') return displayValue(c.expected);
      if (c.kind === 'matches_pattern') return '匹配规则：' + c.pattern;
      return '期望规则：' + displayValue(c);
    })
    .join('\n');
}
export function normalizeObjectAnnotation(
  value: ObjectAnnotation,
  dimensions: string[],
  min: number,
  max: number,
): ObjectAnnotation {
  const scores: ObjectAnnotation['scores'] = {};
  for (const key of dimensions) {
    const score: unknown = value.scores[key];
    if (score === '' || score === null || score === undefined) scores[key] = null;
    else if (typeof score !== 'number' || !Number.isFinite(score) || score < min || score > max)
      throw Error(`分数需在 ${min}—${max} 之间。`);
    else scores[key] = score;
  }
  const evaluators = value.evaluators
    ? Object.fromEntries(
        Object.entries(value.evaluators).map(([id, review]) => [
          id,
          normalizeObjectAnnotation(review, dimensions, min, max),
        ]),
      )
    : undefined;
  return { ...value, scores, tags: [...value.tags], ...(evaluators ? { evaluators } : {}) };
}
export function annotationV2Status(
  task: AnnotationTask,
  prefix: string,
  turnIds: string[],
  evaluatorIds?: string[],
) {
  const groups = annotationObjects.filter((g) => task.template.v2?.[g.key].enabled);
  if (!groups.length || !turnIds.length) return '待标注';
  const complete = turnIds
    .map((id) =>
      groups.every((g) => {
        const value = task.v2Annotations?.[prefix + '/' + id]?.[g.key];
        const criteria = task.template.v2![g.key].criteria;
        const reviews =
          g.key === 'evaluator' && evaluatorIds
            ? evaluatorIds.map((id) => value?.evaluators?.[id])
            : [value];
        return reviews.every(
          (review) =>
            !!review &&
            criteria.length > 0 &&
            criteria.every((d) => {
              const score = review.scores[d.key];
              return (
                typeof score === 'number' &&
                Number.isFinite(score) &&
                score >= task.template.min &&
                score <= task.template.max
              );
            }),
        );
      }),
    )
    .every(Boolean);
  const saved = turnIds.some((id) =>
    groups.some((g) => !!task.v2Annotations?.[prefix + '/' + id]?.[g.key]),
  );
  return complete ? '已标注' : saved ? '标注中' : '待标注';
}
export type TurnObjectDraft = {
  id: string;
  objects: Record<(typeof annotationObjects)[number]['key'], ObjectAnnotation>;
};

export interface EvaluatorEvidence {
  spec: {
    id: string;
    name: string;
    version: string;
    kind: string;
    config: Record<string, unknown>;
  };
  result: import('../../../api/client').EvaluationResult | null;
  evidence: Record<string, unknown>;
  code: { name: string; source: string }[];
  system_prompt: string | null;
  user_prompt: string | null;
  prompt_source: 'recorded' | 'reconstructed' | 'unavailable';
  request_hash_matches: boolean | null;
}
