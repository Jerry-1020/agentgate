import { test, expect } from '@playwright/test';

// Browser-only fixtures: no tasks or dataset samples are written to the backend.
test('single-turn and multi-turn samples have distinct layouts and working view modes', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const turn = (id: string) => ({ id, input: `问题 ${id}`, expectations: [] });
  const cases = [
    { id: 'single', name: '单轮样本', tags: [], turns: [turn('one')] },
    { id: 'multi', name: '多轮样本', tags: [], turns: [turn('first'), turn('second'), turn('third')] },
  ];
  const report = {
    run: { id: 'conversation-fixture', manifest: {
      dataset: { cases }, selected_case_ids: null,
      evaluator_specs: [], primary_evaluator_ids: [],
    } },
    results: [], metrics: [],
  };
  await page.route('**/api/runs/conversation-fixture**', route => route.fulfill({ json:
    route.request().url().endsWith('/status')
      ? { status: 'completed', completed_cases: 2, total_cases: 2 }
      : report,
  }));
  await page.goto('/#/tasks/conversation-fixture/samples/single');
  const panel = page.locator('.conversation-panel');
  await expect(panel.getByRole('heading', { name: '单轮对话', exact: true })).toBeVisible();
  await expect(panel.getByRole('radiogroup')).toHaveCount(0);
  await expect(panel.locator('.conversation-body > aside')).toHaveCount(0);
  await expect(panel.locator('.conversation-turn')).toHaveCount(1);
  await expect(panel).toContainText('问题 one');

  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(panel.getByRole('heading', { name: '多轮对话', exact: true })).toBeVisible();
  await expect(panel.locator('.conversation-body > aside button')).toHaveCount(3);
  await expect(panel.getByRole('radio', { name: '单轮聚焦' })).toHaveAttribute('aria-checked', 'true');
  await expect(panel.locator('.conversation-turn')).toHaveCount(1);
  await panel.locator('.conversation-body > aside button').nth(1).click();
  await expect(panel.locator('.conversation-turn')).toContainText('问题 second');
  await panel.getByRole('radio', { name: '连续对话' }).click();
  await expect(panel.getByRole('radio', { name: '连续对话' })).toHaveAttribute('aria-checked', 'true');
  await expect(panel.locator('.conversation-turn')).toHaveCount(3);
  await expect(panel.getByRole('main')).toHaveCSS('overflow-y', 'auto');
  await panel.getByRole('radio', { name: '单轮聚焦' }).click();
  await expect(panel.locator('.conversation-turn')).toHaveCount(1);
  await expect(panel.locator('.conversation-turn')).toContainText('问题 second');

  await panel.getByRole('radio', { name: '连续对话' }).click();
  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await expect(panel.getByRole('heading', { name: '单轮对话', exact: true })).toBeVisible();
  await expect(panel.getByRole('radiogroup')).toHaveCount(0);
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(panel.getByRole('radio', { name: '单轮聚焦' })).toHaveAttribute('aria-checked', 'true');
  await expect(panel.locator('.conversation-turn')).toHaveCount(1);
  await expect(panel.locator('.conversation-turn')).toContainText('问题 first');

  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await page.setViewportSize({ width: 600, height: 900 });
  await expect(panel.locator('.conversation-body > aside')).toHaveCount(0);
  expect(await panel.locator('.conversation-body').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
});
