import { expect, test } from '@playwright/test';
import { reactive } from 'vue';
import {
  copyEvaluatorDefinition,
  emptyLLMGroup,
  equalLLMWeights,
  llmGroupError,
  llmEvaluatorCardContent,
  llmGroupPayload,
  llmGroupTemplates,
  newLLMChild,
  newLLMGroupFromEvaluator,
  newLLMGroupFromTemplate,
  readLLMGroup,
  type LLMGroupDetail,
} from '../src/views/evaluation/utils/evaluator-group';
import {
  concisenessPrompt,
  evaluatorTemplates,
  promptEvaluatorDefinition,
} from '../src/views/evaluation/utils/evaluator-templates';

test('the comprehensive template creates four independent children with its configured weights', () => {
  const group = newLLMGroupFromTemplate('answer-quality', 'create-one');
  expect(group.name).toBe('回答质量综合评估');
  expect(group.threshold).toBe(0.8);
  expect(group.children.map((child) => child.name)).toEqual([
    '简洁性',
    '相关性',
    '准确性',
    '合理性',
  ]);
  expect(group.children.map((child) => child.templateId)).toEqual([
    'conciseness',
    'relevance',
    'accuracy',
    'reasonableness',
  ]);
  expect(group.children.map((child) => child.weight)).toEqual([10, 30, 40, 20]);
  expect(new Set(group.children.map((child) => child.key)).size).toBe(4);
  expect(group.children.every((child) => !child.id && child.modelKey === '')).toBe(true);
  expect(group.children[0].instruction).toBe(concisenessPrompt);
  group.children.forEach((child, index) => {
    child.modelKey = JSON.stringify({ provider_id: 'official', model_id: 'judge-' + index });
  });
  const payload = llmGroupPayload(group, null);
  expect(payload.children.map((child) => child.weight)).toEqual([0.1, 0.3, 0.4, 0.2]);
  expect(payload.children.map((child) => child.definition.config.model)).toEqual([
    { provider_id: 'official', model_id: 'judge-0' },
    { provider_id: 'official', model_id: 'judge-1' },
    { provider_id: 'official', model_id: 'judge-2' },
    { provider_id: 'official', model_id: 'judge-3' },
  ]);
});

test('customizing, removing and adding template children leaves future applications unchanged', () => {
  const templatesBefore = JSON.stringify({ llmGroupTemplates, evaluatorTemplates });
  const first = newLLMGroupFromTemplate('answer-quality', 'first');
  first.name = '已调整综合评估器';
  first.children[0].instruction = '自定义简洁性 {{input}} {{output}}';
  first.children.splice(1, 1);
  const custom = newLLMChild('custom-child', null, 30);
  custom.name = '自定义评分';
  custom.instruction = '评价 {{input}} {{output}}';
  first.children.push(custom);
  first.children.forEach((child) => {
    child.modelKey = JSON.stringify({ provider_id: 'official', model_id: 'judge' });
  });
  expect(llmGroupError(first)).toBe('');
  expect(llmGroupPayload(first, null).children.map((child) => child.name)).toEqual([
    '简洁性',
    '准确性',
    '合理性',
    '自定义评分',
  ]);
  const second = newLLMGroupFromTemplate('answer-quality', 'second');
  expect(second.name).toBe('回答质量综合评估');
  expect(second.children.map((child) => child.name)).toEqual([
    '简洁性',
    '相关性',
    '准确性',
    '合理性',
  ]);
  expect(second.children[0].instruction).toBe(concisenessPrompt);
  expect(second.children.map((child) => child.weight)).toEqual([10, 30, 40, 20]);
  expect(
    second.children.some((child) => first.children.some((item) => item.key === child.key)),
  ).toBe(false);
  expect(JSON.stringify({ llmGroupTemplates, evaluatorTemplates })).toBe(templatesBefore);
});

function validGroup() {
  const group = emptyLLMGroup();
  group.name = '问答质量';
  group.description = '三项独立模型评估';
  group.children = ['relevance', 'accuracy', 'reasonableness'].map((id, index) => {
    const child = newLLMChild('key-' + index, id, [40, 40, 20][index]);
    child.modelKey = JSON.stringify({ provider_id: 'official', model_id: 'judge-' + index });
    return child;
  });
  return group;
}

