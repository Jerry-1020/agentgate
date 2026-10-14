import {selectHistoryTask} from './history-selection'
import {test,expect} from '@playwright/test'

test('server finding presents its evidence and suggestions together',async({page})=>{
 await page.route('**/api/skill-analysis/capability',r=>r.fulfill({json:{code:'0',message:'success',data:{configured:true,reason:null}}}))
 await page.route('**/api/evaluations/skill-analysis',r=>r.fulfill({json:{code:'0',message:'success',data:{id:'test-report',findings:[{id:'test-finding',category:'工具使用边界',skill_ids:['credit_inquiry'],reason:'查询技能的输入边界需确认',evidence:[{field:'input_schema',detail:'未定义申请编号的约束'}],suggestions:['补充申请编号必填校验']}],errors:[]}}}))
 await page.goto('/#analysis')
 await page.getByLabel('检查对象',{exact:true}).selectOption('loan-agent-v1-risky')
 await page.getByRole('button',{name:'运行分析',exact:true}).click()
 const finding=page.locator('#analysis-item-test-finding')
 await expect(finding).toContainText('征信查询')
 await expect(finding).toContainText('未定义申请编号的约束')
 await expect(finding).toContainText('补充申请编号必填校验')
 await page.getByLabel('筛选问题 Skill').selectOption('loan_approval')
 await expect(finding).toHaveCount(0)
})

test('analysis capability prevents unavailable requests and findings filter precisely',async({page})=>{
 let calls=0
 await page.route('**/api/skill-analysis/capability',r=>r.fulfill({json:{code:'0',message:'success',data:{configured:false,reason:'未配置服务端 Judge 模型，静态分析未启用。'}}}))
 await page.route('**/api/evaluations/skill-analysis',r=>{calls++;return r.fulfill({status:503,json:{code:'1',message:'unavailable',data:null}})})
 await page.goto('/#analysis')
 await page.getByLabel('检查对象',{exact:true}).selectOption('loan-agent-v1-risky')
 await expect(page.getByRole('button',{name:'运行分析',exact:true})).toBeDisabled()
 expect(calls).toBe(0)
 await page.getByRole('button',{name:'查看演示样例',exact:true}).click()
 await page.getByRole('button',{name:'展示样例',exact:true}).click()
 const finding=page.locator('#analysis-item-mock-approval')
 await expect(finding).toContainText('loan')
 await expect(finding).toContainText('request_human_review')
 await expect(finding).toContainText('问题证据')
 await page.getByLabel('筛选问题 Skill').selectOption('repayment_plan')
 await expect(finding).toHaveCount(0)
 await expect(page.getByText('当前筛选下没有发现项；不代表该 Skill 已通过检查。')).toBeVisible()
 await page.getByLabel('筛选问题 Skill').selectOption('loan_approval')
 await expect(finding).toBeVisible()
 await page.getByLabel('检查对象',{exact:true}).selectOption('loan-agent-v2-fixed')
 await page.getByRole('button',{name:'展示样例',exact:true}).click()
 await expect(page.getByText('该版本没有预置问题样例，不代表已通过静态分析。',{exact:true})).toBeVisible()
})

test('rerun requires preview and preserves exact manifest',async({page,request})=>{
 const list=(await (await request.get('/api/runs?limit=100')).json()).data
 const tasks=(await (await request.get('/api/evaluation-tasks')).json()).data
 const source=list.find((r:any)=>r.status==='completed'&&tasks.some((t:any)=>t.kind==='single'&&t.run_ids[0]===r.id))
 const task=tasks.find((t:any)=>t.kind==='single'&&t.run_ids[0]===source?.id)
 expect(source).toBeTruthy()
 await page.goto('/#tasks/'+source.id)
 await page.getByRole('button',{name:'任务配置',exact:true}).click()
 await page.getByRole('button',{name:'使用原配置重跑'}).click()
 const dialog=page.getByRole('dialog',{name:'重新运行当前任务'})
 await expect(dialog.getByTestId('run-configuration')).toBeVisible()
 await expect(dialog).toContainText(source.manifest.target.ref.external_version_id)
 const pending=page.waitForResponse(r=>r.url().endsWith('/rerun')&&r.request().method()==='POST')
 await dialog.getByRole('button',{name:'开始测评',exact:true}).click()
 const response=await pending;expect(response.ok()).toBeTruthy()
 const updated=(await response.json()).data
 expect(updated.id).toBe(task.id)
 const newId=updated.run_ids[0]
 expect(newId).not.toBe(source.id)
 const next=(await (await request.get('/api/runs/'+newId+'/samples')).json()).data
 expect(next.run.manifest).toEqual(source.manifest)
})

test('AB uses exact descriptor snapshots and shows changed prompts',async({page,request})=>{
 const runs=(await (await request.get('/api/runs?limit=200')).json()).data
 const ids=['loan-agent-v1-risky','loan-agent-v2-fixed'].map(v=>runs.find((r:any)=>r.status==='completed'&&r.manifest.target.ref.external_version_id===v).id)
 await page.goto('/#experiments')
 for(let i=0;i<2;i++)await selectHistoryTask(page,i,ids[i])
 await page.getByText('查看方案与测评条件差异（只读）',{exact:true}).click()
 const diff=page.getByTestId('configuration-diff')
 await expect(diff.getByTestId('execution-scope')).toContainText(/(全部用例|指定用例) · \d+ 条/)
 await expect(diff.getByTestId('execution-scope').locator('li').first()).toBeVisible()
 await expect(diff.getByTestId('execution-scope')).not.toContainText('候选：null')
 await expect(diff).toContainText('Loan Approval · 已变更')
 await expect(diff).toContainText('Repayment Plan · 未变更')
 await diff.getByText('智能体提示词 · 已变更').click()
 await expect(diff).toContainText('May approve high-risk applications without human review.')
 await expect(diff).toContainText('High-risk applications must be sent to human review.')
 await page.screenshot({path:'../runtime/ab-configuration-diff.png',fullPage:true})
})
