import type { EvaluationResult, Report } from '../../../api/client';
import type { Comparison } from '../../../api/evaluations';
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

type ComparisonScore = {
  key: string;
  name: string;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
};
export type ComparisonScoreGroup = ComparisonScore & {
  key: 'overall' | 'llm' | 'rule';
  children: ComparisonScore[];
};

const mean = (values: number[]) =>
  values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;

function caseMean(results: EvaluationResult[]): number | null {
  const cases = new Map<string, number[]>();
  for (const result of results) {
    if (result.score == null) continue;
    const scores = cases.get(result.case_id) ?? [];
    scores.push(result.score);
    cases.set(result.case_id, scores);
  }
  return mean([...cases.values()].map((scores) => mean(scores)!));
}

export function comparisonScoreGroups(
  comparison: Comparison,
  baseline: Report,
  candidate: Report,
): ComparisonScoreGroup[] {
  const row = (key: string, name: string, a: number | null, b: number | null): ComparisonScore => ({
    key,
    name,
    baseline: a,
    candidate: b,
    delta: a == null || b == null ? null : b - a,
  });
  const primarySpecs = (baseline.run.manifest.evaluator_specs ?? []).filter((spec) =>
    baseline.run.manifest.primary_evaluator_ids.includes(spec.id),
  );
  const llmKinds = ['llm_judge', 'llm_group'];
  const llmScore = (report: Report) => {
    const summaries = report.metrics.filter(
      (metric) => metric.level === 'kind' && llmKinds.includes(metric.key),
    );
    if (summaries.length === 1) return summaries[0].score;
    const metrics = new Map<string, EvaluationResult[]>();
    for (const result of report.results) {
      if (
        !report.run.manifest.primary_evaluator_ids.includes(result.evaluator_id) ||
        !llmKinds.includes(result.evaluator_kind)
      )
        continue;
      const results = metrics.get(result.metric) ?? [];
      results.push(result);
      metrics.set(result.metric, results);
    }
    // Match kind summaries: average each metric's case scores, then average the metrics.
    return mean(
      [...metrics.values()].flatMap((results) => {
        const value = caseMean(results);
        return value == null ? [] : [value];
      }),
    );
  };
  return (['overall', 'llm', 'rule'] as const).map((key) => {
    const metric = comparison.metric_deltas.find(
      (item) => item.level === (key === 'overall' ? 'overall' : 'kind') && item.key === key,
    );
    const name = { overall: '综合得分', llm: 'LLM评估得分', rule: '规则评估得分' }[key];
    const summary = row(
      key,
      name,
      key === 'llm' ? llmScore(baseline) : (metric?.baseline.score ?? null),
      key === 'llm' ? llmScore(candidate) : (metric?.candidate.score ?? null),
    );
    if (key !== 'llm') summary.delta = metric?.score_delta ?? null;
    const children = primarySpecs
      .filter((spec) =>
        key === 'llm' ? llmKinds.includes(spec.kind) : key === 'rule' && spec.kind === 'rule',
      )
      .map((spec) => {
        const evaluatorScore = (report: Report) =>
          caseMean(
            report.results.filter(
              (result) =>
                result.evaluator_id === spec.id && result.evaluator_version === spec.version,
            ),
          );
        return row(
          spec.id,
          `${spec.name} · v${spec.version}`,
          evaluatorScore(baseline),
          evaluatorScore(candidate),
        );
      });
    return { ...summary, key, children };
  });
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
  const spans = (trace?.spans ?? []).flatMap((span: any) => {
    if (typeof span.started_at !== 'string' || typeof span.ended_at !== 'string') return [];
    const start = Date.parse(span.started_at),
      end = Date.parse(span.ended_at);
    return Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? [{ operationType: span.operation_type, start, end }]
      : [];
  });
  const cases = spans.filter((span: any) => span.operationType === 'case');
  // In-bank traces may contain only turns/nodes; use elapsed time, not summed span durations.
  const timings = cases.length ? cases : spans;
  if (!timings.length) return null;
  const start = timings.reduce((value: number, span: any) => Math.min(value, span.start), Infinity),
    end = timings.reduce((value: number, span: any) => Math.max(value, span.end), -Infinity);
  return (end - start) / 1000;
}
