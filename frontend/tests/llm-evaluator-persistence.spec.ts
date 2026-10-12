import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { passAuthGate } from './auth-gate';

const dimensions = [
  { id: 'relevance', name: '相关性', weight: 25 },
  { id: 'correctness', name: '正确性', weight: 25 },
  { id: 'conciseness', name: '简洁性', weight: 25 },
  { id: 'safety', name: '安全性', weight: 5 },
  { id: 'tools', name: '工具', weight: 20 },
];
const dialog = (page: Page) => page.getByRole('dialog', { name: 'LLM 评估器设计', exact: true });

async function enterCatalog(page: Page) {
  await page.goto('/#/evaluators');
  await passAuthGate(page);
  await page.goto('/#/evaluators');
  await expect(page.getByRole('button', { name: /新建 LLM 评估器/ })).toBeVisible();
}

async function fillDesign(page: Page, name: string) {
  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  const form = dialog(page);
  await form.getByLabel('评估器名称', { exact: true }).fill(name);
  await form.getByLabel('评估器描述', { exact: true }).fill('真实后端草稿、发布与版本历史验证');
  await form.getByRole('button', { name: '自定义模型引用', exact: true }).click();
  await form.getByLabel('评审模型提供商 ID', { exact: true }).fill('browser-test');
  await form.getByLabel('评审模型 ID', { exact: true }).fill('browser-test-judge');
  await form.getByLabel('评审输入范围', { exact: true }).selectOption('full_trajectory');
  await form.getByLabel('评估器通过分数', { exact: true }).fill('83');
  for (const dimension of dimensions) {
    await form
      .getByRole('button', { name: new RegExp(`^${dimension.name}\\s*${dimension.weight}%$`) })
      .click();
    await form.getByLabel('维度说明', { exact: true }).fill(`${dimension.name}的业务说明`);
    await form
      .getByLabel('维度评分提示词', { exact: true })
      .fill(`按执行证据评价${dimension.name}，不得臆测。`);
  }
  return form;
}

async function catalog(request: APIRequestContext) {
  const response = await request.get('/api/evaluators?include_disabled=true');
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data as {
    id: string;
    name: string;
    latest_version: string | null;
    enabled: boolean;
  }[];
}

async function detail(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/evaluators/${id}`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data;
}

async function saveNew(page: Page, form: Locator) {
  const response = page.waitForResponse(
    (result) => result.url().endsWith('/api/evaluators') && result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '保存', exact: true }).click();
  const result = await response;
  expect(result.ok(), await result.text()).toBeTruthy();
  const saved = (await result.json()).data;
  await expect(form.getByRole('button', { name: '发布并启用', exact: true })).toBeVisible();
  return saved.evaluator.id as string;
}

async function publish(page: Page, form: Locator, id: string) {
  const response = page.waitForResponse(
    (result) =>
      result.url().endsWith(`/api/evaluators/${id}/drafts/publish`) &&
      result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '发布并启用', exact: true }).click();
  const result = await response;
  expect(result.ok(), await result.text()).toBeTruthy();
  const version = (await result.json()).data;
  await expect(form.getByText(`v${version.version}`, { exact: true })).toBeVisible();
  return version;
}

test('saved dimensions survive reload, published versions stay immutable, and history is read-only', async ({
  page,
  request,
}, testInfo) => {
  const name = `持久化浏览器验收 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name);
  const id = await saveNew(page, form);
  const saved = await detail(request, id);
  expect(saved.latest).toBeNull();
  expect(saved.draft.implementation_version).toBe('2');
  expect(saved.draft.config).toMatchObject({
    model: { provider_id: 'browser-test', model_id: 'browser-test-judge' },
    input_selection: 'full_trajectory',
    pass_threshold: 0.83,
    dimensions: dimensions.map((dimension) => ({
      ...dimension,
      description: `${dimension.name}的业务说明`,
      prompt: `按执行证据评价${dimension.name}，不得臆测。`,
    })),
  });

  await page.reload();
  await passAuthGate(page);
  await page.goto('/#/evaluators');
  await page
    .locator('.asset-card')
    .filter({ has: page.getByText(name, { exact: true }) })
    .getByRole('button', { name: /查看详情|编辑草稿/ })
    .click();
  await form.getByRole('button', { name: '编辑草稿', exact: true }).click();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue(name);
  await expect(form.getByLabel('评估器通过分数', { exact: true })).toHaveValue('83');
  await form.getByRole('button', { name: /^相关性\s*25%$/ }).click();
  await expect(form.getByLabel('维度说明', { exact: true })).toHaveValue('相关性的业务说明');
  await expect(form.getByLabel('维度评分提示词', { exact: true })).toHaveValue(
    '按执行证据评价相关性，不得臆测。',
  );
  const unchangedSave = page.waitForResponse(
    (result) =>
      result.url().endsWith(`/api/evaluators/${id}/drafts/current`) &&
      result.request().method() === 'PUT',
  );
  await form.getByRole('button', { name: '保存', exact: true }).click();
  expect((await unchangedSave).ok()).toBeTruthy();
  const first = await publish(page, form, id);
  await expect.poll(async () => (await detail(request, id)).evaluator.enabled).toBe(true);
  await expect(form.getByText('v1 已发布并启用，可用于测评。', { exact: true })).toBeVisible();
  const screenshot = testInfo.outputPath('published-evaluator-dialog.png');
  await page.setViewportSize({ width: 1440, height: 1400 });
  await form.locator('.el-dialog__body').evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('published evaluator desktop', {
    path: screenshot,
    contentType: 'image/png',
  });
  await page.setViewportSize({ width: 1440, height: 1000 });

  await form.getByRole('button', { name: /创建新版本草稿/ }).click();
  await form.getByRole('button', { name: /^相关性\s*25%$/ }).click();
  await form
    .getByLabel('维度评分提示词', { exact: true })
    .fill('第二版相关性要求：必须覆盖全部用户问题。');
  const saving = page.waitForResponse(
    (result) =>
      result.url().endsWith(`/api/evaluators/${id}/drafts/current`) &&
      result.request().method() === 'PUT',
  );
  await form.getByRole('button', { name: '保存', exact: true }).click();
  expect((await saving).ok()).toBeTruthy();
  expect((await detail(request, id)).latest).toEqual(first);
  const second = await publish(page, form, id);
  expect(second.version).toBe('2');
  expect(second.config.dimensions[0].prompt).toBe('第二版相关性要求：必须覆盖全部用户问题。');
  const historical = await request.get(`/api/evaluators/${id}/versions/1`);
  expect((await historical.json()).data).toEqual(first);

  await form.getByRole('button', { name: '版本历史', exact: true }).click();
  const history = page.getByRole('dialog', { name: '已发布版本', exact: true });
  await history.getByRole('button', { name: /v1/ }).click();
  await expect(form.getByText('v1', { exact: true })).toBeVisible();
  await expect(form.getByText('按执行证据评价相关性，不得臆测。', { exact: true })).toBeVisible();
  await expect(form.getByRole('button', { name: '保存', exact: true })).toHaveCount(0);
  await expect(form.getByRole('button', { name: '发布并启用', exact: true })).toHaveCount(0);
});

