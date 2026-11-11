import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

// Browser plugin not available: exercise the real Vue dialog with Playwright.
let server: ViteDevServer;
let baseUrl: string;
const fixture = `<!doctype html><html><head><title>Import validation acceptance</title></head>
<body><div id="app"></div><script type="module">
import { createApp, h } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import SampleImportWizard from '/src/views/datasets/components/SampleImportWizard.vue';
import '/node_modules/element-plus/dist/index.css';
import '/src/styles/revision.scss';
createApp({ render: () => h('main', { class: 'revision-app' }, [h(SampleImportWizard,
  { datasetId: 'import-acceptance', datasetName: '导入校验测试' })]) })
  .use(createPinia()).use(ElementPlus).mount('#app');
</script></body></html>`;

test.beforeAll(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)), configFile: false,
    plugins: [vue(), { name: 'import-validation-fixture', configureServer(vite) {
      vite.middlewares.use('/__import-validation', async (req, res, next) => {
        try {
          res.setHeader('Content-Type', 'text/html');
          res.end(await vite.transformIndexHtml(req.url!, fixture));
        } catch (error) { next(error); }
      });
    } }],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('No import acceptance server');
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => { await server?.close(); });

async function open(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseUrl + '/__import-validation');
  await expect(page).toHaveTitle('Import validation acceptance');
  await expect(page.getByRole('dialog'), errors.join('\n')).toBeVisible();
  await page.getByRole('button', { name: /导入测评集/ }).click();
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  return errors;
}

async function upload(page: Page, data: unknown, name = '校验样本.json') {
  await page.getByLabel('样本导入文件').setInputFiles({ name, mimeType: 'application/json',
    buffer: Buffer.from(typeof data === 'string' ? data : JSON.stringify(data)) });
}
const valid = { cases: [{ name: '修正后的样本', turns: [{ input: { txt: '你好' }, expectations: [] }] }] };

test('collects multiple errors, focuses their location and blocks draft writes', async ({ page }, testInfo) => {
  const apiWrites: string[] = [];
  await page.route(url => url.pathname.startsWith('/api/'), route => {
    apiWrites.push(route.request().url()); return route.abort();
  });
  const runtimeErrors = await open(page);
  await upload(page, { cases: [
    { name: '贷款申请', turns: [{ input: null, expectations: [] }] },
    { name: '账户查询', turns: [{ input: { txt: 'hi' }, expectations: [{ kind: 'unknown' }] }] },
  ] });
  const summary = page.getByTestId('import-validation-summary');
  await expect(summary).toContainText('发现 2 处错误，涉及 2 个样本');
  await expect(summary).toBeFocused();
  await expect(page.getByRole('table', { name: '导入错误明细' })).toContainText('贷款申请');
  await expect(page.getByRole('table', { name: '导入错误明细' })).toContainText('账户查询');
  await expect(page.getByRole('table', { name: '导入错误明细' })).toContainText('输入内容');
  await expect(page.getByRole('button', { name: '确认导入到草稿' })).toBeDisabled();
  await expect(page.getByText('请先修正 2 处错误', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '重新上传', exact: true })).toBeVisible();
  expect(apiWrites).toEqual([]);
  expect(runtimeErrors).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('import-errors-desktop.png') });
});

test('reupload replaces invalid state and accepts the same filename again', async ({ page }) => {
  await open(page);
  await upload(page, '{bad');
  await expect(page.getByTestId('import-validation-summary')).toContainText('无法读取这个文件');
  await page.getByLabel('样本导入文件').setInputFiles([]);
  await expect(page.getByTestId('import-validation-summary')).toContainText('无法读取这个文件');
  await expect(page.getByText('校验样本.json', { exact: true })).toBeVisible();
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '重新上传', exact: true }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({ name: '校验样本.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(valid)) });
  await expect(page.getByTestId('import-validation-summary')).toContainText('文件格式校验通过');
  await expect(page.getByTestId('import-validation-summary')).toContainText('1 个样本、1 轮对话');
  await expect(page.getByRole('button', { name: '确认导入到草稿' })).toBeEnabled();
  await expect(page.getByRole('table', { name: '导入错误明细' })).toHaveCount(0);
  await expect(page.getByText('修正后的样本', { exact: true })).toBeVisible();
  await expect(page.getByText('校验样本.json', { exact: true })).toBeVisible();
});

test('unreadable file reports a file error without invented row errors', async ({ page }) => {
  await open(page);
  await upload(page, '{"cases":');
  await expect(page.getByTestId('import-validation-summary')).toContainText('无法读取这个文件');
  await expect(page.getByRole('table', { name: '导入错误明细' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认导入到草稿' })).toBeDisabled();
});

test('large error list scrolls while summary and footer remain reachable', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page);
  await upload(page, { cases: Array.from({ length: 220 }, (_, i) => ({
    name: '错误样本' + i, turns: [{ input: null, expectations: [] }],
  })) });
  await expect(page.getByTestId('import-validation-summary')).toContainText('发现 220 处错误');
  await expect(page.getByText(/仅展示前 200 处/)).toBeVisible();
  await expect(page.getByRole('table', { name: '导入错误明细' }).locator('tbody tr')).toHaveCount(200);
  const button = page.getByRole('button', { name: '确认导入到草稿' });
  await expect(button).toBeVisible();
  const bounds = await button.boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(800);
  await expect(page.getByTestId('import-validation-summary')).toBeVisible();
});

test('narrow viewport retains reupload, error summary and disabled confirmation', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await upload(page, { cases: [{ name: '移动端样本', turns: [{ input: null, expectations: [] }] }] });
  await expect(page.getByTestId('import-validation-summary')).toContainText('发现 1 处错误');
  await expect(page.getByRole('button', { name: '确认导入到草稿' })).toBeDisabled();
  const dialog = await page.getByRole('dialog').boundingBox();
  expect(dialog!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath('import-errors-mobile.png') });
});
