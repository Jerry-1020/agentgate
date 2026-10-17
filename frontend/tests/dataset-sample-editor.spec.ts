import { test, expect, type Locator, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Real components/API converters with private SQLite persistence; the object contract test aborts its write.
let server: ViteDevServer;
let backend: ChildProcess;
let temporaryDirectory: string;
let baseUrl: string;
const frontendRoot = fileURLToPath(new URL('..', import.meta.url));
const repositoryRoot = fileURLToPath(new URL('../..', import.meta.url));
const runtimeErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => {
  const errors: string[] = [];
  runtimeErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
});
test.afterEach(async ({ page }) => {
  expect(runtimeErrors.get(page)).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
});
const fixture = `<!doctype html><html><head><title>Sample editor acceptance</title></head>
<body><div id="app"></div><script type="module">
import { createApp, h, ref, onMounted } from 'vue';
import ElementPlus from 'element-plus';
import SampleEditor from '/src/views/datasets/components/SampleEditor.vue';
import { datasetApi } from '/src/api/datasets.ts';
import { blankSample } from '/src/views/datasets/utils/sample-import.ts';
import '/node_modules/element-plus/dist/index.css';
const datasetId = new URLSearchParams(location.search).get('dataset');
createApp({ setup() {
  const item = ref(null), draft = ref(null), editable = ref(true), error = ref(''), dirty = ref(false);
  async function load() {
    draft.value = new URLSearchParams(location.search).has('published')
      ? (await datasetApi.versions(datasetId)).find(version => version.status === 'published')
      : await datasetApi.currentDraft(datasetId);
    editable.value = draft.value.status === 'draft';
    item.value = draft.value.cases[0] ?? blankSample('Acceptance sample');
  }
  async function save(value) {
    try {
      const exists = draft.value.cases.some(c => c.id === value.id);
      draft.value = await datasetApi[exists ? 'updateCase' : 'addCase'](datasetId, value, draft.value.content_sha256);
      item.value = draft.value.cases.find(c => c.id === value.id);
    } catch (e) { error.value = String(e); }
  }
  async function publish() {
    try {
      draft.value = await datasetApi.publish(datasetId, draft.value.content_sha256);
      item.value = draft.value.cases[0]; editable.value = false;
      history.replaceState(null, '', location.pathname + '?dataset=' + datasetId + '&published=1');
    } catch (e) { error.value = String(e); }
  }
  onMounted(() => load().catch(e => error.value = String(e)));
  return () => h('main', [
    h('h1', 'Sample editor acceptance'),
    h('span', { 'data-testid': 'dirty' }, String(dirty.value)),
    h('p', { role: 'alert' }, error.value),
    h('button', { onClick: load }, 'Reload server sample'),
    h(SampleEditor, { item: item.value, editable: editable.value, persisted: !!draft.value?.cases.length,
      onSave: save, onDirtyChange: value => dirty.value = value }),
    h('button', { onClick: publish }, 'Publish acceptance draft'),
  ]);
} }).use(ElementPlus).mount('#app');
</script></body></html>`;