test('failed save keeps the editor and never reports an in-memory design as saved', async ({
  page,
  request,
}) => {
  const name = `失败保存浏览器验收 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name);
  await page.route('**/api/evaluators', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 503,
        json: { code: '1', message: '测试保存服务不可用', data: null },
      });
    } else await route.continue();
  });
  await form.getByRole('button', { name: '保存', exact: true }).click();
  await expect(form.getByText(/测试保存服务不可用/)).toBeVisible();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue(name);
  await expect(form.getByRole('button', { name: '保存', exact: true })).toBeEnabled();
  await expect(form.getByRole('button', { name: '发布并启用', exact: true })).toHaveCount(0);
  expect((await catalog(request)).some((item) => item.name === name)).toBe(false);
  await page.unroute('**/api/evaluators');
  await saveNew(page, form);
  expect((await catalog(request)).filter((item) => item.name === name)).toHaveLength(1);
});

test('closing a changed design asks before discarding and never creates a draft', async ({
  page,
  request,
}) => {
  const name = `放弃修改浏览器验收 ${Date.now()}`;
  await enterCatalog(page);
  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  const form = dialog(page);
  await form.getByLabel('评估器名称', { exact: true }).fill(name);
  page.once('dialog', async (confirmation) => {
    expect(confirmation.type()).toBe('confirm');
    expect(confirmation.message()).toContain('未保存');
    await confirmation.dismiss();
  });
  await form.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue(name);
  page.once('dialog', async (confirmation) => confirmation.accept());
  await form.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(form).toBeHidden();
  expect((await catalog(request)).some((item) => item.name === name)).toBe(false);
});

test('pending save disables repeated submission and closing until the response arrives', async ({
  page,
  request,
}) => {
  const name = `防重复提交浏览器验收 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name);
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  let submissions = 0;
  await page.route('**/api/evaluators', async (route) => {
    if (route.request().method() === 'POST') {
      submissions += 1;
      await blocked;
    }
    await route.continue();
  });
  const response = page.waitForResponse(
    (result) => result.url().endsWith('/api/evaluators') && result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '保存', exact: true }).click();
  await expect(form.getByRole('button', { name: /保存/ })).toBeDisabled();
  await expect(form.getByRole('button', { name: '关闭', exact: true })).toBeDisabled();
  await expect(form.getByLabel('评估器名称', { exact: true })).toBeDisabled();
  release();
  expect((await response).ok()).toBeTruthy();
  await expect(form.getByRole('button', { name: '发布并启用', exact: true })).toBeVisible();
  expect(submissions).toBe(1);
  expect((await catalog(request)).filter((item) => item.name === name)).toHaveLength(1);
});

