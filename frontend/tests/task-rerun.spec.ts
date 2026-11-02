import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
import type {
  RunState,
  TaskAction,
  TaskKind,
  TaskListSummary,
} from '../src/api/evaluation-summaries';

let server: ViteDevServer;
let url: string;
let listUrl: string;
const fixture = `<!doctype html><html><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue';
import {createRouter,createWebHashHistory,RouterView} from 'vue-router';
import ElementPlus from 'element-plus';
import {pinia} from '/src/stores/index.ts';
import {useAuthStore} from '/src/stores/modules/auth.ts';
import Root from '/src/views/evaluation/index.vue';
import {setBuiltinEnabled} from '/src/views/evaluation/utils/evaluator-preferences.ts';
import '/node_modules/element-plus/dist/index.css';
import '/src/styles/main.scss';
const router=createRouter({history:createWebHashHistory(),routes:[{path:'/:pathMatch(.*)*',component:Root}]});
window.testRouter=router;
window.disableEvaluator=()=>setBuiltinEnabled('judge',false);
window.logout=()=>useAuthStore(pinia).logout();
const auth=useAuthStore(pinia);
const mode=new URLSearchParams(location.search).get('mode');
if(mode==='bank')auth.loginBank('current-bank-token','team','测试团队');
else if(mode==='integrated')auth.initializePlatform({token:'current-bank-token',teamId:'team',teamName:'测试团队',userId:'user',userName:'测试用户'});
else auth.loginExternal();
createApp({render:()=>h(RouterView)}).use(pinia).use(router).use(ElementPlus).mount('#app');
</script></body></html>`;
test.beforeAll(async () => {
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') },
    plugins: [
      vue(),
      {
        name: 'rerun-test',
        configureServer(instance) {
          for (const [path, html] of [
            ['/__task-rerun', fixture],
            [
              '/__task-list-rerun',
              '<!doctype html><html><body><div id="app"></div><script type="module" src="/tests/evaluation-summary-harness.ts"></script></body></html>',
            ],
          ])
            instance.middlewares.use(path, async (_req, res, next) => {
              try {
                res.setHeader('Content-Type', 'text/html');
                res.end(await instance.transformIndexHtml(path, html));
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
  url = `http://127.0.0.1:${address.port}/__task-rerun`;
  listUrl = `http://127.0.0.1:${address.port}/__task-list-rerun`;
});
test.afterAll(async () => {
  await server?.close();
});
const now = new Date().toISOString();
const oldA = '2026-05-06 17:21:16',
  oldB = '2026-05-07 17:21:16',
  newVersion = '2026-05-08 17:21:16';
const cases = ['case-1', 'case-2'].map((id) => ({
  id,
  name: id,
  tags: [],
  initial_state: {},
  turns: [{ id: 'turn-1', input: { txt: '合成测试问题' }, expectations: [] }],
}));
type Mode = 'external' | 'bank' | 'integrated';
interface Options {
  mode?: Mode;
  kind?: 'single' | 'ab';
  status?: 'completed' | 'failed' | 'cancelled';
  missingVersion?: boolean;
  loadError?: boolean;
  rejectSubmission?: boolean;
  hold?: boolean;
  holdValidation?: boolean;
  adapter?: 'demo_loan' | 'local_bank';
  name?: string;
  claw?: boolean;
  staticAnalysis?: boolean;
  hybrid?: boolean;
}
async function open(page: Page, options: Options = {}) {
  const mode = options.mode ?? 'external',
    kind = options.kind ?? 'single',
    status = options.status ?? 'completed';
  const bank = mode !== 'external';
  const agentId =
    options.adapter === 'demo_loan'
      ? 'loan-agent'
      : options.adapter === 'local_bank'
        ? 'loan-base'
        : 'agent-1';
  const descriptor = {
    ref: {
      source_id: 'local',
      target_type: 'agent',
      external_target_id: agentId,
      external_version_id: oldA,
    },
    display_name: '原智能体',
    content_sha256: 'a'.repeat(64),
    metadata: {},
    tools: [],
    skills: [],
  };
  const adapter =
    options.adapter ??
    (bank ? (options.claw ? 'inbank_yunxia' : 'inbank_chatabc') : 'agent_platform_mock');
  const manifest = {
    target: {
      ...descriptor,
      adapter_type: adapter,
      descriptor_sha256: 'a'.repeat(64),
      invocation_config: options.claw
        ? { branch_id: 'original-branch', agent_version: oldA }
        : { arrange_type: 'workflow', agent_version: oldA },
    },
    dataset: { dataset_id: 'dataset', dataset_name: '原测评集', version: 2, cases },
    selected_case_ids: ['case-2'],
    evaluator_specs: [
      {
        id: 'judge',
        name: '原评估器',
        version: '1',
        kind: 'llm_judge',
        config: {},
        content_sha256: 'b'.repeat(64),
      },
      {
        id: 'judge-2',
        name: '辅助评估器',
        version: '2',
        kind: options.hybrid ? 'hybrid' : 'llm_judge',
        config: {},
        content_sha256: 'c'.repeat(64),
      },
    ],
    primary_evaluator_ids: ['judge-2', 'judge'],
    metric_plan: {},
    gate_spec: {},
    timeout_seconds: 147,
    max_parallel_cases: bank ? 3 : 4,
    max_retries: !options.adapter && !bank && kind === 'single' ? 2 : 0,
  };
  const original = {
    id: 'original-task',
    name: options.name ?? '原任务名称',
    kind,
    created_at: now,
    run_ids: kind === 'ab' ? ['old-a', 'old-b'] : ['old-a'],
    previous_run_ids: [],
    static_report_ids: options.staticAnalysis ? ['original-static'] : [],
  };
  const originalSnapshot = JSON.stringify(original);
  const tasks = [original];
  let loadError = !!options.loadError;
  let release: (() => void) | undefined;
  let releaseValidation: (() => void) | undefined;
  const writes: { method: string; path: string; body: any; headers: Record<string, string> }[] = [];
  const reads: string[] = [];
  const directory: { url: string; headers: Record<string, string> }[] = [];
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const summary = (task: typeof original) => ({
    id: task.id,
    task_id: task.id,
    name: task.name,
    kind: task.kind,
    created_at: now,
    status: task.id === original.id ? status : 'pending',
    summary_pending: false,
    total_cases: 1,
    completed_cases: 1,
    previous_run_count: 0,
    runs: task.run_ids.map((id, i) => ({
      run_id: id,
      status,
      summary_pending: false,
      target_name: '原智能体',
      target_version: i ? oldB : oldA,
      dataset_name: '原测评集',
      dataset_version: 2,
      evaluator_kinds: ['llm_judge'],
      scoring_mode: 'overall',
      total_cases: 1,
      completed_cases: 1,
      overall_score: 0.8,
      gate_reason: null,
    })),
  });
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const reply = (data: unknown) =>
      route.fulfill({ json: { code: '0', message: 'success', data } });
    if (req.method() !== 'GET') {
      writes.push({
        method: req.method(),
        path,
        body: req.postDataJSON(),
        headers: await req.allHeaders(),
      });
      if (options.hold)
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      if (options.rejectSubmission)
        return route.fulfill({ status: 422, json: { detail: 'Invalid target' } });
      if (req.method() === 'PUT' && path === '/api/evaluation-tasks/new-task') {
        Object.assign(tasks[1], { name: req.postDataJSON().name });
        return reply(tasks[1]);
      }
      if (path.endsWith('/rerun') || path.includes('/original-task'))
        return route.fulfill({ status: 500, json: { detail: 'Source must not be changed' } });
      if (
        [
          '/api/agent-platform/evaluations',
          '/api/agent-platform/comparisons',
          '/api/evaluations',
          '/api/bank-evaluations',
          '/api/run-comparisons',
        ].includes(path)
      ) {
        tasks.push({
          ...original,
          id: 'new-task',
          name: req.postDataJSON().name ?? '新任务',
          run_ids: kind === 'ab' ? ['new-task', 'new-b'] : ['new-task'],
        });
        if (kind === 'ab')
          return reply({ baseline: { run_id: 'new-task' }, candidate: { run_id: 'new-b' } });
        return reply(
          options.adapter
            ? { run_id: 'new-task' }
            : { id: 'new-task', kind: 'single', run_ids: ['new-task'] },
        );
      }
      return route.fulfill({ status: 500, json: { detail: 'Unexpected write' } });
    }
    reads.push(path);
    if (path === '/api/evaluation-task-summaries')
      return reply({ items: tasks.map(summary), total: tasks.length, page: 1, page_size: 20 });
    if (path === '/api/evaluation-tasks') return reply(tasks);
    if (path.startsWith('/api/evaluation-tasks/'))
      return reply(tasks.find((t) => t.id === path.split('/').pop()));
    if (path === '/api/datasets')
      return reply([
        { id: 'dataset', name: '原测评集', version: 3 },
        { id: 'other', name: '另一测评集', version: 1 },
      ]);
    if (path === '/api/evaluators')
      return reply(
        ['judge', 'judge-2'].map((id, i) => ({
          id,
          name: i ? '辅助评估器' : '原评估器',
          kind: i && options.hybrid ? 'hybrid' : 'llm_judge',
          enabled: true,
          latest_version: '9',
          source: 'builtin',
          description: '测试评估器',
          implementation_id: 'answer_quality',
        })),
      );
    if (/^\/api\/datasets\/[^/]+$/.test(path))
      return reply({
        versions: [
          { version: 1, cases },
          { version: 2, cases },
          { version: 3, cases },
        ],
      });
    if (path.includes('/datasets/')) {
      if (options.holdValidation)
        await new Promise<void>((resolve) => {
          releaseValidation = resolve;
        });
      return reply({ cases });
    }
    if (path === '/api/skill-analysis/reports/original-static')
      return reply({
        report: {
          target_ref: { external_version_id: oldA },
          target_descriptor_sha256: 'a'.repeat(64),
        },
      });
    if (path === '/api/local-targets')
      return reply({
        targets: options.adapter
          ? [oldA, oldB].map((version) => ({
              adapter_type: options.adapter,
              mode: options.adapter === 'local_bank' ? 'base' : null,
              descriptor: {
                ...descriptor,
                ref: { ...descriptor.ref, external_version_id: version },
              },
            }))
          : [],
        unavailable: [],
      });
    if (path === '/api/bank-targets') return reply([]);
    if (path === '/api/versions') return reply([oldA, oldB].map((id) => ({ id, label: id })));
    if (path.endsWith('/manifest')) {
      if (loadError)
        return route.fulfill({
          status: 503,
          json: { detail: 'Private internal error must not be exposed' },
        });
      return reply(
        path.includes('old-b')
          ? {
              ...manifest,
              target: {
                ...manifest.target,
                ref: { ...manifest.target.ref, external_version_id: oldB },
              },
            }
          : manifest,
      );
    }
    const id = path.split('/')[3];
    const run = {
      id,
      status: id.startsWith('new') ? 'pending' : status,
      manifest,
      created_at: now,
    };
    if (path.endsWith('/status'))
      return reply({
        run_id: id,
        status: run.status,
        total_cases: 1,
        completed_cases: 1,
        progress: 1,
        created_at: now,
      });
    if (path.endsWith('/samples')) return reply({ run, results: [], complete: false });
    if (/^\/api\/runs\/[^/]+$/.test(path))
      return reply({ run, results: [], metrics: [], release_gate: { outcome: 'pass' } });
    return reply({});
  });
  await page.route('**/web/**', async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    directory.push({ url: req.url(), headers: await req.allHeaders() });
    const versions = (options.missingVersion ? [oldB, newVersion] : [oldA, oldB, newVersion]).map(
      (v) => ({ agentVersion: v, updatedAt: v, branchId: 'original-branch' }),
    );
    const data = path.endsWith('/agents')
      ? {
          records: [
            { id: 'agent-1', name: '原智能体', agentType: options.claw ? 'abcclaw2' : 'workflow' },
          ],
          total: 1,
          current: 1,
          size: 1000,
          pages: 1,
        }
      : path.endsWith('branchTree')
        ? [{ branchId: 'original-branch', branchName: '原分支' }]
        : versions;
    return route.fulfill({
      json: path.endsWith('/agents') ? data : { code: '0', message: 'success', data },
    });
  });
  await page.goto(`${url}?mode=${mode}#/tasks`);
  await expect(page.getByRole('button', { name: original.name, exact: true })).toBeVisible();
  return {
    writes,
    reads,
    directory,
    errors,
    manifest,
    original,
    tasks,
    originalSnapshot,
    setLoadError: (value: boolean) => {
      loadError = value;
    },
    release: () => release?.(),
    releaseValidation: () => releaseValidation?.(),
  };
}
async function rerun(page: Page) {
  await page.getByRole('button', { name: '重跑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建测评任务', exact: true });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }),
  ).toBeEnabled();
  return dialog;
}
for (const mode of ['external', 'bank', 'integrated'] as const) {
  for (const kind of ['single', 'ab'] as const) {
    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      test(`${mode} ${kind} ${status}: copies exact configuration and creates an independent task`, async ({
        page,
      }) => {
        const state = await open(page, { mode, kind, status });
        const dialog = await rerun(page);
        await expect(dialog.getByLabel('任务名称', { exact: true })).toHaveValue('原任务名称_重跑');
        await expect(dialog.getByLabel('任务测评集版本', { exact: true })).toHaveValue('2');
        await expect(dialog.getByLabel('运行范围', { exact: true })).toHaveValue('selected');
        await expect(dialog.getByLabel('执行超时（秒）', { exact: true })).toHaveValue('147');
        await expect(dialog.getByLabel('并发样本数', { exact: true })).toHaveValue(
          String(state.manifest.max_parallel_cases),
        );
        if (kind === 'ab')
          await expect(
            dialog.locator('.platform-candidate-field .el-select__selected-item.el-select__placeholder'),
          ).toContainText(oldB);
        expect(state.writes).toEqual([]);
        await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
        await expect(page).toHaveURL(/#\/tasks\/new-task$/);
        expect(state.writes).toHaveLength(1);
        const write = state.writes[0];
        expect(write.path).toBe(
          kind === 'ab' ? '/api/agent-platform/comparisons' : '/api/agent-platform/evaluations',
        );
        expect(write.body).toMatchObject({
          name: '原任务名称_重跑',
          dataset_id: 'dataset',
          dataset_version: 2,
          case_ids: ['case-2'],
          evaluator_refs: [
            { evaluator_id: 'judge-2', evaluator_version: '2' },
            { evaluator_id: 'judge', evaluator_version: '1' },
          ],
          timeout_seconds: 147,
        });
        expect(write.body.target).toMatchObject(
          kind === 'ab'
            ? { agent_id: 'agent-1', baseline_version: oldA, candidate_version: oldB }
            : { agent_id: 'agent-1', agent_version: oldA },
        );
        expect(write.headers['x-agent-platform-token']).toBe(
          mode === 'external' ? 'local' : 'current-bank-token',
        );
        expect(write.body.max_parallel_cases).toBe(state.manifest.max_parallel_cases);
        if (kind === 'single')
          expect(write.body).toMatchObject({
            max_parallel_cases: state.manifest.max_parallel_cases,
            max_retries: state.manifest.max_retries,
          });
        expect(state.directory.length).toBeGreaterThan(0);
        expect(
          state.directory.every(
            (call) => new URL(call.url).port === (mode === 'external' ? '8119' : new URL(url).port),
          ),
        ).toBe(true);
        expect(
          state.directory.every(
            (call) =>
              call.headers.authorization ===
              `Bearer ${mode === 'external' ? 'local' : 'current-bank-token'}`,
          ),
        ).toBe(true);
        expect(JSON.stringify(state.original)).toBe(state.originalSnapshot);
        expect(state.tasks).toHaveLength(2);
        await page.evaluate(() => (window as any).testRouter.push('/tasks'));
        await expect(page.getByRole('button', { name: '原任务名称', exact: true })).toBeVisible();
        await expect(
          page.getByRole('button', { name: '原任务名称_重跑', exact: true }),
        ).toBeVisible();
        expect(state.errors).toEqual([]);
      });
    }
  }
}
for (const kind of ['single', 'ab'] as const) {
  test(`${kind}: edits copied configuration before creation`, async ({ page }) => {
    const state = await open(page, { mode: 'bank', kind });
    const dialog = await rerun(page);
    await dialog.getByLabel('任务名称', { exact: true }).fill('修改后的任务');
    await dialog.getByLabel('任务测评集', { exact: true }).selectOption('other');
    await expect(dialog.getByLabel('任务测评集版本', { exact: true })).toHaveValue('1');
    await dialog.getByLabel('运行范围', { exact: true }).selectOption('all');
    await dialog.getByLabel('执行超时（秒）', { exact: true }).fill('222');
    await dialog.getByLabel('并发样本数', { exact: true }).fill('5');
    if (kind === 'ab') {
      await dialog.getByRole('combobox', { name: '平台候选版本', exact: true }).press('Enter');
      await dialog.getByRole('option', { name: newVersion, exact: true }).click();
    }
    await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
    await expect(page).toHaveURL(/#\/tasks\/new-task$/);
    expect(state.writes[0].body).toMatchObject({
      name: '修改后的任务',
      dataset_id: 'other',
      dataset_version: 1,
      timeout_seconds: 222,
      max_parallel_cases: 5,
    });
    expect(state.writes[0].body.case_ids).toBeUndefined();
    if (kind === 'ab') expect(state.writes[0].body.target.candidate_version).toBe(newVersion);
    expect(JSON.stringify(state.original)).toBe(state.originalSnapshot);
  });
}
test('cancel leaves original records intact and creates nothing', async ({ page }) => {
  const state = await open(page, { kind: 'ab' });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(state.writes).toEqual([]);
  expect(state.tasks).toHaveLength(1);
});
test('missing original version is explicit and never selects a replacement', async ({ page }) => {
  const state = await open(page, { missingVersion: true });
  await page.getByRole('button', { name: '重跑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建测评任务' });
  await expect(dialog.getByRole('alert')).toContainText('原智能体版本不可用');
  await expect(
    dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }),
  ).toBeDisabled();
  expect(state.writes).toEqual([]);
});
test('loading failure is sanitized and can be retried', async ({ page }) => {
  const state = await open(page, { loadError: true });
  await page.getByRole('button', { name: '重跑', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('无法读取原任务');
  await expect(page.getByRole('alert')).not.toContainText('Private');
  state.setLoadError(false);
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByLabel('任务名称', { exact: true })).toHaveValue('原任务名称_重跑');
  expect(state.writes).toEqual([]);
});
test('submission failure retains edits and leaves the source intact', async ({ page }) => {
  const state = await open(page, { rejectSubmission: true });
  const dialog = await rerun(page);
  await dialog.getByLabel('任务名称', { exact: true }).fill('保留我的修改');
  await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByLabel('任务名称', { exact: true })).toHaveValue('保留我的修改');
  expect(state.writes).toHaveLength(1);
  expect(state.tasks).toHaveLength(1);
});
test('submission is locked until the creation request completes', async ({ page }) => {
  const state = await open(page, { hold: true });
  const dialog = await rerun(page);
  const submit = dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ });
  await submit.click();
  await expect(submit).toBeDisabled();
  await expect.poll(() => state.writes.length).toBe(1);
  state.release();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes).toHaveLength(1);
});
for (const adapter of ['demo_loan', 'local_bank'] as const) {
  test(`external ${adapter}: copies the local target without substituting a platform agent`, async ({
    page,
  }) => {
    const state = await open(page, { adapter });
    const dialog = await rerun(page);
    await expect(dialog.getByLabel('并发样本数', { exact: true })).toHaveValue('4');
    await dialog.getByLabel('并发样本数', { exact: true }).fill('7');
    await dialog.getByLabel('执行超时（秒）', { exact: true }).fill('200');
    await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
    await expect(page).toHaveURL(/#\/tasks\/new-task$/);
    expect(state.writes[0].path).toBe(
      adapter === 'local_bank' ? '/api/bank-evaluations' : '/api/evaluations',
    );
    expect(state.writes[0].body).toMatchObject({ max_parallel_cases: 7, timeout_seconds: 200 });
    expect(state.writes[0].body.evaluator_refs[0]).toEqual({
      evaluator_id: 'judge-2',
      evaluator_version: '2',
    });
    expect(state.writes.some((write) => write.path.includes('original-task'))).toBe(false);
  });
}
test('A/B demo restores both local versions', async ({ page }) => {
  const state = await open(page, { adapter: 'demo_loan', kind: 'ab' });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes[0]).toMatchObject({
    path: '/api/run-comparisons',
    body: {
      baseline_version: oldA,
      candidate_version: oldB,
      case_ids: ['case-2'],
      timeout_seconds: 147,
      max_parallel_cases: 4,
    },
  });
});
test('bank cloud agent restores its branch and both A/B versions', async ({ page }) => {
  const state = await open(page, { mode: 'bank', kind: 'ab', claw: true });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes[0].body.target).toMatchObject({
    branch_id: 'original-branch',
    type_group: 'abcclaw',
    baseline_version: oldA,
    candidate_version: oldB,
  });
});
test('external cloud agent restores its branch through the local directory', async ({ page }) => {
  const state = await open(page, { mode: 'external', kind: 'ab', claw: true });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: '创建 A/B试验', exact: true }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes[0].body.target).toMatchObject({
    branch_id: 'original-branch',
    type_group: 'abcclaw',
    baseline_version: oldA,
    candidate_version: oldB,
  });
  expect(state.writes[0].headers['x-agent-platform-token']).toBe('local');
});
test('copies immutable static-analysis links to the new local task', async ({ page }) => {
  const state = await open(page, { adapter: 'demo_loan', staticAnalysis: true });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(
    state.writes.find((write) => write.path === '/api/evaluation-tasks/new-task')?.body
      .static_report_ids,
  ).toEqual(['original-static']);
  expect(JSON.stringify(state.original)).toBe(state.originalSnapshot);
});
test('detail rerun opens creation and navigates to a different task', async ({ page }) => {
  const state = await open(page);
  await page.evaluate(() => (window as any).testRouter.push('/tasks/original-task?tab=config'));
  await page.getByRole('button', { name: '使用原配置重跑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建测评任务' });
  await expect(
    dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }),
  ).toBeEnabled();
  await dialog.getByRole('button', { name: /^(开始测评|创建 A\/B试验|正在处理…)$/ }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes).toHaveLength(1);
});
test('long original names leave room for the suffix', async ({ page }) => {
  await open(page, { name: '名'.repeat(128) });
  const dialog = await rerun(page);
  await expect(dialog.getByLabel('任务名称', { exact: true })).toHaveValue(
    '名'.repeat(125) + '_重跑',
  );
});