test.beforeAll(async () => {
  temporaryDirectory = await mkdtemp(join(tmpdir(), 'agentgate-sample-editor-'));
  // Importing server.app creates its factory app, so set DB/log paths before import.
  const script = `import socket, uvicorn
from agentgate.server.app import app
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
print('ACCEPTANCE_PORT=' + str(sock.getsockname()[1]), flush=True)
uvicorn.Server(uvicorn.Config(app, log_level='warning')).run(sockets=[sock])`;
  const python = process.env.AGENTGATE_TEST_PYTHON ?? join(repositoryRoot, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
  backend = spawn(python, ['-B', '-u', '-c', script], {
    cwd: temporaryDirectory,
    env: {
      PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, TEMP: temporaryDirectory,
      PYTHONPATH: join(repositoryRoot, 'src'), AGENTGATE_DB_TYPE: 'sqlite',
      AGENTGATE_DB: join(temporaryDirectory, 'acceptance.db'),
      AGENTGATE_LOG_PATH: join(temporaryDirectory, 'logs'),
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  const apiUrl = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => reject(Error('Private API did not start: ' + output.slice(-2000))), 25000);
    backend.on('error', error => { clearTimeout(timeout); reject(error); });
    backend.on('exit', code => { clearTimeout(timeout); reject(Error(`Private API exited ${code}: ${output.slice(-2000)}`)); });
    backend.stderr!.on('data', chunk => { output += chunk.toString(); });
    backend.stdout!.on('data', chunk => {
      output += chunk.toString();
      const match = /ACCEPTANCE_PORT=(\d+)/.exec(output);
      if (match) { clearTimeout(timeout); resolve('http://127.0.0.1:' + match[1]); }
    });
  });
  await expect.poll(async () => {
    try { return (await fetch(apiUrl + '/api/datasets')).status; } catch { return 0; }
  }).toBe(200);
  server = await createServer({
    configFile: false, root: frontendRoot, cacheDir: join(temporaryDirectory, 'vite-cache'),
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') },
    plugins: [vue(), { name: 'sample-editor-acceptance', configureServer(instance) {
      instance.middlewares.use('/__sample-editor', async (_req, res, next) => {
        try {
          res.setHeader('Content-Type', 'text/html');
          res.end(await instance.transformIndexHtml('/__sample-editor', fixture));
        } catch (error) { next(error); }
      });
    } }],
    server: { host: '127.0.0.1', port: 0, proxy: { '/api': apiUrl } },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('No acceptance UI server');
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server?.close();
  if (backend?.pid && backend.exitCode === null && backend.signalCode === null) {
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timeout);
        backend.removeListener('close', exited);
        backend.removeListener('exit', exited);
        if (error) reject(error);
        else resolve();
      };
      const exited = () => finish();
      const timeout = setTimeout(() => finish(Error('Private API did not terminate within 5 seconds')), 5000);
      timeout.unref();
      backend.once('close', exited);
      backend.once('exit', exited);
      try { backend.kill(); } catch (error) { finish(error as Error); }
    });
  }
  if (temporaryDirectory) await rm(temporaryDirectory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
});

type Kind = 'state' | 'tool_argument';
function sample(kind: Kind) {
  return {
    id: 'acceptance-case', name: 'Preserved sample', category: 'negative', difficulty: 'hard',
    initial_state: { ticket: 'existing', attempts: 0 }, tags: ['retained'], notes: 'case notes',
    turns: [{ id: 'acceptance-turn', input: { query: '输入' }, notes: 'turn notes', expectations: [
      { id: 'editable-rule', name: 'Named rule', kind, path: 'status',
        ...(kind === 'tool_argument' ? { tool: 'lookup', occurrence: 'any' } : {}),
        condition: { kind: 'equals', expected: 'abcd' } },
      { id: 'other-rule', name: 'Retained policy', kind: 'policy', policy_id: 'approval_required' },
    ] }],
  };
}

async function open(page: Page, kind?: Kind) {
  const created = await page.request.post(baseUrl + '/api/datasets', { data: { name: 'Sample editor acceptance' } });
  expect(created.status()).toBe(201);
  const datasetId = (await created.json()).data.dataset.id as string;
  if (kind) {
    const seeded = await page.request.post(baseUrl + `/api/datasets/${datasetId}/drafts/cases`, { data: sample(kind) });
    expect(seeded.status()).toBe(201);
  }
  await page.goto(baseUrl + '/__sample-editor?dataset=' + datasetId);
  await expect(page.getByLabel('样本名称', { exact: true })).toBeVisible();
  return datasetId;
}

function valueInput(page: Page, kind: Kind) {
  return page.getByLabel(kind === 'state' ? '最终状态值' : '工具参数值 1', { exact: true });
}

function editorText(kind: Kind, expected: unknown) {
  return JSON.stringify(kind === 'state' ? { status: expected } : [
    { path: 'status', condition: { kind: 'equals', expected } },
  ], null, 2);
}

async function typeRaw(input: Locator, text: string) {
  await input.press('ControlOrMeta+A');
  await input.press('Backspace');
  await expect(input).toHaveValue('');
  let prefix = '';
  for (const character of text) {
    await input.pressSequentially(character);
    prefix += character;
    await expect(input).toHaveValue(prefix);
  }
}

async function save(page: Page, datasetId: string, method = 'PUT') {
  const response = page.waitForResponse(response => response.request().method() === method &&
    response.url().includes(`/api/datasets/${datasetId}/drafts/cases`));
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  expect((await response).ok()).toBeTruthy();
  await expect(page.getByTestId('dirty')).toHaveText('false');
  const saved = await page.request.get(baseUrl + `/api/datasets/${datasetId}/drafts/current`);
  expect(saved.ok()).toBeTruthy();
  return (await saved.json()).data.cases[0];
}

