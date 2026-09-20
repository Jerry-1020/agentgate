import {defineConfig} from '@playwright/test'
export default defineConfig({testDir:'./tests',testMatch:['review-merge-unit.spec.ts','dataset-import-unit.spec.ts'],workers:1,outputDir:'../runtime/review-unit-tests'})
