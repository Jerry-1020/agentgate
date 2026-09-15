import {test,expect,type Page,type APIRequestContext} from '@playwright/test'
import {comparisonIssues,reportComparisonIssues,comparisonErrorMessage} from '../src/revision/comparison-compatibility'
import {selectHistoryTask} from './history-selection'

const sourceId='eefeb1f1-a588-4eb0-9d76-8e644c940d37'
async function seed(request:APIRequestContext){
 const source=await(await request.get('/api/runs/'+sourceId)).json()
 return ['a','b','c'].map((side,index)=>{
  const report=structuredClone(source)
  report.run.id='ab-ux-'+side
  report.run.created_at=report.run.completed_at='2026-09-14T0'+(6+index)+':00:00Z'
  if(side==='b'){
   report.run.manifest.primary_evaluator_ids=['skill-routing']
   report.run.manifest.evaluator_specs=report.run.manifest.evaluator_specs.filter((e:any)=>e.id==='skill-routing')
  }
  if(side==='c')report.run.manifest.target.ref.external_version_id='loan-agent-v2-fixed'
  return report
 })
}
const comparison={metric_deltas:[],case_deltas:[],overall_score_delta:0}
async function mount(page:Page,reports:any[]){
 await page.route('**/api/runs?*',r=>r.fulfill({json:reports.map(report=>report.run)}))
 await page.route('**/api/runs/page?*',r=>r.fulfill({json:{items:reports.map(report=>report.run),total:reports.length}}))
 await page.route('**/api/runs/ab-ux-*',r=>{
  const report=reports.find(report=>r.request().url().endsWith('/'+report.run.id))
  return r.fulfill({status:report?200:404,json:report??{detail:'未找到测试报告'}})
 })
 await page.goto('/#experiments')
 await expect(page.getByRole('button',{name:'刷新任务',exact:true})).toBeEnabled()
}
test('compatibility mirrors backend identities, hashes, case/evaluator ordering and scoring contracts',async({request})=>{
 const [a,,c]=await seed(request)
 expect(reportComparisonIssues(a,c)).toEqual([])
 const change=(edit:(report:any)=>void,key:string)=>{
  const copy=structuredClone(c);edit(copy)
  expect(reportComparisonIssues(a,copy).map(issue=>issue.key)).toContain(key)
 }
 change(r=>r.run.manifest.primary_evaluator_ids=['skill-routing'],'evaluators')
 change(r=>r.run.manifest.primary_evaluator_ids.reverse(),'evaluators')
 change(r=>r.run.manifest.evaluator_specs[0].version='2','evaluators')
 change(r=>r.run.manifest.evaluator_specs[0].content_sha256='changed','evaluators')
 change(r=>delete r.run.manifest.evaluator_specs[0].content_sha256,'evaluators')
 change(r=>r.run.manifest.dataset.content_sha256='changed','dataset-content')
 change(r=>r.run.manifest.dataset.dataset_id='another','dataset')
 change(r=>r.run.manifest.selected_case_ids=[],'cases')
 change(r=>r.run.manifest.metric_plan.version='2','metric-plan')
 change(r=>r.run.manifest.gate_spec.minimum_score=.5,'gate')
 change(r=>r.run.manifest.target.ref.external_target_id='other','target')
 change(r=>r.metrics.pop(),'metrics')
 change(r=>r.run.status='running','status')
 expect(comparisonIssues(a.run,a.run).map(issue=>issue.key)).toContain('same-run')
 const all=structuredClone(c)
 all.run.manifest.selected_case_ids=all.run.manifest.dataset.cases.map((item:any)=>item.id)
 expect(reportComparisonIssues(a,all)).toEqual([])
 const two=structuredClone(a.run);two.manifest.dataset.cases.push({...two.manifest.dataset.cases[0],id:'second'})
 const reordered=structuredClone(two);reordered.id='other';reordered.manifest.selected_case_ids=two.manifest.dataset.cases.map((item:any)=>item.id).reverse()
 expect(comparisonIssues(two,reordered).map(issue=>issue.key)).toContain('cases')
 expect(comparisonErrorMessage(new Error('reports use different primary Evaluators'))).toContain('评估器')
})


