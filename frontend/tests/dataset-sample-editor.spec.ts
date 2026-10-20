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

async function valueInput(page: Page) {
  const advanced = page.locator('details.advanced');
  if (!(await advanced.evaluate(element => (element as HTMLDetailsElement).open))) await advanced.locator('summary').first().click();
  return advanced.getByPlaceholder('期望值，支持 JSON', { exact: true });
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

async function expandInitialization(page: Page) {
  const section = page.locator('details.case-initialization');
  await expect(section.locator('summary')).toHaveText('初始变量');
  if (!(await section.evaluate(element => (element as HTMLDetailsElement).open))) {
    await section.locator('summary').click();
  }
}

async function addInitializationVariable(page: Page, name: string, value: string) {
  await expandInitialization(page);
  const index = await page.getByLabel(/^初始化变量名 \d+$/).count() + 1;
  await page.getByRole('button', { name: '添加变量', exact: true }).click();
  await page.getByLabel(`初始化变量名 ${index}`, { exact: true }).fill(name);
  await page.getByLabel(`初始化变量值 ${index}`, { exact: true }).fill(value);
}

test('workflow Case initialization and complete JSON turns persist and publish', async ({ page }) => {
  const datasetId = await open(page);
  const variables = [{ name: 'centreId', value: '810000' }, { name: 'userId', value: 'hk_yat' },
    { name: 'bankNo', value: '810000' }];
  const first = { user_input_text: '我们行的年休假政策是什么', menuId: 'KNOWLEDGE_QUERY' };
  const second = { user_input_text: '第二轮', collected_data: {},
    form: { values: [0, false, null, { amount: 12.5 }] } };
  await expect(page.getByText('初始变量', { exact: true })).toBeVisible();
  await expect(page.getByLabel(/^初始化变量名 \d+$/)).toHaveCount(0);
  for (const variable of variables) {
    await addInitializationVariable(page, variable.name, variable.value);
  }
  await expect(page.locator('details.case-initialization select')).toHaveCount(0);
  await expect(page.getByTestId('dirty')).toHaveText('true');
  await page.getByLabel('结构化 JSON 输入', { exact: true }).check();
  await page.getByRole('textbox', { name: '用户输入 JSON', exact: true }).fill(JSON.stringify(first));
  await page.getByRole('button', { name: '添加新轮次' }).click();
  await page.getByLabel('结构化 JSON 输入', { exact: true }).check();
  await page.getByRole('textbox', { name: '用户输入 JSON', exact: true }).fill(JSON.stringify(second));
  const saved = await save(page, datasetId, 'POST');
  expect(saved.initial_state).toEqual({ config_variables: variables });
  expect(saved.turns.map((turn: any) => turn.input)).toEqual([first, second]);
  await page.reload();
  await expandInitialization(page);
  for (const [index, variable] of variables.entries()) {
    await expect(page.getByLabel(`初始化变量名 ${index + 1}`, { exact: true })).toHaveValue(variable.name);
    await expect(page.getByLabel(`初始化变量值 ${index + 1}`, { exact: true })).toHaveValue(variable.value);
  }
  await page.getByRole('button', { name: '对话预览', exact: true }).click();
  await expect(page.getByLabel('初始化变量名 1', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('初始化变量值 1', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '添加变量', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^删除初始化变量 \d+$/ })).toHaveCount(0);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByLabel('初始化变量值 1', { exact: true })).toBeEnabled();
  const published = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
  await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
  expect((await published).ok()).toBeTruthy();
  for (const index of variables.keys()) {
    await expect(page.getByLabel(`初始化变量名 ${index + 1}`, { exact: true })).toBeDisabled();
    await expect(page.getByLabel(`初始化变量值 ${index + 1}`, { exact: true })).toBeDisabled();
  }
  await expect(page.getByRole('button', { name: '添加变量', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^删除初始化变量 \d+$/ })).toHaveCount(0);
  const response = await page.request.get(baseUrl + `/api/datasets/${datasetId}/versions/1`);
  expect((await response.json()).data.cases[0].initial_state).toEqual({ config_variables: variables });
  await test.info().attach('workflow-case-inputs', {
    body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
  });
});

