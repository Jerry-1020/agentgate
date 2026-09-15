import {defineConfig} from '@playwright/test'
export default defineConfig({
 testDir:'./tests', testMatch:['upstream-integration.spec.ts','upstream-api.spec.ts','ux-0915.spec.ts','task-result-navigation.spec.ts','frontend-only-analysis.spec.ts'], timeout:45000, workers:1,
 use:{baseURL:process.env.UX_BASE_URL||'http://127.0.0.1:5196', viewport:{width:1440,height:1000},
  launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROME_PATH||undefined}},
 outputDir:'../runtime/browser-tests',
})
