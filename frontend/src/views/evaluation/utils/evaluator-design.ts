import type { Definition, EvaluatorSummary } from '../../../api/evaluations';
import { modelRefError, readModelRef } from './evaluator-model';

export type JudgeScope = 'final_output' | 'output_and_tools' | 'full_trajectory';
export interface DimensionDesign {
  id: string;
  name: string;
  description: string;
  prompt: string;
  weight: number | null;
}
export interface EvaluatorDesign {
  id: string;
  name: string;
  description: string;
  version: string | null;
  dimensions: DimensionDesign[];
  modelKey: string;
  scope: JudgeScope;
  threshold: number;
}
export function hasDimensionScoring(definition: Definition | null) {
  return (
    definition?.implementation_id === 'answer_quality' && definition.implementation_version === '2'
  );
}

export function readEvaluatorDesign(
  evaluator: EvaluatorSummary,
  definition: Definition,
): EvaluatorDesign {
  const config = definition.config;
  return {
    id: evaluator.id,
    name: evaluator.name,
    description: evaluator.description,
    version: definition.version ?? null,
    modelKey: JSON.stringify(config.model ?? {}),
    scope: (config.input_selection ?? 'final_output') as JudgeScope,
    threshold: Number(config.pass_threshold ?? 0.8) * 100,
    dimensions: hasDimensionScoring(definition)
      ? (Array.isArray(config.dimensions) ? config.dimensions : []).map((row) => ({
          id: typeof row?.id === 'string' ? row.id : '',
          name: typeof row?.name === 'string' ? row.name : '',
          description: typeof row?.description === 'string' ? row.description : '',
          prompt: typeof row?.prompt === 'string' ? row.prompt : '',
          weight: typeof row?.weight === 'number' ? row.weight : null,
        }))
      : [
          {
            id: 'overall',
            name: '整体评分',
            description: '',
            weight: null,
            prompt:
              String(config.instruction ?? '') +
              '\n\n评分标准：\n' +
              JSON.stringify(config.rubric ?? {}, null, 2),
          },
        ],
  };
}

export function evaluatorDesignError(design: EvaluatorDesign) {
  if (!design.name.trim()) return '请输入评估器名称。';
  const error = modelRefError(design.modelKey) || weightError(design.dimensions);
  if (error) return error;
  if (design.dimensions.length > 64) return '最多配置 64 个评估维度。';
  if (design.dimensions.some((row) => !row.name.trim() || !row.id.trim() || !row.prompt.trim()))
    return '请填写各维度名称、标识和评分提示词。';
  if (new Set(design.dimensions.map((row) => row.id.trim())).size !== design.dimensions.length)
    return '维度标识不能重复。';
  if (!Number.isFinite(design.threshold) || design.threshold < 0 || design.threshold > 100)
    return '通过分数须为 0—100。';
  if (!['final_output', 'output_and_tools', 'full_trajectory'].includes(design.scope))
    return '请选择有效的评审输入范围。';
  return '';
}

export function evaluatorDraftDefinition(
  design: EvaluatorDesign,
  base: Definition | null,
): Definition {
  const error = evaluatorDesignError(design);
  if (error) throw new Error(error);
  const original = hasDimensionScoring(base) ? base : null;
  return {
    kind: 'llm_judge',
    dimension: original?.dimension ?? 'answer',
    metric: original?.metric ?? 'answer_quality',
    severity: original?.severity ?? 'standard',
    implementation_id: 'answer_quality',
    implementation_version: '2',
    config: {
      ...original?.config,
      model: readModelRef(design.modelKey),
      input_selection: design.scope,
      pass_threshold: design.threshold / 100,
      dimensions: design.dimensions.map((row) => ({
        ...row,
        id: row.id.trim(),
        name: row.name.trim(),
      })),
    },
    children: [],
    combination: null,
  };
}

export function weightError(rows: { weight: number | null }[]) {
  if (!rows.length) return '至少保留一个评估维度。';
  if (
    rows.some(
      (d) => d.weight === null || !Number.isFinite(d.weight) || d.weight <= 0 || d.weight > 100,
    )
  )
    return '每项权重必须大于 0 且不超过 100。';
  // Compare decimal inputs exactly, matching the backend's Decimal validation.
  const decimals = rows.map(({ weight }) => {
    const [mantissa, exponent = '0'] = String(weight).split('e');
    const [integer, fraction = ''] = mantissa.split('.');
    return { units: BigInt(integer + fraction), scale: fraction.length - Number(exponent) };
  });
  const scale = Math.max(0, ...decimals.map((item) => item.scale));
  const total = decimals.reduce(
    (sum, item) => sum + item.units * 10n ** BigInt(scale - item.scale),
    0n,
  );
  return total === 100n * 10n ** BigInt(scale) ? '' : '权重之和必须为 100%。';
}
