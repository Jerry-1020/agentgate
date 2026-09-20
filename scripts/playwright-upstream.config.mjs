import {defineConfig} from '../frontend/node_modules/@playwright/test/index.mjs';

export default defineConfig({
  testDir: '../frontend/tests',
  testMatch: ['bank-integration.spec.ts', 'unified-tasks.spec.ts', 'upstream-api.spec.ts'],
  timeout: 60000,
  workers: 1,
  use: {baseURL: 'http://127.0.0.1:5197', viewport: {width: 1440, height: 1000}},
  outputDir: '../runtime/upstream-page-tests',
  reporter: [['list'], ['json', {outputFile: '../runtime/upstream-acceptance/page-tests.json'}]],
});
