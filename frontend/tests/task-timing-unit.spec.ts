import { test, expect } from '@playwright/test';
import { createRenderer, nextTick, ref } from 'vue';
import { http } from '../src/utils/request';
import { pinia } from '../src/stores';
import { useAuthStore } from '../src/stores/modules/auth';
import { useTaskTimings } from '../src/views/evaluation/composables/use-task-timings';
import { taskTiming } from '../src/views/evaluation/utils/task-timing';
import type { TaskListSummary } from '../src/api/evaluation-summaries';

const renderer = createRenderer({
  insert: () => {},
  remove: () => {},
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  setText: () => {},
  setElementText: () => {},
  parentNode: () => null,
  nextSibling: () => null,
  patchProp: () => {},
});
function row(status = 'completed') {
  return {
    id: 'old-task',
    name: '历史任务',
    kind: 'single',
    created_at: '2000-01-01T00:00:00Z',
    runs: [{ run_id: 'old-run', status }],
  } as TaskListSummary;
}
function run(start = '2000-01-01T01:00:00Z', status = 'completed') {
  return {
    id: 'old-run',
    status,
    started_at: start,
    completed_at: status === 'completed' ? '2000-01-01T01:05:00Z' : null,
  };
}

for (const mode of ['external', 'bank', 'integrated'] as const) {
  test(`${mode}: the time supplement uses only the existing read endpoint and current identity`, async () => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'document');
    const doc = Object.assign(new EventTarget(), { hidden: false });
    Object.defineProperty(globalThis, 'document', { configurable: true, value: doc });
    const previous = http.defaults.adapter;
    const auth = useAuthStore(pinia),
      snapshot = { ...auth.$state };
    const calls: { url: unknown; method: unknown; headers: any }[] = [];
    let timing!: ReturnType<typeof useTaskTimings>;
    const rows = ref([row()]);
    const app = renderer.createApp({
      setup() {
        timing = useTaskTimings(rows, () => [
          auth.loginMode,
          auth.token,
          auth.teamId,
          auth.userId,
          auth.platformReady,
        ]);
        return () => null;
      },
    });
    try {
      if (mode === 'external') auth.loginExternal();
      else if (mode === 'bank') auth.loginBank('bank-token', 'bank-team', '行内团队');
      else
        auth.initializePlatform({
          token: 'host-token',
          teamId: 'host-team',
          teamName: '集成团队',
          userId: 'host-user',
          userName: '用户',
        });
      http.defaults.adapter = async (config) => {
        calls.push({ url: config.url, method: config.method, headers: { ...config.headers } });
        return {
          data: { run: run(), results: [{ ignored: 'large evidence' }] },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      };
      app.mount({});
      await expect.poll(() => timing.entries.value['old-run']?.state).toBe('ready');
      expect(calls).toHaveLength(1);
      expect(calls[0]).toMatchObject({ url: '/runs/old-run/samples', method: 'get' });
      expect(calls[0].headers.token).toBe(
        mode === 'external' ? undefined : mode === 'bank' ? 'bank-token' : 'host-token',
      );
      expect(calls[0].headers['X-Team-Id']).toBe(
        mode === 'external' ? undefined : mode === 'bank' ? 'bank-team' : 'host-team',
      );
      expect(taskTiming(rows.value[0], timing.entries.value).end.value).toBe(
        '2000-01-01T01:05:00Z',
      );
      rows.value = [row()];
      await nextTick();
      expect(calls).toHaveLength(1);
      expect(timing.entries.value['old-run']).not.toHaveProperty('results');
      doc.hidden = true;
      doc.dispatchEvent(new Event('visibilitychange'));
      doc.hidden = false;
      doc.dispatchEvent(new Event('visibilitychange'));
      await nextTick();
      expect(calls).toHaveLength(1);
    } finally {
      app.unmount();
      http.defaults.adapter = previous;
      auth.$patch(snapshot);
      if (descriptor) Object.defineProperty(globalThis, 'document', descriptor);
      else Reflect.deleteProperty(globalThis, 'document');
    }
  });
}

test('identity changes abort old reads, and page changes prevent stale rows from returning', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'document');
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: Object.assign(new EventTarget(), { hidden: false }),
  });
  const previous = http.defaults.adapter;
  const auth = useAuthStore(pinia),
    snapshot = { ...auth.$state };
  let timing!: ReturnType<typeof useTaskTimings>;
  const rows = ref([row()]);
  const pending: { config: any; resolve: (data: any) => void }[] = [];
  const app = renderer.createApp({
    setup() {
      timing = useTaskTimings(rows, () => [auth.loginMode, auth.token, auth.teamId]);
      return () => null;
    },
  });
  const finish = (index: number, start: string) =>
    pending[index].resolve({
      data: { run: run(start) },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: pending[index].config,
    });
  try {
    auth.loginBank('old-token', 'old-team', '旧团队');
    http.defaults.adapter = (config) => new Promise((resolve) => pending.push({ config, resolve }));
    app.mount({});
    await expect.poll(() => pending.length).toBe(1);
    auth.loginBank('new-token', 'new-team', '新团队');
    expect(pending[0].config.signal.aborted).toBe(true);
    rows.value = [];
    await nextTick();
    rows.value = [row()];
    await expect.poll(() => pending.length).toBe(2);
    finish(1, '2000-01-01T01:02:00Z');
    await expect.poll(() => timing.entries.value['old-run']?.state).toBe('ready');
    finish(0, '2000-01-01T01:00:00Z');
    await nextTick();
    expect(taskTiming(rows.value[0], timing.entries.value).start.value).toBe(
      '2000-01-01T01:02:00Z',
    );
    rows.value = [];
    await nextTick();
    expect(timing.entries.value).toEqual({});
  } finally {
    app.unmount();
    http.defaults.adapter = previous;
    auth.$patch(snapshot);
    if (descriptor) Object.defineProperty(globalThis, 'document', descriptor);
    else Reflect.deleteProperty(globalThis, 'document');
  }
});

test('failed supplementary reads keep historical rows and can be retried without reloading the list', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'document');
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: Object.assign(new EventTarget(), { hidden: false }),
  });
  const previous = http.defaults.adapter;
  const rows = ref([row()]);
  let timing!: ReturnType<typeof useTaskTimings>,
    fail = true;
  const app = renderer.createApp({
    setup() {
      timing = useTaskTimings(rows, () => ['external']);
      return () => null;
    },
  });
  try {
    http.defaults.adapter = async (config) => {
      if (fail) throw Error('unavailable');
      return { data: { run: run() }, status: 200, statusText: 'OK', headers: {}, config };
    };
    app.mount({});
    await expect.poll(() => timing.entries.value['old-run']?.state).toBe('error');
    expect(rows.value).toEqual([row()]);
    fail = false;
    timing.retry();
    await expect.poll(() => timing.entries.value['old-run']?.state).toBe('ready');
    expect(rows.value).toEqual([row()]);
  } finally {
    app.unmount();
    http.defaults.adapter = previous;
    if (descriptor) Object.defineProperty(globalThis, 'document', descriptor);
    else Reflect.deleteProperty(globalThis, 'document');
  }
});
