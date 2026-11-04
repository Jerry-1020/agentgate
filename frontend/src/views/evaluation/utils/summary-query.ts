import type { SummaryQuery, TaskListSummary } from '../../../api/evaluation-summaries';
export function dayWindow(days: number, now: Date = new Date()): SummaryQuery {
  if (!days) return {};
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  return { start_at: start.toISOString() };
}
export function taskPath(
  row: Pick<TaskListSummary, 'kind' | 'task_id'> & (Pick<TaskListSummary, 'runs'> | { run_id: string }),
): string {
  const id = row.task_id ?? ('run_id' in row ? row.run_id : row.runs[0].run_id);
  return `${row.kind === 'stability' ? 'stability' : 'tasks'}/${id}`;
}
export function hasActiveRuns(rows: TaskListSummary[]): boolean {
  return rows.some((row) =>
    row.runs.some((run) => ['pending', 'scheduled', 'waiting', 'running'].includes(run.status)),
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
