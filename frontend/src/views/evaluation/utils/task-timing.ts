import type { TaskListSummary } from '../../../api/evaluation-summaries';

type RunSummary = Pick<TaskListSummary['runs'][number], 'run_id' | 'status'>;
export interface RunTiming {
  id: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
}
export type TimingEntry =
  | { state: 'ready'; run: RunTiming }
  | { state: 'loading'; status: string }
  | { state: 'error'; status: string; retryAt: number };
export type TimingEntries = Readonly<Record<string, TimingEntry>>;
export interface TimeDisplay {
  value: string | null;
  label: string;
}

const unstarted = new Set(['pending', 'waiting', 'scheduled']);
const terminal = new Set(['completed', 'failed', 'cancelled']);
const active = new Set([...unstarted, 'running']);
const absent = (label: string): TimeDisplay => ({ value: null, label });
const recorded = (value: string): TimeDisplay => ({ value, label: '' });

export function formatTaskTime(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value;
  return {
    date: `${part('year')}-${part('month')}-${part('day')}`,
    time: `${part('hour')}:${part('minute')}:${part('second')}`,
  };
}

export function formatTaskDuration(durationMs: number): string {
  const seconds = Math.round(durationMs / 1000);
  if (seconds < 1) return '不足 1 秒';
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const restSeconds = seconds % 60;
  if (minutes < 60) return `${minutes} 分 ${restSeconds} 秒`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分 ${restSeconds} 秒`;
}

function reusable(entry: TimingEntry | undefined, run: RunSummary) {
  return (
    entry?.state === 'ready' &&
    (entry.run.status === run.status || (terminal.has(entry.run.status) && active.has(run.status)))
  );
}

function runTimes(run: RunSummary, entry: TimingEntry | undefined) {
  if (unstarted.has(run.status)) return { start: absent('未启动'), end: absent('未结束') };
  const unavailable = absent(entry?.state === 'error' ? '读取失败' : '加载中…');
  if (!reusable(entry, run) || entry?.state !== 'ready') {
    return { start: unavailable, end: terminal.has(run.status) ? unavailable : absent('未结束') };
  }
  const start = formatTaskTime(entry.run.started_at)
    ? recorded(entry.run.started_at!)
    : absent(
        entry.run.started_at === null && ['failed', 'cancelled'].includes(run.status)
          ? '未启动'
          : '未记录',
      );
  const end = !terminal.has(run.status)
    ? absent('未结束')
    : formatTaskTime(entry.run.completed_at)
      ? recorded(entry.run.completed_at!)
      : absent('未记录');
  return { start, end };
}

function aggregate(values: TimeDisplay[], end: boolean): TimeDisplay {
  if (!values.length) return absent('未记录');
  if (end && values.some((v) => v.label === '未结束')) return absent('未结束');
  for (const label of ['读取失败', '加载中…', '未记录']) {
    if (values.some((v) => v.label === label)) return absent(label);
  }
  const timestamps = values.flatMap((v) => (v.value ? [v.value] : []));
  if (!timestamps.length) return absent(end ? '未记录' : '未启动');
  return recorded(
    timestamps.reduce((a, b) =>
      (end ? Date.parse(a) > Date.parse(b) : Date.parse(a) < Date.parse(b)) ? a : b,
    ),
  );
}

export function taskTiming(task: Pick<TaskListSummary, 'runs'>, entries: TimingEntries) {
  const sides = task.runs.map((run, index) => ({
    id: run.run_id,
    label: index === 0 ? 'A' : index === 1 ? 'B' : String(index + 1),
    ...runTimes(run, entries[run.run_id]),
  }));
  return {
    start: aggregate(
      sides.map((s) => s.start),
      false,
    ),
    end: aggregate(
      sides.map((s) => s.end),
      true,
    ),
    sides,
  };
}

// Existing /samples responses also contain manifests/results. Keep only these four fields.
export function readRunTiming(value: unknown, expectedId: string): RunTiming {
  const run = (value as { run?: RunTiming } | null)?.run;
  if (!run || run.id !== expectedId || ![...active, ...terminal].includes(run.status)) {
    throw new Error('运行时间不可用');
  }
  const timestamp = (value: unknown) =>
    typeof value === 'string' || value === null ? value : undefined;
  return {
    id: run.id,
    status: run.status,
    started_at: timestamp(run.started_at),
    completed_at: timestamp(run.completed_at),
  };
}

export async function loadRunTimings(options: {
  runs: RunSummary[];
  entries: TimingEntries;
  read: (id: string, signal: AbortSignal) => Promise<RunTiming>;
  update: (id: string, entry: TimingEntry) => void;
  signal: AbortSignal;
  now?: number;
}) {
  const now = options.now ?? Date.now();
  const queue = [...new Map(options.runs.map((run) => [run.run_id, run])).values()].filter(
    (run) => {
      const entry = options.entries[run.run_id];
      return (
        !unstarted.has(run.status) &&
        !reusable(entry, run) &&
        !(entry?.state === 'error' && entry.status === run.status && entry.retryAt > now)
      );
    },
  );
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(3, queue.length) }, async () => {
      while (!options.signal.aborted && next < queue.length) {
        const run = queue[next++];
        options.update(run.run_id, { state: 'loading', status: run.status });
        try {
          const timing = await options.read(run.run_id, options.signal);
          if (!options.signal.aborted) options.update(run.run_id, { state: 'ready', run: timing });
        } catch {
          if (!options.signal.aborted) {
            options.update(run.run_id, {
              state: 'error',
              status: run.status,
              retryAt: now + 30_000,
            });
          }
        }
      }
    }),
  );
}