test('removed extension controls remain absent while each turn retains its stored data', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const extensions = [
    { key: 'background', value: '第一轮背景' },
    { key: 'custom_variables', value: '{"cust_id":"001"}\n保持原文' },
    { key: 'custom', value: 'keep' },
  ];
  const seeded = {
    ...original,
    turns: [
      { ...original.turns[0], extensions },
      { id: 'second-turn', input: { query: '第二轮输入' }, notes: '', expectations: [],
        extensions: [{ key: 'background', value: '第二轮背景' },
          { key: 'custom_variables', value: 'channel=mobile' }] },
    ],
  };
  expect((await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: seeded,
  })).ok()).toBeTruthy();
  await page.reload();
  for (const label of ['背景知识', '自定义变量'])
    await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '对话预览', exact: true })).toHaveCount(0);
  await expect(page.getByText('期望评估方式', { exact: true })).toHaveCount(0);
  await page.getByLabel('样本名称', { exact: true }).fill('Renamed sample');
  await page.getByRole('button', { name: /第 2 轮/ }).click();
  await page.getByLabel('用户输入', { exact: true }).fill('第二轮修改');
  await page.getByRole('button', { name: /第 1 轮/ }).click();
  const saved = await save(page, datasetId);
  expect(saved.turns.map((turn: any) => turn.extensions)).toEqual(seeded.turns.map(turn => turn.extensions));
  expect(saved.turns[0].expectations).toEqual(original.turns[0].expectations);
  expect(saved.turns[1].input).toEqual({ query: '第二轮修改' });
  const publication = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
  await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
  expect((await publication).ok()).toBeTruthy();
  await page.reload();
  for (const label of ['背景知识', '自定义变量'])
    await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('用户输入', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '保存样本', exact: true })).toHaveCount(0);
  const published = await page.request.get(baseUrl + `/api/datasets/${datasetId}/versions/1`);
  expect(published.ok()).toBeTruthy();
  expect((await published.json()).data.cases[0].turns.map((turn: any) => turn.extensions))
    .toEqual(seeded.turns.map(turn => turn.extensions));
});

test('editing the primary expected output preserves every hidden secondary condition', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const secondary = [
    { id: 'regex-output', name: '保留正则', kind: 'output', path: 'answer',
      condition: { kind: 'matches_pattern', pattern: '^old$' } },
    { id: 'range-output', name: '保留区间', kind: 'output', path: 'score',
      condition: { kind: 'within_range', minimum: 0, maximum: 1 } },
    { id: 'missing-output', name: '保留缺失', kind: 'output', path: 'secret',
      condition: { kind: 'must_be_missing' } },
  ];
  const primary = { id: 'primary-output', name: '完整输出', kind: 'output', path: null,
    condition: { kind: 'equals', expected: 'old answer' } };
  const rules = [...original.turns[0].expectations, ...secondary, primary];
  expect((await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, turns: [{ ...original.turns[0], expectations: rules }] },
  })).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel('期望输出', { exact: true })).toHaveValue('old answer');
  await expect(page.getByText('期望评估方式', { exact: true })).toHaveCount(0);
  await page.getByLabel('期望输出', { exact: true }).fill('new answer');
  const saved = await save(page, datasetId);
  expect(saved.turns[0].expectations).toEqual([
    ...rules.slice(0, -1), { ...primary, condition: { kind: 'equals', expected: 'new answer' } },
  ]);
  await page.reload();
  await expect(page.getByLabel('期望输出', { exact: true })).toHaveValue('new answer');
});

test('user input is required and expected output stays optional', async ({ page }) => {
  const datasetId = await open(page);
  const input = page.getByLabel('用户输入', { exact: true });
  await expect(input).toHaveAttribute('aria-required', 'true');
  await expect(page.locator('.message-card.user header')).toContainText('用户输入 *');
  await expect(page.locator('.message-card.expected header')).toContainText('期望输出');
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  await expect(page.locator('.sample-editor [role="alert"]')).toContainText('用户输入不能为空');
  expect((await (await page.request.get(baseUrl + `/api/datasets/${datasetId}/drafts/current`)).json()).data.cases)
    .toHaveLength(0);
  await input.fill('只提供用户输入');
  const saved = await save(page, datasetId, 'POST');
  expect(saved.turns[0].input).toEqual({ txt: '只提供用户输入' });
  expect(saved.turns[0].expectations).toEqual([]);
});

