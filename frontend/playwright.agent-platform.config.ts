import { defineConfig } from '@playwright/test'

// Agent platform login + target selection flows (welcome page, picker, task form).
export default defineConfig({
  testDir: './tests',
  testMatch: [
    'welcome-login.spec.ts',
    'agent-target-picker.spec.ts',
    'agent-platform-task.spec.ts',
  ],
  timeout: 45000,
  workers: 1,
  outputDir: '../runtime/agent-platform-tests',
})
