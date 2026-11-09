import { expect, test } from '@playwright/test';
import { passAuthGate } from './auth-gate';

test('rule history loads only on demand and pages within the selected version', async ({
  page,
}) => {
  const evaluator = {
    id: 'history-rule',
    name: '历史测试规则',
    description: '规则详情',
    source: 'user',
    enabled: true,
    has_draft: false,
    latest_version: '2',
    kind: 'rule',
    dimension: 'test',
    metric: 'test',
    implementation_id: 'test',
    implementation_version: '1',
  };
  const definition = {
    kind: evaluator.kind,
    dimension: evaluator.dimension,
    metric: evaluator.metric,
    implementation_id: evaluator.implementation_id,
    implementation_version: evaluator.implementation_version,
    config: {},
    children: [],
    version: '2',
  };
  const calls: string[] = [];
  await page.route('**/api/evaluators?*', (route) => route.fulfill({ json: [evaluator] }));
  await page.route('**/api/evaluators/history-rule', (route) =>
    route.fulfill({ json: { evaluator, latest: definition, draft: null } }),
  );
  await page.route('**/api/evaluators/history-rule/versions', (route) =>
    route.fulfill({ json: [definition, { ...definition, version: '1' }] }),
  );
  await page.route('**/api/evaluators/history-rule/versions/*/related-tasks?*', (route) => {
    const url = new URL(route.request().url());
    const version = url.pathname.split('/').at(-2);
    const cursor = url.searchParams.get('cursor');
    calls.push(version + (url.searchParams.has('cursor') ? '/' + cursor : ''));
    const current = {
      task_id: 'task-ab',
      run_id: 'run-ab',
      name: '对比测评',
      kind: 'ab',
      status: 'completed',
      created_at: '2026-10-20T01:00:00Z',
      evaluator_version: '2',
    };
    const older = {
      ...current,
      task_id: null,
      run_id: 'run-old',
      name: '独立运行',
      kind: 'single',
    };
    return route.fulfill({
      json: {
        items: version === '1' ? [] : [cursor ? older : current],
        next_cursor: version === '2' && !cursor ? 'next' : null,
      },
    });
  });

  await page.goto('/agentgate/#/evaluators');
  await expect(
    page
      .getByRole('heading', { name: '欢迎页面' })
      .or(page.getByText(evaluator.name, { exact: true })),
  ).toBeVisible();
  await passAuthGate(page);
  await page.getByRole('link', { name: '评估器', exact: true }).click();
  await page
    .locator('article')
    .filter({ hasText: evaluator.name })
    .getByRole('button', { name: '查看详情' })
    .click();
  expect(calls).toEqual([]);
  const detail = page.getByRole('dialog', { name: '规则评估器详情' });
  const detailsTab = detail.getByRole('tab', { name: '评估器详情', exact: true });
  const entry = detail.getByRole('tab', { name: '关联测评历史', exact: true });
  await expect(entry).toBeVisible({ timeout: 4000 });
  await expect(detailsTab).toHaveAttribute('aria-selected', 'true');
  await detailsTab.focus();
  await page.keyboard.press('ArrowRight');
  const history = detail.getByRole('tabpanel', { name: '关联测评历史' });
  await expect(entry).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await expect(history.getByLabel('发布版本')).toHaveValue('2');
  await expect(history.getByRole('link', { name: '查看任务 对比测评' })).toHaveAttribute(
    'href',
    /#\/?tasks\/task-ab$/,
  );
  await history.getByRole('button', { name: '下一页' }).click();
  await expect(history.getByRole('link', { name: '查看任务 独立运行' })).toHaveAttribute(
    'href',
    /#\/?tasks\/run-old$/,
  );
  await history.getByRole('button', { name: '上一页' }).click();
  await expect(history.getByRole('link', { name: '查看任务 对比测评' })).toBeVisible();
  await history.getByLabel('发布版本').selectOption('1');
  await expect(history.getByText('当前版本暂无关联测评任务')).toBeVisible();
  await expect(history.getByRole('button', { name: '上一页' })).toBeDisabled();
  expect(calls).toEqual(['2', '2/next', '2', '1']);
  await detailsTab.click();
  await expect(history).toBeHidden();
  await expect(detail).toBeVisible();
  await expect(detailsTab).toHaveAttribute('aria-selected', 'true');
});
