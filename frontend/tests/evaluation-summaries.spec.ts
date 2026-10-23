import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
const envelope = (data: unknown) => ({ code: '0', message: 'success', data });
function row(id = 'task-1', kind = 'single', status = 'completed', taskId: string | null = id) {
  const run = (side: string) => ({ run_id: id + side, status, target_name: 'Agent ' + side,
    target_version: 'v1', dataset_name: 'Dataset ' + side, dataset_version: 1,
    evaluator_kinds: ['rule'], scoring_mode: 'overall', total_cases: 2,
    completed_cases: status === 'completed' ? 2 : 1, overall_score: status === 'completed' ? 0 : null, gate_reason: null });
  return { id, task_id: taskId, name: id, kind, created_at: new Date().toISOString(), status,
    total_cases: 2, completed_cases: status === 'completed' ? 2 : 1, previous_run_count: 2,
    runs: kind === 'ab' ? [run('-a'), run('-b')] : [run('-a')] };
}
const metrics = { task_count: 104, average_score: 0, scored_run_count: 104, completed_sample_count: 208, dataset_count: 2, dataset_sample_count: 8 };
async function setup(page: Page, rows = [row()], total = rows.length) {
  const calls: {path: string; method: string; headers: Record<string,string>}[] = [];
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    calls.push({path:url.pathname + url.search, method:route.request().method(),headers:route.request().headers()});
    if (url.pathname === '/api/evaluation-overview/summary') return route.fulfill({json:envelope(metrics)});
    if (url.pathname === '/api/evaluation-task-summaries') return route.fulfill({json:envelope({items:rows,total,page:Number(url.searchParams.get('page')||1),page_size:Number(url.searchParams.get('page_size')||20)})});
    if (/^\/api\/evaluation-tasks\/[^/]+$/.test(url.pathname)) {
      const id = url.pathname.split('/').pop()!;
      return route.fulfill({json:envelope({id,kind:id==='ab'?'ab':'single',run_ids:id==='ab'?['ab-a','ab-b']:[id==='created'?'created-run':id+'-a'],static_report_ids:[]})});
    }
    if (url.pathname === '/api/evaluation-tasks') return route.fulfill({json:envelope([
      { id:'task-1', kind:'single', run_ids:['task-1-a'],previous_run_ids:[],static_report_ids:[] },
      { id:'ab', kind:'ab', run_ids:['ab-a','ab-b'],previous_run_ids:[],static_report_ids:[] },
      { id:'stable', kind:'stability', run_ids:['s'],previous_run_ids:[],static_report_ids:[] },
      { id:'created',kind:'single',run_ids:['created-run'],previous_run_ids:[],static_report_ids:[] },
    ])});
    if (url.pathname === '/api/runs') return route.fulfill({json:envelope(['task-1-a','ab-a','ab-b','s','created-run'].map(id=>({id,status:'completed',manifest:{}})))});
    return route.fulfill({json:envelope({})});
  });
  await page.goto('/tests/summary-harness.html');
  await page.waitForFunction(() => !!(window as any).summaryHarness);
  return calls;
}
async function mount(page: Page, path='/tasks', component='parent', props={}) {
  await page.evaluate(args => (window as any).summaryHarness.mount(...args), [path,component,props]);
}
async function navigate(page: Page, path: string) { await page.evaluate(path => (window as any).summaryHarness.navigate(path), path); }

