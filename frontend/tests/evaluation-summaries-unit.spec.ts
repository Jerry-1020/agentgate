import { test, expect } from '@playwright/test';
import {
  dayWindow,
  taskPath,
  hasActiveRuns,
  evaluatorStrategy,
} from '../src/views/evaluation/utils/summary-query';
test('calendar windows preserve local midnight and zero means unbounded', () => {
  const now = new Date(2026, 9, 21, 12);
  expect(dayWindow(1, now)).toEqual({ start_at: new Date(2026, 9, 21).toISOString() });
  expect(dayWindow(7, now)).toEqual({ start_at: new Date(2026, 9, 15).toISOString() });
  expect(dayWindow(0, now)).toEqual({});
});
test('row presentation preserves kinds, nullable task identity and running sides', () => {
  const row = {
    kind: 'single',
    task_id: 'task',
    runs: [{ run_id: 'run', status: 'completed' }],
  } as any;
  expect(taskPath(row)).toBe('tasks/task');
  expect(taskPath({ ...row, kind: 'stability', task_id: null })).toBe('stability/run');
  expect(hasActiveRuns([row])).toBe(false);
  for (const status of ['pending', 'scheduled', 'waiting', 'running'])
    expect(hasActiveRuns([{ ...row, runs: [{ status }] }])).toBe(true);
  expect(evaluatorStrategy(['rule', 'llm_judge', 'llm_group', 'hybrid'])).toBe(
    '规则评估 + LLM 评估 + 复合评估',
  );
});

import {
  formatTaskTime,
  taskTiming,
  loadRunTimings,
  readRunTiming,
  type RunTiming,
  type TimingEntry,
} from '../src/views/evaluation/utils/task-timing';
const start = '2026-11-03T01:00:00Z';
const end = '2026-11-03T01:05:00Z';
function summaryRun(id: string, status = 'completed') {
  return { run_id: id, status } as any;
}
function timingRun(id: string, status = 'completed', times: Partial<RunTiming> = {}): RunTiming {
  return { id, status, started_at: start, completed_at: end, ...times };
}
function ready(run: RunTiming): TimingEntry {
  return { state: 'ready', run };
}

test('task times use Shanghai dates including midnight and reject missing/invalid history', () => {
  expect(formatTaskTime('2026-11-02T16:00:00Z')).toEqual({ date: '2026-11-03', time: '00:00:00' });
  expect(formatTaskTime('2026-11-03T09:00:00+08:00')).toEqual({
    date: '2026-11-03',
    time: '09:00:00',
  });
  for (const value of [null, undefined, '', 'not-a-date']) expect(formatTaskTime(value)).toBeNull();
});

test('queued and scheduled runs need no detail request or fabricated timestamps', async () => {
  const runs = ['pending', 'waiting', 'scheduled'].map((s) => summaryRun(s, s));
  let calls = 0;
  await loadRunTimings({
    runs,
    entries: {},
    read: async (id) => {
      calls++;
      return timingRun(id);
    },
    update: () => {},
    signal: new AbortController().signal,
  });
  expect(calls).toBe(0);
  for (const run of runs)
    expect(taskTiming({ runs: [run] }, {})).toMatchObject({
      start: { value: null, label: '未启动' },
      end: { value: null, label: '未结束' },
    });
});

for (const status of ['completed', 'failed', 'cancelled']) {
  test(`${status}: persisted execution times are shown for existing tasks`, () => {
    const result = taskTiming(
      { runs: [summaryRun('old', status)] },
      { old: ready(timingRun('old', status)) },
    );
    expect(result.start.value).toBe(start);
    expect(result.end.value).toBe(end);
  });
}

test('cancellation or failure before engine start has an end without a start', () => {
  for (const status of ['failed', 'cancelled']) {
    const result = taskTiming(
      { runs: [summaryRun('old', status)] },
      { old: ready(timingRun('old', status, { started_at: null })) },
    );
    expect(result.start).toEqual({ value: null, label: '未启动' });
    expect(result.end.value).toBe(end);
  }
});

test('incomplete historical timestamps remain explicitly unknown, with no creation-time fallback', () => {
  const value = readRunTiming(
    { run: { id: 'old', status: 'completed', manifest: { large: true } } },
    'old',
  );
  expect(taskTiming({ runs: [summaryRun('old')] }, { old: ready(value) })).toMatchObject({
    start: { label: '未记录' },
    end: { label: '未记录' },
  });
  expect(value).not.toHaveProperty('manifest');
  expect(() => readRunTiming({ run: { id: 'other', status: 'completed' } }, 'old')).toThrow();
  expect(() => readRunTiming({}, 'old')).toThrow();
});

test('A/B start is earliest and end is latest across mixed terminal statuses', () => {
  const result = taskTiming(
    { runs: [summaryRun('a', 'cancelled'), summaryRun('b')] },
    {
      a: ready(timingRun('a', 'cancelled', { completed_at: '2026-11-03T01:04:00Z' })),
      b: ready(timingRun('b', 'completed', { started_at: '2026-11-03T01:02:00Z' })),
    },
  );
  expect(result.start.value).toBe(start);
  expect(result.end.value).toBe(end);
  expect(result.sides.map((s) => s.label)).toEqual(['A', 'B']);
});