function savedGroup(): LLMGroupDetail {
  const group = validGroup();
  return {
    evaluator: {
      id: 'parent',
      name: '最新名称',
      description: '最新备注',
      enabled: true,
      source: 'user',
    },
    definition: {
      kind: 'llm_group',
      dimension: 'answer',
      metric: 'answer_quality',
      severity: 'standard',
      implementation_id: 'llm_group',
      implementation_version: '1',
      version: '2',
      name: '历史名称',
      config: { pass_threshold: 0.82, description: '历史备注' },
      combination: 'weighted_score',
      children: [],
    },
    latest_version: '3',
    has_draft: false,
    viewing_draft: false,
    children: group.children.map((child, index) => ({
      evaluator: {
        id: 'child-' + index,
        name: '改后的名称',
        description: '改后的描述',
        source: 'user',
        enabled: false,
      },
      definition: {
        ...promptEvaluatorDefinition(child),
        name: child.name,
        version: String(index + 1),
        config: { ...promptEvaluatorDefinition(child).config, max_input_chars: 9000 },
      },
      description: child.description,
      template_id: child.templateId,
      weight: child.weight / 100,
    })),
  };
}

test('custom group cards display the stored child names and percentage weights', () => {
  const source = savedGroup();
  const before = structuredClone(source);
  expect(llmEvaluatorCardContent(source)).toEqual({
    name: '历史名称',
    description: '历史备注',
    itemLabel: '子评估器',
    children: [
      { id: 'child-0', name: '相关性', weight: 40 },
      { id: 'child-1', name: '准确性', weight: 40 },
      { id: 'child-2', name: '合理性', weight: 20 },
    ],
  });
  expect(source).toEqual(before);
});

test('single evaluator cards display their actual scoring dimensions and prefer saved drafts', () => {
  const child = savedGroup().children[0];
  const single = {
    evaluator: child.evaluator,
    latest: child.definition,
    draft: null,
  };
  expect(llmEvaluatorCardContent(single)).toMatchObject({
    itemLabel: '子评估器',
    children: [{ id: child.evaluator.id, name: child.evaluator.name, weight: 100 }],
  });
  const dimensions = [
    { id: 'accuracy', name: '准确性', prompt: '核对准确性', description: '', weight: 70 },
    { id: 'relevance', name: '相关性', prompt: '核对相关性', description: '', weight: 30 },
  ];
  expect(
    llmEvaluatorCardContent({
      ...single,
      draft: {
        ...child.definition,
        implementation_version: '2',
        config: { ...child.definition.config, dimensions },
      },
    }).children,
  ).toEqual([
    { id: 'accuracy', name: '准确性', weight: 70 },
    { id: 'relevance', name: '相关性', weight: 30 },
  ]);
  expect(() => llmEvaluatorCardContent({ ...single, latest: null })).toThrow(
    '此评估器暂无可读取的配置',
  );
});

test('copying an evaluator definition keeps execution fields and isolates nested values', () => {
  const source = {
    ...savedGroup().children[0].definition,
    id: 'source-draft',
    based_on_version: '2',
    created_at: '2026-10-16T08:00:00Z',
    updated_at: '2026-10-16T09:00:00Z',
    content_sha256: 'source-hash',
    config: {
      model: { provider_id: 'official', model_id: 'source-model' },
      rubric: { business: '保留原始标准' },
      options: [{ label: '原始选项' }],
    },
    children: [{ evaluator_id: 'dependency', evaluator_version: '2', weight: 1 }],
  };
  const before = structuredClone(source);
  const copied = copyEvaluatorDefinition(reactive(source));
  expect(copied).toMatchObject({
    kind: source.kind,
    dimension: source.dimension,
    metric: source.metric,
    severity: source.severity,
    implementation_id: source.implementation_id,
    implementation_version: source.implementation_version,
    config: source.config,
    children: source.children,
    combination: source.combination,
  });
  for (const field of [
    'id',
    'name',
    'version',
    'based_on_version',
    'created_at',
    'updated_at',
    'content_sha256',
  ]) {
    expect(copied).not.toHaveProperty(field);
  }
  (copied.config.model as { model_id: string }).model_id = 'copied-model';
  (copied.config.rubric as Record<string, string>).business = '副本标准';
  (copied.config.options as { label: string }[])[0].label = '副本选项';
  copied.children[0].evaluator_version = '3';
  copied.children.splice(0, 1);
  expect(source).toEqual(before);
});

