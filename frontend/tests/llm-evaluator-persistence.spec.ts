import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
  type TestInfo,
} from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { passAuthGate } from './auth-gate';
import type { EvaluatorSummary } from '../src/api/evaluations';
import {
  concisenessPrompt,
  emptyPromptEvaluator,
  promptEvaluatorDefinition,
} from '../src/views/evaluation/utils/evaluator-templates';
import {
  llmGroupPayload,
  newLLMGroupFromTemplate,
  type LLMGroupDetail,
} from '../src/views/evaluation/utils/evaluator-group';

const editor = (page: Page) => page.getByRole('region', { name: 'LLM 子评估器表单', exact: true });
const modelLabel = 'browser-test-judge · browser-test';
async function enterCatalog(page: Page) {
  await page.goto('/#/evaluators');
  await expect(
    page
      .getByRole('heading', { name: '欢迎页面', exact: true })
      .or(page.getByRole('button', { name: '规则评估', exact: true })),
  ).toBeVisible();
  await passAuthGate(page);
  await page.goto('/#/evaluators');
  await expect(page.getByRole('button', { name: '规则评估', exact: true })).toHaveClass('active');
  await page.getByRole('button', { name: 'LLM 评估', exact: true }).click();
  await expect(page.getByRole('button', { name: /新建 LLM 评估器/ })).toBeVisible();
}
async function fillDesign(page: Page, name: string, testInfo?: TestInfo) {
  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  const form = editor(page);
  await expect(form).toBeHidden();
  const templates = page.getByRole('dialog', { name: '评估器模板', exact: true });
  await expect(templates.getByRole('button', { name: /自定义创建 LLM 评估器/ })).toBeEnabled();
  await expect(
    templates.getByRole('heading', { name: '回答质量综合评估', exact: true }),
  ).toBeVisible();
  await expect(templates.locator('.llm-group-template-card')).toHaveCount(1);
  await expect(templates.getByRole('button', { name: '应用简洁性模板', exact: true })).toHaveCount(
    0,
  );
  if (testInfo) {
    const panel = page.locator('.el-dialog.llm-group-create-template-dialog');
    await expect
      .poll(async () => (await panel.boundingBox())?.height ?? 0)
      .toBeGreaterThanOrEqual(800);
    await panel.screenshot({
      path: testInfo.outputPath('comprehensive-evaluator-template.png'),
      animations: 'disabled',
    });
    const bounds = await panel.boundingBox();
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
    const style = await panel.evaluate((element) => {
      const computed = window.getComputedStyle(element);
      return {
        height: computed.height,
        maxHeight: computed.maxHeight,
        marginTop: computed.marginTop,
      };
    });
    writeFileSync(
      testInfo.outputPath('comprehensive-template-geometry.json'),
      JSON.stringify({ viewport: page.viewportSize(), dialog: bounds, style }, null, 2),
    );
  }
  await templates.getByLabel('搜索评估器模板').fill('不存在的模板');
  await expect(templates.getByText('没有匹配的模板，请调整搜索。')).toBeVisible();
  await templates.getByLabel('搜索评估器模板').fill('简洁性');
  await templates.getByRole('button', { name: '使用此模版创建', exact: true }).click();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue('回答质量综合评估');
  await expect(form.locator('.child-row')).toHaveCount(4);
  for (const [childName, weight] of [
    ['简洁性', '10'],
    ['相关性', '30'],
    ['准确性', '40'],
    ['合理性', '20'],
  ]) {
    await expect(form.getByLabel(childName + '权重', { exact: true })).toHaveValue(weight);
    await expect(
      form.getByRole('button', { name: '删除子评估器 ' + childName, exact: true }),
    ).toBeVisible();
    await form.getByRole('button', { name: '配置子评估器 ' + childName, exact: true }).click();
    await expect(form.getByLabel('子评估器模型', { exact: true })).toHaveValue('');
    await form.getByLabel('子评估器模型', { exact: true }).selectOption({ label: modelLabel });
  }
  await form.getByRole('button', { name: '配置子评估器 简洁性', exact: true }).click();
  await expect(form.getByRole('button', { name: /选择模[版板]/ })).toHaveCount(0);
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(concisenessPrompt);
  await form.getByLabel('评估器名称', { exact: true }).fill(name);
  await form
    .getByLabel('评估器备注描述', { exact: true })
    .fill('父子配置、草稿、原子发布与版本历史验证');
  await form.getByRole('button', { name: '子评估器高级设置', exact: true }).click();
  await form.getByLabel('子评估器通过分数', { exact: true }).fill('0.83');
  await form.getByRole('button', { name: /添加 User Prompt/ }).click();
  await form
    .getByLabel('User Prompt', { exact: true })
    .fill('依据 {{input}} 与 {{output}} 评价简洁性。');
  return form;
}
async function detail(
  request: APIRequestContext,
  id: string,
  version?: string,
): Promise<LLMGroupDetail> {
  const response = await request.get(
    `/api/evaluators/${id}/llm-group` + (version ? `?version=${version}` : ''),
  );
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}
async function catalog(request: APIRequestContext) {
  const response = await request.get('/api/evaluators?include_disabled=true');
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data as EvaluatorSummary[];
}
async function openEvaluatorDeletion(page: Page, name: string) {
  await page.getByRole('button', { name: name + '更多操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '删除', exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: '删除评估器', exact: true });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toContainText(name);
  return confirmation;
}
async function saveNew(page: Page, form: Locator) {
  const response = page.waitForResponse(
    (result) =>
      result.url().endsWith('/api/evaluators/llm-groups') && result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '保存草稿', exact: true }).click();
  const result = await response;
  expect(result.ok(), await result.text()).toBeTruthy();
  expect(
    result
      .request()
      .postDataJSON()
      .children.map((child: { weight: number }) => child.weight),
  ).toEqual([0.1, 0.3, 0.4, 0.2]);
  const saved = (await result.json()).data as LLMGroupDetail;
  await expect(form.getByRole('button', { name: '编辑草稿', exact: true })).toBeVisible();
  return saved.evaluator.id;
}
async function publish(page: Page, form: Locator, id: string) {
  const response = page.waitForResponse(
    (result) =>
      result.url().endsWith(`/api/evaluators/${id}/llm-group/publish`) &&
      result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '发布并启用', exact: true }).click();
  const result = await response;
  expect(result.ok(), await result.text()).toBeTruthy();
  const published = (await result.json()).data as LLMGroupDetail;
  await expect(form.getByRole('button', { name: '打开测评配置', exact: true })).toBeEnabled();
  return published;
}