test('A/B failed aggregate cannot produce an end while another side is running or waiting', () => {
  for (const status of ['running', 'waiting']) {
    const result = taskTiming(
      { runs: [summaryRun('a', 'failed'), summaryRun('b', status)] },
      {
        a: ready(timingRun('a', 'failed')),
        b: ready(timingRun('b', status, { started_at: null, completed_at: null })),
      },
    );
    expect(result.end).toEqual({ value: null, label: '未结束' });
  }
});

test('A/B missing or unreadable side never produces a misleading aggregate timestamp', () => {
  const runs = [summaryRun('a'), summaryRun('b')];
  const a = ready(timingRun('a'));
  expect(taskTiming({ runs }, { a }).end.label).toBe('加载中…');
  expect(
    taskTiming({ runs }, { a, b: { state: 'error', status: 'completed', retryAt: 30 } }).end.label,
  ).toBe('读取失败');
  expect(
    taskTiming({ runs }, { a, b: ready(timingRun('b', 'completed', { completed_at: null })) }).end
      .label,
  ).toBe('未记录');
  expect(taskTiming({ runs: [] }, {}).end.label).toBe('未记录');
});

test('cached running start refreshes on completion while terminal times are reused', async () => {
  const entries: Record<string, TimingEntry> = {
    r: ready(timingRun('r', 'running', { completed_at: null })),
  };
  const calls: string[] = [];
  const options = {
    entries,
    read: async (id: string) => {
      calls.push(id);
      return timingRun(id);
    },
    update: (id: string, entry: TimingEntry) => {
      entries[id] = entry;
    },
    signal: new AbortController().signal,
  };
  await loadRunTimings({ ...options, runs: [summaryRun('r', 'running')] });
  expect(calls).toEqual([]);
  await loadRunTimings({ ...options, runs: [summaryRun('r')] });
  expect(calls).toEqual(['r']);
  await loadRunTimings({ ...options, runs: [summaryRun('r')] });
  expect(calls).toEqual(['r']);
  expect(taskTiming({ runs: [summaryRun('r')] }, entries).end.value).toBe(end);
});

test('detail finishes ahead of summary: end waits for terminal summary without repeating the read', async () => {
  const entries = { r: ready(timingRun('r')) };
  expect(taskTiming({ runs: [summaryRun('r', 'running')] }, entries).end.label).toBe('未结束');
  let calls = 0;
  await loadRunTimings({
    runs: [summaryRun('r', 'running')],
    entries,
    read: async (id) => {
      calls++;
      return timingRun(id);
    },
    update: () => {},
    signal: new AbortController().signal,
  });
  expect(calls).toBe(0);
  expect(taskTiming({ runs: [summaryRun('r')] }, entries).end.value).toBe(end);
});

test('time reads are limited to three concurrent requests and deduplicate current-page runs', async () => {
  let concurrent = 0,
    peak = 0;
  const calls: string[] = [];
  const entries: Record<string, TimingEntry> = {};
  const runs = Array.from({ length: 10 }, (_, i) => summaryRun(String(i)));
  await loadRunTimings({
    runs: [...runs, ...runs],
    entries,
    signal: new AbortController().signal,
    read: async (id) => {
      calls.push(id);
      concurrent++;
      peak = Math.max(peak, concurrent);
      await new Promise((r) => setTimeout(r, 1));
      concurrent--;
      return timingRun(id);
    },
    update: (id, entry) => {
      entries[id] = entry;
    },
  });
  expect(peak).toBe(3);
  expect(calls).toHaveLength(10);
  expect(Object.values(entries).every((e) => e.state === 'ready')).toBe(true);
});

test('a failed detail does not prevent other historical times from displaying; retries are throttled', async () => {
  const entries: Record<string, TimingEntry> = {};
  let calls = 0;
  const options = {
    runs: [summaryRun('bad'), summaryRun('good')],
    entries,
    signal: new AbortController().signal,
    read: async (id: string) => {
      calls++;
      if (id === 'bad') throw Error('Unavailable');
      return timingRun(id);
    },
    update: (id: string, entry: TimingEntry) => {
      entries[id] = entry;
    },
  };
  await loadRunTimings({ ...options, now: 1000 });
  expect(calls).toBe(2);
  expect(taskTiming({ runs: [summaryRun('good')] }, entries).end.value).toBe(end);
  expect(taskTiming({ runs: [summaryRun('bad')] }, entries).end.label).toBe('读取失败');
  await loadRunTimings({ ...options, now: 2000 });
  expect(calls).toBe(2);
  await loadRunTimings({ ...options, now: 31000 });
  expect(calls).toBe(3);
});

test('aborting page/identity reads neither publishes late responses nor dispatches the remaining queue', async () => {
  const controller = new AbortController();
  const releases: (() => void)[] = [];
  const entries: Record<string, TimingEntry> = {};
  const promise = loadRunTimings({
    runs: Array.from({ length: 8 }, (_, i) => summaryRun(String(i))),
    entries,
    signal: controller.signal,
    read: async (id) => {
      await new Promise<void>((resolve) => releases.push(resolve));
      return timingRun(id);
    },
    update: (id, entry) => {
      entries[id] = entry;
    },
  });
  expect(releases).toHaveLength(3);
  controller.abort();
  releases.forEach((release) => release());
  await promise;
  expect(releases).toHaveLength(3);
  expect(Object.values(entries).every((e) => e.state === 'loading')).toBe(true);
});