test('overview uses two summaries, keeps values and recent tasks, day controls and retry', async ({page}) => {
  const calls=await setup(page,[row('ab','ab')]);
  await mount(page,'/overview');
  await expect(page.locator('.metric-value').first()).toHaveText('104');
  await expect(page.locator('.metric-value').nth(1)).toContainText('0');
  expect(calls.map(c=>c.path.split('?')[0]).sort()).toEqual(['/api/evaluation-overview/summary','/api/evaluation-task-summaries']);
  await page.getByRole('button',{name:'近30天',exact:true}).click();
  await expect.poll(()=>calls.length).toBe(4);
  await page.locator('table').getByRole('button',{name:'查看'}).click();
  await expect(page.getByText('Comparisons',{exact:true})).toBeVisible();
  await navigate(page,'/overview');
  await page.route('**/api/evaluation-overview/summary?*',r=>r.fulfill({status:503,json:{detail:'evaluation_summary_not_ready'}}));
  await page.getByRole('button',{name:'今日',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('摘要尚未就绪');
  await page.unroute('**/api/evaluation-overview/summary?*');
  await page.getByRole('button',{name:'重试',exact:true}).click();
  await expect(page.locator('.metric-value').first()).toHaveText('104');
});

test('task pagination, debounce, selection, kind and local dates have no detail reads',async({page})=>{
  const calls=await setup(page,[row()],104); await mount(page);
  await expect(page.getByText('共 104 个任务')).toBeVisible();
  expect(calls).toHaveLength(1);
  await page.getByLabel('选择本页任务').check();
  await page.getByRole('button',{name:'下一页'}).click();
  await expect.poll(()=>calls.length).toBe(2);
  expect(calls[1].path).toContain('page=2');
  await expect(page.getByLabel('选择本页任务')).not.toBeChecked();
  await page.getByRole('button',{name:'上一页'}).click();
  await page.getByLabel('搜索任务名称').fill('测试 %_&');
  await expect.poll(()=>calls.length).toBe(4);
  expect(new URL('http://x'+calls[3].path).searchParams.get('keyword')).toBe('测试 %_&');
  await page.getByRole('button',{name:'A/B试验',exact:true}).click();
  await expect.poll(()=>calls.length).toBe(5);
  expect(calls[4].path).toContain('kind=ab');
  await page.getByRole('button',{name:'单任务',exact:true}).click();
  await page.getByRole('button',{name:'全部',exact:true}).click();
  await page.getByRole('button',{name:'今日',exact:true}).click();
  await expect.poll(()=>calls.length).toBe(8);
  expect(calls.every(c=>c.path.startsWith('/api/evaluation-task-summaries?'))).toBe(true);
});

test('A/B scores, nulls, independent and stability rows preserve presentation and navigation',async({page})=>{
  const ab=row('ab','ab'); ab.runs[1].overall_score=.8; ab.runs[1].evaluator_kinds=['llm_group'];
  const stable=row('stable','stability');stable.runs[0].gate_reason='evaluator_error' as any;
  const independent=row('independent','single','failed',null); independent.runs[0].dataset_version=null as any;
  independent.previous_run_count=0;independent.total_cases=0;
  independent.runs[0].evaluator_kinds=['llm_judge','hybrid'];
  await setup(page,[ab,stable,independent]);await mount(page);
  await expect(page.locator('.task-score').first()).toContainText('B 80');
  await page.locator('.ab-summary').first().hover();
  await expect(page.locator('.ab-tooltip').first()).toContainText('Agent -b');
  await expect(page.getByText('评估器异常')).toBeVisible();
  await page.getByRole('button',{name:'stable',exact:true}).click();
  await expect(page.getByText('Stability',{exact:true})).toBeVisible();
});

test('delete handles dismiss, errors, success and last-page correction',async({page})=>{
  const calls=await setup(page,[row()],21);await mount(page);
  await page.getByRole('button',{name:'下一页'}).click();
  await expect(page.locator('footer')).toContainText('2 / 2');
  await page.getByRole('button',{name:'删除',exact:true}).click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  expect(calls.filter(c=>c.method==='DELETE')).toHaveLength(0);
  await page.route('**/api/evaluation-tasks/task-1',r=>r.fulfill({status:500,json:{detail:'delete failed'}}));
  await page.getByRole('button',{name:'删除',exact:true}).click();
  await page.getByRole('button',{name:'永久删除'}).click();
  await expect(page.getByText(/删除失败/)).toBeVisible();
  await page.unroute('**/api/evaluation-tasks/task-1');
  await page.route('**/api/evaluation-task-summaries?*',r=>r.fulfill({json:envelope({items:[],total:20,page:1,page_size:20})}));
  await page.getByRole('button',{name:'删除',exact:true}).click();
  await page.getByRole('button',{name:'永久删除'}).click();
  await expect(page.locator('footer')).toContainText('1 / 1');
});

test('cancel uses run identity; rerun uses task identity and detail follows task ID',async({page})=>{
  const calls=await setup(page,[row('task-1','single','running')]);await mount(page);
  await page.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'返回',exact:true}).click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'确认',exact:true}).click();
  await expect.poll(()=>calls.filter(c=>c.method==='POST').length).toBe(1);
  expect(calls.find(c=>c.method==='POST')?.path).toBe('/api/runs/task-1-a/cancel');
  await page.route('**/api/evaluation-task-summaries?*',r=>r.fulfill({json:envelope({items:[row()],total:1,page:1,page_size:20})}));
  await page.getByRole('button',{name:'今日',exact:true}).click();
  await page.getByRole('button',{name:'重跑',exact:true}).click();
  await expect(page.getByText('Rerun task-1-a task-1',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'close rerun'}).click();
  await page.getByRole('button',{name:'重跑',exact:true}).click();
  await page.getByRole('button',{name:'rerun complete'}).click();
  await expect(page.getByText('Detail task-1-a task-1',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'detail rerun complete'}).click();
  await page.getByRole('button',{name:'detail back'}).click();
  await expect(page.getByRole('heading',{name:'测评任务',exact:true})).toBeVisible();
});

