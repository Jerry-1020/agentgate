import type { SummaryQuery, TaskListSummary } from '../../../api/evaluation-summaries';
export function dayWindow(days: number, now: Date = new Date()): SummaryQuery {
  if (!days) return {};
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  return { start_at: start.toISOString() };
}
export function taskPath(row: TaskListSummary): string {
  return `${row.kind === 'stability' ? 'stability' : 'tasks'}/${row.task_id ?? row.runs[0].run_id}`;
}
export function hasActiveRuns(rows: TaskListSummary[]): boolean {
  return rows.some((row) =>
    row.runs.some((run) => ['pending', 'scheduled', 'running'].includes(run.status)),
  );
}
export function evaluatorStrategy(kinds: string[]): string {
  return [
    ...new Set(
      kinds.map((kind) =>
        kind === 'rule'
          ? '规则评估'
          : ['llm_judge', 'llm_group'].includes(kind)
            ? 'LLM 评估'
            : '复合评估',
      ),
    ),
  ].join(' + ');
}
