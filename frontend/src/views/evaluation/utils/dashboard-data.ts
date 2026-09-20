import type { EvaluationRun, RunProgress, Report } from '../../../api/evaluations';
export function targetLabel(type: string) {
  return (
    (
      { workflow: '工作流', base: '基础编排', cloudshrimp: '云虾', agent: '智能体' } as Record<
        string,
        string
      >
    )[type] || type
  );
}
export function taskTitle(run: EvaluationRun, kind?: string) {
  const app =
    run.manifest.target.display_name === 'Loan Agent'
      ? '贷款智能体'
      : run.manifest.target.display_name;
  const specs = (run.manifest as any).evaluator_specs ?? [];
  const kinds = new Set(
    specs
      .filter((s: any) => run.manifest.primary_evaluator_ids.includes(s.id))
      .map((s: any) => s.kind),
  );
  const mode =
    kind === 'ab'
      ? 'A/B 对比'
      : kind === 'stability'
        ? '稳定性测试'
        : kinds.has('hybrid') || kinds.size > 1
          ? '综合评测'
          : kinds.has('llm_judge')
            ? 'LLM 评测'
            : kinds.has('rule')
              ? '规则评测'
              : '评测';
  return `${app} · ${mode} · ${run.id.slice(0, 8)}`;
}
export function periodRuns(runs: EvaluationRun[], days: number, type: string, now = new Date()) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - days + 1);
  return runs.filter(
    (r) =>
      Date.parse(r.created_at) >= start.getTime() &&
      Date.parse(r.created_at) <= now.getTime() &&
      (!type || r.manifest.target.ref.target_type === type),
  );
}
export function targetDistribution(runs: EvaluationRun[]) {
  const seen = new Set<string>(),
    counts: Record<string, number> = {};
  for (const r of runs) {
    const ref = r.manifest.target.ref,
      key = JSON.stringify([ref.source_id, ref.target_type, ref.external_target_id]);
    if (seen.has(key)) continue;
    seen.add(key);
    counts[ref.target_type] = (counts[ref.target_type] ?? 0) + 1;
  }
  return Object.entries(counts).map(([key, value]) => ({ key, label: targetLabel(key), value }));
}
export function sampleDistribution(runs: EvaluationRun[], progress: Record<string, RunProgress>) {
  const counts: Record<string, number> = {
    processed: 0,
    running: 0,
    pending: 0,
    failed: 0,
    cancelled: 0,
    unknown: 0,
  };
  for (const r of runs) {
    const p = progress[r.id];
    const total = (r.manifest.selected_case_ids ?? r.manifest.dataset.cases.map((c) => c.id))
      .length;
    if (!p) {
      counts.unknown += total;
      continue;
    }
    const done = Math.min(p.total_cases, Math.max(0, p.completed_cases));
    counts.processed += done;
    const remaining = Math.max(0, p.total_cases - done);
    const key =
      r.status === 'running'
        ? 'running'
        : ['pending', 'scheduled'].includes(r.status)
          ? 'pending'
          : r.status === 'failed'
            ? 'failed'
            : r.status === 'cancelled'
              ? 'cancelled'
              : 'unknown';
    counts[key] += remaining;
  }
  const labels: Record<string, string> = {
    processed: '已处理',
    running: '运行中待处理',
    pending: '等待执行',
    failed: '失败任务未完成',
    cancelled: '已取消未执行',
    unknown: '进度未知',
  };
  return Object.entries(counts).map(([key, value]) => ({ key, label: labels[key], value }));
}
export function averageScore(runs: EvaluationRun[], reports: Record<string, Report>) {
  const completed = runs.filter((r) => r.status === 'completed');
  if (completed.some((r) => !reports[r.id])) return null;
  const scores = completed.flatMap((r) => {
    const report = reports[r.id],
      score = report.metrics.find((m) => m.level === 'overall')?.score;
    return report.release_gate.reason_code !== 'evaluator_error' &&
      typeof score === 'number' &&
      Number.isFinite(score)
      ? [score]
      : [];
  });
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
}
export function recentEvents(runs: EvaluationRun[]) {
  return runs
    .flatMap((run) => [
      { key: run.id + ':created', run, label: '创建任务', time: run.created_at },
      ...(run.started_at
        ? [{ key: run.id + ':started', run, label: '开始执行', time: run.started_at }]
        : []),
      ...(run.completed_at
        ? [
            {
              key: run.id + ':ended',
              run,
              label:
                run.status === 'failed'
                  ? '执行失败'
                  : run.status === 'cancelled'
                    ? '任务取消'
                    : '执行完成',
              time: run.completed_at,
            },
          ]
        : []),
    ])
    .filter((e) => Number.isFinite(Date.parse(e.time)))
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))
    .slice(0, 8);
}