test('workflow initialization starts collapsed and keeps values when collapsed and saved', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const section = page.locator('details.case-initialization');
  const summary = section.locator('summary');
  await expect(summary).toHaveText('初始变量');
  await expect(section).toHaveJSProperty('open', false);
  const summaryStyles = await page.locator('details.case-initialization > summary, details.advanced > summary')
    .evaluateAll(elements => elements.map(element => {
      const style = getComputedStyle(element);
      return ['color', 'font-size', 'font-weight', 'display', 'list-style-type']
        .map(property => style.getPropertyValue(property));
    }));
  expect(summaryStyles).toHaveLength(2);
  expect(summaryStyles[0]).toEqual(summaryStyles[1]);
  await summary.press('Enter');
  await expect(section).toHaveJSProperty('open', true);
  await addInitializationVariable(page, 'centreId', '810000');
  await summary.click();
  await expect(section).toHaveJSProperty('open', false);
  await expect(page.getByLabel('初始化变量值 1', { exact: true })).toBeHidden();
  await test.info().attach('workflow-initialization-collapsed', {
    body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
  });
  expect((await save(page, datasetId)).initial_state).toEqual({
    ...sample('state').initial_state, config_variables: [{ name: 'centreId', value: '810000' }],
  });
  await page.reload();
  await expect(summary).toBeVisible();
  await expect(section).toHaveJSProperty('open', false);
  await summary.press('Enter');
  await expect(page.getByLabel('初始化变量名 1', { exact: true })).toHaveValue('centreId');
  await expect(page.getByLabel('初始化变量值 1', { exact: true })).toHaveValue('810000');
  await test.info().attach('workflow-initialization-expanded', {
    body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
  });
});

test('workflow initialization is optional and ignores completely blank rows', async ({ page }) => {
  const datasetId = await open(page);
  await page.getByLabel('用户输入', { exact: true }).fill('无需初始化变量的输入');
  expect((await save(page, datasetId, 'POST')).initial_state).toEqual({});
  await addInitializationVariable(page, '', '');
  await addInitializationVariable(page, '  ', '');
  expect((await save(page, datasetId)).initial_state).toEqual({});
  await page.reload();
  await expandInitialization(page);
  await expect(page.getByRole('button', { name: '添加变量', exact: true })).toBeVisible();
  await expect(page.getByLabel(/^初始化变量名 \d+$/)).toHaveCount(0);
  await addInitializationVariable(page, 'optionalText', '');
  expect((await save(page, datasetId)).initial_state).toEqual({
    config_variables: [{ name: 'optionalText', value: '' }],
  });
});

test('workflow initialization validates names and JSON values, and clears without losing other state', async ({ page }) => {
  const datasetId = await open(page, 'state');
  await addInitializationVariable(page, '', '810000');
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  await expect(page.locator('.sample-editor [role=alert]')).toContainText('初始化变量');
  await page.getByLabel('初始化变量名 1', { exact: true }).fill('centreId');
  await addInitializationVariable(page, 'centreId', 'false');
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  await expect(page.locator('.sample-editor [role=alert]')).toContainText('不能重复');
  await page.getByRole('button', { name: '删除初始化变量 2', exact: true }).click();
  await save(page, datasetId);
  const original = sample('state');
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, initial_state: { ...original.initial_state, config_variables: [
      { name: 'centreId', value: '810000' }, { name: 'settings', value: { enabled: false } },
    ] } },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  await expandInitialization(page);
  await page.getByLabel('初始化变量值 2', { exact: true }).fill('{invalid');
  await page.getByRole('button', { name: '保存样本', exact: true }).click();
  await expect(page.locator('.sample-editor [role=alert]')).toContainText('JSON');
  await page.getByRole('button', { name: '删除初始化变量 2', exact: true }).click();
  expect((await save(page, datasetId)).initial_state).toEqual({ ticket: 'existing', attempts: 0,
    config_variables: [{ name: 'centreId', value: '810000' }] });
  await page.getByRole('button', { name: '删除初始化变量 1', exact: true }).click();
  expect((await save(page, datasetId)).initial_state).toEqual(sample('state').initial_state);
  await page.reload();
  await expandInitialization(page);
  await expect(page.getByRole('button', { name: '添加变量', exact: true })).toBeVisible();
  await expect(page.getByLabel(/^初始化变量名 \d+$/)).toHaveCount(0);
});

