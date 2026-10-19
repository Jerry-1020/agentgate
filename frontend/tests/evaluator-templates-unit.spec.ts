import { test, expect } from '@playwright/test';
import type { Definition, EvaluatorSummary } from '../src/api/evaluations';
import {
  concisenessPrompt,
  emptyPromptEvaluator,
  evaluatorTemplates,
  isPromptEvaluator,
  promptEvaluatorDefinition,
  promptEvaluatorError,
  promptModelOptions,
  readPromptEvaluator,
} from '../src/views/evaluation/utils/evaluator-templates';

const model = { provider_id: 'direct-provider', model_id: 'test-judge' };
const evaluator = { id: 'judge', name: '简洁性', description: '说明' } as EvaluatorSummary;
function validForm() {
  return {
    ...emptyPromptEvaluator(),
    name: '简洁性',
    description: '评估回答简洁性',
    modelKey: JSON.stringify(model),
    instruction: concisenessPrompt,
  };
}

test('conciseness template preserves the requested criteria and input/output placeholders', () => {
  expect(evaluatorTemplates.find((item) => item.id === 'conciseness')).toMatchObject({
    name: '简洁性',
    instruction: concisenessPrompt,
  });
  expect(concisenessPrompt).toContain('仅包含被请求的确切信息。');
  expect(concisenessPrompt).toContain('除非明确要求，否则不包含解释内容。');
  expect(concisenessPrompt).toContain('像“希望这有帮助”或“如果您还需要其他信息请告诉我”');
  expect(concisenessPrompt).toContain('<输入>\n{{input}}\n</输入>');
  expect(concisenessPrompt).toContain('<输出>\n{{output}}\n</输出>');
  expect(concisenessPrompt).not.toContain('&#x20;');
  expect(concisenessPrompt).not.toContain('\\');
});

test('preset sub-evaluators have distinct criteria and only supported prompt variables', () => {
  expect(evaluatorTemplates.map((item) => item.name)).toEqual([
    '简洁性',
    '相关性',
    '准确性',
    '合理性',
  ]);
  expect(new Set(evaluatorTemplates.map((item) => item.instruction)).size).toBe(4);
  for (const template of evaluatorTemplates) {
    expect(
      promptEvaluatorError({
        ...validForm(),
        name: template.name,
        instruction: template.instruction,
      }),
    ).toBe('');
    expect(template.instruction).toContain('{{input}}');
    expect(template.instruction).toContain('{{output}}');
  }
});

test('new prompt evaluator persists only the execution contract and leaves model selection explicit', () => {
  expect(emptyPromptEvaluator().modelKey).toBe('');
  const draft = promptEvaluatorDefinition(validForm());
  expect(draft).toEqual({
    kind: 'llm_judge',
    dimension: 'answer',
    metric: 'answer_quality',
    severity: 'standard',
    implementation_id: 'answer_quality',
    implementation_version: '1',
    config: {
      render_template: true,
      instruction: concisenessPrompt,
      rubric: { overall: '按照提示词中的评分标准评估。' },
      model,
      input_selection: 'final_output',
      pass_threshold: 0.8,
      min_confidence: 0,
      timeout_seconds: 180,
      max_output_tokens: 6000,
    },
    children: [],
    combination: null,
  });
  expect(draft.config).not.toHaveProperty('user_prompt');
  expect(draft).not.toHaveProperty('version');
});

