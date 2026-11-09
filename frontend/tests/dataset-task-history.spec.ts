import { expect, test } from '@playwright/test';
import { passAuthGate } from './auth-gate';

test('dataset history reads only the selected published version and pages by cursor', async ({
  page,
}) => {
  const createdAt = '2026-10-20T01:00:00Z';
  const dataset = {
    id: 'history-dataset',
    name: '历史测试测评集',
    description: '',
    archived: false,
    created_at: createdAt,
    updated_at: createdAt,
  };
  const published = {
    id: 'v2',
    dataset_id: dataset.id,
    dataset_name: dataset.name,
    dataset_description: '',
    version: 2,
    status: 'published',
    based_on_version: 1,
    cases: [],
    notes: '',
    created_at: createdAt,
    updated_at: createdAt,
    published_at: createdAt,
    content_sha256: 'fixture',
  };
  const envelope = (data: unknown) => ({ code: 0, message: '', data });
  await page.route('**/api/datasets', (route) =>
    route.fulfill({ json: envelope([{ ...dataset, version: 2, case_count: 0, has_draft: true }]) }),
  );
  await page.route('**/api/datasets/history-dataset', (route) =>
    route.fulfill({
      json: envelope({
        dataset,
        versions: [
          { ...published, id: 'draft', version: null, status: 'draft', published_at: null },
          published,
          { ...published, id: 'v1', version: 1 },
        ],
      }),
    }),
  );
  const calls: string[] = [];
  await page.route('**/api/datasets/history-dataset/versions/*/related-tasks?*', (route) => {
    const url = new URL(route.request().url());
    const version = url.pathname.split('/').at(-2);
    const cursor = url.searchParams.get('cursor');
    calls.push(version + url.search);
    const task = {
      task_id: 'stability-test',
      run_id: 'run-stability',
      name: '稳定性回归',
      kind: 'stability',
      status: 'waiting',
      created_at: createdAt,
      dataset_version: 2,
    };
    const standalone = {
      ...task,
      task_id: null,
      run_id: 'run-legacy',
      kind: 'single',
      name: '独立运行',
    };
    return route.fulfill({
      json: envelope({
        items: version === '2' ? [cursor ? standalone : task] : [],
        next_cursor: version === '2' && !cursor ? 'older' : null,
      }),
    });
  });

  await page.goto('/agentgate/#/datasets');
  await expect(page.getByRole('heading', { name: '欢迎页面' })).toBeVisible();
  await passAuthGate(page);
  await page.getByRole('link', { name: '测评集', exact: true }).click();
  await page
    .getByRole('button', { name: /历史测试测评集/ })
    .first()
    .click();
  await page.getByTestId('version-published-2').click();
  expect(calls).toEqual([]);
  await page.getByRole('button', { name: '关联测评历史', exact: true }).click();
  const table = page.getByRole('table', { name: '关联测评任务' });
  await expect(table.getByRole('columnheader')).toHaveText(
    ['任务名称', '版本', '状态', '创建时间', '操作'],
    { timeout: 4000 },
  );
  await expect(page.getByText('任务创建时间倒序', { exact: true })).toHaveCount(0);
  await expect(table.getByRole('rowheader')).toHaveText('稳定性回归');
  await expect(table.getByRole('cell', { name: '2026-10-20 09:00:00', exact: true })).toBeVisible();
  await expect(table.getByRole('cell', { name: '等待中' })).toBeVisible();
  await expect(table.getByRole('link', { name: '查看任务 稳定性回归' })).toHaveAttribute(
    'href',
    /#\/?stability\/stability-test$/,
  );
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(table.getByRole('link', { name: '查看任务 独立运行' })).toHaveAttribute(
    'href',
    /#\/?tasks\/run-legacy$/,
  );
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await expect(table.getByRole('rowheader')).toContainText('稳定性回归');
  await page.getByTestId('version-published-1').click();
  await expect(page.getByText('当前版本暂无关联测评任务')).toBeVisible();
  await expect(page.getByRole('button', { name: '上一页', exact: true })).toBeDisabled();
  await page.getByTestId('version-draft-draft').click();
  await expect(page.getByText('草稿尚未发布，暂无关联测评任务')).toBeVisible();
  expect(calls).toEqual(['2?limit=20', '2?limit=20&cursor=older', '2?limit=20', '1?limit=20']);
});
