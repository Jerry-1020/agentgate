import { defineConfig } from '@playwright/test';
export default defineConfig({
  globalSetup: './tests/evaluation-summary-setup.ts',
  testDir: './tests', testMatch: ['evaluation-summaries.spec.ts'],
  timeout: 30000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5299', viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined } },
  outputDir: '../runtime/summary-browser-tests',
  webServer: { command: 'npm run dev -- --port 5299 --mode summary-coverage',
    url: 'http://127.0.0.1:5299', reuseExistingServer: false, timeout: 120000 },
});