test('visibility pauses polling; active rows refresh, terminal rows stop, unmount cancels',async({page})=>{
  const calls=await setup(page,[row('active','single','scheduled')]);
  await page.clock.install();await mount(page);
  await expect(page.getByText('共 1 个任务')).toBeVisible();
  await page.clock.fastForward(5100);await expect.poll(()=>calls.length).toBe(2);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
  await page.clock.fastForward(10000);expect(calls).toHaveLength(2);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>calls.length).toBe(3);
  await page.route('**/api/evaluation-task-summaries?*',r=>r.fulfill({json:envelope({items:[row()],total:1,page:1,page_size:20})}));
  await page.clock.fastForward(5100);await expect(page.getByRole('button',{name:'task-1',exact:true})).toBeVisible();
  const count=calls.length;await page.clock.fastForward(15000);expect(calls).toHaveLength(count);
  await page.evaluate(()=>(window as any).summaryHarness.unmount());
  await page.clock.fastForward(15000);expect(calls).toHaveLength(count);
});

test('team change clears prior data and sends five headers; old delayed responses cannot overwrite',async({page})=>{
  const calls=await setup(page);await mount(page);
  await expect(page.getByRole('button',{name:'task-1',exact:true})).toBeVisible();
  await page.route('**/api/evaluation-task-summaries?*',async route=>{
    const team=route.request().headers()['x-team-id'];
    if(team==='a') await new Promise(resolve=>setTimeout(resolve,200));
    await route.fulfill({json:envelope({items:[row(team||'unknown')],total:1,page:1,page_size:20})}).catch(()=>{});
  });
  const teamARequest=page.waitForRequest(r=>r.headers()['x-team-id']==='a');
  await page.evaluate(()=>(window as any).summaryHarness.auth({loginMode:'bank',token:'fake-token',teamId:'a',teamName:'团队',userId:'u',userName:'用户'}));
  const sent = await teamARequest;
  expect(sent.headers()).toMatchObject({token:'fake-token','x-team-id':'a','x-team-name':encodeURIComponent('团队'),'x-user-id':'u','x-user-name':encodeURIComponent('用户')});
  await page.evaluate(()=>(window as any).summaryHarness.auth({teamId:'b'}));
  await expect(page.getByRole('button',{name:'b',exact:true})).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByRole('button',{name:'a',exact:true})).toHaveCount(0);
  await page.route('**/api/evaluation-task-summaries?*',r=>r.fulfill({status:503,json:{detail:'missing'}}));
  await page.evaluate(()=>(window as any).summaryHarness.auth({teamId:'c'}));
  await expect(page.getByRole('alert')).toContainText('摘要尚未就绪');
  await expect(page.getByRole('button',{name:'b',exact:true})).toHaveCount(0);
});

