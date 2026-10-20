import type { Definition, EvaluatorDetail, EvaluatorIdentity } from '../../../api/evaluations';
import { hasDimensionScoring, readEvaluatorDesign, weightError } from './evaluator-design';
import {
  emptyPromptEvaluator,
  evaluatorTemplates,
  promptEvaluatorDefinition,
  promptEvaluatorError,
  readPromptEvaluator,
  type PromptEvaluatorDesign,
} from './evaluator-templates';

export interface GroupDefinition extends Definition {
  id?: string;
  name?: string;
  created_at?: string;
  updated_at?: string;
}
export interface LLMGroupDetail {
  evaluator: EvaluatorIdentity;
  definition: GroupDefinition;
  latest_version: string | null;
  has_draft: boolean;
  viewing_draft: boolean;
  children: {
    evaluator: EvaluatorIdentity;
    definition: GroupDefinition;
    description: string;
    template_id: string | null;
    weight: number;
  }[];
}
export interface LLMChildDesign extends PromptEvaluatorDesign {
  key: string;
  templateId: string | null;
  weight: number;
  original: GroupDefinition | null;
}
export interface LLMGroupDesign {
  id: string;
  name: string;
  description: string;
  threshold: number;
  children: LLMChildDesign[];
}
export function llmEvaluatorCardContent(value: EvaluatorDetail | LLMGroupDetail) {
  if ('definition' in value) {
    const group = readLLMGroup(value);
    return {
      name: group.name,
      description: group.description,
      itemLabel: '子评估器',
      children: group.children.map((child) => ({
        id: child.key,
        name: child.name,
        weight: child.weight,
      })),
    };
  }
  const definition = value.draft ?? value.latest;
  if (!definition) throw new Error('此评估器暂无可读取的配置。');
  return {
    name: value.evaluator.name,
    description: value.evaluator.description,
    itemLabel: '评分维度',
    children: hasDimensionScoring(definition)
      ? readEvaluatorDesign(value.evaluator, definition).dimensions.map((dimension) => ({
          id: dimension.id,
          name: dimension.name,
          weight: dimension.weight,
        }))
      : [{ id: value.evaluator.id, name: value.evaluator.name, weight: 100 }],
  };
}
export const llmGroupTemplates = [
  {
    id: 'answer-quality',
    name: '回答质量综合评估',
    description:
      '从简洁性、相关性、准确性、合理性四个方面综合评估回答质量。每个子评估器独立配置模型、提示词与权重。',
    threshold: 0.8,
    children: [
      { templateId: 'conciseness', weight: 10 },
      { templateId: 'relevance', weight: 30 },
      { templateId: 'accuracy', weight: 40 },
      { templateId: 'reasonableness', weight: 20 },
    ],
  },
] as const;
export interface LLMGroupPayload {
  name: string;
  description: string;
  pass_threshold: number;
  children: {
    id?: string;
    name: string;
    description: string;
    template_id: string | null;
    weight: number;
    definition: Definition;
  }[];
  based_on_version?: string | null;
  expected_draft_id?: string | null;
  expected_draft_updated_at?: string | null;
}

export function emptyLLMGroup(): LLMGroupDesign {
  return { id: '', name: '', description: '', threshold: 0.8, children: [] };
}

export function newLLMChild(
  key: string,
  templateId: string | null = null,
  weight = 100,
): LLMChildDesign {
  const template = evaluatorTemplates.find((item) => item.id === templateId);
  return {
    ...emptyPromptEvaluator(),
    key,
    name: template?.name ?? '',
    description: template?.description ?? '',
    instruction: template?.instruction ?? '',
    templateId: template?.id ?? null,
    weight,
    original: null,
  };
}

export function newLLMGroupFromTemplate(templateId: string, keyPrefix: string): LLMGroupDesign {
  const template = llmGroupTemplates.find((item) => item.id === templateId);
  if (!template) throw new Error('评估器模板不存在。');
  return {
    ...emptyLLMGroup(),
    name: template.name,
    description: template.description,
    threshold: template.threshold,
    children: template.children.map((child, index) =>
      newLLMChild(`${keyPrefix}:${index}`, child.templateId, child.weight),
    ),
  };
}

