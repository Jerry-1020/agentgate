import { pinia } from '../../../stores';
import { useTaskLinksStore } from '../../../stores/modules/task-links';
import { api, type EvaluationRun } from '../../../api/evaluations';
export type { TaskLink } from '../../../stores/modules/task-links';
export const { readTaskLinks, refreshTaskLinks, saveTaskLink } = useTaskLinksStore(pinia);

// The recent execution window can be filled by history; current tasks must not disappear.
export async function includeCurrentTaskRuns(recent: EvaluationRun[]): Promise<EvaluationRun[]> {
  const records = new Map(recent.map((run) => [run.id, run]));
  const missing = [...new Set(readTaskLinks().flatMap((task) => task.runIds))].filter(
    (id) => !records.has(id),
  );
  for (let start = 0; start < missing.length; start += 6) {
    await Promise.all(
      missing.slice(start, start + 6).map(async (id) => {
        const { run } = await api.samples(id);
        records.set(id, run);
      }),
    );
  }
  return [...records.values()];
}
