import {test,expect,type Page,type APIRequestContext} from '@playwright/test'
import {mkdirSync} from 'node:fs'
import {sameJson,equalsCondition} from '../src/revision/report-presentation'

const sourceId='ca7ebd14-832e-4b1e-9a63-56b4d376174b'
const runId='result-ux-fixture'

async function fixture(page:Page,request:APIRequestContext,change?:(data:any)=>void){
 const report=await(await request.get('/api/runs/'+sourceId)).json()
 const progress=await(await request.get('/api/runs/'+sourceId+'/status')).json()
 const sample={...report.run.manifest.dataset.cases[0],id:'case-1',name:'较大金额申请禁止直接批准',
  turns:[{id:'turn-1',input:{application_id:'MOCK-1',risk:'high',amount:100000},expectations:[]}]}
 const check=(field:string,index:number)=>({id:'state-'+index,name:'最终状态：'+field,turn_id:'turn-1',
  expectation_id:'expect-'+index,outcome:'fail',score:0,reason:'实际值与预期值不相等',
  expected:{kind:'equals',expected:index===0?'pending_review':false},actual:index===0?'approved':true,
  actual_missing:false,span_ids:[],failure_stage:'state',failure_sequence:null,failure_span_id:null})
 const base={trace_id:'trace',case_id:'case-1',evaluator_version:'2',evaluator_kind:'rule',dimension:'state',severity:'standard'}
 const results=[
  {...base,evaluator_id:'routing',evaluator_name:'UX验证-规则草稿',metric:'skill_routing_accuracy',
   outcome:'pass',score:1,reason:'所有适用检查均通过',checks:[{...check('路由',9),id:'route-check',name:'技能路由',outcome:'pass',score:1,reason:'通过',expected:'loan_approval',actual:'loan_approval'}]},
  {...base,evaluator_id:'final-output',evaluator_name:'Final Output',metric:'final_output_match',outcome:'not_applicable',score:null,reason:'该用例没有适用检查',checks:[]},
  {...base,evaluator_id:'final-state',evaluator_name:'Final State',metric:'final_state_match',
   outcome:'fail',score:0,reason:'实际值与预期值不相等；实际值与预期值不相等；实际值与预期值不相等',
   checks:[check('status',0),check('approved',1),check('auto_approve',2)]}
 ]
 report.run.id=runId
 report.run.manifest.dataset.cases=[sample]
 report.run.manifest.primary_evaluator_ids=['routing','final-output','final-state']
 report.results=results
 report.release_gate={outcome:'fail',reason_code:'blocking_failure',score:0,minimum_score:.8,missing_results:[]}
 report.metrics=[]
 const data={report,progress:{...progress,run_id:runId,status:'completed',completed_cases:1,total_cases:1},
  trace:{trace_id:'trace',case_id:'case-1',spans:[],turn_outcomes:{'turn-1':{
   input:{amount:100000,risk:'high',application_id:'MOCK-1'},output:{status:'approved'},state:{status:'approved',approved:true,auto_approve:true}
  }},final_state:{},final_output:{}},traceStatus:200}
 change?.(data)
 await page.route('**/api/runs/'+runId+'**',async route=>{
  const path=new URL(route.request().url()).pathname
  if(path.includes('/traces/')){
   await route.fulfill({status:data.traceStatus,json:data.traceStatus===200?data.trace:{detail:'Trace 暂不可用'}})
  }else if(path.endsWith('/status'))await route.fulfill({json:data.progress})
  else if(path.endsWith('/samples'))await route.fulfill({json:{run:data.report.run,results:data.report.results,complete:true}})
  else await route.fulfill({json:data.report})
 })
 await page.goto('/#results/'+runId)
 await expect(page.getByRole('heading',{name:sample.name,exact:true})).toBeVisible()
 return data
}

test('JSON comparison preserves absent, null, false, nested keys and array order',()=>{
 expect(sameJson({b:2,a:{y:false,x:null}},{a:{x:null,y:false},b:2})).toBe(true)
 expect(sameJson(undefined,undefined)).toBe(false)
 expect(sameJson({},undefined)).toBe(false)
 expect(sameJson(null,null)).toBe(true)
 expect(sameJson(false,false)).toBe(true)
 expect(sameJson(0,false)).toBe(false)
 expect(sameJson([1,2],[2,1])).toBe(false)
 expect(equalsCondition({kind:'equals',expected:false})).toBe(true)
 expect(equalsCondition({kind:'equals',expected:1,extra:'keep'})).toBe(false)
 expect(equalsCondition({kind:'within_tolerance',expected:1,epsilon:.1})).toBe(false)
})