for (const state of ['draft', 'published'] as const) {
  test(`copying a ${state} group preserves configuration without source identities or revisions`, () => {
    const source = savedGroup();
    source.viewing_draft = state === 'draft';
    source.has_draft = source.viewing_draft;
    source.definition.id = state === 'draft' ? 'parent-draft' : 'parent';
    source.definition.updated_at = '2026-10-16T08:00:00Z';
    if (source.viewing_draft) delete source.definition.version;
    source.children.forEach((child, index) => {
      child.definition.id = `source-child-definition-${index}`;
      child.definition.created_at = '2026-10-15T08:00:00Z';
      child.definition.updated_at = '2026-10-16T08:00:00Z';
      child.definition.content_sha256 = `source-child-hash-${index}`;
      child.definition.config = {
        ...child.definition.config,
        model: {
          provider_id: 'official',
          model_id: `judge-${index}`,
          credential_ref: 'env:TEST_JUDGE_REFERENCE',
        },
        user_prompt: '输入 {{input}}，回答 {{output}}',
        rubric: { business: `业务标准 ${index}` },
        input_selection: 'full_trajectory',
        pass_threshold: 0.74,
        min_confidence: 0.6,
        timeout_seconds: 75,
        max_output_tokens: 2200,
        temperature: 0.2,
        render_template: false,
      };
    });
    const before = structuredClone(source);
    const copied = newLLMGroupFromEvaluator(reactive(source), 'independent');
    expect(copied).toMatchObject({
      id: '',
      name: '历史名称（副本）',
      description: '历史备注',
      threshold: 0.82,
    });
    expect(copied.children.map((child) => child.id)).toEqual(['', '', '']);
    expect(new Set(copied.children.map((child) => child.key)).size).toBe(3);
    expect(copied.children.map((child) => child.name)).toEqual(['相关性', '准确性', '合理性']);
    expect(copied.children.map((child) => child.templateId)).toEqual([
      'relevance',
      'accuracy',
      'reasonableness',
    ]);
    expect(copied.children.map((child) => child.weight)).toEqual([40, 40, 20]);
    const payload = llmGroupPayload(copied, null);
    expect(payload.children.map((child) => child.weight)).toEqual([0.4, 0.4, 0.2]);
    for (const field of [
      'id',
      'based_on_version',
      'expected_draft_id',
      'expected_draft_updated_at',
    ]) {
      expect(payload).not.toHaveProperty(field);
    }
    for (const [index, child] of copied.children.entries()) {
      const original = source.children[index];
      expect(child.key).not.toBe(original.evaluator.id);
      expect(child.description).toBe(original.description);
      expect(JSON.parse(child.modelKey)).toEqual(original.definition.config.model);
      expect(child.instruction).toBe(original.definition.config.instruction);
      expect(child.userPrompt).toBe(original.definition.config.user_prompt);
      expect(child.threshold).toBe(0.74);
      expect(child.original?.config).toEqual(original.definition.config);
      expect(payload.children[index]).not.toHaveProperty('id');
      for (const field of ['id', 'name', 'version', 'content_sha256', 'created_at', 'updated_at']) {
        expect(child.original).not.toHaveProperty(field);
        expect(payload.children[index].definition).not.toHaveProperty(field);
      }
      expect(payload.children[index].definition.config).toEqual({
        ...original.definition.config,
        render_template: true,
      });
    }
    expect(source).toEqual(before);
  });
}

test('editing and removing copied group children leaves the source and another copy unchanged', () => {
  const source = savedGroup();
  source.definition.name = '长'.repeat(50);
  source.children[0].definition.config.rubric = { business: '原始标准' };
  const before = structuredClone(source);
  const copied = newLLMGroupFromEvaluator(source, 'first');
  const other = newLLMGroupFromEvaluator(source, 'second');
  const otherBefore = structuredClone(other);
  expect(copied.name).toBe('长'.repeat(46) + '（副本）');
  expect(copied.name).toHaveLength(50);
  expect(
    copied.children.some((child) => other.children.some((item) => item.key === child.key)),
  ).toBe(false);
  copied.name = '副本名称';
  copied.description = '副本备注';
  copied.threshold = 0.7;
  copied.children[0].name = '副本子项';
  copied.children[0].instruction = '副本提示词 {{input}} {{output}}';
  copied.children[0].modelKey = JSON.stringify({ provider_id: 'official', model_id: 'new-model' });
  (copied.children[0].original!.config.rubric as Record<string, string>).business = '副本标准';
  copied.children.splice(1, 1);
  copied.children[0].weight = 80;
  const payload = llmGroupPayload(copied, null);
  expect(payload.children).toHaveLength(2);
  expect(payload.children.map((child) => child.weight)).toEqual([0.8, 0.2]);
  expect(payload.children[0].definition.config).toMatchObject({
    instruction: '副本提示词 {{input}} {{output}}',
    model: { provider_id: 'official', model_id: 'new-model' },
    rubric: { business: '副本标准' },
  });
  expect(source).toEqual(before);
  expect(other).toEqual(otherBefore);
});

