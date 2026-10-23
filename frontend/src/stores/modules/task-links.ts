import { ref } from 'vue';
import { defineStore } from 'pinia';
import { request } from '../../api/evaluations';
import { ApiError } from '../../utils/request';
export interface TaskLink {
  id: string;
  name?: string;
  kind: 'single' | 'ab' | 'stability';
  mockSelection?: { branch: string; credentialScope: string; credentialLabel: string };
  runIds: string[];
  previousRunIds?: string[];
  createdAt?: string;
  staticReports: { version: string; descriptorHash?: string; reportId?: string; error?: string }[];
}
interface StoredTask {
  id: string;
  name?: string | null;
  kind: 'single' | 'ab' | 'stability';
  run_ids: string[];
  previous_run_ids?: string[];
  created_at?: string;
  static_report_ids: string[];
}
export const useTaskLinksStore = defineStore('task-links', () => {
  const cache = ref<TaskLink[]>([]);
  let generation = 0;
  let latestRefresh: Promise<TaskLink[]>;
  function readTaskLinks(): TaskLink[] {
    return cache.value;
  }
  function refreshTaskLinks(taskId?: string): Promise<TaskLink[]> {
    const current = ++generation;
    const refresh = (async () => {
      let tasks: StoredTask[];
      if (taskId) {
        try {
          tasks = [await request<StoredTask>('/evaluation-tasks/' + encodeURIComponent(taskId))];
        } catch (error) {
          // Standalone execution links have no task association; the run endpoint still checks access.
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
          tasks = [];
        }
      } else {
        tasks = await request<StoredTask[]>('/evaluation-tasks');
      }
      const ids = [...new Set(tasks.flatMap((t) => t.static_report_ids))];
      const versions = new Map(
        await Promise.all(
          ids.map(async (id) => {
            const detail = await request<{
              report: {
                target_ref: { external_version_id: string };
                target_descriptor_sha256: string;
              };
            }>('/skill-analysis/reports/' + encodeURIComponent(id));
            return [
              id,
              {
                version: detail.report.target_ref.external_version_id,
                descriptorHash: detail.report.target_descriptor_sha256,
              },
            ] as const;
          }),
        ),
      );
      const links = tasks.map((t) => ({
        id: t.id,
        name: t.name ?? undefined,
        kind: t.kind,
        runIds: t.run_ids,
        previousRunIds: t.previous_run_ids ?? [],
        createdAt: t.created_at,
        staticReports: t.static_report_ids.map((id) => ({ reportId: id, ...versions.get(id)! })),
      }));
      if (current !== generation) return latestRefresh;
      cache.value = links;
      return cache.value;
    })();
    latestRefresh = refresh;
    return refresh;
  }
  async function saveTaskLink(link: TaskLink): Promise<void> {
    await request('/evaluation-tasks/' + encodeURIComponent(link.id), 'PUT', {
      kind: link.kind,
      ...(link.name ? { name: link.name } : {}),
      run_ids: link.runIds,
      static_report_ids: link.staticReports.flatMap((r) => (r.reportId ? [r.reportId] : [])),
    });
    await refreshTaskLinks();
    window.dispatchEvent(new Event('task-links-updated'));
  }
  return { cache, readTaskLinks, refreshTaskLinks, saveTaskLink };
});