test('disabled original evaluators require an explicit selection change', async ({ page }) => {
  const state = await open(page);
  await page.evaluate(() => (window as any).disableEvaluator());
  const dialog = await rerun(page);
  await expect(dialog.getByText('原评估器已停用或不可用', { exact: false })).toBeVisible();
  await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
  expect(state.writes).toEqual([]);
  await dialog.getByRole('button', { name: '移除不可用评估器', exact: true }).click();
  await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
  await expect(page).toHaveURL(/#\/tasks\/new-task$/);
  expect(state.writes[0].body.evaluator_refs).toEqual([
    { evaluator_id: 'judge-2', evaluator_version: '2' },
  ]);
});
test('changing login identity closes a copied configuration', async ({ page }) => {
  const state = await open(page, { mode: 'bank' });
  const dialog = await rerun(page);
  await page.evaluate(() => (window as any).logout());
  await expect(dialog).toHaveCount(0);
  expect(state.writes).toEqual([]);
});

test('closing through an identity change during validation cannot create a task', async ({
  page,
}) => {
  const state = await open(page, { mode: 'bank', holdValidation: true });
  const dialog = await rerun(page);
  await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
  await expect.poll(() => state.reads.includes('/api/datasets/dataset/versions/2')).toBe(true);
  await page.evaluate(() => (window as any).logout());
  await expect(dialog).toHaveCount(0);
  state.releaseValidation();
  await page.waitForLoadState('networkidle');
  expect(state.writes).toEqual([]);
});

for (const removeHybrid of [false, true]) {
  test(`restores a published hybrid evaluator and ${removeHybrid ? 'allows removing it' : 'submits its original version'}`, async ({
    page,
  }) => {
    const state = await open(page, { hybrid: true });
    const dialog = await rerun(page);
    const group = dialog.getByRole('region', { name: '复合评估器', exact: true });
    await expect(group).toContainText('v2');
    const selection = group.getByLabel('选择评估器 辅助评估器', { exact: true });
    await expect(selection).toBeChecked();
    if (removeHybrid) await selection.uncheck();
    await dialog.getByRole('button', { name: '开始测评', exact: true }).click();
    await expect(page).toHaveURL(/#\/tasks\/new-task$/);
    expect(state.writes[0].body.evaluator_refs).toEqual(
      removeHybrid
        ? [{ evaluator_id: 'judge', evaluator_version: '1' }]
        : [
            { evaluator_id: 'judge-2', evaluator_version: '2' },
            { evaluator_id: 'judge', evaluator_version: '1' },
          ],
    );
  });
}

test.describe('task-list rerun action', () => {
  for (const loginMode of ['external', 'bank'] as const) {
    test(`${loginMode}: terminal single and A/B tasks emit their identities without submitting`, async ({
      page,
    }) => {
      const terminal: RunState[] = ['completed', 'failed', 'cancelled'];
      const states: RunState[] = [...terminal, 'pending', 'running', 'scheduled'];
      const kinds: TaskKind[] = ['single', 'ab', 'stability'];
      const rows: TaskListSummary[] = kinds.flatMap((kind) =>
        states.map((status) => {
          const id = `${kind}-${status}`;
          return {
            id,
            task_id: `${id}-task`,
            name: id,
            kind,
            created_at: now,
            status,
            summary_pending: false,
            total_cases: 1,
            completed_cases: 1,
            previous_run_count: 0,
            runs: (kind === 'single' ? ['a'] : ['a', 'b']).map((side) => ({
              run_id: `${id}-run-${side}`,
              status,
              summary_pending: false,
              target_name: `Agent ${side}`,
              target_version: 'v1',
              dataset_name: 'Dataset',
              dataset_version: 1,
              evaluator_kinds: ['rule'],
              scoring_mode: 'overall',
              total_cases: 1,
              completed_cases: 1,
              overall_score: null,
              gate_reason: null,
            })),
          };
        }),
      );
      const calls: { path: string; method: string }[] = [];
      await page.route('**/api/**', async (route) => {
        const req = route.request();
        const path = new URL(req.url()).pathname;
        if (!path.startsWith('/api/')) return route.continue();
        calls.push({ path, method: req.method() });
        if (path !== '/api/evaluation-task-summaries' || req.method() !== 'GET') {
          return route.fulfill({ status: 500, json: { detail: 'Unexpected request' } });
        }
        return route.fulfill({
          json: {
            code: '0',
            message: 'success',
            data: {
              items: rows,
              total: rows.length,
              page: 1,
              page_size: 20,
            },
          },
        });
      });
      await page.goto(listUrl);
      await page.waitForFunction(() => !!(window as any).summaryHarness);
      await page.evaluate(async (mode) => {
        const harness = (window as any).summaryHarness;
        harness.auth({ loginMode: mode, token: mode === 'bank' ? 'test-bank-token' : '' });
        await harness.mount('/tasks', 'list');
      }, loginMode);
      await expect(page.locator('.tasks-list tbody tr')).toHaveCount(rows.length);
      const actions: TaskAction[][] = [];
      for (const row of rows) {
        const tableRow = page.locator('.tasks-list tbody tr').filter({
          has: page.getByRole('button', { name: row.name, exact: true }),
        });
        const rerun = tableRow.getByRole('button', { name: '重跑', exact: true });
        if (row.kind === 'stability' || !terminal.includes(row.status)) {
          await expect(rerun).toHaveCount(0);
          continue;
        }
        await expect(rerun).toHaveCount(1);
        await rerun.click();
        actions.push([{ runId: row.runs[0].run_id, taskId: row.task_id, action: 'rerun' }]);
        expect(await page.evaluate(() => (window as any).summaryHarness.events().action)).toEqual(
          actions,
        );
        await expect(tableRow.getByRole('button', { name: row.name, exact: true })).toBeVisible();
      }
      expect(actions).toHaveLength(6);
      expect(calls.length).toBeGreaterThan(0);
      expect(
        calls.every(
          (call) => call.method === 'GET' && call.path === '/api/evaluation-task-summaries',
        ),
      ).toBe(true);
    });
  }
});