test('group payload owns complete independent child definitions and normalizes percent weights', () => {
  const group = validGroup();
  group.children[1].userPrompt = '参考输入：{{input}}，回答：{{output}}';
  const payload = llmGroupPayload(group, null);
  expect(payload).toMatchObject({
    name: '问答质量',
    description: '三项独立模型评估',
    pass_threshold: 0.8,
  });
  expect(payload.children.map((child) => child.weight)).toEqual([0.4, 0.4, 0.2]);
  expect(payload.children.map((child) => child.definition.config.model)).toEqual([
    { provider_id: 'official', model_id: 'judge-0' },
    { provider_id: 'official', model_id: 'judge-1' },
    { provider_id: 'official', model_id: 'judge-2' },
  ]);
  expect(payload.children[1].definition.config.user_prompt).toContain('{{input}}');
  expect(payload.children[0]).not.toHaveProperty('key');
  expect(payload.children[0]).not.toHaveProperty('id');
  expect(payload.children[0]).not.toHaveProperty('original');
  expect(payload).not.toHaveProperty('expected_draft_id');
});

test('reading a historical group uses pinned child definitions and versioned metadata', () => {
  const source = savedGroup(),
    before = structuredClone(source);
  const form = readLLMGroup(source);
  expect(form.name).toBe('历史名称');
  expect(form.description).toBe('历史备注');
  expect(form.children.map((child) => child.name)).toEqual(['相关性', '准确性', '合理性']);
  expect(form.children.map((child) => child.weight)).toEqual([40, 40, 20]);
  form.children[0].instruction = '修订 {{input}} {{output}}';
  const payload = llmGroupPayload(form, source);
  expect(payload.based_on_version).toBe('2');
  expect(payload.expected_draft_id).toBeNull();
  expect(payload.expected_draft_updated_at).toBeNull();
  expect(payload.children[0].definition.config.max_input_chars).toBe(9000);
  expect(payload.children[0].definition).not.toHaveProperty('version');
  expect(payload.children[0].id).toBe('child-0');
  expect(source).toEqual(before);
});

test('editing current draft passes concurrency identity and supports Vue-reactive responses', () => {
  const source = reactive(savedGroup());
  source.viewing_draft = true;
  source.has_draft = true;
  source.definition.id = 'draft-id';
  source.definition.updated_at = '2026-10-16T08:00:00Z';
  delete source.definition.version;
  const form = readLLMGroup(source);
  const payload = llmGroupPayload(form, source);
  expect(payload.expected_draft_id).toBe('draft-id');
  expect(payload.expected_draft_updated_at).toBe('2026-10-16T08:00:00Z');
  expect(payload.based_on_version).toBeNull();
});

test('group validation rejects missing fields, invalid models, duplicate names and invalid weights', () => {
  expect(llmGroupError(validGroup())).toBe('');
  const mutations: ((group: ReturnType<typeof validGroup>) => void)[] = [
    (group) => {
      group.name = '';
    },
    (group) => {
      group.description = '字'.repeat(201);
    },
    (group) => {
      group.threshold = NaN;
    },
    (group) => {
      group.children = [];
    },
    (group) => {
      group.children[0].name = group.children[1].name;
    },
    (group) => {
      group.children[0].modelKey = '';
    },
    (group) => {
      group.children[1].instruction = ' ';
    },
    (group) => {
      group.children[2].userPrompt = '{{unsupported}}';
    },
    (group) => {
      group.children[0].weight = 0;
    },
    (group) => {
      group.children[0].weight = 39.999;
    },
    (group) => {
      group.children[0].id = 'same';
      group.children[1].id = 'same';
    },
  ];
  for (const mutate of mutations) {
    const group = validGroup();
    mutate(group);
    expect(llmGroupError(group)).not.toBe('');
    expect(() => llmGroupPayload(group, null)).toThrow();
  }
});

test('equal weights sum to exactly 100 for every supported child count', () => {
  expect(equalLLMWeights(3)).toEqual([33.34, 33.33, 33.33]);
  expect(equalLLMWeights(0)).toEqual([]);
  const group = validGroup();
  group.children.forEach((child, index) => {
    child.weight = equalLLMWeights(3)[index];
  });
  expect(llmGroupPayload(group, null).children.map((child) => child.weight)).toEqual([
    0.3334, 0.3333, 0.3333,
  ]);
  for (let count = 1; count <= 32; count++) {
    const weights = equalLLMWeights(count);
    expect(weights).toHaveLength(count);
    expect(weights.reduce((sum, weight) => sum + Math.round(weight * 100), 0)).toBe(10000);
    expect(weights.every((weight) => weight > 0)).toBe(true);
  }
});
