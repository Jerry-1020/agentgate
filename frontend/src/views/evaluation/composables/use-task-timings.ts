import { onMounted, onUnmounted, shallowRef, watch, type Ref } from 'vue';
import type { TaskListSummary } from '../../../api/evaluation-summaries';
import { httpRequest } from '../../../utils/request';
import { loadRunTimings, readRunTiming, type TimingEntries } from '../utils/task-timing';

export function useTaskTimings(rows: Ref<TaskListSummary[]>, identity: () => unknown) {
  const entries = shallowRef<TimingEntries>({});
  let controller = new AbortController();
  let busy = false;
  let requested = false;
  let disposed = false;

  async function refresh() {
    if (disposed || document.hidden || !rows.value.length) return;
    if (busy) {
      requested = true;
      return;
    }
    busy = true;
    requested = false;
    const signal = controller.signal;
    try {
      await loadRunTimings({
        runs: rows.value.flatMap((row) => row.runs),
        entries: entries.value,
        signal,
        read: async (id, signal) =>
          readRunTiming(
            await httpRequest(`/runs/${encodeURIComponent(id)}/samples`, {
              signal,
              timeout: 15000,
            }),
            id,
          ),
        update: (id, entry) => {
          if (!signal.aborted) entries.value = { ...entries.value, [id]: entry };
        },
      });
    } finally {
      if (!signal.aborted) {
        busy = false;
        if (requested) void refresh();
      }
    }
  }

  function stop(clear: boolean) {
    controller.abort();
    controller = new AbortController();
    busy = false;
    requested = false;
    if (clear) entries.value = {};
  }
  function retry() {
    entries.value = Object.fromEntries(
      Object.entries(entries.value).filter(([, e]) => e.state !== 'error'),
    );
    void refresh();
  }
  watch(identity, () => stop(true), { deep: true, flush: 'sync' });
  watch(
    rows,
    (value) => {
      // The list clears on paging/filter/identity changes, invalidating old requests and cache.
      if (!value.length) stop(true);
      else void refresh();
    },
    { flush: 'sync' },
  );
  function visibilityChanged() {
    if (document.hidden) stop(false);
    else void refresh();
  }
  onMounted(() => {
    document.addEventListener('visibilitychange', visibilityChanged);
    void refresh();
  });
  onUnmounted(() => {
    disposed = true;
    stop(true);
    document.removeEventListener('visibilitychange', visibilityChanged);
  });
  return { entries, retry };
}
