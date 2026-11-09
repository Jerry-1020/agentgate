import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
const envelope = (data: unknown) => ({code:'0',message:'success',data});
async function setup(page: Page, fail = false) {
  page.on('pageerror', error => console.error('PAGE ERROR', error.message));
  page.on('console', message => { if (message.type() === 'error') console.error(message.text()); });
  const calls: string[] = [];
  const state = { fail, status: 'completed' };
  const run = () => ({id:'run-1',created_at:'2026-11-07T00:00:00Z',status:state.status,manifest:{target:{ref:{external_version_id:'v1'}},
    dataset:{cases:[{id:'case-1',name:'sample one',tags:[],turns:[{id:'t1',input:{query:'hello'}}]}]},
    primary_evaluator_ids:['e1'],evaluator_specs:[{id:'e1',name:'Rule',kind:'rule'}]}});
  const results = [{case_id:'case-1',evaluator_id:'e1',score:0.8,outcome:'pass'}];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    calls.push(path);
    if(path.endsWith('/sample-resource-usage')) return route.fulfill(state.fail
      ? {status:503,json:{detail:'unavailable'}}
      : {json:envelope({items:[{case_id:'case-1',total_tokens:14351,duration_ms:5850,token_status:'partial',duration_source:'turn_bounds'}]})});
    if(path.endsWith('/status')) return route.fulfill({json:envelope({status:state.status,progress:1,total_cases:1,completed_cases:1,created_at:'2026-11-07T00:00:00Z'})});
    if(path.endsWith('/samples')) return route.fulfill({json:envelope({run:run(),results})});
    if(path==='/api/runs/run-1') return route.fulfill({json:envelope({run:run(),results,metrics:[{level:'overall',score:0.8}],release_gate:{outcome:'pass'}})});
    return route.fulfill({json:envelope({})});
  });
  await page.goto('/tests/summary-harness.html');
  await page.waitForFunction(() => !!(window as any).summaryHarness);
  return {calls,state};
}
async function mount(page: Page) {
  await page.evaluate(() => (window as any).summaryHarness.mount('/tasks/run-1','results',{id:'run-1'}));
}
test('resource columns and CSV use one summary, never per-sample Trace',async({page})=>{
  const {calls}=await setup(page); await mount(page);
  await expect(page.getByRole('columnheader',{name:'总 Token'})).toBeVisible();
  await expect(page.getByRole('cell',{name:'14,351（部分）',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'5.850 秒',exact:true})).toBeVisible();
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 CSV',exact:true}).click();
  const file=await (await download).path();
  const csv=await readFile(file!,'utf8');
  expect(csv).toContain('14351'); expect(csv).toContain('5.85'); expect(csv).toContain('部分');
  expect(calls.filter(p=>p.endsWith('/sample-resource-usage'))).toHaveLength(1);
  expect(calls.some(p=>p.includes('/traces/'))).toBe(false);
});
test('summary failure leaves scores visible and supports independent retry',async({page})=>{
  const {state}=await setup(page,true); await mount(page);
  await expect(page.getByRole('status')).toContainText('不影响评估结果');
  await expect(page.getByRole('cell',{name:'80.0',exact:true}).first()).toBeVisible();
  state.fail=false;
  await page.getByRole('button',{name:'重试资源统计'}).click();
  await expect(page.getByRole('cell',{name:'14,351（部分）',exact:true})).toBeVisible();
  await expect(page.getByRole('status')).toHaveCount(0);
});
test('running refresh is throttled and completion fetches final summary then stops',async({page})=>{
  const {state,calls}=await setup(page); state.status='running';
  await page.clock.install(); await mount(page);
  await expect(page.getByRole('cell',{name:'5.850 秒',exact:true})).toBeVisible();
  await page.clock.fastForward(5000);
  await expect.poll(()=>calls.filter(p=>p.endsWith('/status')).length).toBe(2);
  expect(calls.filter(p=>p.endsWith('/sample-resource-usage'))).toHaveLength(1);
  state.status='completed';
  await page.clock.fastForward(5000);
  await expect.poll(()=>calls.filter(p=>p.endsWith('/sample-resource-usage')).length).toBe(2);
  await page.clock.fastForward(60000);
  expect(calls.filter(p=>p.endsWith('/sample-resource-usage'))).toHaveLength(2);
});
