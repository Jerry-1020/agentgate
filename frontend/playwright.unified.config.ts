import {defineConfig} from '@playwright/test'
export default defineConfig({
 testDir:'./tests',testMatch:'unified-tasks.spec.ts',workers:1,timeout:60000,
 use:{baseURL:'http://127.0.0.1:5197',viewport:{width:1440,height:1000},launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROME_PATH||undefined}},
 outputDir:'../runtime/unified-ui-tests',
})
