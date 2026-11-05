import type { HistoricalComparison, HistoricalScoreRow } from '../../../api/historical-comparisons';
import type { Report } from '../../../api/evaluations';
import type { ComparisonScoreGroup } from './task-report';

const reasonLabels: Record<string, string> = {
  target_changed: '被测智能体不同',
  dataset_changed: '测评集或测评集内容不同',
  case_scope_changed: '执行样本范围不同',
  case_content_changed: '样本内容不同',
  case_missing: '某一侧没有该样本',
  evaluator_changed: '评估器版本或定义不同',
  evaluator_missing: '某一侧未使用该评估器',
  evaluator_snapshot_incomplete: '评估器快照不完整',
  metric_plan_changed: '指标计算口径不同',
  result_missing: '某一侧缺少评估结果',
  evaluation_error: '存在评估错误',
  scored_scope_changed: '有效计分范围不同',
  score_unavailable: '缺少可用得分',
  gate_changed: '通过条件不同',
};
export function comparisonReasons(reasons: string[]) {
  return reasons.map((reason) => reasonLabels[reason] ?? '比较条件不完整').join('；');
}

export function historicalScoreGroups(
  comparison: HistoricalComparison,
  a: Report,
  b: Report,
): ComparisonScoreGroup[] {
  const spec = (report: Report, id: string) =>
    (report.run.manifest.evaluator_specs ?? []).find(
      (item) => item.id === id && report.run.manifest.primary_evaluator_ids.includes(id),
    );
  const row = (value: HistoricalScoreRow, name: string) => ({
    key: value.key,
    name,
    baseline: value.baseline_score,
    candidate: value.candidate_score,
    delta: value.score_delta,
    reasons: comparisonReasons(value.reasons),
  });
  return (['overall', 'llm', 'rule'] as const).map((key) => {
    const value = comparison.score_rows.find(
      (item) => item.key === key && item.level === (key === 'overall' ? 'overall' : 'kind'),
    )!;
    const children = comparison.score_rows
      .filter((item) => item.level === 'evaluator')
      .filter((item) => {
        const kinds = [spec(a, item.key)?.kind, spec(b, item.key)?.kind];
        return key === 'llm'
          ? kinds.some((kind) => kind === 'llm_judge' || kind === 'llm_group')
          : key === 'rule' && kinds.includes('rule');
      })
      .map((item) => {
        const left = spec(a, item.key),
          right = spec(b, item.key);
        const label = (s: typeof left) => (s ? `${s.name} · ${s.version}` : '未使用');
        return row(
          item,
          label(left) === label(right) ? label(left) : `A：${label(left)} / B：${label(right)}`,
        );
      });
    return {
      ...row(value, { overall: '综合得分', llm: 'LLM评估得分', rule: '规则评估得分' }[key]),
      key,
      children,
    };
  });
}
