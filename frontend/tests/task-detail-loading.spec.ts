import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';

let server: ViteDevServer;
let url: string;
const html = `<!doctype html><html><body><div id="app"></div><script type="module">
import { createApp, h } from 'vue';
import { createRouter, createWebHashHistory, RouterView } from 'vue-router';
import ElementPlus from 'element-plus';
import { pinia } from '/src/stores/index.ts';
import { useAuthStore } from '/src/stores/modules/auth.ts';
import Root from '/src/views/evaluation/index.vue';
import '/node_modules/element-plus/dist/index.css';
const auth = useAuthStore(pinia);
if (new URL(location.href).searchParams.get('bank')) auth.loginBank('test-token', 'team-a', 'Team A');
else auth.loginExternal();
const router = createRouter({history:createWebHashHistory(),routes:[{path:'/:pathMatch(.*)*',component:Root}]});
const app = createApp({render:()=>h(RouterView)}).use(pinia).use(router).use(ElementPlus);
window.detailHarness = {router, auth, unmount: () => app.unmount()};
app.mount('#app');
</script></body></html>`;

test.beforeAll(async () => {
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') },
    plugins: [
      vue(),
      {
        name: 'task-detail-loading-test',
        configureServer(instance) {
          instance.middlewares.use('/__task-detail', async (_req, res, next) => {
            try {
              res.setHeader('Content-Type', 'text/html');
              res.end(await instance.transformIndexHtml('/__task-detail', html));
            } catch (error) {
              next(error);
            }
          });
        },
      },
    ],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('No test server');
  url = `http://127.0.0.1:${address.port}/__task-detail`;
});
test.afterAll(async () => {
  await server?.close();
});

const now = '2026-10-23T02:00:00Z';
const cases = Array.from({ length: 7 }, (_, i) => ({
  id: `case-${i + 1}`,
  name: `样本 ${i + 1}`,
  tags: [i % 2 ? 'B' : 'A'],
  turns: [{ id: 'turn-1', input: `问题 ${i + 1}`, expectations: [] }],
}));
const manifest = {
  target: {
    display_name: '智能体',
    ref: {
      source_id: 'bank',
      target_type: 'agent',
      external_target_id: 'agent',
      external_version_id: 'v1',
    },
  },
  dataset: {
    dataset_id: 'dataset',
    dataset_name: '测评集',
    version: 1,
    content_sha256: 'a'.repeat(64),
    cases,
  },
  selected_case_ids: null,
  evaluator_specs: [
    {
      id: 'rule',
      name: '规则',
      version: '1',
      kind: 'rule',
      content_sha256: 'b'.repeat(64),
      config: {},
    },
  ],
  primary_evaluator_ids: ['rule'],
  metric_plan: {},
  gate_spec: {},
  max_parallel_cases: 1,
  timeout_seconds: 300,
  max_retries: 0,
};
const results = cases.map((c) => ({
  case_id: c.id,
  evaluator_id: 'rule',
  evaluator_name: '规则',
  evaluator_version: '1',
  evaluator_kind: 'rule',
  metric: 'overall',
  outcome: 'pass',
  score: 1,
  reason: '通过',
  checks: [],
  details: {},
  evidence: [],
}));
const task = (id: string) => ({
  id,
  name: `任务 ${id}`,
  kind: id === 'ab' ? 'ab' : 'single',
  run_ids: id === 'ab' ? ['run-a', 'run-b'] : [`${id}-run`],
  static_report_ids: [],
});
const run = (id: string, status: string) => ({
  id,
  status,
  created_at: now,
  manifest,
  completed_at: status === 'completed' ? now : null,
});

