import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

let server: ViteDevServer;
let directory: string;
let origin: string;
const fixture = `<!doctype html><html><body><div id="app"></div><script type="module">
import { createApp, h, ref } from 'vue';
import ElementPlus from 'element-plus';
import CaseEditor from '/src/views/datasets/components/CaseEditor.vue';
import { blankSample } from '/src/views/datasets/utils/sample-import.ts';
import '/node_modules/element-plus/dist/index.css';
const clone = value => JSON.parse(JSON.stringify(value));
const initial = blankSample('Case output contract');
initial.turns[0].input = { txt: 'Check the result' };
initial.turns[0].expectations = [
  { id: 'primary', kind: 'output', name: 'Whole output', path: null, condition: { kind: 'equals', expected: 'old' } },
  { id: 'state', kind: 'state', name: 'State check', path: 'status', condition: { kind: 'equals', expected: 'done' } },
];
if (new URLSearchParams(location.search).has('without-output')) initial.turns[0].expectations.shift();
createApp({ setup() {
  const item = ref(clone(initial)), stored = ref(clone(initial)), saves = ref(0), dirty = ref(false);
  return () => h('main', [
    h('button', { onClick: () => item.value = clone(stored.value) }, 'Reload saved case'),
    h('span', { 'data-testid': 'save-count' }, String(saves.value)),
    h('span', { 'data-testid': 'dirty' }, String(dirty.value)),
    h('pre', { 'data-testid': 'saved' }, JSON.stringify(stored.value)),
    h(CaseEditor, { item: item.value, editable: true,
      onDirtyChange: value => dirty.value = value,
      onSave: value => { stored.value = clone(value); item.value = clone(value); saves.value++; } }),
  ]);
} }).use(ElementPlus).mount('#app');
</script></body></html>`;

test.beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), 'agentgate-case-expectations-'));
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: join(directory, 'cache'),
    plugins: [vue(), {
      name: 'isolated-case-editor',
      configureServer(instance) {
        instance.middlewares.use('/__case-editor', async (_request, response, next) => {
          try {
            response.setHeader('Content-Type', 'text/html');
            response.end(await instance.transformIndexHtml('/__case-editor', fixture));
          } catch (error) { next(error); }
        });
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('No private fixture address');
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => {
  await server?.close();
  if (directory) await rm(directory, { recursive: true, force: true });
});

async function open(page: Page, query = '') {
  await page.goto(origin + '/__case-editor' + query);
  await page.locator('.other-expectations > summary').click();
}
async function saved(page: Page) {
  return JSON.parse(await page.getByTestId('saved').innerText());
}
async function save(page: Page, count: number) {
  await page.getByTestId('save-case').click();
  await expect(page.getByTestId('save-count')).toHaveText(String(count));
  return saved(page);
}

test('full output stays configurable across shared-field edits, reload and deletion', async ({ page }) => {
  await open(page);
  await expect(page.locator('.expectation-row')).toHaveCount(2);
  await page.getByTestId('expectation-value-0').fill('"from rule"');
  await expect(page.getByTestId('turn-output-0')).toHaveValue('"from rule"');
  await page.getByTestId('turn-output-0').fill('"from basic"');
  await expect(page.getByTestId('expectation-value-0')).toHaveValue('"from basic"');
  const first = await save(page, 1);
  expect(first.turns[0].expectations).toHaveLength(2);
  expect(first.turns[0].expectations[0]).toEqual({
    id: 'primary', name: 'Whole output', kind: 'output', path: null,
    condition: { kind: 'equals', expected: 'from basic' },
  });
  await expect(page.locator('.expectation-row')).toHaveCount(2);
  await page.getByRole('button', { name: 'Reload saved case' }).click();
  await expect(page.locator('.expectation-row')).toHaveCount(2);
  await page.getByTestId('expectation-0').getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByTestId('turn-output-0')).toHaveValue('');
  const second = await save(page, 2);
  expect(second.turns[0].expectations.map((rule: any) => rule.id)).toEqual(['state']);
});

test('rule and basic-output invalid drafts survive unrelated edits and reload discards them', async ({ page }) => {
  await open(page);
  await page.getByTestId('expectation-value-1').fill('{"unfinished":');
  await page.getByTestId('turn-output-0').fill('"pending basic edit"');
  await expect(page.getByTestId('expectation-value-1')).toHaveValue('{"unfinished":');
  await page.getByTestId('save-case').click();
  await expect(page.getByTestId('save-count')).toHaveText('0');
  await expect(page.getByTestId('dirty')).toHaveText('true');
  await page.getByTestId('expectation-value-1').fill('"fixed"');
  const first = await save(page, 1);
  expect(first.turns[0].expectations[0].condition.expected).toBe('pending basic edit');
  expect(first.turns[0].expectations[1].condition.expected).toBe('fixed');

  await page.getByTestId('turn-output-0').fill('{"basic":');
  await page.getByTestId('expectation-value-1').fill('"unrelated edit"');
  await expect(page.getByTestId('turn-output-0')).toHaveValue('{"basic":');
  await page.getByTestId('save-case').click();
  await expect(page.getByTestId('save-count')).toHaveText('1');
  await page.getByRole('button', { name: 'Reload saved case' }).click();
  await expect(page.getByTestId('turn-output-0')).toHaveValue('"pending basic edit"');
  await page.getByTestId('expectation-value-1').fill('{"again":');
  await page.getByRole('button', { name: 'Reload saved case' }).click();
  await expect(page.getByTestId('expectation-value-1')).toHaveValue('"fixed"');
  await expect(page.getByTestId('dirty')).toHaveText('false');
  expect(await save(page, 2)).toEqual(first);
});

test('added whole-output rules remain in the list and changing their kind clears the basic field', async ({ page }) => {
  await open(page, '?without-output=1');
  await page.getByTestId('add-expectation').click();
  await page.getByRole('menuitem', { name: '最终输出', exact: true }).click();
  await page.getByTestId('expectation-value-1').fill('false');
  await expect(page.getByTestId('turn-output-0')).toHaveValue('false');
  const first = await save(page, 1);
  await expect(page.locator('.expectation-row')).toHaveCount(2);
  const id = first.turns[0].expectations[1].id;
  await page.getByTestId('expectation-1').locator('.expectation-row-head .el-select').click();
  await page.getByRole('option', { name: '最终状态', exact: true }).click();
  await page.getByTestId('expectation-path-1').fill('approved');
  await expect(page.getByTestId('turn-output-0')).toHaveValue('');
  const second = await save(page, 2);
  expect(second.turns[0].expectations).toHaveLength(2);
  expect(second.turns[0].expectations[1]).toEqual({
    id, name: null, kind: 'state', path: 'approved', condition: { kind: 'equals', expected: false },
  });
});