test('failure first; distinct fields retained; successful and inapplicable results collapsed',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await fixture(page,request)
 const report=page.getByTestId('case-report')
 await expect(page.getByTestId('evaluation-counts')).toHaveText('需处理 1 项通过 1 项不适用 1 项')
 await expect(report.locator('[data-evaluator="final-state"]')).toBeVisible()
 await expect(report.locator('[data-evaluator="routing"]')).not.toBeVisible()
 await expect(report.locator('[data-evaluator="final-output"]')).not.toBeVisible()
 await expect(report.locator('.check-comparison tbody tr:visible')).toHaveCount(3)
 await expect(report.locator('[data-check="state-0"]')).toContainText('pending_review')
 await expect(report.locator('[data-check="state-0"]')).toContainText('approved')
 await expect(report.locator('[data-check="state-1"]')).toContainText('false')
 await expect(report.getByText('实际值与预期值不相等；实际值与预期值不相等；实际值与预期值不相等',{exact:true})).toHaveCount(0)
 await expect(page.getByTestId('input-match')).toBeVisible()
 await expect(page.getByTestId('sample-input')).toHaveCount(1)
 await expect(page.getByTestId('actual-input')).toHaveCount(0)
 await expect(report.getByRole('heading',{name:'实际执行状态',exact:true})).not.toBeVisible()
 await page.getByTestId('passed-results').locator('summary').first().click()
 await expect(report.locator('[data-evaluator="routing"]')).toContainText('UX验证-规则草稿 · v2')
 await expect(report.locator('[data-evaluator="routing"]')).toContainText('本评估器 100.0 / 100')
 await page.getByTestId('passed-results').locator('summary').first().click()
 await page.getByTestId('inapplicable-results').locator('summary').first().click()
 await expect(report.getByText('未参与本样本评分，不等于通过或失败。',{exact:true})).toBeVisible()
 await page.getByTestId('inapplicable-results').locator('summary').first().click()
 for(const width of [1440,1280,760]){
  await page.setViewportSize({width,height:1000})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy()
 }
 await page.setViewportSize({width:1440,height:1000})
 await page.locator('.case-report-layout').evaluate(element=>window.scrollTo(0,window.scrollY+element.getBoundingClientRect().top-80))
 mkdirSync('../runtime/visual-review',{recursive:true})
 await page.screenshot({path:'../runtime/visual-review/result-detail-2026-09-14.png'})
 await page.getByRole('tab',{name:'执行 Trace',exact:true}).click()
 await expect(page.getByRole('tabpanel')).toContainText('"trace_id": "trace"')
 await page.getByRole('tab',{name:'输入与输出',exact:true}).click()
 expect(errors).toEqual([])
})

test('different input is shown separately, false output is not lost',async({page,request})=>{
 await fixture(page,request,data=>{
  data.trace.turn_outcomes['turn-1'].input.amount=50000
  data.trace.turn_outcomes['turn-1'].output=false
 })
 await expect(page.getByTestId('actual-input')).toContainText('50000')
 await expect(page.getByTestId('sample-input')).toContainText('100000')
 await expect(page.getByTestId('input-match')).toHaveCount(0)
 await expect(page.getByTestId('actual-output')).toHaveText('false')
})

test('missing input and output remain missing, missing check evidence stays explicit',async({page,request})=>{
 await fixture(page,request,data=>{
  delete data.trace.turn_outcomes['turn-1'].input
  delete data.trace.turn_outcomes['turn-1'].output
  data.report.results[2].checks[0].actual_missing=true
 })
 await expect(page.getByText('未记录实际输入，无法比对。',{exact:true})).toBeVisible()
 await expect(page.getByTestId('actual-output')).toHaveText('未记录输出')
 await expect(page.locator('[data-check="state-0"]')).toContainText('证据缺失')
 await expect(page.getByTestId('input-match')).toHaveCount(0)
})

test('trace failure leaves evaluator evidence usable without a false input match',async({page,request})=>{
 await fixture(page,request,data=>{data.traceStatus=503})
 await expect(page.getByTestId('case-report').getByRole('alert')).toContainText('Trace 暂不可用')
 await expect(page.locator('[data-check="state-0"]')).toBeVisible()
 await expect(page.getByText('输出读取失败',{exact:true})).toBeVisible()
 await expect(page.getByTestId('input-match')).toHaveCount(0)
})

test('not applicable is not passing',async({page,request})=>{
 await fixture(page,request,data=>{
  data.report.results=data.report.results.filter((result:any)=>result.outcome==='not_applicable')
 })
 await expect(page.getByText('本样本没有适用检查，不能据此判断通过。',{exact:true})).toBeVisible()
})

test('error and review remain attention items',async({page,request})=>{
 await fixture(page,request,data=>{
  data.report.results[0].outcome='review'
  data.report.results[0].checks=[]
  data.report.results[0].reason='需人工核对路由'
  data.report.results[2].outcome='error'
  data.report.results[2].checks=[]
  data.report.results[2].reason='评估器执行异常'
 })
 await expect(page.getByTestId('evaluation-counts')).toContainText('需处理 2 项')
 await expect(page.getByText('需人工核对路由',{exact:true})).toBeVisible()
 await expect(page.getByText('评估器执行异常',{exact:true})).toBeVisible()
})
