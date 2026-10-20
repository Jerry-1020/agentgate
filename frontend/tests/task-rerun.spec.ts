import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

let server: ViteDevServer;
let url: string;
const fixture = `<!doctype html><html><head><title>任务重跑测试</title></head><body><div id="app"></div><script type="module">
import { createApp, h } from 'vue';
import { createRouter, createWebHashHistory, RouterView } from 'vue-router';
import ElementPlus from 'element-plus';
import { pinia } from '/src/stores/index.ts';
import Root from '/src/views/evaluation/index.vue';
import { setBuiltinEnabled } from '/src/views/evaluation/utils/evaluator-preferences.ts';
import '/node_modules/element-plus/dist/index.css';
const router = createRouter({ history: createWebHashHistory(), routes: [{ path: '/:pathMatch(.*)*', component: Root }] });
window.testRouter = router;
window.disableEvaluator = () => setBuiltinEnabled('judge', false);
createApp({ render: () => h(RouterView) }).use(pinia).use(router).use(ElementPlus).mount('#app');
</script></body></html>`;

test.beforeAll(async () => {
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') },
    plugins: [vue(), {
      name: 'task-rerun-test',
      configureServer(instance) {
        instance.middlewares.use('/__task-rerun', async (_req, res, next) => {
          try {
            res.setHeader('Content-Type', 'text/html');
            res.end(await instance.transformIndexHtml('/__task-rerun', fixture));
          } catch (error) { next(error); }
        });
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('No test server');
  url = `http://127.0.0.1:${address.port}/__task-rerun#/tasks`;
});
test.afterAll(async () => { await server?.close(); });

const now = new Date().toISOString();
const manifest = {
  target: {
    ref: { source_id: 'bank', target_type: 'agent', external_target_id: 'agent-1', external_version_id: '2026-05-06 17:21:16' },
    display_name: '基础编排智能体', descriptor_sha256: 'a'.repeat(64), adapter_type: 'inbank_chatabc',
    adapter_version: '1', invocation_config: { arrange_type: 'base', agent_version: '2026-05-06 17:21:16' },
    credential_ref: 'encrypted-key-ref',
  },
  dataset: { dataset_id: 'dataset', dataset_name: '原测评集', version: 2, cases: [
    { id: 'case-1', name: '原样本', tags: [], turns: [{ id: 'turn-1', input: { txt: '测试' }, expectations: [] }] },
  ] },
  selected_case_ids: null,
  evaluator_specs: [{ id: 'judge', name: '原评估器', version: '1', kind: 'rule', dimension: 'answer', metric: 'accuracy', config: {} }],
  primary_evaluator_ids: ['judge'], metric_plan: {}, gate_spec: {},
  timeout_seconds: 300, max_parallel_cases: 1, max_retries: 0,
};
const run = (id: string, status = 'completed') => ({ id, status, created_at: now, manifest });
const task = (runId = 'old-run', history: string[] = []) => ({
  id: 'original-task', name: '原任务名称', kind: 'single', created_at: now,
  run_ids: [runId], previous_run_ids: history, static_report_ids: [],
});

async function open(page: Page, options: { history?: boolean; status?: string; grouped?: boolean; hold?: boolean; overflow?: boolean } = {}) {
  page.on('pageerror', error => console.log('Page error:', error.message));
  page.on('console', message => { if (message.type() === 'error') console.log('Console error:', message.text()); });
  let tasks = [task(options.history ? 'current-run' : 'old-run', options.history ? ['old-run'] : [])];
  let runs = options.history ? [run('current-run'), run('old-run')] : [run('old-run', options.status)];
  if (options.overflow) {
    const history = Array.from({ length: 199 }, (_, index) => `history-${index}`);
    tasks = [task('current-run', history), { ...task('unrelated-run'), id: 'unrelated-task', name: '另一个任务' }];
    runs = [run('current-run'), ...history.map(id => run(id)), run('unrelated-run')];
  }
  if (options.grouped) {
    tasks = [
      { ...task('a'), kind: 'ab', run_ids: ['a', 'b'] },
      { ...task('s1'), id: 'stability-task', kind: 'stability', run_ids: ['s1', 's2'] },
    ];
    runs = ['a', 'b', 's1', 's2'].map(id => run(id));
  }
  const writes: { method: string; path: string; body: any }[] = [];
  let release: (() => void) | undefined;
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const method = req.method();
    const respond = (data: unknown) => route.fulfill({ json: { code: '0', message: 'success', data } });
    if (method === 'POST' && path.endsWith('/rerun')) {
      writes.push({ method, path, body: req.postDataJSON() });
      if (options.hold) await new Promise<void>(resolve => { release = resolve; });
      const source = tasks[0].run_ids[0];
      tasks = [task('new-run', [...tasks[0].previous_run_ids, source])];
      runs = [run('new-run', 'pending'), ...runs];
      return respond(tasks[0]);
    }
    if (method === 'DELETE') {
      writes.push({ method, path, body: null }); tasks = []; runs = [];
      return respond({ deleted: 'original-task' });
    }
    if (path === '/api/overview') return respond({ total_runs: runs.length, completed_runs: 1, running_runs: 0, pending_runs: 0, failed_runs: 0, cancelled_runs: 0, dataset_count: 1, case_count: 1 });
    if (path === '/api/runs') return respond(runs.slice(0, 200));
    if (path === '/api/evaluation-tasks') return respond(tasks);
    if (path.endsWith('/manifest')) return respond(manifest);
    const id = path.split('/')[3], current = runs.find(r => r.id === id);
    if (path.endsWith('/status')) return respond({ run_id: id, status: current?.status ?? 'pending', completed_cases: current?.status === 'completed' ? 1 : 0, total_cases: 1 });
    if (path.endsWith('/samples')) return respond({ run: current, results: [], complete: false });
    if (/\/api\/runs\/[^/]+$/.test(path)) return respond({ run: current, results: [], metrics: [{ level: 'overall', score: .8 }], release_gate: { status: 'pass' } });
    if (path.includes('/traces/')) return respond({ spans: [] });
    return respond([]);
  });
  await page.goto(url);
  await expect(page.getByRole('heading', { name: '测评任务', exact: true })).toBeVisible();
  return { writes, release: () => release?.() };
}

for (const status of ['completed', 'failed', 'cancelled']) {
  test(`single ${status} task previews original settings and submits only on confirmation`, async ({ page }) => {
    const state = await open(page, { status });
    await page.getByRole('button', { name: '重跑', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '重新运行当前任务' });
    await expect(dialog).toContainText('将该任务按照原始配置重新运行一次，该任务原始运行结果保留。');
    await expect(dialog.getByTestId('run-configuration')).toBeVisible();
    await expect(dialog).toContainText('2026-05-06 17:21:16');
    await expect(dialog).toContainText('原测评集');
    expect(state.writes).toEqual([]);
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(state.writes).toEqual([]);
  });
}

test('confirmation retains task URL and one row, replaces latest progress and prevents double submission', async ({ page }) => {
  const state = await open(page, { hold: true });
  await page.getByRole('button', { name: '重跑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '重新运行当前任务' });
  const confirm = dialog.getByRole('button', { name: '开始测评', exact: true });
  await confirm.click();
  await expect(confirm).toBeDisabled();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toEqual({ method: 'POST', path: '/api/evaluation-tasks/original-task/rerun', body: { source_run_id: 'old-run' } });
  state.release();
  await expect(page).toHaveURL(/#\/tasks\/original-task$/);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('排队中', { exact: true }).first()).toBeVisible();
  await page.evaluate(() => (window as any).testRouter.push('/tasks'));
  const rows = page.locator('.tasks-list tbody tr');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('原任务名称');
  await expect(rows.first()).toContainText('排队中');
  await expect(rows.first()).not.toContainText('80.0');
  expect(state.writes).toHaveLength(1);
});

test('reload hides historical rows and deletion uses stable task ID', async ({ page }) => {
  const state = await open(page, { history: true });
  const rows = page.locator('.tasks-list tbody tr');
  await expect(rows).toHaveCount(1);
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await page.getByRole('button', { name: '永久删除', exact: true }).click();
  await expect(rows).toHaveCount(0);
  expect(state.writes).toEqual([{ method: 'DELETE', path: '/api/evaluation-tasks/original-task', body: null }]);
});

for (const status of ['pending', 'waiting', 'running', 'scheduled']) {
  test(`active ${status} task has no rerun action`, async ({ page }) => {
    await open(page, { status });
    await expect(page.locator('.tasks-list tbody tr')).toHaveCount(1);
    await expect(page.getByRole('button', { name: '重跑', exact: true })).toHaveCount(0);
  });
}

test('A/B rerun is display-only and stability has no rerun action', async ({ page }) => {
  const state = await open(page, { grouped: true });
  await expect(page.locator('.tasks-list tbody tr')).toHaveCount(2);
  const abRow = page.locator('.tasks-list tbody tr').filter({ hasText: 'A/B试验' });
  const stabilityRow = page.locator('.tasks-list tbody tr').filter({ hasText: '稳定性测试' });
  await expect(stabilityRow.getByRole('button', { name: '重跑', exact: true })).toHaveCount(0);
  await abRow.getByRole('button', { name: '重跑', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '重新运行当前任务' })).toHaveCount(0);
  expect(state.writes).toEqual([]);
});

test('task rerun still honors locally disabled evaluators', async ({ page }) => {
  const state = await open(page);
  await page.evaluate(() => (window as any).disableEvaluator());
  await page.getByRole('button', { name: '重跑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '重新运行当前任务' });
  await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('禁用');
  expect(state.writes).toEqual([]);
});

test('task count does not increase for retained historical executions', async ({ page }) => {
  await open(page, { history: true });
  await page.getByRole('link', { name: '测评总览', exact: true }).click();
  await expect(page.locator('.overview-metrics article').first().locator('.metric-value')).toHaveText('1');
});

test('sample navigation retains the stable task identity', async ({ page }) => {
  await open(page, { history: true });
  await page.getByRole('button', { name: '原任务名称', exact: true }).click();
  await page.getByRole('button', { name: '样本详情', exact: true }).first().click();
  await expect(page).toHaveURL(/#\/tasks\/original-task\/samples\/case-1$/);
});

test('historical executions cannot evict another current task from the list', async ({ page }) => {
  await open(page, { overflow: true });
  await expect(page.locator('.tasks-list tbody tr')).toHaveCount(2);
  await expect(page.getByRole('button', { name: '另一个任务', exact: true })).toBeVisible();
});

test('task count uses durable task identities beyond the recent execution window', async ({ page }) => {
  await open(page, { overflow: true });
  await page.getByRole('link', { name: '测评总览', exact: true }).click();
  await expect(page.locator('.overview-metrics article').first().locator('.metric-value')).toHaveText('2');
});