test('deleting six published single evaluators and one group leaves only the preset after refresh', async ({
  page,
  request,
}, testInfo) => {
  const ids: string[] = [];
  const names: string[] = [];
  const modelKey = JSON.stringify({ provider_id: 'browser-test', model_id: 'browser-test-judge' });
  for (let index = 1; index <= 6; index++) {
    const name = `待删除已发布单体 ${index}`;
    const response = await request.post('/api/evaluators', {
      data: {
        name,
        description: '已发布 LLM 删除回归',
        draft: promptEvaluatorDefinition({
          ...emptyPromptEvaluator(),
          name,
          instruction: concisenessPrompt,
          modelKey,
        }),
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const id = (await response.json()).data.evaluator.id as string;
    ids.push(id);
    names.push(name);
    const publication = await request.post(`/api/evaluators/${id}/drafts/publish`);
    expect(publication.ok(), await publication.text()).toBeTruthy();
    const enabled = await request.patch(`/api/evaluators/${id}`, { data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
  }
  const group = newLLMGroupFromTemplate('answer-quality', 'archive-test');
  group.name = '待删除已发布综合评估器';
  group.children.forEach((child) => {
    child.modelKey = modelKey;
  });
  const creation = await request.post('/api/evaluators/llm-groups', {
    data: llmGroupPayload(group, null),
  });
  expect(creation.ok(), await creation.text()).toBeTruthy();
  const saved = (await creation.json()).data as LLMGroupDetail;
  const groupId = saved.evaluator.id;
  ids.push(groupId);
  names.push(group.name);
  const publication = await request.post(`/api/evaluators/${groupId}/llm-group/publish`, {
    data: {
      expected_draft_id: saved.definition.id,
      expected_draft_updated_at: saved.definition.updated_at,
    },
  });
  expect(publication.ok(), await publication.text()).toBeTruthy();
  await enterCatalog(page);
  await expect(page.locator('.asset-card')).toHaveCount(7);
  await expect(page.locator('.catalogue-template-card')).toHaveCount(1);
  await page.goto('/#/evaluators/' + groupId);
  await expect(editor(page)).toBeVisible();
  await expect(editor(page).getByRole('heading', { name: group.name, exact: true })).toBeVisible();
  await editor(page).getByRole('button', { name: '← 返回评估器列表', exact: true }).click();

  const deleteRequests: string[] = [];
  page.on('request', (outgoing) => {
    const path = new URL(outgoing.url()).pathname;
    if (outgoing.method() === 'DELETE' && path.startsWith('/api/evaluators/'))
      deleteRequests.push(path);
  });
  const firstCard = page.locator('.asset-card').filter({
    has: page.getByRole('heading', { name: names[0], exact: true }),
  });
  const cancelled = await openEvaluatorDeletion(page, names[0]);
  await cancelled.getByRole('button', { name: '取消', exact: true }).click();
  await expect(cancelled).toBeHidden();
  await expect(firstCard.getByRole('button', { name: /更多操作$/ })).toBeEnabled();
  expect(deleteRequests).toEqual([]);
  await expect(firstCard).toBeVisible();

  const failedPath = '**/api/evaluators/' + ids[0];
  await page.route(failedPath, (route) =>
    route.request().method() === 'DELETE'
      ? route.fulfill({
          status: 503,
          json: { code: '1', message: '测试删除服务不可用', data: null },
        })
      : route.continue(),
  );
  const failed = await openEvaluatorDeletion(page, names[0]);
  await failed.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '删除失败' })).toContainText(
    '测试删除服务不可用',
  );
  await expect(firstCard).toBeVisible();
  expect((await catalog(request)).some((item) => item.id === ids[0])).toBe(true);
  await page.unroute(failedPath);

  for (const [index, id] of ids.entries()) {
    const confirmation = await openEvaluatorDeletion(page, names[index]);
    const deletion = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/evaluators/${id}` &&
        response.request().method() === 'DELETE',
    );
    await confirmation.getByRole('button', { name: '删除', exact: true }).click();
    const deleted = await deletion;
    expect(deleted.status(), await deleted.text()).toBe(204);
    await expect(
      page.locator('.asset-card').filter({
        has: page.getByRole('heading', { name: names[index], exact: true }),
      }),
    ).toHaveCount(0);
    const version = await request.get(`/api/evaluators/${id}/versions/1`);
    expect(version.ok(), await version.text()).toBeTruthy();
    expect((await version.json()).data).toMatchObject({ id, version: '1' });
  }
  expect((await catalog(request)).filter((item) => ids.includes(item.id))).toEqual([]);
  for (let attempt = 0; attempt < 2; attempt++) {
    const refreshed = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/evaluators',
    );
    await page.reload();
    await expect(
      page
        .getByRole('heading', { name: '欢迎页面', exact: true })
        .or(page.getByRole('button', { name: '规则评估', exact: true })),
    ).toBeVisible();
    await passAuthGate(page);
    await page.goto('/#/evaluators/' + groupId);
    expect((await refreshed).ok()).toBeTruthy();
    await expect(editor(page)).toBeHidden();
    await page.getByRole('button', { name: 'LLM 评估', exact: true }).click();
    await expect(page.locator('.asset-card')).toHaveCount(0);
    const template = page.locator('.catalogue-template-card');
    await expect(template).toHaveCount(1);
    await expect(
      template.getByRole('button', { name: '查看回答质量综合评估模板', exact: true }),
    ).toBeVisible();
    await expect(template.getByRole('button', { name: /应用/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /新建 LLM 评估器/ })).toBeVisible();
  }
  expect((await catalog(request)).filter((item) => ids.includes(item.id))).toEqual([]);
  await page.screenshot({
    path: testInfo.outputPath('catalog-after-deleting-seven-evaluators.png'),
    fullPage: true,
    animations: 'disabled',
  });
});

test('catalog deletion removes unpublished single and group records with their owned children', async ({
  page,
  request,
}) => {
  const modelKey = JSON.stringify({ provider_id: 'browser-test', model_id: 'browser-test-judge' });
  const name = '待删除未发布单体';
  const single = await request.post('/api/evaluators', {
    data: {
      name,
      draft: promptEvaluatorDefinition({
        ...emptyPromptEvaluator(),
        name,
        instruction: concisenessPrompt,
        modelKey,
      }),
    },
  });
  expect(single.ok(), await single.text()).toBeTruthy();
  const singleId = (await single.json()).data.evaluator.id as string;
  const group = newLLMGroupFromTemplate('answer-quality', 'draft-delete-test');
  group.name = '待删除未发布综合评估器';
  group.children.forEach((child) => {
    child.modelKey = modelKey;
  });
  const creation = await request.post('/api/evaluators/llm-groups', {
    data: llmGroupPayload(group, null),
  });
  expect(creation.ok(), await creation.text()).toBeTruthy();
  const saved = (await creation.json()).data as LLMGroupDetail;
  expect(saved.latest_version).toBeNull();
  expect(saved.children).toHaveLength(4);

  await enterCatalog(page);
  await expect(
    page.locator('.catalogue-template-card').getByRole('button', { name: /更多操作|删除/ }),
  ).toHaveCount(0);
  for (const item of [
    { id: singleId, name, suffix: '' },
    { id: saved.evaluator.id, name: group.name, suffix: '/llm-group/draft' },
  ]) {
    const confirmation = await openEvaluatorDeletion(page, item.name);
    const deletion = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/evaluators/${item.id}${item.suffix}` &&
        response.request().method() === 'DELETE',
    );
    await confirmation.getByRole('button', { name: '删除', exact: true }).click();
    const deleted = await deletion;
    expect(deleted.status(), await deleted.text()).toBe(204);
    if (item.suffix) {
      expect(deleted.request().postDataJSON()).toEqual({
        expected_draft_id: saved.definition.id,
        expected_draft_updated_at: saved.definition.updated_at,
      });
    }
    await expect(page.getByRole('heading', { name: item.name, exact: true })).toHaveCount(0);
    expect((await request.get(`/api/evaluators/${item.id}`)).status()).toBe(404);
  }
  for (const child of saved.children) {
    expect((await request.get(`/api/evaluators/${child.evaluator.id}`)).status()).toBe(404);
  }
  const removedIds = [
    singleId,
    saved.evaluator.id,
    ...saved.children.map((child) => child.evaluator.id),
  ];
  expect((await catalog(request)).filter((item) => removedIds.includes(item.id))).toEqual([]);
  await page.getByRole('button', { name: '规则评估', exact: true }).click();
  const presetRules = page.locator('.asset-card').filter({
    has: page.locator('.asset-chip').filter({ hasText: /^预置/ }),
  });
  await expect(presetRules).toHaveCount(6);
  await expect(presetRules.getByRole('button', { name: /更多操作|删除/ })).toHaveCount(0);
});

test('rule catalog uses Chinese preset names and hides Policy without changing API identities or custom names', async ({
  page,
  request,
}) => {
  const rules = [
    ['skill_routing', 'Skill Routing', '技能路由'],
    ['required_tool', 'Required Tool', '必需工具调用'],
    ['forbidden_tool', 'Forbidden Tool', '禁止工具调用'],
    ['tool_arguments', 'Tool Arguments', '工具参数'],
    ['final_state', 'Final State', '最终状态'],
    ['final_output', 'Final Output', '最终输出'],
  ];
  const before = await catalog(request);
  const builtin = before.filter((item) => item.source === 'builtin');
  const policy = builtin.find((item) => item.implementation_id === 'policy_compliance');
  expect(policy).toMatchObject({ name: 'Policy Compliance' });
  const base = await request.get('/api/evaluators/final-output');
  expect(base.ok(), await base.text()).toBeTruthy();
  const {
    kind,
    dimension,
    metric,
    severity,
    implementation_id,
    implementation_version,
    config,
    children,
    combination,
  } = (await base.json()).data.latest;
  const creation = await request.post('/api/evaluators', {
    data: {
      name: 'Final Output',
      description: '自建规则名称保持原文',
      draft: {
        kind,
        dimension,
        metric,
        severity,
        implementation_id,
        implementation_version,
        config,
        children,
        combination,
      },
    },
  });
  expect(creation.ok(), await creation.text()).toBeTruthy();
  const customId = (await creation.json()).data.evaluator.id as string;
  const publication = await request.post(`/api/evaluators/${customId}/drafts/publish`);
  expect(publication.ok(), await publication.text()).toBeTruthy();

  await enterCatalog(page);
  await page.getByRole('button', { name: '规则评估', exact: true }).click();
  for (const [implementationId, english, chinese] of rules) {
    expect(builtin.find((item) => item.implementation_id === implementationId)).toMatchObject({
      name: english,
    });
    await expect(page.getByRole('heading', { name: chinese, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: 'Policy Compliance', exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole('heading', { name: 'Final Output', exact: true })).toBeVisible();
  const search = page.getByLabel('搜索评估器', { exact: true });
  for (const [implementationId, english, chinese] of rules) {
    for (const term of [chinese, english.toLowerCase()]) {
      await search.fill(term);
      await expect(page.getByRole('heading', { name: chinese, exact: true })).toBeVisible();
    }
    const card = page.locator('.asset-card').filter({
      has: page.getByRole('heading', { name: chinese, exact: true }),
    });
    await card.getByRole('button', { name: '查看详情', exact: true }).click();
    const details = page.getByRole('dialog', { name: '规则评估器详情', exact: true });
    await expect(details.getByRole('heading', { name: chinese, exact: true })).toBeVisible();
    await expect(details).toContainText(implementationId);
    await details.getByRole('button', { name: '关闭', exact: true }).click();
  }
  await search.fill('Policy');
  await expect(page.locator('.asset-card')).toHaveCount(0);
  await search.fill('Final Output');
  await expect(page.getByRole('heading', { name: '最终输出', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Final Output', exact: true })).toBeVisible();
  await search.fill('');
  const after = await catalog(request);
  expect(after.filter((item) => item.source === 'builtin')).toEqual(builtin);
  expect(after.find((item) => item.id === policy!.id)).toEqual(policy);
  expect(after.find((item) => item.id === customId)).toMatchObject({
    source: 'user',
    name: 'Final Output',
  });
});

test('the catalog only previews the comprehensive template while creation applies it', async ({
  page,
  request,
}, testInfo) => {
  await enterCatalog(page);
  const previous = await catalog(request);
  expect(previous.some((item) => item.name === 'Answer Quality')).toBe(true);
  await expect(
    page.locator('.asset-card').filter({ has: page.getByText('Answer Quality', { exact: true }) }),
  ).toHaveCount(0);
  const template = page.locator('.catalogue-template-card');
  await expect(template).toHaveCount(1);
  await expect(
    template.getByRole('heading', { name: '回答质量综合评估', exact: true }),
  ).toBeVisible();
  await expect(template.getByRole('button', { name: /应用/ })).toHaveCount(0);
  await expect(
    template.getByRole('button', { name: '查看回答质量综合评估模板', exact: true }),
  ).toBeVisible();
  const search = page.getByLabel('搜索评估器', { exact: true });
  for (const term of ['回答质量综合评估', '简洁性', '相关性', '准确性', '合理性']) {
    await search.fill(term);
    await expect(template).toBeVisible();
  }
  await search.fill('没有匹配的评估器');
  await expect(template).toHaveCount(0);
  await search.fill('');
  const readCardStyle = (locator: Locator) =>
    locator.evaluate((element) => {
      const readStyle = (target: Element) => {
        const style = getComputedStyle(target);
        return {
          backgroundColor: style.backgroundColor,
          color: style.color,
          border: style.border,
          borderRadius: style.borderRadius,
          padding: style.padding,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
        };
      };
      const { backgroundColor, border, borderRadius, padding } = readStyle(element);
      return {
        card: { backgroundColor, border, borderRadius, padding },
        title: readStyle(element.querySelector('h2')!),
        chip: readStyle(element.querySelector('.asset-chip')!),
      };
    });
  const readActionStyle = (locator: Locator) =>
    locator.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        height: style.height,
        backgroundColor: style.backgroundColor,
        color: style.color,
        border: style.border,
        borderRadius: style.borderRadius,
        padding: style.padding,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        lineHeight: style.lineHeight,
        boxShadow: style.boxShadow,
      };
    });
  await page.getByRole('button', { name: '规则评估', exact: true }).click();
  await expect(template).toHaveCount(0);
  const ruleCard = page.locator('.asset-card').first();
  await expect(ruleCard).toBeVisible();
  const ruleCardStyle = await readCardStyle(ruleCard);
  const ruleActionStyle = await readActionStyle(ruleCard.locator('.asset-link'));
  await page.getByRole('button', { name: 'LLM 评估', exact: true }).click();
  await expect(template).toBeVisible();
  const catalogCardStyle = await readCardStyle(template);
  expect(catalogCardStyle).toEqual(ruleCardStyle);
  expect(await readActionStyle(template.locator('.asset-link'))).toEqual(ruleActionStyle);
  const catalogCardBounds = await template.boundingBox();
  expect(catalogCardBounds).not.toBeNull();
  await page.screenshot({
    path: testInfo.outputPath('comprehensive-template-catalog.png'),
    fullPage: true,
    animations: 'disabled',
  });

  const writes: string[] = [];
  page.on('request', (outgoing) => {
    if (
      new URL(outgoing.url()).pathname.startsWith('/api/evaluators') &&
      !['GET', 'HEAD'].includes(outgoing.method())
    )
      writes.push(outgoing.method() + ' ' + new URL(outgoing.url()).pathname);
  });
  await template.getByRole('button', { name: '查看回答质量综合评估模板', exact: true }).click();
  const preview = page.getByRole('dialog', { name: '预置评估器模板', exact: true });
  const form = editor(page);
  await expect(preview).toBeVisible();
  await expect(form).toBeHidden();
  await expect(preview.getByRole('button', { name: /应用|新增|删除|保存|发布|编辑/ })).toHaveCount(
    0,
  );
  for (const [childName, weight] of [
    ['简洁性', '10%'],
    ['相关性', '30%'],
    ['准确性', '40%'],
    ['合理性', '20%'],
  ]) {
    await preview.getByRole('button', { name: '查看子评估器 ' + childName, exact: true }).click();
    await expect(preview.getByText(weight, { exact: true })).toBeVisible();
    await expect(preview.getByLabel('模板 System Prompt', { exact: true })).toHaveAttribute(
      'readonly',
      '',
    );
    const prompt = await preview.getByLabel('模板 System Prompt', { exact: true }).inputValue();
    expect(prompt).toContain(childName);
    expect(prompt).toContain('{{input}}');
    expect(prompt).toContain('{{output}}');
    if (childName === '简洁性') expect(prompt).toBe(concisenessPrompt);
  }
  await preview.getByRole('button', { name: '查看子评估器 简洁性', exact: true }).click();
  await preview.locator('.el-dialog').screenshot({
    path: testInfo.outputPath('comprehensive-template-readonly.png'),
    animations: 'disabled',
  });
  expect(writes).toEqual([]);
  expect(await catalog(request)).toEqual(previous);
  await preview.locator('.el-dialog__headerbtn').click();
  await expect(preview).toBeHidden();
  await expect(template).toBeVisible();

  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  const modal = page.getByRole('dialog', { name: '评估器模板', exact: true });
  await expect(modal).toBeVisible();
  const creationTemplate = modal.locator('.llm-group-template-card');
  expect(await readCardStyle(creationTemplate)).toEqual(catalogCardStyle);
  const templateCreateButton = creationTemplate.getByRole('button', {
    name: '使用此模版创建',
    exact: true,
  });
  const customCreateButton = modal.getByRole('button', { name: /自定义创建 LLM 评估器/ });
  await expect(templateCreateButton).toBeVisible();
  await expect(templateCreateButton).toBeEnabled();
  await expect(creationTemplate.getByRole('button', { name: /应用/ })).toHaveCount(0);
  expect(await readActionStyle(templateCreateButton)).toEqual(
    await readActionStyle(customCreateButton),
  );
  const creationCardBounds = await creationTemplate.boundingBox();
  expect(creationCardBounds).not.toBeNull();
  expect(creationCardBounds!.width).toBeCloseTo(catalogCardBounds!.width, 1);
  expect(creationCardBounds!.height).toBeCloseTo(catalogCardBounds!.height, 1);
  await page.locator('.el-dialog.llm-group-create-template-dialog').screenshot({
    path: testInfo.outputPath('comprehensive-template-matching-cards.png'),
    animations: 'disabled',
  });
  await expect(modal.locator('.llm-group-template-card')).toHaveCount(1);
  await expect(
    modal.getByRole('button', { name: /应用(简洁性|相关性|准确性|合理性)模板/ }),
  ).toHaveCount(0);
  await modal.getByRole('button', { name: '使用此模版创建', exact: true }).click();
  await expect(form).toBeVisible();
  await expect(modal).toBeHidden();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue('回答质量综合评估');
  const nameBounds = await form.getByLabel('评估器名称', { exact: true }).boundingBox();
  const descriptionBounds = await form.getByLabel('评估器备注描述', { exact: true }).boundingBox();
  expect(nameBounds).not.toBeNull();
  expect(descriptionBounds).not.toBeNull();
  expect(descriptionBounds!.height).toBeCloseTo(nameBounds!.height, 1);
  await form.getByRole('region', { name: '评估器基本信息', exact: true }).screenshot({
    path: testInfo.outputPath('evaluator-matching-basic-fields.png'),
    animations: 'disabled',
  });
  await expect(form.locator('.child-row')).toHaveCount(4);
  expect(writes).toEqual([]);
  expect(await catalog(request)).toEqual(previous);
  page.once('dialog', (dialog) => dialog.accept());
  await form.getByRole('button', { name: '取消编辑', exact: true }).click();
  await expect(form).toBeHidden();
  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  await expect(modal).toBeVisible();
  await expect(form).toBeHidden();
  await modal.getByRole('button', { name: '使用此模版创建', exact: true }).click();
  await expect(form).toBeVisible();
  await expect(modal).toBeHidden();
  expect(writes).toEqual([]);
  for (const [childName, weight] of [
    ['简洁性', '10'],
    ['相关性', '30'],
    ['准确性', '40'],
    ['合理性', '20'],
  ]) {
    await expect(form.getByLabel(childName + '权重', { exact: true })).toHaveValue(weight);
    await expect(
      form.getByRole('button', { name: '删除子评估器 ' + childName, exact: true }),
    ).toBeVisible();
    await form.getByRole('button', { name: '配置子评估器 ' + childName, exact: true }).click();
    await form.getByLabel('子评估器模型', { exact: true }).selectOption({ label: modelLabel });
  }
  page.once('dialog', (dialog) => dialog.accept());
  await form.getByRole('button', { name: '删除子评估器 合理性', exact: true }).click();
  await form.getByRole('button', { name: '＋ 新增', exact: true }).click();
  await expect(modal).toBeHidden();
  await expect(form.getByLabel('子评估器名称', { exact: true })).toHaveValue('');
  await form.getByLabel('子评估器名称', { exact: true }).fill('综合模板自定义项');
  await form.getByLabel('子评估器模型', { exact: true }).selectOption({ label: modelLabel });
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill('检查回答是否可行 {{input}} {{output}}');
  await form.getByLabel('综合模板自定义项权重', { exact: true }).fill('20');
  const name = `列表综合模板实例 ${Date.now()}`;
  await form.getByLabel('评估器名称', { exact: true }).fill(name);
  const id = await saveNew(page, form);
  const saved = await detail(request, id);
  expect(saved.children.map((child) => child.evaluator.name)).toEqual([
    '简洁性',
    '相关性',
    '准确性',
    '综合模板自定义项',
  ]);
  expect(saved.children[3].template_id).toBeNull();
  expect(writes).toEqual(['POST /api/evaluators/llm-groups']);
  const published = await publish(page, form, id);
  expect(published.evaluator.enabled).toBe(true);
  expect(published.children.map((child) => child.weight)).toEqual([0.1, 0.3, 0.4, 0.2]);
  expect((await catalog(request)).some((item) => item.name === 'Answer Quality')).toBe(true);
  await form.getByRole('button', { name: '← 返回评估器列表', exact: true }).click();
  await expect(form).toBeHidden();
  await page
    .locator('.asset-card')
    .filter({ has: page.getByText(name, { exact: true }) })
    .getByRole('button', { name: '查看详情', exact: true })
    .click();
  await expect(form.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(modal).toBeHidden();
  await expect(
    form.getByRole('button', { name: '配置子评估器 综合模板自定义项', exact: true }),
  ).toBeVisible();
  await form.getByRole('button', { name: '配置子评估器 综合模板自定义项', exact: true }).click();
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(
    '检查回答是否可行 {{input}} {{output}}',
  );
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveAttribute('readonly', '');
});

test('multiple children retain independent configuration, reject invalid weights and pin historical versions', async ({
  page,
  request,
}, testInfo) => {
  const name = `子评估器持久化 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name, testInfo);
  await form.getByRole('button', { name: '配置子评估器 准确性', exact: true }).click();
  const accuracyPrompt = await form.getByLabel('System Prompt', { exact: true }).inputValue();
  await expect(
    form.getByRole('button', { name: '配置子评估器 准确性', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  page.once('dialog', (dialog) => dialog.dismiss());
  await form.getByRole('button', { name: '删除子评估器 合理性', exact: true }).click();
  await expect(form.locator('.child-row')).toHaveCount(4);
  await expect(
    form.getByRole('button', { name: '配置子评估器 准确性', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  page.once('dialog', (dialog) => dialog.accept());
  await form.getByRole('button', { name: '删除子评估器 合理性', exact: true }).click();
  await expect(form.getByRole('button', { name: '配置子评估器 合理性', exact: true })).toHaveCount(
    0,
  );
  await expect(form.locator('.child-row')).toHaveCount(3);
  await expect(
    form.getByRole('button', { name: '配置子评估器 准确性', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(accuracyPrompt);
  await form.getByRole('button', { name: '＋ 新增', exact: true }).click();
  const templates = page.getByRole('dialog', { name: '评估器模板', exact: true });
  await expect(templates).toBeHidden();
  await expect(form.locator('.child-row')).toHaveCount(4);
  await expect(
    form.getByRole('button', { name: '配置子评估器 未命名', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(form.getByLabel('子评估器名称', { exact: true })).toHaveValue('');
  await expect(form.getByLabel('子评估器模型', { exact: true })).toHaveValue('');
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue('');
  await expect(form.getByLabel('未命名权重', { exact: true })).toHaveValue('0');
  await expect(
    form.getByRole('button', { name: '删除子评估器 未命名', exact: true }),
  ).toBeVisible();
  await form.getByLabel('子评估器名称', { exact: true }).fill('自定义合理性');
  await form.getByLabel('子评估器模型', { exact: true }).selectOption({ label: modelLabel });
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill('独立合理性标准 {{input}} {{output}}');
  await form.getByRole('button', { name: '配置子评估器 准确性', exact: true }).click();
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill('独立准确性标准 {{input}} {{output}}');
  await form.getByRole('button', { name: '配置子评估器 相关性', exact: true }).click();
  await form.getByLabel('子评估器模型', { exact: true }).selectOption({ label: modelLabel });
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill('独立相关性标准 {{input}} {{output}}');
  await form.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('每项权重必须大于 0');
  expect((await catalog(request)).some((item) => item.name === name)).toBe(false);
  await form.getByLabel('自定义合理性权重', { exact: true }).fill('20');
  await expect(form.getByLabel('简洁性权重', { exact: true })).toHaveValue('10');
  await form.getByRole('button', { name: '配置子评估器 简洁性', exact: true }).click();
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(concisenessPrompt);
  await expect(form.getByLabel('User Prompt', { exact: true })).toHaveValue(
    '依据 {{input}} 与 {{output}} 评价简洁性。',
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('llm-group-editing.png'),
    fullPage: true,
    animations: 'disabled',
  });
  const id = await saveNew(page, form);
  const draft = await detail(request, id);
  expect(draft.children).toHaveLength(4);
  expect(draft.children.map((child) => child.weight)).toEqual([0.1, 0.3, 0.4, 0.2]);
  expect(draft.children.map((child) => child.evaluator.name)).toEqual([
    '简洁性',
    '相关性',
    '准确性',
    '自定义合理性',
  ]);
  expect(draft.children[0].definition.config.pass_threshold).toBe(0.83);
  expect(draft.children[1].definition.config.instruction).toContain('独立相关性标准');
  expect(draft.children[2].definition.config.instruction).toContain('独立准确性标准');
  expect(draft.children[3].definition.config.instruction).toContain('独立合理性标准');
  expect(draft.children[3].template_id).toBeNull();
  const first = await publish(page, form, id);
  expect(first.definition.kind).toBe('llm_group');
  expect(first.evaluator.enabled).toBe(true);
  expect((await catalog(request)).filter((item) => item.id === id)).toHaveLength(1);
  expect(
    (await catalog(request)).filter((item) =>
      first.children.some((child) => child.evaluator.id === item.id),
    ),
  ).toHaveLength(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('published-llm-group.png'),
    fullPage: true,
    animations: 'disabled',
  });

  await page.reload();
  await passAuthGate(page);
  await page.goto('/#/evaluators');
  await page.getByRole('button', { name: 'LLM 评估', exact: true }).click();
  await page
    .locator('.asset-card')
    .filter({ has: page.getByText(name, { exact: true }) })
    .getByRole('button', { name: '查看详情' })
    .click();
  await expect(form.getByText('4 个子评估器', { exact: true })).toBeVisible();
  await form.getByRole('button', { name: '编辑新版本', exact: true }).click();
  await form.getByRole('button', { name: '配置子评估器 简洁性', exact: true }).click();
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill(concisenessPrompt + '\n第二版：保留必要事实。');
  await form.getByRole('button', { name: '移除 User Prompt', exact: true }).click();
  await form.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(form.getByRole('button', { name: '编辑草稿', exact: true })).toBeVisible();
  const second = await publish(page, form, id);
  expect(second.definition.version).toBe('2');
  expect(second.children[0].definition.config).not.toHaveProperty('user_prompt');
  const old = await detail(request, id, '1');
  expect(old.definition).toEqual(first.definition);
  expect(old.children.map((child) => child.definition)).toEqual(
    first.children.map((child) => child.definition),
  );
  await form.getByRole('button', { name: '版本历史', exact: true }).click();
  await page
    .getByRole('dialog', { name: '已发布版本', exact: true })
    .getByRole('button', { name: '查看 v1', exact: true })
    .click();
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(concisenessPrompt);
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveAttribute('readonly', '');
  await expect(form.getByRole('button', { name: '保存草稿', exact: true })).toHaveCount(0);
  await expect(form.getByRole('button', { name: '打开测评配置', exact: true })).toHaveCount(0);
});

test('failed atomic save keeps the form and retry creates one parent', async ({
  page,
  request,
}) => {
  const name = `原子保存失败 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name);
  await page.route('**/api/evaluators/llm-groups', (route) =>
    route.fulfill({ status: 503, json: { code: '1', message: '测试保存服务不可用', data: null } }),
  );
  await form.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('测试保存服务不可用');
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue(name);
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue(concisenessPrompt);
  expect((await catalog(request)).some((item) => item.name === name)).toBe(false);
  await page.unroute('**/api/evaluators/llm-groups');
  await saveNew(page, form);
  expect((await catalog(request)).filter((item) => item.name === name)).toHaveLength(1);
});

test('atomic publication failure leaves the entire group as draft and can retry', async ({
  page,
  request,
}) => {
  await enterCatalog(page);
  const form = await fillDesign(page, `原子发布重试 ${Date.now()}`);
  const id = await saveNew(page, form);
  const path = `**/api/evaluators/${id}/llm-group/publish`;
  await page.route(path, (route) =>
    route.fulfill({ status: 503, json: { code: '1', message: '测试发布服务不可用', data: null } }),
  );
  await form.getByRole('button', { name: '发布并启用', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('测试发布服务不可用');
  const draft = await detail(request, id);
  expect(draft.viewing_draft).toBe(true);
  expect(draft.latest_version).toBeNull();
  expect(draft.children.every((child) => !child.definition.version)).toBe(true);
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveAttribute('readonly', '');
  await page.unroute(path);
  const published = await publish(page, form, id);
  expect(published.definition.version).toBe('1');
  expect(published.children.every((child) => child.definition.version === '1')).toBe(true);
});

test('custom creation supports prompt editing and clearing without individual templates', async ({
  page,
  request,
}) => {
  const name = `取消子评估器 ${Date.now()}`;
  await enterCatalog(page);
  await page.getByRole('button', { name: /新建 LLM 评估器/ }).click();
  const form = editor(page),
    templates = page.getByRole('dialog', { name: '评估器模板', exact: true });
  await templates.getByRole('button', { name: /自定义创建 LLM 评估器/ }).click();
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue('');
  await expect(form.getByRole('button', { name: /选择模[版板]/ })).toHaveCount(0);
  await expect(templates).toBeHidden();
  const variables = form.getByLabel('Prompt 变量', { exact: true });
  const systemPrompt = form.getByLabel('System Prompt', { exact: true });
  await expect(variables).toHaveCount(0);
  await systemPrompt.fill('普通说明，没有变量。{{ }} {{}}');
  await expect(variables).toHaveCount(0);
  await form
    .getByLabel('System Prompt', { exact: true })
    .fill('自定义评价 {{ input }} 与 {{output}}，结合 {{reference}}。重复 {{input}}。');
  await expect(variables.locator('code')).toHaveText([
    '{{ input }}',
    '{{ output }}',
    '{{ reference }}',
  ]);
  await expect(variables).toContainText('为用例输入');
  await expect(variables).toContainText('为被测 Agent 的最终回答');
  await form.getByRole('button', { name: /添加 User Prompt/ }).click();
  await form
    .getByLabel('User Prompt', { exact: true })
    .fill('补充 {{output}} {{context}} {{ reference }} {{context}}');
  await expect(variables.locator('code')).toHaveText([
    '{{ input }}',
    '{{ output }}',
    '{{ reference }}',
    '{{ context }}',
  ]);
  await systemPrompt.fill('');
  await expect(variables.locator('code')).toHaveText([
    '{{ output }}',
    '{{ context }}',
    '{{ reference }}',
  ]);
  await form.getByRole('button', { name: '移除 User Prompt', exact: true }).click();
  await expect(variables).toHaveCount(0);

  await form.getByLabel('子评估器名称', { exact: true }).fill('变量维度一');
  await systemPrompt.fill('第一项 {{input}}');
  await form.getByRole('button', { name: '＋ 新增', exact: true }).click();
  await expect(variables).toHaveCount(0);
  await form.getByLabel('子评估器名称', { exact: true }).fill('变量维度二');
  await systemPrompt.fill('第二项 {{output}}');
  await expect(variables.locator('code')).toHaveText(['{{ output }}']);
  await form.getByRole('button', { name: '配置子评估器 变量维度一', exact: true }).click();
  await expect(variables.locator('code')).toHaveText(['{{ input }}']);
  await form.getByRole('button', { name: '配置子评估器 变量维度二', exact: true }).click();
  await expect(variables.locator('code')).toHaveText(['{{ output }}']);
  await form.getByRole('button', { name: '清空', exact: true }).click();
  await expect(form.getByLabel('System Prompt', { exact: true })).toHaveValue('');
  await expect(variables).toHaveCount(0);
  await form.getByLabel('评估器名称', { exact: true }).fill(name);
  page.once('dialog', (dialog) => dialog.dismiss());
  await form.getByRole('button', { name: '取消编辑', exact: true }).click();
  await expect(form.getByLabel('评估器名称', { exact: true })).toHaveValue(name);
  page.once('dialog', (dialog) => dialog.accept());
  await form.getByRole('button', { name: '取消编辑', exact: true }).click();
  await expect(form).toBeHidden();
  expect((await catalog(request)).some((item) => item.name === name)).toBe(false);
});

test('pending parent save blocks duplicate submissions and field edits', async ({
  page,
  request,
}) => {
  const name = `父子防重复提交 ${Date.now()}`;
  await enterCatalog(page);
  const form = await fillDesign(page, name);
  let release!: () => void,
    submissions = 0;
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/evaluators/llm-groups', async (route) => {
    submissions++;
    await blocked;
    await route.continue();
  });
  const response = page.waitForResponse(
    (result) =>
      result.url().endsWith('/api/evaluators/llm-groups') && result.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(form.getByRole('button', { name: '处理中…', exact: true })).toBeDisabled();
  await expect(form.getByRole('button', { name: '取消编辑', exact: true })).toBeDisabled();
  await expect(form.getByLabel('评估器名称', { exact: true })).toBeDisabled();
  await expect(form.getByLabel('子评估器名称', { exact: true })).toBeDisabled();
  release();
  expect((await response).ok()).toBeTruthy();
  await expect(form.getByRole('button', { name: '编辑草稿', exact: true })).toBeVisible();
  expect(submissions).toBe(1);
  expect((await catalog(request)).filter((item) => item.name === name)).toHaveLength(1);
});

test('existing single prompt evaluators retain their editor and immutable version workflow', async ({
  page,
  request,
}) => {
  const name = `历史单评估器 ${Date.now()}`;
  const response = await request.post('/api/evaluators', {
    data: {
      name,
      description: '历史单评估器',
      draft: promptEvaluatorDefinition({
        ...emptyPromptEvaluator(),
        name,
        instruction: concisenessPrompt,
        modelKey: JSON.stringify({ provider_id: 'browser-test', model_id: 'browser-test-judge' }),
      }),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const id = (await response.json()).data.evaluator.id;
  await enterCatalog(page);
  await page
    .locator('.asset-card')
    .filter({ has: page.getByText(name, { exact: true }) })
    .getByRole('button', { name: '查看详情' })
    .click();
  const legacy = page.getByRole('region', { name: 'LLM 评估器表单', exact: true });
  await expect(legacy).toBeVisible();
  await legacy.getByRole('button', { name: '编辑草稿', exact: true }).click();
  await expect(legacy.getByRole('button', { name: /选择模[版板]/ })).toHaveCount(0);
  await expect(legacy.getByLabel('System Prompt', { exact: true })).toHaveValue(concisenessPrompt);
  const variables = legacy.getByLabel('Prompt 变量', { exact: true });
  await expect(variables.locator('code')).toHaveText(['{{ input }}', '{{ output }}']);
  await legacy.getByRole('button', { name: '清空', exact: true }).click();
  await expect(variables).toHaveCount(0);
  await legacy.getByLabel('System Prompt', { exact: true }).fill('仅含说明 {{ }}，没有变量。');
  await expect(variables).toHaveCount(0);
  await legacy
    .getByLabel('System Prompt', { exact: true })
    .fill('动态 {{ reference }} {{input}} {{reference}}');
  await expect(variables.locator('code')).toHaveText(['{{ reference }}', '{{ input }}']);
  await legacy.getByRole('button', { name: /添加 User Prompt/ }).click();
  await legacy.getByLabel('User Prompt', { exact: true }).fill('{{input}} {{output}}');
  await expect(variables.locator('code')).toHaveText([
    '{{ reference }}',
    '{{ input }}',
    '{{ output }}',
  ]);
  await legacy.getByRole('button', { name: '移除 User Prompt', exact: true }).click();
  await expect(variables.locator('code')).toHaveText(['{{ reference }}', '{{ input }}']);
  await legacy.getByLabel('System Prompt', { exact: true }).fill(concisenessPrompt);
  await expect(variables.locator('code')).toHaveText(['{{ input }}', '{{ output }}']);
  await legacy.getByRole('button', { name: '保存草稿', exact: true }).click();
  const publication = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/api/evaluators/${id}/drafts/publish`) && r.request().method() === 'POST',
  );
  await legacy.getByRole('button', { name: '发布并启用', exact: true }).click();
  expect((await publication).ok()).toBeTruthy();
  await expect(legacy.getByRole('button', { name: '打开测评配置', exact: true })).toBeEnabled();
});

test('existing dimension evaluators keep the original editor', async ({ page, request }) => {
  const name = `保留维度编辑 ${Date.now()}`;
  const response = await request.post('/api/evaluators', {
    data: {
      name,
      description: '历史多维评估器',
      draft: {
        kind: 'llm_judge',
        dimension: 'answer',
        metric: 'answer_quality',
        severity: 'standard',
        implementation_id: 'answer_quality',
        implementation_version: '2',
        config: {
          model: { provider_id: 'browser-test', model_id: 'browser-test-judge' },
          input_selection: 'final_output',
          pass_threshold: 0.8,
          dimensions: [
            {
              id: 'quality',
              name: '质量',
              description: '',
              prompt: '基于证据评价质量。',
              weight: 100,
            },
          ],
        },
        children: [],
        combination: null,
      },
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  await enterCatalog(page);
  await page
    .locator('.asset-card')
    .filter({ has: page.getByText(name, { exact: true }) })
    .getByRole('button', { name: '查看详情' })
    .click();
  const legacy = page.getByRole('dialog', { name: 'LLM 评估器设计', exact: true });
  await expect(legacy).toBeVisible();
  await legacy.getByRole('button', { name: '编辑草稿', exact: true }).click();
  await expect(legacy.getByLabel('维度评分提示词', { exact: true })).toHaveValue(
    '基于证据评价质量。',
  );
});

test('recorded official-model report displays one parent score and version-pinned child results', async ({
  page,
}, testInfo) => {
  const fixture = JSON.parse(
    readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
  );
  const report = fixture.report,
    manifest = report.run.manifest,
    runId = report.run.id;
  const parent = manifest.evaluator_specs.find(
    (spec: { kind: string }) => spec.kind === 'llm_group',
  );
  const children = manifest.evaluator_specs.filter(
    (spec: { kind: string }) => spec.kind === 'llm_judge',
  );
  const rule = {
    id: 'browser-evidence-rule',
    name: '期望输出',
    version: '1',
    kind: 'rule',
    dimension: 'answer',
    metric: 'final_output_match',
    severity: 'standard',
    implementation_id: 'final_output',
    implementation_version: '1',
    config: {},
    children: [],
    combination: null,
    content_sha256: 'd38af903c0ca3d57fb4c41dbd33390b480564cfaab5b46cb12b8457b8578d719',
  };
  const parentResult = report.results.find(
    (result: { evaluator_id: string }) => result.evaluator_id === parent.id,
  );
  const finalOutput = fixture.traces[parentResult.case_id].final_output;
  manifest.evaluator_specs.push(rule);
  manifest.primary_evaluator_ids.push(rule.id);
  report.results.push({
    ...structuredClone(parentResult),
    id: 'browser-evidence-rule-result',
    evaluator_id: rule.id,
    evaluator_name: rule.name,
    evaluator_version: rule.version,
    evaluator_content_sha256: rule.content_sha256,
    evaluator_kind: rule.kind,
    dimension: rule.dimension,
    metric: rule.metric,
    severity: rule.severity,
    outcome: 'pass',
    score: 1,
    reason: '最终输出符合预期。',
    checks: [
      {
        id: 'browser-evidence-rule-check',
        name: '最终输出',
        turn_id: null,
        expectation_id: null,
        outcome: 'pass',
        score: 1,
        reason: '最终输出符合预期。',
        expected: { kind: 'equals', expected: finalOutput },
        actual: finalOutput,
        actual_missing: false,
        methods: [],
        span_ids: [],
      },
    ],
    judge_record: null,
    error_detail: null,
    primary_failure_stage: null,
  });
  const pageErrors: string[] = [],
    consoleErrors: string[] = [];
  let optimizationCalls = 0;
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.route('**/api/runs/' + runId + '**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const prefix = '/api/runs/' + runId;
    if (pathname === prefix + '/optimization') {
      optimizationCalls++;
      await route.fulfill({ status: 400, json: { message: 'Unexpected optimization request' } });
      return;
    }
    const payload =
      pathname === prefix
        ? report
        : pathname === prefix + '/status'
          ? fixture.status
          : pathname.startsWith(prefix + '/traces/')
            ? fixture.traces[decodeURIComponent(pathname.slice((prefix + '/traces/').length))]
            : undefined;
    if (payload)
      await route.fulfill({ status: 200, json: { code: '0', message: 'ok', data: payload } });
    else await route.continue();
  });
  await enterCatalog(page);
  await page.goto('/#/tasks/' + runId);
  const tabs = page.getByRole('navigation', { name: '测评任务详情页签', exact: true });
  await expect(tabs.getByRole('button')).toHaveText([
    '执行结果',
    '低分样本',
    '优化迭代',
    '任务快照',
  ]);
  await expect(tabs.getByRole('button', { name: '执行结果', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(tabs.getByRole('button', { name: /样本结果|任务配置|Skill 静态分析/ })).toHaveCount(
    0,
  );
  const headings = page.locator('.sample-table thead th');
  await expect(headings.filter({ hasText: parent.name })).toBeVisible();
  for (const child of children)
    await expect(headings.filter({ hasText: child.name })).toHaveCount(0);
  await page.getByRole('button', { name: '样本详情', exact: true }).click();
  const parentCard = page.locator('.evaluation-result[data-evaluator="' + parent.id + '"]');
  const childSection = parentCard.getByRole('region', { name: '子评估器结果', exact: true });
  await expect(childSection).toBeVisible();
  await expect(childSection.locator(':scope > .evaluation-result')).toHaveCount(3);
  const evaluationPanel = page.locator('.evaluation-panel');
  await expect(evaluationPanel.locator('.score-box')).toHaveCount(0);
  await expect(evaluationPanel.locator('.dimension-bars')).toHaveCount(0);
  const evidenceCards = evaluationPanel.locator(':scope > details > .evaluation-result');
  await expect(evidenceCards).toHaveCount(2);
  await expect(evidenceCards.nth(0)).toHaveAttribute('data-evaluator', rule.id);
  await expect(evidenceCards.nth(1)).toHaveAttribute('data-evaluator', parent.id);
  for (const child of children) {
    const card = childSection.locator('.evaluation-result[data-evaluator="' + child.id + '"]');
    const weight = parent.children.find(
      (ref: { evaluator_id: string }) => ref.evaluator_id === child.id,
    ).weight;
    const result = report.results.find(
      (item: { evaluator_id: string }) => item.evaluator_id === child.id,
    );
    await expect(card.getByRole('heading', { name: child.name, exact: true })).toBeVisible();
    await expect(card.locator('.evaluator-reference')).toContainText(`v${child.version}`);
    await expect(card.locator('.evaluator-reference')).toContainText(`权重 ${weight * 100}%`);
    await expect(card.locator('.evaluation-score')).toContainText((result.score * 100).toFixed(1));
    await expect(card.locator('.result-reason')).toContainText(result.checks[0].reason);
    await card.locator('.raw-checks > summary').click();
    await expect(card.locator('.raw-checks > pre')).toContainText('deepseek-v4-pro');
    await expect(card.locator('.raw-checks > pre')).toContainText('judge_record');
    await card.locator('.raw-checks > summary').click();
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('llm-group-task-result.png'),
    fullPage: true,
    animations: 'disabled',
  });
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await tabs.getByRole('button', { name: '优化迭代', exact: true }).click();
  const iteration = page.getByRole('region', { name: '优化迭代', exact: true });
  await expect(iteration).toHaveText('能力构建中');
  await expect(iteration.getByRole('button')).toHaveCount(0);
  expect(optimizationCalls).toBe(0);
  await tabs.getByRole('button', { name: '任务快照', exact: true }).click();
  await expect(tabs.getByRole('button', { name: '任务快照', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('heading', { name: '被测智能体', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '执行设置', exact: true })).toBeVisible();
  await expect(page.getByText('子评估器配置（3）', { exact: true })).toBeVisible();
  for (const child of children) {
    const weight = parent.children.find(
      (ref: { evaluator_id: string }) => ref.evaluator_id === child.id,
    ).weight;
    await expect(
      page.getByText(`${child.name} · v${child.version} · ${weight * 100}%`, { exact: true }),
    ).toBeVisible();
  }
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('multi-evaluator results stay contained and expose every sample and score on desktop and narrow screens', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1265, height: 1600 });
  const fixture = JSON.parse(
    readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
  );
  const runId = 'browser-multi-evaluator-layout';
  const report = fixture.report,
    manifest = report.run.manifest,
    originalCase = manifest.dataset.cases[0],
    originalResults = report.results;
  const parent = manifest.evaluator_specs.find(
    (spec: { kind: string }) => spec.kind === 'llm_group',
  );
  const ruleNames = [
    '最终状态',
    '期望工具调用',
    '期望 Skill 调用',
    '工具参数完整性检查',
    '期望输出',
  ];
  const rules = ruleNames.map((name, index) => ({
    ...structuredClone(parent),
    id: `browser-layout-rule-${index}`,
    name,
    kind: 'rule',
    children: [],
    combination: null,
    config: {},
  }));
  const primarySpecs = [...rules, parent];
  manifest.evaluator_specs = [...rules, ...manifest.evaluator_specs];
  manifest.primary_evaluator_ids = primarySpecs.map((spec) => spec.id);
  report.run.id = runId;
  manifest.dataset.cases = Array.from({ length: 12 }, (_, index) => ({
    ...structuredClone(originalCase),
    id: `layout-case-${index + 1}`,
    name: `样本 ${index + 1} · 用于检查长名称与多个评估器结果的完整展示`,
    tags: ['贷款申请与多轮补充信息场景'],
    turns: [
      {
        ...structuredClone(originalCase.turns[0]),
        id: `layout-turn-${index + 1}`,
        input: {
          txt: `第 ${index + 1} 条用户输入。${'请根据完整申请资料检查贷款条件。'.repeat(8)}`,
        },
      },
    ],
  }));
  manifest.selected_case_ids = manifest.dataset.cases.map((sample: { id: string }) => sample.id);
  report.results = manifest.dataset.cases.flatMap((sample: { id: string }) => [
    ...originalResults.map((result: any) => ({
      ...structuredClone(result),
      id: `${sample.id}-${result.id}`,
      run_id: runId,
      case_id: sample.id,
    })),
    ...rules.map((rule) => ({
      ...structuredClone(originalResults[0]),
      id: `${sample.id}-${rule.id}`,
      run_id: runId,
      case_id: sample.id,
      evaluator_id: rule.id,
      evaluator_name: rule.name,
      evaluator_kind: 'rule',
      outcome: 'pass',
      score: 1,
      checks: [],
      judge_record: null,
    })),
  ]);
  fixture.status = { ...fixture.status, run_id: runId, total_cases: 12, completed_cases: 12 };
  await page.route('**/api/runs/' + runId + '**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const prefix = '/api/runs/' + runId;
    const payload =
      pathname === prefix
        ? report
        : pathname === prefix + '/status'
          ? fixture.status
          : pathname.startsWith(prefix + '/traces/')
            ? {
                trace_id: 'browser-layout-trace',
                run_id: runId,
                case_id: decodeURIComponent(pathname.slice((prefix + '/traces/').length)),
                spans: [],
                turn_outcomes: {},
              }
            : undefined;
    await route.fulfill(
      payload
        ? { json: { code: '0', message: 'ok', data: payload } }
        : { status: 400, json: { message: 'Unexpected report request' } },
    );
  });
  await enterCatalog(page);
  await page.goto('/#/tasks/' + runId);
  const scroll = page.getByRole('region', { name: '执行结果表格', exact: true });
  const rows = scroll.locator('tbody tr');
  const headings = scroll.locator('thead th');
  const tableGeometry = () =>
    scroll.evaluate((element) => {
      const headerBottom = Math.max(
        ...Array.from(
          element.querySelectorAll('thead th'),
          (cell) => cell.getBoundingClientRect().bottom,
        ),
      );
      const viewportBottom = element.getBoundingClientRect().top + element.clientHeight;
      const rowBounds = Array.from(element.querySelectorAll('tbody tr'), (row) =>
        row.getBoundingClientRect(),
      );
      return {
        containerHeight: element.clientHeight,
        headerHeight: headerBottom - element.getBoundingClientRect().top,
        firstTenRowsHeight: rowBounds[9].bottom - rowBounds[0].top,
        fullyVisibleRows: rowBounds.filter(
          (bounds) => bounds.top >= headerBottom - 1 && bounds.bottom <= viewportBottom + 1,
        ).length,
      };
    });
  await expect(rows).toHaveCount(12);
  await expect(headings).toHaveText([
    '用户输入',
    '场景',
    '状态',
    '综合分',
    ...primarySpecs.map((spec) => spec.name),
    '操作',
  ]);
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollWidth - element.clientWidth))
    .toBeLessThanOrEqual(1);
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollHeight - element.clientHeight))
    .toBeGreaterThan(0);
  await expect
    .poll(async () => (await tableGeometry()).fullyVisibleRows)
    .toBeGreaterThanOrEqual(10);
  const desktopGeometry = await tableGeometry();
  await expect(rows.nth(9)).toBeInViewport({ ratio: 1 });
  await scroll.evaluate((element) => (element.scrollTop = element.scrollHeight));
  await expect(rows.last()).toBeInViewport({ ratio: 1 });
  await expect(headings.first()).toBeInViewport({ ratio: 1 });
  const desktopHeader = await headings.first().boundingBox();
  const desktopScroll = await scroll.boundingBox();
  expect(Math.abs(desktopHeader!.y - desktopScroll!.y)).toBeLessThanOrEqual(2);
  await scroll.screenshot({ path: testInfo.outputPath('multi-evaluator-desktop.png') });

  await page.setViewportSize({ width: 768, height: 1600 });
  await scroll.scrollIntoViewIfNeeded();
  await scroll.evaluate((element) => (element.scrollTop = 0));
  await expect
    .poll(async () => (await tableGeometry()).fullyVisibleRows)
    .toBeGreaterThanOrEqual(10);
  writeFileSync(
    testInfo.outputPath('multi-evaluator-geometry.json'),
    JSON.stringify({ desktop: desktopGeometry, narrow: await tableGeometry() }, null, 2),
  );
  await expect(rows.nth(9).getByRole('button', { name: '样本详情', exact: true })).toBeInViewport({
    ratio: 1,
  });
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollWidth - element.clientWidth))
    .toBeGreaterThan(0);
  // Wrapped headers change the table height on narrow screens.
  await scroll.evaluate((element) => (element.scrollTop = element.scrollHeight));
  await expect
    .poll(() =>
      scroll.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop),
    )
    .toBeLessThanOrEqual(1);
  const action = rows.last().getByRole('button', { name: '样本详情', exact: true });
  await expect(action).toBeInViewport({ ratio: 1 });
  const before = await action.boundingBox();
  await scroll.evaluate((element) => (element.scrollLeft = element.scrollWidth));
  await expect(headings.nth(9)).toBeInViewport({ ratio: 1 });
  await expect(action).toBeInViewport({ ratio: 1 });
  const after = await action.boundingBox();
  expect(Math.abs(before!.x - after!.x)).toBeLessThanOrEqual(1);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath('multi-evaluator-narrow.png'),
    fullPage: true,
    animations: 'disabled',
  });
});

test('low-score tab excludes the 80-point boundary and missing scores, and preserves its detail context', async ({
  page,
}, testInfo) => {
  const fixture = JSON.parse(
    readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
  );
  const runId = 'browser-low-score-fixture';
  const variants = [
    { id: 'low', name: '低分样本', input: '低分样本输入', score: 0.79, tag: '低分场景' },
    { id: 'boundary', name: '边界样本', input: '边界样本输入', score: 0.8, tag: '其他场景' },
    { id: 'high', name: '高分样本', input: '高分样本输入', score: 0.95, tag: '其他场景' },
    { id: 'unscored', name: '无分数样本', input: '无分数样本输入', score: null, tag: '其他场景' },
  ];
  const originalCase = fixture.report.run.manifest.dataset.cases[0];
  const originalResults = fixture.report.results;
  const report = fixture.report;
  report.run.id = runId;
  report.run.manifest.selected_case_ids = variants.map((variant) => variant.id);
  report.run.manifest.dataset.cases = variants.map((variant) => ({
    ...structuredClone(originalCase),
    id: variant.id,
    name: variant.name,
    tags: [variant.tag],
    turns: [
      {
        ...structuredClone(originalCase.turns[0]),
        id: variant.id + '-turn',
        input: { txt: variant.input },
      },
    ],
  }));
  report.results = variants.flatMap((variant) =>
    originalResults.map((result: any) => ({
      ...structuredClone(result),
      id: variant.id + '-' + result.id,
      run_id: runId,
      case_id: variant.id,
      score: variant.score,
      outcome: variant.score === null ? 'review' : variant.score < 0.8 ? 'fail' : 'pass',
    })),
  );
  fixture.status = { ...fixture.status, run_id: runId, total_cases: 4, completed_cases: 4 };
  await page.route('**/api/runs/' + runId + '**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const prefix = '/api/runs/' + runId;
    const payload =
      pathname === prefix
        ? report
        : pathname === prefix + '/status'
          ? fixture.status
          : pathname.startsWith(prefix + '/traces/')
            ? {
                trace_id: 'browser-fixture-trace',
                run_id: runId,
                case_id: decodeURIComponent(pathname.slice((prefix + '/traces/').length)),
                spans: [],
                turn_outcomes: {},
              }
            : undefined;
    if (payload) await route.fulfill({ json: { code: '0', message: 'ok', data: payload } });
    else await route.continue();
  });
  await enterCatalog(page);
  await page.goto('/#/tasks/' + runId);
  const tabs = page.getByRole('navigation', { name: '测评任务详情页签', exact: true });
  const rows = page.locator('.sample-table tbody tr');
  await expect(rows).toHaveCount(4);
  await page.getByLabel('分数区间', { exact: true }).selectOption('high');
  await expect(rows).toHaveCount(2);
  await tabs.getByRole('button', { name: '低分样本', exact: true }).click();
  await expect(tabs.getByRole('button', { name: '低分样本', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByLabel('分数区间', { exact: true })).toHaveCount(0);
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('低分样本');
  await expect(rows.first().locator('td').nth(3)).toHaveText('79.0');
  await tabs.getByRole('button', { name: '执行结果', exact: true }).click();
  await expect(page.getByLabel('分数区间', { exact: true })).toHaveValue('high');
  await expect(rows).toHaveCount(2);
  await tabs.getByRole('button', { name: '低分样本', exact: true }).click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出 CSV', exact: true }).click();
  const download = await downloadEvent;
  const csvPath = testInfo.outputPath('low-score-samples.csv');
  await download.saveAs(csvPath);
  const csv = readFileSync(csvPath, 'utf8');
  expect(csv).toContain('低分样本输入');
  for (const variant of variants.slice(1)) expect(csv).not.toContain(variant.input);
  await page.getByLabel('样本场景', { exact: true }).selectOption('其他场景');
  await expect(rows).toHaveCount(0);
  await expect(page.getByText('暂无匹配的低分样本', { exact: true })).toBeVisible();
  await page.getByLabel('样本场景', { exact: true }).selectOption('');
  await rows.getByRole('button', { name: '样本详情', exact: true }).click();
  await expect(page).toHaveURL(new RegExp('/tasks/' + runId + '/samples/low\\?tab=low-samples$'));
  await expect(page.getByRole('heading', { name: '样本测评详情', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '下一条', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '上一条', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await expect(page).toHaveURL(new RegExp('/tasks/' + runId + '\\?tab=low-samples$'));
  await expect(tabs.getByRole('button', { name: '低分样本', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('低分样本');
  await tabs.getByRole('button', { name: '执行结果', exact: true }).click();
  await expect(page.getByLabel('分数区间', { exact: true })).toHaveValue('');
  await expect(rows).toHaveCount(4);
});

for (const status of ['running', 'failed'] as const) {
  test(`optimization tab shows the construction placeholder for ${status} tasks without requesting model analysis`, async ({
    page,
  }) => {
    const fixture = JSON.parse(
      readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
    );
    const runId = 'browser-iteration-' + status;
    fixture.report.run = { ...fixture.report.run, id: runId, status, completed_at: null };
    fixture.status = {
      ...fixture.status,
      run_id: runId,
      status,
      completed_cases: 0,
      progress: 0,
      completed_at: null,
      error: status === 'failed' ? '测试运行失败' : null,
    };
    let optimizationCalls = 0;
    await page.route('**/api/runs/' + runId + '**', async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const prefix = '/api/runs/' + runId;
      if (pathname === prefix + '/optimization') optimizationCalls++;
      const payload =
        pathname === prefix + '/status'
          ? fixture.status
          : { run: fixture.report.run, results: [], complete: status === 'failed' };
      await route.fulfill({ json: { code: '0', message: 'ok', data: payload } });
    });
    await enterCatalog(page);
    await page.goto('/#/tasks/' + runId);
    await page
      .getByRole('navigation', { name: '测评任务详情页签', exact: true })
      .getByRole('button', { name: '优化迭代', exact: true })
      .click();
    const iteration = page.getByRole('region', { name: '优化迭代', exact: true });
    await expect(iteration).toHaveText('能力构建中');
    await expect(iteration.getByRole('button')).toHaveCount(0);
    expect(optimizationCalls).toBe(0);
  });
}
