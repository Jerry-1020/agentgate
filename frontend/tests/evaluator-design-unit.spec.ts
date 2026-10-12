import { test, expect } from '@playwright/test';
import type { Definition, EvaluatorSummary } from '../src/api/evaluations';
import {
  evaluatorDesignError,
  evaluatorDraftDefinition,
  readEvaluatorDesign,
  weightError,
} from '../src/views/evaluation/utils/evaluator-design';

const evaluator = { id: 'judge', name: '业务评估器', description: '说明' } as EvaluatorSummary;
function definition(): Definition {
  return {
    kind: 'llm_judge',
    dimension: 'answer',
    metric: 'business_quality',
    severity: 'blocking',
    implementation_id: 'answer_quality',
    implementation_version: '2',
    version: '12',
    content_sha256: 'hash',
    config: {
      model: { provider_id: 'judge', model_id: 'model', credential_ref: 'env:JUDGE_KEY' },
      dimensions: [
        {
          id: 'correctness',
          name: '正确性',
          description: '核对事实',
          prompt: ' 按事实评分\n保留换行 ',
          weight: 33.33,
        },
        { id: 'coverage', name: '完整性', description: '', prompt: '检查完整性', weight: 66.67 },
      ],
      input_selection: 'full_trajectory',
      pass_threshold: 0.83,
      min_confidence: 0.6,
      temperature: 0.2,
      max_input_chars: 9000,
    },
    children: [],
    combination: null,
  };
}

test('server draft roundtrip preserves dimensions, prompts, model references and execution settings', () => {
  const original = definition(),
    before = structuredClone(original);
  const design = readEvaluatorDesign(evaluator, original);
  expect(design.version).toBe('12');
  expect(design.threshold).toBe(83);
  expect(evaluatorDesignError(design)).toBe('');
  const draft = evaluatorDraftDefinition(design, original);
  const { version, content_sha256, ...expected } = original;
  expect(draft).toEqual(expected);
  expect(draft).not.toHaveProperty('version');
  expect(draft).not.toHaveProperty('content_sha256');
  design.dimensions[0].prompt = '新草稿';
  expect(evaluatorDraftDefinition(design, original).config.dimensions[0].prompt).toBe('新草稿');
  expect(original).toEqual(before);
  expect(version).toBe('12');
  expect(content_sha256).toBe('hash');
});

test('new editor config never sends local state or silently claims old weights existed', () => {
  const original = definition();
  original.implementation_version = '1';
  original.config = {
    model: original.config.model,
    instruction: '整体评分提示词',
    rubric: { correctness: '事实正确' },
    pass_threshold: 0.8,
  };
  const design = readEvaluatorDesign(evaluator, original);
  expect(design.dimensions[0].weight).toBeNull();
  expect(design.dimensions[0].prompt).toContain('整体评分提示词');
  expect(design.dimensions[0].prompt).toContain('事实正确');
  design.dimensions[0].weight = 100;
  const draft = evaluatorDraftDefinition(design, null);
  expect(draft.implementation_version).toBe('2');
  expect(Object.keys(draft.config).sort()).toEqual([
    'dimensions',
    'input_selection',
    'model',
    'pass_threshold',
  ]);
});

test('invalid editor configs fail before a save request', () => {
  for (const mutate of [
    (d) => (d.name = ' '),
    (d) => (d.modelKey = '{}'),
    (d) => (d.threshold = 101),
    (d) => (d.dimensions[0].prompt = ''),
    (d) => (d.dimensions[0].id = ' coverage '),
    (d) => (d.dimensions[0].weight = 10),
    (d) => (d.scope = 'unrecognized'),
  ]) {
    const design = readEvaluatorDesign(evaluator, definition());
    mutate(design);
    expect(evaluatorDesignError(design)).not.toBe('');
    expect(() => evaluatorDraftDefinition(design, null)).toThrow();
  }
});

test('decimal weight totals match the backend without accepting near-100 totals', () => {
  for (const weights of [
    [33.333, 66.666],
    [33.333, 66.6671],
    [0.0000001, 99.9999998],
  ])
    expect(weightError(weights.map((weight) => ({ weight })))).not.toBe('');
  for (const weights of [
    [33.33, 66.67],
    [33.333, 66.667],
    [1e-7, 99.9999999],
  ])
    expect(weightError(weights.map((weight) => ({ weight })))).toBe('');
});

test('incomplete server drafts remain editable without being considered publishable', () => {
  const draft = definition();
  delete draft.version;
  delete draft.config.dimensions;
  const design = readEvaluatorDesign(evaluator, draft);
  expect(design.dimensions).toEqual([]);
  expect(evaluatorDesignError(design)).toBe('至少保留一个评估维度。');
  draft.config.dimensions = [null, { id: 'quality' }];
  expect(readEvaluatorDesign(evaluator, draft).dimensions[1]).toEqual({
    id: 'quality',
    name: '',
    description: '',
    prompt: '',
    weight: null,
  });
});
