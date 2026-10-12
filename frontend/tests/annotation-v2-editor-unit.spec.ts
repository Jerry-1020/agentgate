import { test, expect } from '@playwright/test';
import {
  annotationV2Status,
  normalizeObjectAnnotation,
  originalExpectedAnswer,
} from '../src/views/evaluation/utils/annotation-v2-editor';
import type { AnnotationTask, ObjectAnnotation } from '../src/stores/modules/review';
import type { CaseTurn } from '../src/views/datasets/types';
const group = { enabled: true, criteria: [{ key: 'quality', text: '质量' }], tags: [] };
const task = (): AnnotationTask => ({
  id: 'task',
  name: '模板',
  description: '',
  app: { source_id: 'x', target_type: 'agent', external_target_id: 'a', name: 'A' },
  template: {
    id: 't',
    name: 'T',
    description: '',
    min: 0,
    max: 100,
    message: [],
    tools: [],
    messageTags: [],
    toolTags: [],
    v2: {
      dataset: structuredClone(group),
      evaluator: { ...group, enabled: false },
      agent: structuredClone(group),
    },
  },
  annotations: {},
});
const review = (score: number | null): ObjectAnnotation => ({
  scores: { quality: score },
  tags: [],
  note: '',
});
test('v2 completion requires every enabled object in every turn and keeps zero valid', () => {
  const t = task();
  expect(annotationV2Status(t, 'r/c', ['1', '2'])).toBe('待标注');
  t.v2Annotations = { 'r/c/1': { dataset: review(0), agent: review(100) } };
  expect(annotationV2Status(t, 'r/c', ['1', '2'])).toBe('标注中');
  t.v2Annotations['r/c/2'] = { dataset: review(50), agent: review(60) };
  expect(annotationV2Status(t, 'r/c', ['1', '2'])).toBe('已标注');
  expect(annotationV2Status(t, 'other/c', ['1'])).toBe('待标注');
  t.template.v2!.evaluator.enabled = true;
  expect(annotationV2Status(t, 'r/c', ['1', '2'])).toBe('标注中');
});
test('empty input saves as null, invalid scores fail and normalization does not change the source', () => {
  const draft = {
    ...review(0),
    scores: { quality: '', stale: 100 },
    expected: '人工答案',
  } as unknown as ObjectAnnotation;
  const before = structuredClone(draft);
  expect(normalizeObjectAnnotation(draft, ['quality'], 0, 100)).toEqual({
    ...draft,
    scores: { quality: null },
  });
  expect(draft).toEqual(before);
  for (const value of [-1, 101, NaN, Infinity])
    expect(() => normalizeObjectAnnotation(review(value), ['quality'], 0, 100)).toThrow('0—100');
});
test('original answer uses source expectations and labels patterns without inventing an answer', () => {
  expect(originalExpectedAnswer()).toBe('未配置');
  const source = {
    expectations: [
      {
        id: 'a',
        kind: 'output',
        path: 'output',
        name: null,
        condition: { kind: 'equals', expected: '原始答案' },
      },
    ],
  } as CaseTurn;
  expect(originalExpectedAnswer(source)).toBe('原始答案');
  source.expectations[0].condition = { kind: 'matches_pattern', pattern: 'hello.*' };
  expect(originalExpectedAnswer(source)).toBe('匹配规则：hello.*');
});

test('evaluator reviews keep independent scores and prompt edits through normalization', () => {
  const value = {
    ...review(null),
    evaluators: {
      rule: { ...review(0) },
      llm: { ...review(99), optimizedPrompt: '改进后的提示词' },
    },
  };
  const normalized = normalizeObjectAnnotation(value, ['quality'], 0, 100);
  expect(normalized.evaluators?.llm.optimizedPrompt).toBe('改进后的提示词');
  expect(normalized.evaluators?.rule.scores.quality).toBe(0);
  value.evaluators.llm.scores.quality = 101;
  expect(() => normalizeObjectAnnotation(value, ['quality'], 0, 100)).toThrow();
});
test('evaluator completion requires each configured evaluator', () => {
  const t = task();
  t.template.v2!.dataset.enabled = false;
  t.template.v2!.agent!.enabled = false;
  t.template.v2!.evaluator.enabled = true;
  t.v2Annotations = {
    'r/c/1': { evaluator: { ...review(null), evaluators: { rule: review(0) } } },
  };
  expect(annotationV2Status(t, 'r/c', ['1'], ['rule', 'llm'])).toBe('标注中');
  t.v2Annotations['r/c/1'].evaluator!.evaluators!.llm = { ...review(100), optimizedPrompt: 'new' };
  expect(annotationV2Status(t, 'r/c', ['1'], ['rule', 'llm'])).toBe('已标注');
});

test('removed agent annotation does not affect v2 completion', () => {
  const t = task();
  t.v2Annotations = { 'r/c/1': { dataset: review(100) } };
  expect(annotationV2Status(t, 'r/c', ['1'])).toBe('已标注');
  t.template.v2!.dataset.enabled = false;
  expect(annotationV2Status(t, 'r/c', ['1'])).toBe('待标注');
});

test('v2 feedback updates human expected output, preserves other checks and stays idempotent', async () => {
  const { annotatedV2Case, hasV2Expected } = await import(
    '../src/views/evaluation/utils/annotation-v2-feedback'
  );
  const t = task();
  t.v2Annotations = { 'r/c/1': { dataset: { ...review(90), expected: '人工修订答案' } } };
  const source = {
    id: 'c',
    name: 'sample',
    turns: [
      {
        id: '1',
        input: { txt: 'question' },
        notes: '原备注',
        expectations: [
          {
            id: 'o',
            kind: 'output',
            path: 'output',
            name: null,
            condition: { kind: 'matches_pattern', pattern: '.*' },
          },
          { id: 'tool', kind: 'tool_call', name: null, tool: 'lookup', mode: 'required' },
        ],
      },
    ],
    category: 'positive',
    difficulty: 'medium',
    tags: [],
    initial_state: {},
    notes: '',
  } as import('../src/views/evaluation/utils/annotation-feedback').RawCase;
  const trace = {
    turn_outcomes: {
      '1': { input: { txt: 'question' }, output: { output: '真实回答' }, state: {} },
    },
    final_output: { output: '真实回答' },
  } as import('../src/api/client').Trace;
  const before = structuredClone(source);
  const updated = annotatedV2Case(source, trace, t, 'r/c');
  expect(source).toEqual(before);
  expect(updated.turns[0].expectations).toContainEqual(source.turns[0].expectations[1]);
  expect(updated.turns[0].expectations.find((e) => e.kind === 'output')?.condition).toEqual({
    kind: 'equals',
    expected: '人工修订答案',
  });
  expect(annotatedV2Case(updated, trace, t, 'r/c')).toEqual(updated);
  expect(hasV2Expected(t, 'r/c', ['1'])).toBe(true);
  t.v2Annotations['r/c/1'].dataset!.expected = '';
  expect(hasV2Expected(t, 'r/c', ['1'])).toBe(false);
  expect(annotatedV2Case(source, trace, t, 'r/c').turns[0].expectations).toEqual(
    source.turns[0].expectations,
  );
  t.v2Annotations['r/c/1'].dataset!.expected = '新的回答';
  source.turns[0].expectations.push({
    id: 'other',
    kind: 'output',
    path: 'other',
    name: null,
    condition: { kind: 'equals', expected: 'other' },
  });
  expect(() => annotatedV2Case(source, trace, t, 'r/c')).toThrow('多个输出路径');
});