export function readLLMGroup(detail: LLMGroupDetail): LLMGroupDesign {
  return {
    id: detail.evaluator.id,
    name: detail.definition.name ?? detail.evaluator.name,
    description:
      typeof detail.definition.config.description === 'string'
        ? detail.definition.config.description
        : detail.evaluator.description,
    threshold: Number(detail.definition.config.pass_threshold ?? 0.8),
    children: detail.children.map((child) => ({
      ...readPromptEvaluator(
        {
          ...child.evaluator,
          name: child.definition.name ?? child.evaluator.name,
          description: child.description,
        },
        child.definition,
      ),
      key: child.evaluator.id,
      templateId: child.template_id,
      weight: Number((child.weight * 100).toFixed(10)),
      original: JSON.parse(JSON.stringify(child.definition)) as GroupDefinition,
    })),
  };
}

export function copyEvaluatorDefinition(source: Definition): Definition {
  return JSON.parse(
    JSON.stringify({
      kind: source.kind,
      dimension: source.dimension,
      metric: source.metric,
      severity: source.severity,
      implementation_id: source.implementation_id,
      implementation_version: source.implementation_version,
      config: source.config,
      children: source.children,
      combination: source.combination,
    }),
  ) as Definition;
}

export function newLLMGroupFromEvaluator(
  detail: LLMGroupDetail,
  keyPrefix: string,
): LLMGroupDesign {
  const group = readLLMGroup(detail);
  return {
    ...group,
    id: '',
    name: group.name.slice(0, 46) + '（副本）',
    children: group.children.map((child, index) => ({
      ...child,
      id: '',
      key: `${keyPrefix}:${index}`,
      original: child.original ? copyEvaluatorDefinition(child.original) : null,
    })),
  };
}

export function llmGroupError(group: LLMGroupDesign): string {
  if (!group.name.trim()) return '请输入评估器名称。';
  if (group.name.length > 50) return '评估器名称不能超过 50 字。';
  if (group.description.length > 200) return '备注描述不能超过 200 字。';
  if (!Number.isFinite(group.threshold) || group.threshold < 0 || group.threshold > 1)
    return '综合通过分数须为 0.0—1.0。';
  if (!group.children.length) return '至少添加一个子评估器。';
  if (group.children.length > 32) return '最多添加 32 个子评估器。';
  const weights = weightError(group.children);
  if (weights) return weights.replaceAll('评估维度', '子评估器');
  const names = group.children.map((child) => child.name.trim());
  if (new Set(names).size !== names.length) return '子评估器名称不能重复。';
  const identities = group.children.filter((child) => child.id).map((child) => child.id);
  if (new Set(identities).size !== identities.length) return '不能重复添加同一个子评估器。';
  for (const [index, child] of group.children.entries()) {
    const error = promptEvaluatorError(child);
    if (error) return `子评估器「${child.name.trim() || index + 1}」：${error}`;
    if (child.templateId && !evaluatorTemplates.some((item) => item.id === child.templateId))
      return `子评估器「${child.name}」的模板来源无效。`;
  }
  return '';
}

export function llmGroupPayload(
  group: LLMGroupDesign,
  source: LLMGroupDetail | null,
): LLMGroupPayload {
  const error = llmGroupError(group);
  if (error) throw new Error(error);
  const payload: LLMGroupPayload = {
    name: group.name.trim(),
    description: group.description,
    pass_threshold: group.threshold,
    children: group.children.map((child) => ({
      ...(child.id ? { id: child.id } : {}),
      name: child.name.trim(),
      description: child.description,
      template_id: child.templateId,
      weight: percentWeight(child.weight),
      definition: promptEvaluatorDefinition(child, child.original),
    })),
  };
  if (source) {
    payload.based_on_version = source.viewing_draft ? null : (source.definition.version ?? null);
    payload.expected_draft_id = source.viewing_draft ? (source.definition.id ?? null) : null;
    payload.expected_draft_updated_at = source.viewing_draft
      ? (source.definition.updated_at ?? null)
      : null;
  }
  return payload;
}

function percentWeight(percent: number): number {
  const [coefficient, exponent = '0'] = String(percent).split('e');
  return Number(coefficient + 'e' + (Number(exponent) - 2));
}

export function equalLLMWeights(count: number): number[] {
  if (!Number.isInteger(count) || count < 1 || count > 32) return [];
  const base = Math.floor(10000 / count);
  return Array.from(
    { length: count },
    (_, index) => (base + (index < 10000 % count ? 1 : 0)) / 100,
  );
}

export function llmGroupDate(value?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false });
}