async function setup(page: Page, options: { status?: string; associationStatus?: number } = {}) {
  const calls: { path: string; headers: Record<string, string> }[] = [];
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  let status = options.status ?? 'completed';
  let rerunCreated = false;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push({ path, headers: route.request().headers() });
    const reply = (data: unknown) =>
      route.fulfill({ json: { code: '0', message: 'success', data } });
    if (path.startsWith('/api/stability-experiments/'))
      return reply({
        experiment: { id: 'stable', run_ids: ['stable-run'], created_at: now },
        runs: [{ progress: { run_id: 'stable-run', status, total_cases: 7, completed_cases: 1 },
          score: null, outcome: null }],
        measured_runs: 0, mean: null, sample_variance: null, sample_stddev: null,
        min: null, max: null, complete: ['completed', 'failed', 'cancelled'].includes(status),
      });
    // Bulk reads are deliberately unavailable: detail rendering must not depend on them.
    if (path === '/api/runs' || path === '/api/evaluation-tasks')
      return route.fulfill({
        status: 500,
        json: { detail: 'Unrelated bulk query must not be called' },
      });
    if (path === '/api/evaluation-tasks/task/rerun' && route.request().method() === 'POST') {
      rerunCreated = true;
      return reply({ ...task('task'), run_ids: ['new-run'] });
    }
    if (path.startsWith('/api/evaluation-tasks/')) {
      if (options.associationStatus)
        return route.fulfill({
          status: options.associationStatus,
          json: { detail: 'Task unavailable' },
        });
      const detail = task(path.split('/').pop()!);
      return reply(
        rerunCreated && detail.id === 'task' ? { ...detail, run_ids: ['new-run'] } : detail,
      );
    }
    if (path === '/api/run-comparisons')
      return reply({
        baseline_run_id: 'run-a',
        candidate_run_id: 'run-b',
        overall_score_delta: 0,
        metric_deltas: [],
        case_deltas: [],
      });
    const id = path.split('/')[3];
    if (path.endsWith('/manifest')) return reply(manifest);
    if (path.endsWith('/status'))
      return reply({
        run_id: id,
        status,
        total_cases: 7,
        completed_cases: status === 'completed' ? 7 : 1,
        progress: status === 'completed' ? 1 : 1 / 7,
        created_at: now,
      });
    if (path.endsWith('/samples')) return reply({ run: run(id, status), results, complete: false });
    if (path.includes('/traces/')) {
      const caseId = path.split('/').pop()!;
      return reply({
        trace_id: `trace-${id}-${caseId}`,
        case_id: caseId,
        turn_outcomes: { 'turn-1': { output: `回答 ${caseId}` } },
        spans: [
          {
            span_id: caseId,
            name: caseId,
            operation_type: 'case',
            attributes: {},
            started_at: now,
            ended_at: '2026-10-23T02:00:02Z',
          },
        ],
      });
    }
    if (/^\/api\/runs\/[^/]+$/.test(path))
      return reply({
        run: run(id, status),
        results,
        metrics: [{ level: 'overall', key: 'overall', score: 1 }],
        release_gate: { outcome: 'pass' },
      });
    return route.fulfill({ status: 404, json: { detail: `Unexpected API ${path}` } });
  });
  return {
    calls,
    errors,
    setStatus: (next: string) => {
      status = next;
    },
  };
}
const count = (calls: { path: string }[], path: string) =>
  calls.filter((c) => c.path === path).length;