test('workflow initialization keeps text and JSON value types after save and reload', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const textVariables = [
    { name: 'centreId', value: '810000' },
    { name: 'textFalse', value: 'false' },
    { name: 'textObject', value: '{"enabled":false}' },
    { name: 'emptyText', value: '' },
  ];
  const existingVariables = [
    { name: 'count', value: 0 },
    { name: 'enabled', value: false },
    { name: 'optional', value: null },
    { name: 'items', value: [0, false, null, '810000'] },
    { name: 'settings', value: { nested: { active: false, count: 0 } } },
  ];
  const original = sample('state');
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, initial_state: { ...original.initial_state, config_variables: existingVariables } },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  for (const variable of textVariables) {
    await addInitializationVariable(page, variable.name, variable.value);
  }
  await expect(page.locator('details.case-initialization select')).toHaveCount(0);
  const variables = [...existingVariables, ...textVariables];
  expect((await save(page, datasetId)).initial_state.config_variables).toEqual(variables);
  await page.reload();
  await expandInitialization(page);
  for (const [index, variable] of variables.entries()) {
    await expect(page.getByLabel(`初始化变量名 ${index + 1}`, { exact: true })).toHaveValue(variable.name);
    const value = page.getByLabel(`初始化变量值 ${index + 1}`, { exact: true });
    if (typeof variable.value === 'string') await expect(value).toHaveValue(variable.value);
    else await expect.poll(async () => JSON.parse(await value.inputValue())).toEqual(variable.value);
  }
  await page.getByLabel('样本名称', { exact: true }).fill('Re-saved typed configuration');
  expect((await save(page, datasetId)).initial_state.config_variables).toEqual(variables);
});

