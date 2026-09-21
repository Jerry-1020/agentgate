import { ref } from 'vue';
import { defineStore } from 'pinia';
import { request } from '../../api/evaluations';
export interface TaskLink {
  id: string;
  kind: 'single' | 'ab' | 'stability';
  mockSelection?: { branch: string; credentialScope: string; credentialLabel: string };
  runIds: string[];
  staticReports: { version: string; descriptorHash?: string; reportId?: string; error?: string }[];
}
interface StoredTask {
  id: string;
  kind: 'single' | 'ab' | 'stability';
  run_ids: string[];
  static_report_ids: string[];
}
export const useTaskLinksStore = defineStore('task-links', () => {
  const cache = ref<TaskLink[]>([]);
  let generation = 0;
  function readTaskLinks(): TaskLink[] {
    return cache.value;
  }
  async function refreshTaskLinks(): Promise<TaskLink[]> {
    const current = ++generation;
    const tasks = await request<StoredTask[]>('/evaluation-tasks');
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
      kind: t.kind,
      runIds: t.run_ids,
      staticReports: t.static_report_ids.map((id) => ({ reportId: id, ...versions.get(id)! })),
    }));
    if (current === generation) cache.value = links;
    return cache.value;
  }
  async function saveTaskLink(link: TaskLink): Promise<void> {
    await request('/evaluation-tasks/' + encodeURIComponent(link.id), 'PUT', {
      kind: link.kind,
      run_ids: link.runIds,
      static_report_ids: link.staticReports.flatMap((r) => (r.reportId ? [r.reportId] : [])),
    });
    await refreshTaskLinks();
    window.dispatchEvent(new Event('task-links-updated'));
  }
  return { cache, readTaskLinks, refreshTaskLinks, saveTaskLink };
});
