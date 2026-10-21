import { test as base, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
export const test = base.extend({
  page: async ({ page }, use, info) => {
    page.on('pageerror', error => console.error('Browser error:', error.message));
    const snapshots: unknown[] = [];
    await page.exposeFunction('__saveSummaryCoverage', (value: unknown) => snapshots.push(value));
    await page.addInitScript(() => {
      window.addEventListener('beforeunload', () => {
        const w = window as any;
        if (w.__coverage__) void w.__saveSummaryCoverage(w.__coverage__);
      });
    });
    await use(page);
    for (const frame of page.frames()) {
      const coverage = await frame.evaluate(() => (window as any).__coverage__).catch(() => null);
      if (coverage) snapshots.push(coverage);
    }
    const directory = resolve('../runtime/summary-coverage/raw');
    await mkdir(directory, { recursive: true });
    await writeFile(resolve(directory, `${info.testId}-${info.retry}.json`), JSON.stringify(snapshots));
  },
});
export { expect };