async function visibility(page: Page, hidden: boolean) {
  await page.evaluate((value) => {
    Object.defineProperty(document, 'hidden', { configurable: true, value });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);
}
const traces = (calls: { path: string }[]) => calls.filter((c) => c.path.includes('/traces/'));
async function open(page: Page, path = '/tasks/task', bank = false) {
  await page.goto(`${url}${bank ? '?bank=1' : ''}#${path}`);
}

for (const bank of [false, true]) {
  test(`detail uses only one task, status and report (${bank ? 'bank' : 'external'})`, async ({
    page,
  }) => {
    const state = await setup(page);
    await open(page, '/tasks/task', bank);
    await expect(page.getByRole('heading', { name: '任务 task', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '样本详情', exact: true })).toHaveCount(7);
    expect(state.calls.map((c) => c.path)).toEqual([
      '/api/evaluation-tasks/task',
      '/api/runs/task-run/status',
      '/api/runs/task-run',
    ]);
    if (bank)
      expect(
        state.calls.every(
          (c) => c.headers['token'] === 'test-token' && c.headers['x-team-id'] === 'team-a',
        ),
      ).toBe(true);
    else
      expect(state.calls.every((c) => !c.headers['token'] && !c.headers['x-team-id'])).toBe(true);
    expect(state.errors).toEqual([]);
  });
}

test('sample navigation loads selected traces only and reuses task, report and trace', async ({
  page,
}) => {
  const state = await setup(page);
  await open(page);
  await page.getByRole('button', { name: '样本详情', exact: true }).first().click();
  await expect(page.getByText('回答 case-1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(page.getByText('回答 case-2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await expect(page.getByText('回答 case-1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await expect(page.getByRole('heading', { name: '任务 task', exact: true })).toBeVisible();
  expect(traces(state.calls).map((c) => c.path)).toEqual([
    '/api/runs/task-run/traces/case-1',
    '/api/runs/task-run/traces/case-2',
  ]);
  expect(count(state.calls, '/api/evaluation-tasks/task')).toBe(1);
  expect(count(state.calls, '/api/runs/task-run')).toBe(1);
  expect(state.errors).toEqual([]);
});

test('direct sample link reads only its trace and can retry an unavailable trace', async ({
  page,
}) => {
  const state = await setup(page);
  await page.route('**/api/runs/task-run/traces/case-3', (route) =>
    route.fulfill({ status: 503, json: { detail: 'temporary trace failure' } }),
  );
  await open(page, '/tasks/task/samples/case-3');
  await expect(page.getByRole('button', { name: '重试读取轨迹' })).toBeVisible();
  await page.unroute('**/api/runs/task-run/traces/case-3');
  await page.getByRole('button', { name: '重试读取轨迹' }).click();
  await expect(page.getByText('回答 case-3', { exact: true })).toBeVisible();
  expect(traces(state.calls).map((c) => c.path)).toEqual(['/api/runs/task-run/traces/case-3']);
  expect(state.errors).toEqual([]);
});

test('CSV waits for selected rows traces, preserves duration and does not refetch cached traces', async ({
  page,
}) => {
  const state = await setup(page);
  await open(page);
  await page.getByRole('button', { name: '样本详情', exact: true }).first().click();
  await expect(page.getByText('回答 case-1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await page.getByLabel('样本场景', { exact: true }).selectOption('A');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出 CSV', exact: true }).click();
  const csv = await readFile((await (await download).path())!, 'utf8');
  expect(csv).toContain('耗时（秒）');
  expect(csv.trim().split('\r\n')).toHaveLength(5);
  expect(
    csv
      .trim()
      .split('\r\n')
      .slice(1)
      .every((row) => row.endsWith(',"2"')),
  ).toBe(true);
  expect(
    traces(state.calls)
      .map((c) => c.path.split('/').pop())
      .sort(),
  ).toEqual(['case-1', 'case-3', 'case-5', 'case-7']);
  expect(state.errors).toEqual([]);
});

test('failed export is explicit and retry retrieves missing traces before downloading', async ({
  page,
}) => {
  const state = await setup(page);
  const downloads: string[] = [];
  page.on('download', (d) => downloads.push(d.suggestedFilename()));
  await page.route('**/api/runs/task-run/traces/case-1', (route) =>
    route.fulfill({ status: 503, json: { detail: 'trace unavailable' } }),
  );
  await open(page);
  await page.getByRole('button', { name: '导出 CSV', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('未导出');
  expect(downloads).toEqual([]);
  await page.unroute('**/api/runs/task-run/traces/case-1');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出 CSV', exact: true }).click();
  await download;
  expect(traces(state.calls)).toHaveLength(7);
  expect(state.errors).toEqual([]);
});

test('running task keeps polling current run and stops when completed', async ({ page }) => {
  const state = await setup(page, { status: 'running' });
  await page.clock.install();
  await open(page);
  await expect(page.getByRole('heading', { name: '任务 task', exact: true })).toBeVisible();
  expect(count(state.calls, '/api/runs/task-run/samples')).toBe(1);
  state.setStatus('completed');
  await page.clock.fastForward(5100);
  await expect(page.getByText('100%', { exact: true }).first()).toBeVisible();
  const requests = state.calls.length;
  await page.clock.fastForward(15000);
  expect(state.calls).toHaveLength(requests);
  expect(count(state.calls, '/api/evaluation-tasks/task')).toBe(1);
  expect(traces(state.calls)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

for (const detail of [
  { name: 'single', route: '/tasks/task', endpoint: '/api/runs/task-run/status' },
  { name: 'ab', route: '/tasks/ab', endpoint: '/api/runs/run-a/status' },
  { name: 'stability', route: '/stability/stable', endpoint: '/api/stability-experiments/stable' },
]) {
  for (const bank of [false, true]) {
    test(`${detail.name} polls at 5s, pauses hidden, resumes, stops and cleans up (${bank ? 'bank' : 'external'})`, async ({ page }) => {
      const state = await setup(page, { status: 'running' });
      await page.clock.install();
      await open(page, detail.route, bank);
      await expect.poll(() => count(state.calls, detail.endpoint)).toBe(1);
      await page.clock.fastForward(4000);
      expect(count(state.calls, detail.endpoint)).toBe(1);
      await page.clock.fastForward(1100);
      await expect.poll(() => count(state.calls, detail.endpoint)).toBe(2);
      await visibility(page, true);
      await page.clock.fastForward(30000);
      expect(count(state.calls, detail.endpoint)).toBe(2);
      await visibility(page, false);
      await expect.poll(() => count(state.calls, detail.endpoint)).toBe(3);
      state.setStatus('completed');
      await page.clock.fastForward(5100);
      await expect.poll(() => count(state.calls, detail.endpoint)).toBe(4);
      await page.clock.fastForward(30000);
      expect(count(state.calls, detail.endpoint)).toBe(4);
      if (bank) expect(state.calls.every(c => c.headers['token'] === 'test-token')).toBe(true);
      else expect(state.calls.every(c => !c.headers['token'])).toBe(true);
      await page.evaluate(() => (window as any).detailHarness.unmount());
      await visibility(page, true);
      await visibility(page, false);
      await page.clock.fastForward(30000);
      expect(count(state.calls, detail.endpoint)).toBe(4);
      expect(state.errors).toEqual([]);
    });
  }

  test(`${detail.name} ignores a response from before the tab was hidden`, async ({ page }) => {
    const state = await setup(page, { status: 'running' });
    let release!: () => void;
    const hold = new Promise<void>(resolve => { release = resolve; });
    let delayed = false;
    await page.route(`**${detail.endpoint}`, async route => {
      if (delayed) return route.fallback();
      delayed = true;
      await hold;
      const data = detail.name === 'stability'
        ? { experiment: { id: 'stable', run_ids: [], created_at: now }, runs: [],
            measured_runs: 0, mean: null, min: null, max: null, complete: true }
        : { run_id: detail.name === 'ab' ? 'run-a' : 'task-run', status: 'completed',
            total_cases: 7, completed_cases: 7, progress: 1, created_at: now };
      await route.fulfill({ json: { code: '0', message: 'success', data } });
    });
    await page.clock.install();
    await open(page, detail.route);
    await expect.poll(() => delayed).toBe(true);
    await visibility(page, true);
    await page.clock.fastForward(30000);
    expect(count(state.calls, detail.endpoint)).toBe(0);
    await visibility(page, false);
    await expect.poll(() => count(state.calls, detail.endpoint)).toBe(1);
    release();
    await page.clock.fastForward(5100);
    await expect.poll(() => count(state.calls, detail.endpoint)).toBe(2);
    await page.clock.fastForward(5100);
    await expect.poll(() => count(state.calls, detail.endpoint)).toBe(3);
    if (detail.name === 'single') expect(count(state.calls, '/api/runs/task-run')).toBe(0);
    await page.evaluate(() => (window as any).detailHarness.unmount());
    expect(state.errors).toEqual([]);
  });
}

test('embedded A/B reads only the two associated runs and both side details still open', async ({
  page,
}) => {
  const state = await setup(page);
  await open(page, '/tasks/ab');
  await expect(page.getByTestId('comparison-results')).toBeVisible();
  for (const side of ['A', 'B']) {
    await page.getByRole('button', { name: `实验 ${side} · 运行完成`, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '实验运行详情' });
    await expect(dialog.getByRole('button', { name: '样本详情', exact: true })).toHaveCount(7);
    await dialog.getByRole('button', { name: 'Close this dialog' }).click();
  }
  expect(
    state.calls.some((c) => c.path === '/api/runs' || c.path === '/api/evaluation-tasks'),
  ).toBe(false);
  expect(traces(state.calls)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test('A/B candidate sample navigation retains candidate run identity', async ({ page }) => {
  const state = await setup(page);
  await open(page, '/tasks/ab');
  await page.getByRole('button', { name: '实验 B · 运行完成', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '实验运行详情' });
  await dialog.getByRole('button', { name: '样本详情', exact: true }).first().click();
  await expect(page.getByText('回答 case-1', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/tasks\/ab\/samples\/case-1\?run=run-b$/);
  expect(traces(state.calls).map((c) => c.path)).toEqual(['/api/runs/run-b/traces/case-1']);
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await expect(page.getByTestId('comparison-results')).toBeVisible();
  expect(
    state.calls.some((c) => c.path === '/api/runs' || c.path === '/api/evaluation-tasks'),
  ).toBe(false);
  expect(state.errors).toEqual([]);
});

test('task and team changes reload context and run with current identity', async ({ page }) => {
  const state = await setup(page);
  await open(page);
  await expect(page.getByRole('button', { name: '样本详情', exact: true })).toHaveCount(7);
  await page.evaluate(() => (window as any).detailHarness.router.push('/tasks/other'));
  await expect(page.getByRole('heading', { name: '任务 other', exact: true })).toBeVisible();
  expect(count(state.calls, '/api/evaluation-tasks/other')).toBe(1);
  expect(count(state.calls, '/api/runs/other-run')).toBe(1);
  await page.evaluate(() =>
    (window as any).detailHarness.auth.loginBank('new-token', 'team-b', 'Team B'),
  );
  await expect.poll(() => count(state.calls, '/api/runs/other-run')).toBe(2);
  expect(state.calls.at(-1)?.headers['token']).toBe('new-token');
  expect(state.calls.at(-1)?.headers['x-team-id']).toBe('team-b');
  expect(state.errors).toEqual([]);
});

test('query-only tab navigation updates the tab without reloading the report', async ({ page }) => {
  const state = await setup(page);
  await open(page);
  await expect(page.getByRole('button', { name: '样本详情', exact: true })).toHaveCount(7);
  await page.evaluate(() =>
    (window as any).detailHarness.router.push('/tasks/task?tab=low-samples'),
  );
  await expect(page.getByRole('button', { name: '低分样本', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.evaluate(() => (window as any).detailHarness.router.push('/tasks/task'));
  await expect(page.getByRole('button', { name: '执行结果', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(count(state.calls, '/api/runs/task-run')).toBe(1);
  expect(state.errors).toEqual([]);
});

test('rerun refreshes the run binding without changing the task route or reusing old traces', async ({
  page,
}) => {
  const state = await setup(page);
  await open(page);
  await page.getByRole('button', { name: '任务快照', exact: true }).click();
  await page.getByRole('button', { name: '使用原配置重跑', exact: true }).click();
  await page
    .getByRole('dialog', { name: '重新运行当前任务' })
    .getByRole('button', { name: '开始测评', exact: true })
    .click();
  await expect.poll(() => count(state.calls, '/api/runs/new-run')).toBe(1);
  await expect(page).toHaveURL(/#\/tasks\/task$/);
  expect(count(state.calls, '/api/evaluation-tasks/task')).toBe(2);
  await page.getByRole('button', { name: '样本详情', exact: true }).first().click();
  await expect(page.getByText('回答 case-1', { exact: true })).toBeVisible();
  expect(traces(state.calls).map((c) => c.path)).toEqual(['/api/runs/new-run/traces/case-1']);
  expect(state.errors).toEqual([]);
});

test('a late trace response cannot replace the newly selected sample', async ({ page }) => {
  const state = await setup(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started = false;
  await page.route('**/api/runs/task-run/traces/case-1', async (route) => {
    started = true;
    await held;
    await route.fallback();
  });
  try {
    await open(page);
    await page.getByRole('button', { name: '样本详情', exact: true }).first().click();
    await expect.poll(() => started).toBe(true);
    await page.getByRole('button', { name: '下一条', exact: true }).click();
    await expect(page.getByText('回答 case-2', { exact: true })).toBeVisible();
    release();
    await expect.poll(() => count(state.calls, '/api/runs/task-run/traces/case-1')).toBe(1);
    await expect(page.getByText('回答 case-2', { exact: true })).toBeVisible();
    await expect(page.getByText('回答 case-1', { exact: true })).toHaveCount(0);
    expect(state.errors).toEqual([]);
  } finally {
    release();
  }
});

test('403 is surfaced without bypassing task access checks; standalone 404 still uses run authorization', async ({
  page,
}) => {
  const state = await setup(page, { associationStatus: 403 });
  await open(page);
  await expect(page.getByRole('alert')).toContainText('Task unavailable');
  expect(state.calls.map((c) => c.path)).toEqual(['/api/evaluation-tasks/task']);
  await page.unroute('**/api/**');
  const standalone = await setup(page, { associationStatus: 404 });
  await open(page, '/results/standalone');
  await expect(page.getByRole('button', { name: '样本详情', exact: true })).toHaveCount(7);
  expect(standalone.calls.map((c) => c.path)).toEqual([
    '/api/evaluation-tasks/standalone',
    '/api/runs/standalone/status',
    '/api/runs/standalone',
  ]);
  expect(standalone.errors).toEqual([]);
});