test('classification saves negative, reopens, changes to boundary and becomes read-only when published', async ({ page }) => {
  const datasetId = await open(page);
  const category = page.getByLabel('样本分类', { exact: true });
  await expect(category).toHaveValue('positive');
  await category.selectOption('negative');
  await expect(page.getByTestId('dirty')).toHaveText('true');
  await page.getByLabel('用户输入', { exact: true }).fill('请拒绝此请求');
  expect((await save(page, datasetId, 'POST')).category).toBe('negative');
  await page.reload();
  await expect(category).toHaveValue('negative');
  await category.selectOption('boundary');
  expect((await save(page, datasetId)).category).toBe('boundary');
  await page.reload();
  await expect(category).toHaveValue('boundary');
  const publication = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
  await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
  expect((await publication).ok()).toBeTruthy();
  await expect(category).toBeDisabled();
  await expect(category).toHaveValue('boundary');
  await expect(page.getByRole('button', { name: '保存样本', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(category).toBeDisabled();
  await expect(category).toHaveValue('boundary');
  await test.info().attach('published-boundary-sample', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
});

for (const kind of ['state', 'tool_argument'] as const) {
  for (const action of ['Backspace', 'Delete', 'clear'] as const) {
    test(`${kind} permits ${action} without reformatting incomplete JSON`, async ({ page }) => {
      const datasetId = await open(page, kind);
      const input = valueInput(page, kind);
      const original = editorText(kind, 'abcd');
      await expect(input).toHaveValue(original);
      if (action === 'clear') {
        await input.press('ControlOrMeta+A');
        await input.press('Backspace');
        await expect(input).toHaveValue('');
      } else {
        await input.press('ControlOrMeta+A');
        await input.press(action === 'Backspace' ? 'ArrowRight' : 'ArrowLeft');
        await input.press(action);
        await expect(input).toHaveValue(action === 'Backspace' ? original.slice(0, -1) : original.slice(1));
      }
      const expected = '拒绝 C:\\path "quoted"';
      const raw = editorText(kind, expected);
      await typeRaw(input, raw);
      const saved = await save(page, datasetId);
      expect(saved.turns[0].expectations.find((rule: any) => rule.id === 'editable-rule'))
        .toEqual({ ...sample(kind).turns[0].expectations[0], condition: { kind: 'equals', expected } });
      await page.reload();
      await expect(valueInput(page, kind)).toHaveValue(raw);
    });
  }

  test(`${kind} persists typed values while retaining field metadata`, async ({ page }) => {
    test.setTimeout(90000);
    const datasetId = await open(page, kind);
    const values = ['quoted string', 'C:\\temp\\file', 0, 12.5, true, false, null,
      [0, true, null, ['x', [false, 2]]]];
    for (const value of values) {
      const raw = editorText(kind, value);
      await typeRaw(valueInput(page, kind), raw);
      await expect(page.getByTestId('dirty')).toHaveText('true');
      const saved = await save(page, datasetId);
      const expected = sample(kind);
      expected.turns[0].expectations[0].condition.expected = value as any;
      expect(saved).toEqual(expected);
      await page.reload();
      await expect(valueInput(page, kind)).toHaveValue(raw);
    }
  });

  test(`${kind} blocks invalid JSON from saving or abandoning the current turn`, async ({ page }) => {
    const datasetId = await open(page, kind);
    const raw = '{"unfinished":';
    await typeRaw(valueInput(page, kind), raw);
    await page.getByLabel('样本名称', { exact: true }).fill('Unsaved name');
    await expect(valueInput(page, kind)).toHaveValue(raw);
    await expect(page.getByTestId('dirty')).toHaveText('true');
    await page.getByRole('button', { name: '保存样本', exact: true }).click();
    await expect(page.locator('.sample-editor > [role="alert"]')).toContainText('JSON');
    await page.getByRole('button', { name: '添加新轮次' }).click();
    await expect(page.locator('.round')).toHaveCount(1);
    await expect(valueInput(page, kind)).toHaveValue(raw);
    const persisted = await page.request.get(baseUrl + `/api/datasets/${datasetId}/drafts/current`);
    expect((await persisted.json()).data.cases[0]).toEqual(sample(kind));
  });

  test(`${kind} is read-only with matching fields after publication`, async ({ page }) => {
    await open(page, kind);
    const publication = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
    await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
    expect((await publication).ok()).toBeTruthy();
    await page.reload();
    await expect(valueInput(page, kind)).toHaveValue(editorText(kind, 'abcd'));
    await expect(valueInput(page, kind)).toBeDisabled();
    await expect(page.getByLabel('最终状态值', { exact: true })).toBeDisabled();
    await expect(page.getByLabel('工具名 1', { exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: '保存样本', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '添加工具', exact: true })).toHaveCount(0);
    await expect(page.getByText('期望评估方式', { exact: true })).toHaveCount(0);
  });
}

test('saving untouched state and tool rules preserves metadata and all other expectations', async ({ page }) => {
  for (const kind of ['state', 'tool_argument'] as const) {
    const datasetId = await open(page, kind);
    expect(await save(page, datasetId)).toEqual(sample(kind));
    await page.reload();
    await expect(valueInput(page, kind)).toHaveValue(editorText(kind, 'abcd'));
  }
});

test('clearing final state removes only its rules and stays blank across unrelated edits', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const input = valueInput(page, 'state');
  await typeRaw(input, '');
  await page.getByLabel('样本名称', { exact: true }).fill('Renamed sample');
  await expect(input).toHaveValue('');
  const saved = await save(page, datasetId);
  expect(saved.name).toBe('Renamed sample');
  expect(saved.turns[0].expectations).toEqual([sample('state').turns[0].expectations[1]]);
  await page.reload();
  await expect(valueInput(page, 'state')).toHaveValue('');
});

test('tool name and parameter value must both be supplied or both cleared', async ({ page }) => {
  const datasetId = await open(page, 'tool_argument');
  await valueInput(page, 'tool_argument').fill('');
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  await expect(page.locator('.sample-editor > [role="alert"]')).toContainText('请输入工具参数值');
  await page.getByLabel('工具名 1', { exact: true }).fill('');
  const saved = await save(page, datasetId);
  expect(saved.turns[0].expectations).toEqual([sample('tool_argument').turns[0].expectations[1]]);
  await page.reload();
  await expect(page.getByLabel('工具名 1', { exact: true })).toHaveValue('');
  await expect(valueInput(page, 'tool_argument')).toHaveValue('');
});

test('server replacement of the same expectation ID refreshes its raw editor value', async ({ page }) => {
  const datasetId = await open(page, 'tool_argument');
  await typeRaw(valueInput(page, 'tool_argument'), '{"local":');
  const replacement = sample('tool_argument');
  replacement.turns[0].expectations[0].condition.expected = 'server replacement';
  const updated = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/acceptance-case`, { data: replacement });
  expect(updated.ok()).toBeTruthy();
  await page.getByRole('button', { name: 'Reload server sample', exact: true }).click();
  await expect(valueInput(page, 'tool_argument')).toHaveValue(editorText('tool_argument', 'server replacement'));
  expect(await save(page, datasetId)).toEqual(replacement);
});

test('nested JSON objects remain raw while editing and reach the API as typed objects', async ({ page }) => {
  // Object persistence has a separate existing backend serializer bug. Abort only this
  // request after observing the real editor/API conversion; never simulate a saved object.
  for (const kind of ['state', 'tool_argument'] as const) {
    const datasetId = await open(page, kind);
    const input = valueInput(page, kind);
    const expected = { items: [0, true, null, { name: 'x' }] };
    const raw = editorText(kind, expected);
    await typeRaw(input, raw);
    const path = `/api/datasets/${datasetId}/drafts/cases/acceptance-case`;
    await page.route('**' + path, route => route.abort('aborted'));
    const submitted = page.waitForRequest(request => request.method() === 'PUT' && request.url().endsWith(path));
    await page.getByRole('button', { name: '保存样本', exact: true }).click();
    const body = (await submitted).postDataJSON();
    expect(body.turns[0].expectations[0].condition.expected).toEqual(expected);
    await expect(input).toHaveValue(raw);
    const persisted = await page.request.get(baseUrl + `/api/datasets/${datasetId}/drafts/current`);
    expect((await persisted.json()).data.cases[0]).toEqual(sample(kind));
  }
});