test('history requires only two records; selection automatically fetches results without any writes',async({page,request})=>{
 const writes:string[]=[],errors:string[]=[]
 page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url())})
 page.on('pageerror',e=>errors.push(e.message))
 let comparisons=0
 await page.route('**/api/run-comparisons?*',route=>{comparisons++;return route.fulfill({json:comparison})})
 await mount(page,await seed(request))
 await expect(page.locator('.tabs > button')).toHaveText(['创建实验并运行','比较已有结果'])
 await expect(page.getByTestId('ab-side').first().getByRole('heading',{name:'实验A',exact:true})).toBeVisible()
 await expect(page.getByTestId('ab-side').last().getByRole('heading',{name:'实验B',exact:true})).toBeVisible()
 await expect(page.getByRole('combobox',{name:'实验B已完成任务'})).toBeDisabled()
 await expect(page.getByLabel('选择智能体',{exact:true})).toHaveCount(0)
 await expect(page.getByLabel('选择方案版本',{exact:true})).toHaveCount(0)
 await expect(page.getByLabel('筛选历史评估器',{exact:true})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'比较结果',exact:true})).toHaveCount(0)
 await expect(page.getByText('实验 A · 基线',{exact:true})).toHaveCount(0)
 await expect(page.getByText('实验 B · 候选',{exact:true})).toHaveCount(0)
 await selectHistoryTask(page,0,'ab-ux-a')
 await selectHistoryTask(page,1,'ab-ux-c')
 await expect(page.getByRole('heading',{name:'指标对比',exact:true})).toBeVisible()
 await expect(page.getByRole('columnheader',{name:'实验A',exact:true})).toHaveCount(2)
 await expect(page.getByRole('columnheader',{name:'实验B',exact:true})).toHaveCount(2)
 await expect(page.getByRole('columnheader',{name:'分数差（B − A）',exact:true})).toBeVisible()
 await expect(page.getByRole('columnheader',{name:/左侧结果|右侧结果/})).toHaveCount(0)
 await expect(page.getByTestId('ab-side').first()).toContainText('本次实际使用的评估器 · 7 个')
 await expect(page.getByText('配置核对通过，可比较两次运行。',{exact:true})).toHaveCount(0)
 await expect(page.getByTestId('configuration-diff')).toHaveCount(0)
 expect(comparisons).toBe(1)
 expect(writes).toEqual([])
 expect(errors).toEqual([])
})

test('seven versus one is only displayed side by side; compatible records automatically compare',async({page,request})=>{
 let comparisons=0
 await page.route('**/api/run-comparisons?*',route=>{comparisons++;return route.fulfill({json:comparison})})
 await mount(page,await seed(request))
 await selectHistoryTask(page,0,'ab-ux-a')
 await selectHistoryTask(page,1,'ab-ux-b')
 await expect(page.getByTestId('comparison-preflight')).toContainText('A 使用 7 个，B 使用 1 个')
 await expect(page.getByTestId('comparison-preflight')).toContainText('仅 A 包含：Required Tool')
 await expect(page.getByTestId('history-result')).toHaveCount(2)
 await expect(page.getByTestId('comparison-results')).toHaveCount(0)
 expect(comparisons).toBe(0)
 await selectHistoryTask(page,1,'ab-ux-c')
 await expect(page.getByRole('heading',{name:'结果对比',exact:true})).toBeVisible()
 await expect(page.getByTestId('comparison-preflight')).toHaveCount(0)
 expect(comparisons).toBe(1)
})

test('server validation failure is translated; retry loads results without submitting a task',async({page,request})=>{
 let fail=true
 await page.route('**/api/run-comparisons?*',route=>route.fulfill(fail?{status:409,json:{detail:'reports use different primary Evaluators'}}:{json:comparison}))
 await mount(page,await seed(request))
 await selectHistoryTask(page,0,'ab-ux-a')
 await selectHistoryTask(page,1,'ab-ux-c')
 const error=page.getByRole('alert').filter({hasText:'两侧使用的评估器'})
 await expect(error).toBeVisible()
 await expect(error.locator('pre')).not.toBeVisible()
 await error.locator('summary').click()
 await expect(error.locator('pre')).toHaveText('reports use different primary Evaluators')
 fail=false
 await page.getByRole('button',{name:'重试加载结果'}).click()
 await expect(page.getByTestId('comparison-results')).toBeVisible()
})

