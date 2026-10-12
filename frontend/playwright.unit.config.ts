import {defineConfig} from '@playwright/test'

// Pure data/contract tests. These tests never create a browser or page fixture.
export default defineConfig({
  testDir: './tests',
  testMatch: ['architecture-unit.spec.ts', 'dataset-export-unit.spec.ts', 'dataset-import-unit.spec.ts', 'review-merge-unit.spec.ts', 'task-report-unit.spec.ts', 'annotation-progress-unit.spec.ts', 'annotation-template-store-unit.spec.ts', 'annotation-feedback-unit.spec.ts', 'annotation-v2-editor-unit.spec.ts', 'annotation-v2-list-unit.spec.ts', 'sample-output-unit.spec.ts', 'trace-presentation-unit.spec.ts', 'dashboard-unit.spec.ts', 'evaluator-design-unit.spec.ts'],
  workers: 1,
  outputDir: '../runtime/unit-tests',
})