test('a created next-version draft stays editable when the following detail refresh fails', async ({
  page,
  request,
}) => {
  await enterCatalog(page);
  const form = await fillDesign(page, `新版本读取失败验收 ${Date.now()}`);
  const id = await saveNew(page, form);
  const first = await publish(page, form, id);
  await expect(form.getByText('v1 已发布并启用，可用于测评。', { exact: true })).toBeVisible();
  let creations = 0;
  let failedReads = 0;
  page.on('request', (outgoing) => {
    if (outgoing.method() === 'POST' && outgoing.url().endsWith(`/api/evaluators/${id}/drafts`))
      creations += 1;
  });
  const path = `**/api/evaluators/${id}`;
  await page.route(path, async (route) => {
    if (route.request().method() === 'GET') {
      failedReads += 1;
      await route.fulfill({
        status: 503,
        json: { code: '1', message: '测试详情读取失败', data: null },
      });
    } else await route.continue();
  });
  await form.getByRole('button', { name: '创建新版本草稿', exact: true }).click();
  await expect(form.getByLabel('维度评分提示词', { exact: true })).toBeEnabled();
  await expect(form.getByRole('button', { name: '创建新版本草稿', exact: true })).toHaveCount(0);
  const created = await detail(request, id);
  expect(created.draft.based_on_version).toBe('1');
  expect(created.latest).toEqual(first);
  expect(creations).toBe(1);
  expect(failedReads).toBeGreaterThan(0);
  await form.getByLabel('维度评分提示词', { exact: true }).fill('读取失败后保留编辑的新提示词。');
  await page.unroute(path);
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/evaluators/${id}/drafts/current`) &&
      response.request().method() === 'PUT',
  );
  await form.getByRole('button', { name: '保存', exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(
    form.getByText('草稿已保存到服务器；发布后可用于测评。', { exact: true }),
  ).toBeVisible();
  const persisted = await detail(request, id);
  expect(persisted.draft.id).toBe(created.draft.id);
  expect(persisted.draft.config.dimensions[0].prompt).toBe('读取失败后保留编辑的新提示词。');
  expect(persisted.latest).toEqual(first);
  expect(creations).toBe(1);
});

test('successful publication remains read-only when enable and refresh fail, then enable can recover', async ({
  page,
  request,
}) => {
  await enterCatalog(page);
  const form = await fillDesign(page, `发布后恢复验收 ${Date.now()}`);
  const id = await saveNew(page, form);
  let publications = 0;
  let failedReads = 0;
  let failedEnables = 0;
  page.on('request', (outgoing) => {
    if (
      outgoing.method() === 'POST' &&
      outgoing.url().endsWith(`/api/evaluators/${id}/drafts/publish`)
    )
      publications += 1;
  });
  const path = `**/api/evaluators/${id}`;
  await page.route(path, async (route) => {
    const method = route.request().method();
    if (method === 'GET' || method === 'PATCH') {
      if (method === 'GET') failedReads += 1;
      else failedEnables += 1;
      await route.fulfill({
        status: 503,
        json: { code: '1', message: '测试启用及详情服务不可用', data: null },
      });
    } else await route.continue();
  });
  const published = await publish(page, form, id);
  await expect(form.getByRole('alert')).toContainText('v1 已发布，但启用或刷新失败');
  await expect(form.getByText('v1', { exact: true })).toBeVisible();
  await expect(form.getByRole('button', { name: '发布并启用', exact: true })).toHaveCount(0);
  await expect(form.getByRole('button', { name: '保存', exact: true })).toHaveCount(0);
  await expect(form.getByRole('button', { name: '启用', exact: true })).toBeEnabled();
  await expect(form.getByRole('button', { name: '打开测评配置', exact: true })).toHaveCount(0);
  const retained = await detail(request, id);
  expect(retained.latest).toEqual(published);
  expect(retained.draft).toBeNull();
  expect(retained.evaluator.enabled).toBe(false);
  expect(publications).toBe(1);
  expect(failedReads).toBeGreaterThan(0);
  expect(failedEnables).toBe(1);

  await page.unroute(path);
  await form.getByRole('button', { name: '启用', exact: true }).click();
  await expect(form.getByText('评估器已启用。', { exact: true })).toBeVisible();
  await expect(form.getByRole('button', { name: '打开测评配置', exact: true })).toBeEnabled();
  expect((await detail(request, id)).evaluator.enabled).toBe(true);
  const versions = await request.get(`/api/evaluators/${id}/versions`);
  expect((await versions.json()).data).toEqual([published]);
  expect(publications).toBe(1);
});