test('parent route context, A/B tabs, creation, dirty guard, logout and unknown route',async({page})=>{
  await setup(page);await mount(page,'/tasks/ab');
  await expect(page.getByText('Comparisons',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'调优分析',exact:true}).click();await expect(page.getByText('Tuning',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Skill 静态分析',exact:true}).click();await expect(page.getByText('Static',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'实验对比',exact:true}).click();
  await page.getByRole('button',{name:/实验 A/}).click();
  await navigate(page,'/tasks');
  await page.getByRole('button',{name:'新建测评任务'}).click();await page.getByRole('button',{name:'close form'}).click();
  await page.getByRole('button',{name:'新建测评任务'}).click();await page.getByRole('button',{name:'submit single'}).click();
  await expect(page.getByText('Detail created-run created',{exact:false})).toBeVisible();
  await navigate(page,'/datasets');await page.getByRole('button',{name:'dataset launch'}).click();await page.getByRole('button',{name:'submit stability'}).click();
  await expect(page.getByText('Stability',{exact:true})).toBeVisible();
  await navigate(page,'/judges');await page.getByRole('button',{name:'judge launch'}).click();await page.getByRole('button',{name:'close form'}).click();
  await navigate(page,'/settings');await page.getByRole('button',{name:'dirty',exact:true}).click();
  page.once('dialog',d=>d.dismiss());await navigate(page,'/tasks');await expect(page.getByText('Settings',{exact:false})).toBeVisible();
  page.once('dialog',d=>d.accept());await navigate(page,'/annotations');await expect(page.getByText('待实现',{exact:true})).toBeVisible();
  await navigate(page,'/dataset-merge');await expect(page.getByText(/多 Skill 合并需求已挂起/)).toBeVisible();
  await navigate(page,'/analysis');await expect(page.getByText('Analysis',{exact:true})).toBeVisible();
  await navigate(page,'/unknown');await expect(page.getByText(/页面不存在/)).toBeVisible();
  await page.getByRole('button',{name:'logout',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'logout',exact:true}).click();await page.getByRole('button',{name:'确认登出',exact:true}).click();
});

test('empty metrics and helper boundaries including DST',async({page})=>{
  await setup(page,[]);await mount(page,'/overview');
  await expect(page.getByText('尚无测评任务，请从“测评任务”发起。')).toBeVisible();
  await mount(page,'/','metrics',{data:null,error:'network'});
  await expect(page.locator('.metric-value').first()).toHaveText('—');
  await page.getByRole('button',{name:'重试'}).click();
  const result=await page.evaluate(()=>{
    const h=(window as any).summaryHarness.helpers;
    return [h.dayWindow(0),h.dayWindow(1),h.taskPath({kind:'single',task_id:null,runs:[{run_id:'r'}]}),h.hasActiveRuns([]),h.evaluatorStrategy(['rule','rule','llm_group','hybrid'])];
  });
  expect(result[0]).toEqual({});expect(result[2]).toBe('tasks/r');expect(result[3]).toBe(false);
});


test('real integrated iframe sends all five identity headers and hides auth controls',async({page})=>{
  const calls=await setup(page);
  await page.route('**/summary-host', r=>r.fulfill({contentType:'text/html',body:`<iframe style="width:1400px;height:1000px" src="/?embedded=1&token=fake&teamId=bank-team&teamName=Bank&userId=bank-user&userName=User#/tasks"></iframe>`}));
  await page.goto('/summary-host');
  const frame=page.frameLocator('iframe');
  await expect(frame.getByRole('heading',{name:'测评任务',exact:true})).toBeVisible();
  await expect(frame.getByText('共 1 个任务')).toBeVisible();
  await expect(frame.getByRole('button',{name:'登出',exact:true})).toHaveCount(0);
  const summary=calls.filter(c=>c.path.startsWith('/api/evaluation-task-summaries'));
  expect(summary).toHaveLength(1);
  expect(summary[0].headers).toMatchObject({token:'fake','x-team-id':'bank-team','x-team-name':'Bank','x-user-id':'bank-user','x-user-name':'User'});
  expect(calls.some(c=>/^\/api\/(runs|evaluation-tasks|overview)([/?]|$)/.test(c.path))).toBe(false);
  const footer=frame.locator('.tasks-list footer');await expect(footer).toBeVisible();
  await expect(footer.getByRole('button',{name:'下一页'})).toBeDisabled();
});

test('integrated iframe accepts empty identity fields without falling back to old APIs',async({page})=>{
  const calls=await setup(page);
  await page.route('**/summary-host',r=>r.fulfill({contentType:'text/html',body:'<iframe style="width:1400px;height:1000px" src="/?embedded=1#/overview"></iframe>'}));
  await page.goto('/summary-host');
  const frame=page.frameLocator('iframe');
  await expect(frame.locator('.metric-value').first()).toHaveText('104');
  expect(calls).toHaveLength(2);
  for(const call of calls) expect(call.headers).toMatchObject({token:'','x-team-id':'','x-team-name':'','x-user-id':'','x-user-name':''});
});

test('real external page preserves layout and starts only summary requests',async({page})=>{
  const calls=await setup(page);
  await page.goto('/#/welcome');
  await page.getByRole('button',{name:'行外Login',exact:true}).click();
  await expect(page.locator('.metric-value').first()).toHaveText('104');
  const before=calls.length;
  await page.locator('.sidebar').getByText('测评任务',{exact:true}).click();
  await expect(page.getByText('共 1 个任务')).toBeVisible();
  expect(calls.slice(before)).toHaveLength(1);
  expect(calls.slice(before)[0].path).toContain('/api/evaluation-task-summaries');
  await page.getByRole('button',{name:'新建测评任务',exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('parent error and cancellation failure remain visible and recoverable',async({page})=>{
  await setup(page,[row('task-1','single','running')]);await mount(page);
  await page.route('**/api/runs/task-1-a/cancel',r=>r.fulfill({status:500,json:{detail:'cancel failed'}}));
  await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'确认',exact:true}).click();
  await expect(page.getByText(/cancel failed/)).toBeVisible();
  await page.route('**/api/runs?*',r=>r.fulfill({status:500,json:{detail:'context failed'}}));
  await navigate(page,'/tasks/task-1');await expect(page.locator('.notice.error')).toContainText('context failed');
  await page.unroute('**/api/runs?*');await page.getByRole('button',{name:'重试',exact:true}).click();
  await expect(page.getByText('Detail task-1-a task-1',{exact:false})).toBeVisible();
  await navigate(page,'/optimizer/ab-a?tab=analysis');await expect(page.getByText('Tuning',{exact:true})).toBeVisible();
  await navigate(page,'/results/task-1');await expect(page.getByText('Detail task-1-a task-1',{exact:false})).toBeVisible();
  await navigate(page,'/scoring-templates');await expect(page.getByText('Judges',{exact:false})).toBeVisible();
  await navigate(page,'/annotation-templates');await expect(page.getByText('待实现',{exact:true})).toBeVisible();
});