test('saved prompt drafts roundtrip System and optional User without changing historical versions', () => {
  const original: Definition = {
    ...promptEvaluatorDefinition(validForm()),
    version: '3',
    content_sha256: 'published',
  };
  original.config.user_prompt = '输入：{{ input }}\n回答：{{output}}';
  original.config.temperature = 0.2;
  original.config.rubric = { business: '历史业务标准' };
  original.config.render_template = false;
  const snapshot = structuredClone(original);
  const form = readPromptEvaluator(evaluator, original);
  expect(form.userPrompt).toBe(original.config.user_prompt);
  const updated = promptEvaluatorDefinition(form, original);
  expect(updated.config).toEqual({ ...original.config, render_template: true });
  expect(updated).not.toHaveProperty('content_sha256');
  form.userPrompt = null;
  expect(promptEvaluatorDefinition(form, original).config).not.toHaveProperty('user_prompt');
  expect(original).toEqual(snapshot);
  expect(isPromptEvaluator(original)).toBe(true);
  expect(isPromptEvaluator({ ...original, implementation_version: '2' })).toBe(false);
});

test('validation rejects missing required inputs, unsupported variables and invalid thresholds', () => {
  for (const mutate of [
    (form: ReturnType<typeof validForm>) => {
      form.name = ' ';
    },
    (form: ReturnType<typeof validForm>) => {
      form.name = '字'.repeat(51);
    },
    (form: ReturnType<typeof validForm>) => {
      form.description = '字'.repeat(201);
    },
    (form: ReturnType<typeof validForm>) => {
      form.modelKey = '';
    },
    (form: ReturnType<typeof validForm>) => {
      form.modelKey = JSON.stringify({ ...model, model_id: 'sk-secret' });
    },
    (form: ReturnType<typeof validForm>) => {
      form.instruction = ' ';
    },
    (form: ReturnType<typeof validForm>) => {
      form.instruction = '{{reference}}';
    },
    (form: ReturnType<typeof validForm>) => {
      form.userPrompt = '{{unknown}}';
    },
    (form: ReturnType<typeof validForm>) => {
      form.userPrompt = '';
    },
    (form: ReturnType<typeof validForm>) => {
      form.threshold = 1.01;
    },
    (form: ReturnType<typeof validForm>) => {
      form.threshold = NaN;
    },
  ]) {
    const form = validForm();
    mutate(form);
    expect(promptEvaluatorError(form)).not.toBe('');
    expect(() => promptEvaluatorDefinition(form)).toThrow();
  }
  expect(promptEvaluatorError({ ...validForm(), userPrompt: '{{ input }} {{output}}' })).toBe('');
});

test('model options include configured runtime connections and deduplicate existing references', () => {
  const options = promptModelOptions(
    [
      { configured: true, provider_id: model.provider_id, model: model.model_id },
      { configured: true, provider_id: model.provider_id, model: model.model_id },
      { configured: false, provider_id: 'offline', model: 'offline-model' },
      { configured: true, model: 'tested-agent-model' },
    ],
    [
      [JSON.stringify(model), model],
      [
        JSON.stringify({ provider_id: 'second', model_id: 'second-model' }),
        { provider_id: 'second', model_id: 'second-model' },
      ],
    ],
  );
  expect(options).toEqual([
    [JSON.stringify(model), model],
    [
      JSON.stringify({ provider_id: 'second', model_id: 'second-model' }),
      { provider_id: 'second', model_id: 'second-model' },
    ],
  ]);
});

test('default environment references share one option with runtime while other connections stay selectable', () => {
  const defaultRef = { ...model, credential_ref: 'env:AGENTGATE_JUDGE_API_KEY' };
  const customRef = { ...model, credential_ref: 'env:OTHER_JUDGE_KEY' };
  const options = promptModelOptions(
    [{ configured: true, provider_id: model.provider_id, model: model.model_id }],
    [
      [JSON.stringify(defaultRef), defaultRef],
      [JSON.stringify(customRef), customRef],
    ],
  );
  expect(options).toHaveLength(2);
  expect(options.map(([, ref]) => ref)).toEqual([defaultRef, customRef]);
});

test('reopened model selection uses the same key regardless of server object key order', () => {
  const definition = promptEvaluatorDefinition(validForm());
  definition.config.model = { model_id: model.model_id, provider_id: model.provider_id };
  const form = readPromptEvaluator(evaluator, definition);
  expect(form.modelKey).toBe(JSON.stringify(model));
});
