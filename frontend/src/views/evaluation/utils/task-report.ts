import type { EvaluationResult } from '../../../api/client';
import type { EvaluationRun } from '../types/run';

export type EvaluatorSnapshot = NonNullable<EvaluationRun['manifest']['evaluator_specs']>[number];
export interface WeightedChildResult {
  result: EvaluationResult;
  weight: number | null;
}
export interface EvaluatorResultGroup {
  result: EvaluationResult;
  children: WeightedChildResult[];
}
export function groupEvaluatorResults(
  results: EvaluationResult[],
  specs: EvaluatorSnapshot[] = [],
): EvaluatorResultGroup[] {
  const grouped = results.map((result) => {
    const parent = specs.find(
      (s) =>
        s.id === result.evaluator_id &&
        s.version === result.evaluator_version &&
        s.kind === 'llm_group',
    );
    const children = (parent?.children ?? []).flatMap((ref) => {
      const child = results.find(
        (r) =>
          r.case_id === result.case_id &&
          r.evaluator_id === ref.evaluator_id &&
          r.evaluator_version === ref.evaluator_version,
      );
      return child ? [{ result: child, weight: ref.weight }] : [];
    });
    return { result, children };
  });
  const nested = new Set(grouped.flatMap((g) => g.children.map((c) => c.result)));
  return grouped.filter((g) => !nested.has(g.result));
}

export type ScoreColumn = { key: string; name: string; evaluatorId: string };
export function scoreColumns(manifest: any): ScoreColumn[] {
  return (manifest.evaluator_specs ?? [])
    .filter((s: any) => manifest.primary_evaluator_ids.includes(s.id))
    .map((s: any) => ({ key: s.id, name: s.name, evaluatorId: s.id }));
}
export function columnScore(results: EvaluationResult[], column: ScoreColumn): number | null {
  const r = results.find((x) => x.evaluator_id === column.evaluatorId);
  return r?.score ?? null;
}
export function sampleSummary(results: EvaluationResult[], primary: string[]) {
  const rows = results.filter((r) => primary.includes(r.evaluator_id)),
    numbers = rows.flatMap((r) => (r.score === null ? [] : [r.score]));
  const outcome = rows.some((r) => r.outcome === 'error')
    ? 'error'
    : rows.some((r) => r.outcome === 'fail')
      ? 'fail'
      : rows.some((r) => r.outcome === 'review')
        ? 'review'
        : rows.length < primary.length
          ? 'pending'
          : numbers.length
            ? 'pass'
            : 'not_applicable';
  return {
    outcome,
    score: numbers.length ? numbers.reduce((a, b) => a + b, 0) / numbers.length : null,
  };
}
export function csvCell(value: unknown) {
  const text = String(value ?? '');
  return '"' + (/^[=+@\-\t\r]/.test(text) ? "'" + text : text).replace(/"/g, '""') + '"';
}
export function downloadCsv(rows: unknown[][], name: string) {
  const blob = new Blob(['\ufeff' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n')], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob),
    a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function displayValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}
export function traceSeconds(trace: any): number | null {
  const spans = (trace?.spans ?? []).filter((s: any) => s.operation_type === 'case');
  if (!spans.length) return null;
  const start = Date.parse(spans[0].started_at),
    end = Date.parse(spans[0].ended_at);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, (end - start) / 1000) : null;
}
