import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue';
import { ApiError } from '../../../utils/request';

// Component-owned reads only: no cross-page cache or identity-header handling.
export function useSummaryQuery<T>(options: {
  source: () => unknown;
  identity: () => unknown;
  ready: () => boolean;
  load: (signal: AbortSignal) => Promise<T>;
  poll?: (value: T) => boolean;
}) {
  const data = shallowRef<T | null>(null);
  const error = ref('');
  const loading = ref(false);
  let generation = 0;
  let disposed = false;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function invalidate() {
    generation++;
    controller?.abort();
    clearTimeout(timer);
  }
  async function reload() {
    invalidate();
    if (disposed || document.hidden || !options.ready()) {
      loading.value = false;
      return;
    }
    const ticket = generation;
    controller = new AbortController();
    loading.value = true;
    error.value = '';
    try {
      const result = await options.load(controller.signal);
      if (ticket === generation && !disposed) data.value = result;
    } catch (cause) {
      if (ticket === generation && !disposed) {
        error.value =
          cause instanceof ApiError && cause.status === 503
            ? '统计摘要尚未就绪，请完成数据升级后重试。'
            : String(cause);
      }
    } finally {
      if (ticket === generation && !disposed) {
        loading.value = false;
        if (!error.value && data.value !== null && options.poll?.(data.value) && !document.hidden)
          timer = setTimeout(() => void reload(), 5000);
      }
    }
  }
  function clear() {
    invalidate();
    data.value = null;
    error.value = '';
    loading.value = false;
  }
  watch(
    () => [options.source(), options.identity()],
    () => {
      clear();
      void reload();
    },
    { deep: true },
  );
  function visibilityChanged() {
    if (document.hidden) {
      invalidate();
      loading.value = false;
    } else void reload();
  }
  onMounted(() => {
    document.addEventListener('visibilitychange', visibilityChanged);
    void reload();
  });
  onUnmounted(() => {
    disposed = true;
    invalidate();
    document.removeEventListener('visibilitychange', visibilityChanged);
  });
  return { data, error, loading, reload, clear };
}