test('base initialization saves both variable groups and excludes workflow fields', async ({ page }) => {
  const datasetId = await open(page, 'state');
  await addInitializationVariable(page, 'centreId', '810000');
  const types = page.getByRole('group', { name: '初始化类型', exact: true });
  await types.getByRole('button', { name: '基础编排', exact: true }).click();
  await expect(page.getByLabel('初始化变量名 1', { exact: true })).toHaveCount(0);
  for (const [label, name, value] of [['提示词变量', 'userId', 'hk_yat'], ['工具变量', 'bankNo', '810000']]) {
    await page.getByRole('button', { name: `添加${label}`, exact: true }).click();
    await page.getByLabel(`${label}名 1`, { exact: true }).fill(name);
    await page.getByLabel(`${label}值 1`, { exact: true }).fill(value);
  }
  const initial = { ...sample('state').initial_state,
    prompt_variables: [{ name: 'userId', value: 'hk_yat' }],
    tool_variables: [{ name: 'bankNo', value: '810000' }] };
  expect((await save(page, datasetId)).initial_state).toEqual(initial);
  await page.reload();
  await expandInitialization(page);
  await expect(types.getByRole('button', { name: '基础编排', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('提示词变量值 1', { exact: true })).toHaveValue('hk_yat');
  await expect(page.getByLabel('工具变量值 1', { exact: true })).toHaveValue('810000');
  await page.getByRole('button', { name: '对话预览', exact: true }).click();
  await expect(types.getByRole('button', { name: '工作流', exact: true })).toBeDisabled();
  await expect(page.getByLabel('提示词变量值 1', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const publication = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
  await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
  expect((await publication).ok()).toBeTruthy();
  await expect(types.getByRole('button', { name: '基础编排', exact: true })).toBeDisabled();
  await expect(page.getByLabel('工具变量值 1', { exact: true })).toBeDisabled();
  await test.info().attach('base-initialization', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
});

test('switching initialization types only saves the selected fields without a confirmation dialog', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, initial_state: { ...original.initial_state,
      prompt_variables: [{ name: 'prompt', value: 'old prompt' }],
      tool_variables: [{ name: 'tool', value: { enabled: false }, type: 'custom' }] } },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  await expandInitialization(page);
  const types = page.getByRole('group', { name: '初始化类型', exact: true });
  await expect(types.getByRole('button', { name: '基础编排', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const dialogs: string[] = [];
  page.on('dialog', async dialog => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  await types.getByRole('button', { name: '工作流', exact: true }).click();
  await addInitializationVariable(page, 'centreId', '810000');
  await types.getByRole('button', { name: '基础编排', exact: true }).click();
  expect((await save(page, datasetId)).initial_state).toEqual({ ...original.initial_state,
    prompt_variables: [{ name: 'prompt', value: 'old prompt' }],
    tool_variables: [{ name: 'tool', value: { enabled: false }, type: 'custom' }] });
  await types.getByRole('button', { name: '工作流', exact: true }).click();
  await addInitializationVariable(page, 'centreId', '810000');
  expect((await save(page, datasetId)).initial_state).toEqual({ ...original.initial_state,
    config_variables: [{ name: 'centreId', value: '810000' }] });
  expect(dialogs).toEqual([]);
});

test('mixed imported initialization is reduced to the selected type and inactive invalid values do not block saving', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, initial_state: { ...original.initial_state,
      config_variables: 'invalid inactive configuration',
      prompt_variables: [{ name: 'prompt', value: 'retained' }], tool_variables: [] } },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  await expandInitialization(page);
  await page.getByRole('group', { name: '初始化类型', exact: true })
    .getByRole('button', { name: '基础编排', exact: true }).click();
  expect((await save(page, datasetId)).initial_state).toEqual({ ...original.initial_state,
    prompt_variables: [{ name: 'prompt', value: 'retained' }], tool_variables: [] });
});

async function expectAnnotationInputsAbsent(page: Page) {
  await expect(page.getByLabel('背景知识', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('自定义变量', { exact: true })).toHaveCount(0);
}

test('hidden annotations survive editing and reloading without changing other turn data', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const extensions = [
    { key: 'custom', value: 'keep' },
    { key: 'background', value: '客户已完成身份核验\n仅供记录' },
    { key: 'custom_variables', value: '{"cust_id":"001","amount":100}\n备注=保持原文' },
  ];
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, turns: original.turns.map(turn => ({
      ...turn, extensions,
    })) },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel('样本名称', { exact: true })).toHaveValue(original.name);
  await expectAnnotationInputsAbsent(page);
  await page.getByLabel('样本名称', { exact: true }).fill('Edited sample with hidden annotations');
  await expect(page.getByTestId('dirty')).toHaveText('true');
  const saved = await save(page, datasetId);
  expect(saved.turns[0].extensions).toEqual(extensions);
  expect(saved.turns[0].input).toEqual(original.turns[0].input);
  expect(saved.turns[0].expectations).toEqual(original.turns[0].expectations);
  await page.reload();
  await expect(page.getByLabel('样本名称', { exact: true })).toHaveValue(saved.name);
  await expectAnnotationInputsAbsent(page);
  await page.getByRole('button', { name: '对话预览', exact: true }).click();
  await expectAnnotationInputsAbsent(page);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('样本分类', { exact: true }).selectOption('boundary');
  expect((await save(page, datasetId)).turns[0].extensions).toEqual(extensions);
});

test('hidden annotations stay with each turn and survive publication', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const original = sample('state');
  const extensions = [
    [{ key: 'background', value: '第一轮背景' }, { key: 'custom_variables', value: 'channel=web' },
      { key: 'custom', value: 'first-only' }],
    [{ key: 'background', value: '第二轮背景' }, { key: 'custom_variables', value: 'channel=mobile' },
      { key: 'custom', value: 'second-only' }],
  ];
  const seeded = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/${original.id}`, {
    data: { ...original, turns: [
      { ...original.turns[0], extensions: extensions[0] },
      { id: 'annotation-second-turn', input: { query: '第二轮输入' }, expectations: [], extensions: extensions[1] },
    ] },
  });
  expect(seeded.ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel('样本名称', { exact: true })).toHaveValue(original.name);
  await expectAnnotationInputsAbsent(page);
  await page.getByRole('button', { name: /第 2 轮/ }).click();
  await expectAnnotationInputsAbsent(page);
  await page.getByLabel('用户输入', { exact: true }).fill('第二轮修改后的输入');
  await page.getByRole('button', { name: '添加新轮次' }).click();
  await expectAnnotationInputsAbsent(page);
  await page.getByLabel('用户输入', { exact: true }).fill('无历史附加信息的新轮次');
  const saved = await save(page, datasetId);
  expect(saved.turns[0].input).toEqual(original.turns[0].input);
  expect(saved.turns[0].expectations).toEqual(original.turns[0].expectations);
  expect(saved.turns[1].input).toEqual({ query: '第二轮修改后的输入' });
  expect(saved.turns).toHaveLength(3);
  expect(saved.turns.slice(0, 2).map((turn: { extensions: unknown }) => turn.extensions)).toEqual(extensions);
  expect(saved.turns[2]).not.toHaveProperty('extensions');
  await page.reload();
  await expect(page.getByLabel('样本名称', { exact: true })).toHaveValue(original.name);
  await page.getByRole('button', { name: /第 2 轮/ }).click();
  await page.getByRole('button', { name: '对话预览', exact: true }).click();
  await expectAnnotationInputsAbsent(page);
  const publication = page.waitForResponse(response => response.url().endsWith('/drafts/publish'));
  await page.getByRole('button', { name: 'Publish acceptance draft' }).click();
  expect((await publication).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel('样本名称', { exact: true })).toBeDisabled();
  await expectAnnotationInputsAbsent(page);
  await page.getByRole('button', { name: /第 2 轮/ }).click();
  await expectAnnotationInputsAbsent(page);
  const response = await page.request.get(baseUrl + `/api/datasets/${datasetId}/versions/1`);
  const published = (await response.json()).data.cases[0];
  expect(published.turns).toHaveLength(3);
  expect(published.turns.slice(0, 2).map((turn: { extensions: unknown }) => turn.extensions)).toEqual(extensions);
  expect(published.turns[2]).not.toHaveProperty('extensions');
  await test.info().attach('annotations-hidden-published', {
    body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
  });
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
    test(`${kind} permits ${action} without reinserting JSON quotes`, async ({ page }) => {
      const datasetId = await open(page, kind);
      const input = await valueInput(page);
      await expect(input).toHaveValue('"abcd"');
      if (action === 'clear') {
        await input.press('ControlOrMeta+A');
        await input.press('Backspace');
        await expect(input).toHaveValue('');
      } else {
        await input.press(action === 'Backspace' ? 'End' : 'Home');
        await input.press(action);
        await expect(input).toHaveValue(action === 'Backspace' ? '"abcd' : 'abcd"');
      }
      const text = '拒绝 C:\\path "quoted"';
      await typeRaw(input, text);
      const saved = await save(page, datasetId);
      expect(saved.turns[0].expectations.find((rule: any) => rule.id === 'editable-rule').condition.expected).toBe(text);
      await page.reload();
      await expect(await valueInput(page)).toHaveValue(JSON.stringify(text));
    });
  }

  test(`${kind} incrementally types JSON and persists its actual types across reloads`, async ({ page }) => {
    test.setTimeout(90000);
    const datasetId = await open(page, kind);
    const values = [
      { text: '"quoted string"', expected: 'quoted string' },
      { text: String.raw`"C:\\temp\\file"`, expected: 'C:\\temp\\file' },
      { text: '0', expected: 0 },
      { text: '12.5', expected: 12.5 },
      { text: 'true', expected: true },
      { text: 'false', expected: false },
      { text: 'null', expected: null },
      { text: '[0,true,null,["x",[false,2]]]', expected: [0, true, null, ['x', [false, 2]]] },
      { text: '{"unfinished":', expected: '{"unfinished":' },
    ];
    for (const value of values) {
      await typeRaw(await valueInput(page), value.text);
      await expect(page.getByTestId('dirty')).toHaveText('true');
      if (value.text === '{"unfinished":') {
        await page.screenshot({ path: test.info().outputPath(kind + '-incomplete-json.png'), fullPage: true });
      }
      const saved = await save(page, datasetId);
      const expected = sample(kind);
      expected.turns[0].expectations[0].condition.expected = value.expected as any;
      expect(saved).toEqual(expected);
      await page.reload();
      await expect(await valueInput(page)).toHaveValue(JSON.stringify(value.expected));
    }
  });
}

test('saving untouched state and tool rules preserves metadata and all other expectations', async ({ page }) => {
  for (const kind of ['state', 'tool_argument'] as const) {
    const datasetId = await open(page, kind);
    expect(await save(page, datasetId)).toEqual(sample(kind));
    await page.reload();
    await expect(await valueInput(page)).toHaveValue('"abcd"');
  }
});

test('cleared expected value remains blank through unrelated edits and persists an empty string', async ({ page }) => {
  const datasetId = await open(page, 'state');
  const input = await valueInput(page);
  await typeRaw(input, '');
  await page.getByLabel('样本名称', { exact: true }).fill('Renamed sample');
  await expect(input).toHaveValue('');
  const saved = await save(page, datasetId);
  expect(saved.name).toBe('Renamed sample');
  expect(saved.turns[0].expectations[0].condition.expected).toBe('');
  await page.reload();
  await expect(await valueInput(page)).toHaveValue('""');
});

test('server replacement of the same expectation ID refreshes its raw editor value', async ({ page }) => {
  const datasetId = await open(page, 'tool_argument');
  await typeRaw(await valueInput(page), '{"local":');
  const replacement = sample('tool_argument');
  replacement.turns[0].expectations[0].condition.expected = 'server replacement';
  const updated = await page.request.put(baseUrl + `/api/datasets/${datasetId}/drafts/cases/acceptance-case`, { data: replacement });
  expect(updated.ok()).toBeTruthy();
  await page.getByRole('button', { name: 'Reload server sample', exact: true }).click();
  await expect(await valueInput(page)).toHaveValue('"server replacement"');
  expect(await save(page, datasetId)).toEqual(replacement);
});

test('nested JSON objects remain raw while editing and reach the API as typed objects', async ({ page }) => {
  // Object persistence has a separate existing backend serializer bug. Abort only this
  // request after observing the real editor/API conversion; never simulate a saved object.
  for (const kind of ['state', 'tool_argument'] as const) {
    const datasetId = await open(page, kind);
    const input = await valueInput(page);
    const raw = '{"items":[0,true,null,{"name":"x"}]}';
    await typeRaw(input, raw);
    const path = `/api/datasets/${datasetId}/drafts/cases/acceptance-case`;
    await page.route('**' + path, route => route.abort('aborted'));
    const submitted = page.waitForRequest(request => request.method() === 'PUT' && request.url().endsWith(path));
    await page.getByRole('button', { name: '保存样本', exact: true }).click();
    const body = (await submitted).postDataJSON();
    expect(body.turns[0].expectations[0].condition.expected).toEqual({ items: [0, true, null, { name: 'x' }] });
    await expect(input).toHaveValue(raw);
    const persisted = await page.request.get(baseUrl + `/api/datasets/${datasetId}/drafts/current`);
    expect((await persisted.json()).data.cases[0]).toEqual(sample(kind));
  }
});
