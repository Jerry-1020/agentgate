import { test, expect, type Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
test.beforeEach(async ({page}) => { await page.coverage.startJSCoverage({resetOnNavigation:false}); });
test.afterEach(async ({page}, info) => { await writeFile(info.outputPath('coverage.json'), JSON.stringify(await page.coverage.stopJSCoverage())); });
const envelope=(data:unknown)=>({code:'0',message:'success',data});
const entry=(id:string,kind='rule')=>({id,name:id,description:'description',source:'user',enabled:true,kind,
  latest_version:'1',has_draft:false,implementation_id:kind==='rule'?'final_output':'answer_quality',implementation_version:'1',metric:'quality',dimension:'answer',child_count:0});
async function setup(page:Page){
  const state={catalog:[entry('rule-one'),entry('llm-one','llm_judge')],fail:false,detailFail:false};
  const calls:string[]=[];
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!path.startsWith('/api/'))return route.continue();
    calls.push(path);
    if(path==='/api/evaluator-catalog')return route.fulfill(state.fail?{status:503,json:{detail:'failed'}}:{json:envelope(state.catalog)});
    if(path.startsWith('/api/evaluators/')) {
      if(state.detailFail)return route.fulfill({status:503,json:{detail:'failed'}});
      const id=path.split('/').pop()!;
      return route.fulfill({json:envelope({evaluator:entry(id,'llm_judge'),latest:{kind:'llm_judge',version:'1',implementation_id:'answer_quality',implementation_version:'1',config:{instruction:'judge carefully',rubric:{quality:'accurate'},model:{provider_id:'provider',model_id:'model'}},dimension:'answer',metric:'quality'},draft:null})});
    }
    return route.fulfill({json:envelope({})});
  });
  await page.goto('/tests/summary-harness.html');await page.waitForFunction(()=>!!(window as any).summaryHarness);
  return {state,calls};
}
const mount=(page:Page,component='judges')=>page.evaluate(component=>(window as any).summaryHarness.mount('/judges',component),component);
const snapshot=(page:Page)=>page.evaluate(()=>(window as any).summaryHarness.review());
test('directory renders without fetching all definitions; LLM cards load only on their tab',async({page})=>{
  const {calls}=await setup(page);await mount(page);
  await expect(page.getByRole('heading',{name:'rule-one',exact:true})).toBeVisible();
  expect(calls).toEqual(['/api/evaluator-catalog']);
  await page.getByRole('button',{name:'LLM 评估',exact:true}).click();
  await expect(page.getByRole('heading',{name:'llm-one',exact:true})).toBeVisible();
  await expect.poll(()=>calls.filter(p=>p==='/api/evaluators/llm-one').length).toBe(1);
  expect(calls).not.toContain('/api/evaluators/rule-one');
});
test('refresh replaces whole catalog and failed refresh preserves saved rows until retry',async({page})=>{
  const {state,calls}=await setup(page);await mount(page);
  await expect(page.getByRole('heading',{name:'rule-one',exact:true})).toBeVisible();
  state.catalog=[entry('saved-rule')];
  await page.evaluate(()=>(window as any).summaryHarness.refreshCatalog());
  await expect(page.getByRole('heading',{name:'saved-rule',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'rule-one',exact:true})).toHaveCount(0);
  state.fail=true;await page.evaluate(()=>(window as any).summaryHarness.refreshCatalog());
  await expect(page.getByRole('alert')).toContainText('已成功保存的操作不受影响');
  await expect(page.getByRole('heading',{name:'saved-rule',exact:true})).toBeVisible();
  state.fail=false;await page.getByRole('button',{name:'重试',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(calls.every(p=>p==='/api/evaluator-catalog')).toBe(true);
});
test('scoring templates and model references load on demand; detail failure leaves catalog intact',async({page})=>{
  const {state,calls}=await setup(page);await mount(page);
  await expect(page.getByRole('heading',{name:'rule-one',exact:true})).toBeVisible();
  state.detailFail=true;await page.evaluate(()=>(window as any).summaryHarness.loadDetails());
  expect((await snapshot(page)).catalog).toHaveLength(2);
  expect((await snapshot(page)).detailsError).toContain('读取失败');
  state.detailFail=false;await page.evaluate(()=>(window as any).summaryHarness.loadDetails());
  const value=await snapshot(page);
  expect(value.details['llm-one'].latest.config.model.model_id).toBe('model');
  expect(value.templates[0].instruction).toBe('judge carefully');
  expect(calls).not.toContain('/api/evaluators/rule-one');
  await mount(page,'templates');
  await expect(page.getByRole('heading',{name:'llm-one · 评分模板',exact:true})).toBeVisible();
});
test('identity change clears data and ignores delayed old directory response',async({page})=>{
  const {state}=await setup(page);let release!:()=>void;let seen=false;
  const gate=new Promise<void>(resolve=>release=resolve);
  await page.route('**/api/evaluator-catalog?*',async route=>{
    if(!seen){seen=true;await gate;await route.fulfill({json:envelope([entry('old-team')])});}
    else await route.fulfill({json:envelope([entry('new-team')])});
  });
  await mount(page);await expect.poll(()=>seen).toBe(true);
  await page.evaluate(()=>(window as any).summaryHarness.auth({teamId:'new-team'}));
  await expect(page.getByRole('heading',{name:'new-team',exact:true})).toBeVisible();
  release();
  await expect.poll(async()=>(await snapshot(page)).catalog.map((e:any)=>e.id)).toEqual(['new-team']);
  await expect(page.getByRole('heading',{name:'old-team',exact:true})).toHaveCount(0);
});

test('concurrent directory and configuration consumers share in-flight requests',async({page})=>{
  const {calls}=await setup(page);
  await page.evaluate(()=>Promise.all([(window as any).summaryHarness.refreshCatalog(),(window as any).summaryHarness.refreshCatalog()]));
  expect(calls).toEqual(['/api/evaluator-catalog']);
  await page.evaluate(()=>Promise.all([(window as any).summaryHarness.loadDetails(),(window as any).summaryHarness.loadDetails()]));
  expect(calls.filter(p=>p==='/api/evaluators/llm-one')).toHaveLength(1);
});
test('delayed model definitions from old identity cannot restore cleared data',async({page})=>{
  await setup(page);await mount(page);
  await expect(page.getByRole('heading',{name:'rule-one',exact:true})).toBeVisible();
  let release!:()=>void;let seen=false;const gate=new Promise<void>(resolve=>release=resolve);
  await page.route('**/api/evaluators/llm-one',async route=>{
    seen=true;await gate;await route.fulfill({json:envelope({evaluator:entry('llm-one','llm_judge'),latest:{kind:'llm_judge',config:{model:{model_id:'old-model'}},version:'1'},draft:null})});
  });
  await page.evaluate(()=>{void (window as any).summaryHarness.loadDetails();});
  await expect.poll(()=>seen).toBe(true);
  await page.evaluate(()=>(window as any).summaryHarness.auth({teamId:'other-team'}));
  release();
  await expect.poll(async()=>(await snapshot(page)).details).toEqual({});
  expect((await snapshot(page)).templates).toEqual([]);
});
test('catalog failure does not silently fall back to legacy endpoint',async({page})=>{
  const {state,calls}=await setup(page);state.fail=true;await mount(page);
  await expect(page.getByRole('alert')).toContainText('目录刷新失败');
  expect(calls).toEqual(['/api/evaluator-catalog']);
  await page.evaluate(()=>(window as any).summaryHarness.loadDetails());
  expect(calls).toEqual(['/api/evaluator-catalog']);
});
