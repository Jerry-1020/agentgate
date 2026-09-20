import { ref } from 'vue';
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
  version: number;
  dimensions: DimensionDesign[];
  modelKey: string;
  scope: string;
  threshold: number;
}
export const evaluatorDesigns = ref<EvaluatorDesign[]>([]);
export const evaluatorDesignHistory = ref<Record<string, EvaluatorDesign[]>>({});
export function weightError(rows: { weight: number | null }[]) {
  if (!rows.length) return '至少保留一个评估维度。';
  if (
    rows.some(
      (d) => d.weight === null || !Number.isFinite(d.weight) || d.weight <= 0 || d.weight > 100,
    )
  )
    return '每项权重必须大于 0 且不超过 100。';
  return Math.abs(rows.reduce((sum, d) => sum + (d.weight ?? 0), 0) - 100) > 0.001
    ? '权重之和必须为 100%。'
    : '';
}