test('report read failure blocks comparison and retries automatically after the report is recovered',async({page,request})=>{
 let comparisons=0
 await page.route('**/api/run-comparisons?*',route=>{comparisons++;return route.fulfill({json:comparison})})
 await mount(page,await seed(request))
 await page.route('**/api/runs/ab-ux-c',route=>route.fulfill({status:503,json:{detail:'暂不可用'}}))
 await selectHistoryTask(page,0,'ab-ux-a')
 const selector=page.getByRole('combobox',{name:'实验B已完成任务'})
 await selector.click();await selector.fill('ab-ux-c');await page.getByRole('listbox',{name:'实验B已完成任务'}).getByTestId('run-option-ab-ux-c').click()
 await expect(page.getByRole('alert')).toContainText('未能读取完整报告')
 expect(comparisons).toBe(0)
 await page.unroute('**/api/runs/ab-ux-c')
 await page.getByRole('button',{name:'重试读取报告',exact:true}).click()
 await expect(page.getByTestId('comparison-results')).toBeVisible()
 expect(comparisons).toBe(1)
})

for(const lateStatus of [200,409]){
 test('late comparison '+lateStatus+' cannot overwrite a newly selected pair',async({page,request})=>{
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/run-comparisons?*',async route=>{await gate;await route.fulfill(lateStatus===200?{json:comparison}:{status:409,json:{detail:'reports use different primary Evaluators'}})})
  await mount(page,await seed(request))
  await selectHistoryTask(page,0,'ab-ux-a')
  await selectHistoryTask(page,1,'ab-ux-c')
  await expect(page.getByText('正在加载结果差异…',{exact:true})).toBeVisible()
  await selectHistoryTask(page,1,'ab-ux-b')
  const response=page.waitForResponse(r=>r.url().includes('/api/run-comparisons?'))
  release();await response
  await expect(page.getByTestId('comparison-preflight')).toBeVisible()
  await expect(page.getByTestId('comparison-results')).toHaveCount(0)
  await expect(page.getByRole('alert').filter({hasText:'两侧使用的评估器'})).toHaveCount(0)
 })
}

test('clearing selection removes old differences and the same run cannot be selected twice',async({page,request})=>{
 await page.route('**/api/run-comparisons?*',r=>r.fulfill({json:comparison}))
 await mount(page,await seed(request))
 await selectHistoryTask(page,0,'ab-ux-a');await selectHistoryTask(page,1,'ab-ux-c')
 await expect(page.getByTestId('comparison-results')).toBeVisible()
 const column=page.getByTestId('ab-side').last()
 await column.getByRole('combobox').click()
 await column.getByRole('combobox').fill('ab-ux-a')
 await expect(page.getByTestId('run-option-ab-ux-a').filter({visible:true})).toHaveCount(0)
 await page.keyboard.press('Escape')
 await column.locator('.el-select__wrapper').hover()
 await column.locator('.el-select__clear').click()
 await expect(page.getByTestId('comparison-results')).toHaveCount(0)
 await expect(page.getByTestId('history-result')).toHaveCount(1)
})

test('history loads every page, ignores unfinished records and offers a list retry',async({page,request})=>{
 const reports=await seed(request)
 await mount(page,reports)
 let fail=true;const offsets:string[]=[]
 await page.route('**/api/runs/page?*',route=>{
  if(new URL(route.request().url()).searchParams.get('status')!=='completed')return route.fallback()
  if(fail)return route.fulfill({status:503,json:{detail:'temporarily unavailable'}})
  const offset=new URL(route.request().url()).searchParams.get('offset')??'0';offsets.push(offset)
  const items=offset==='0'?[reports[0].run]:[reports[2].run,{...reports[1].run,status:'running'}]
  return route.fulfill({json:{items,total:3}})
 })
 await page.getByRole('button',{name:'刷新任务',exact:true}).click()
 await expect(page.getByRole('alert').filter({hasText:'已完成任务列表读取失败'})).toBeVisible()
 fail=false
 await page.getByRole('button',{name:'重试加载任务'}).click()
 await selectHistoryTask(page,0,'ab-ux-a');await selectHistoryTask(page,1,'ab-ux-c')
 expect(offsets).toEqual(['0','1'])
 await page.getByRole('combobox',{name:'实验B已完成任务'}).click()
 await expect(page.getByTestId('run-option-ab-ux-b').filter({visible:true})).toHaveCount(0)
})
