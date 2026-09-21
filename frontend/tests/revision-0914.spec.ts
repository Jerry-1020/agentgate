import {selectHistoryTask} from './history-selection'
import {test,expect} from '@playwright/test'
import {previewSources,type MergeSource} from '../src/revision/merge-preview'
import {toApiCase} from '../src/upstream/api/datasets'
import type {EvaluationCase} from '../src/upstream/types/dataset'

test('editor transport preserves named output and special route conditions',()=>{
 const original:any[]=[
  {id:'special',name:'路由集合',kind:'skill_route',condition:{kind:'one_of',options:['a','b']}},
  {id:'route',name:'主要路由',kind:'skill_route',condition:{kind:'equals',expected:'a'}},
  {id:'out',name:'自定义输出名',kind:'output',path:null,condition:{kind:'equals',expected:{status:'ok'}}},
  {id:'tool',name:'审计调用',kind:'tool_call',mode:'required',tool:'audit'},
 ]
 const item:EvaluationCase={id:'case',name:'名称',initial_state:{},category:'positive',difficulty:'easy',tags:[],notes:'',turns:[{id:'turn',input:{},expected_skill:'a',required_tools:['audit'],forbidden_tools:[],policy_rules:[],notes:'',preserved_skill_routes:[original[0]],original_expectations:original,expectations:[original[2]]}]}
 expect(toApiCase(item).turns[0].expectations).toEqual(original)
 expect(toApiCase({...item,turns:[{...item.turns[0],expected_skill:'b'}]}).turns[0].expectations[1]).toEqual({...original[1],condition:{kind:'equals',expected:'b'}})
 expect(toApiCase(item).turns[0]).not.toHaveProperty('original_expectations')
})

test('merge comparison preserves contexts, types, order and source identities',()=>{
 const c={id:'same',name:'场景',initial_state:{risk:'high'},turns:[{id:'t',input:{query:'查申请'},expectations:[{id:'e',kind:'output',condition:{kind:'equals',expected:{ok:true}}}]}]}
 const source=(id:string,cases:any[]):MergeSource=>({dataset_id:id,name:id,version:1,content_sha256:'snapshot',cases})
 const result=previewSources([source('a',[c]),source('b',[{...structuredClone(c),id:'copy'},{...structuredClone(c),id:'context',initial_state:{risk:'low'}}])])
 expect(result.rows).toHaveLength(3)
 expect(result.duplicates).toHaveLength(1)
 expect(result.duplicates[0]).toHaveLength(2)
 expect(result.differences).toHaveLength(1)
 expect(new Set(result.rows.map(r=>r.key)).size).toBe(3)
 expect(c.initial_state).toEqual({risk:'high'})
 const changed=structuredClone(c);(changed.turns[0].expectations[0].condition as any).expected={ok:'true'}
 expect(previewSources([source('a',[c]),source('b',[changed])]).duplicates).toHaveLength(0)
 const multi={...structuredClone(c),turns:[...c.turns,{...c.turns[0],id:'t2',input:{query:'第二轮'}}]}
 expect(previewSources([source('a',[multi]),source('b',[{...multi,turns:[...multi.turns].reverse()}])]).duplicates).toHaveLength(0)
})

test('merge demo reaches reviewed plan but never calls a write endpoint',async({page})=>{
 const writes:string[]=[]
 page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url())})
 await page.goto('/#datasets')
 await page.getByRole('link',{name:'合并现有评测集',exact:true}).click()
 await page.getByRole('button',{name:'检查合并',exact:true}).click()
 await expect(page.getByText(/完全一致候选 1 组/)).toBeVisible()
 await page.getByLabel('预览中折叠完全一致项，保留全部来源').check()
 await expect(page.getByText(/预计保留 2 条/)).toBeVisible()
 await page.getByRole('button',{name:'下一步',exact:true}).click()
 await expect(page.getByRole('button',{name:'下一步',exact:true})).toBeDisabled()
 await page.getByLabel('已核对：保留为不同场景，不拼接期望或轮次').check()
 await page.getByRole('button',{name:'下一步',exact:true}).click()
 await expect(page.getByRole('button',{name:'生成草稿 · 待后端接入'})).toBeDisabled()
 await expect(page.getByRole('heading',{name:'预计保留用例与来源 · 2 条'})).toBeVisible()
 await expect(page.locator('tbody tr').first()).toContainText('approval-copy')
 const download=page.waitForEvent('download')
 await page.getByRole('button',{name:'导出计划清单（不含用例正文）'}).click()
 expect((await download).suggestedFilename()).toMatch(/merge-plan.*json/)
 expect(writes).toEqual([])
 await page.screenshot({path:'../runtime/browser-tests/0914-merge-plan.png',fullPage:true})
})

test('closed extra expectations and initial state survive a normal case edit',async({page,request})=>{
 const response=await request.post('/api/datasets/loan-risk-policy/copy',{data:{name:'0914-hidden-'+Date.now(),source_version:1}})
 expect(response.ok()).toBeTruthy()
 const created=(await response.json()).data,id=created.dataset.id
 try{
  let draft=created.draft
  const original={...draft.cases[0],initial_state:{review_ticket:'existing-context',attempts:2}}
  const changed=await request.put('/api/datasets/'+id+'/drafts/cases/'+original.id,{headers:{'If-Match':draft.content_sha256},data:original})
  expect(changed.ok()).toBeTruthy();draft=(await changed.json()).data
  await page.goto('/#datasets/'+id)
  await expect(page.locator('.other-expectations').first()).not.toHaveAttribute('open')
  await expect(page.getByTestId('expected-skill-0')).not.toBeVisible()
  await page.getByTestId('case-name').fill('只修改名称')
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿',{exact:true})).toBeVisible()
  const saved=(await(await request.get('/api/datasets/'+id+'/drafts/current')).json()).data
  expect(saved.cases[0].initial_state).toEqual(original.initial_state)
  expect(saved.cases[0].turns).toEqual(original.turns)
  await page.locator('.other-expectations summary').first().click()
  await expect(page.getByTestId('expected-skill-0')).toBeVisible()
 }finally{await request.delete('/api/datasets/'+id+'/unpublished')}
})

test('one scoring guide saves a real LLM draft without losing the backend rubric',async({page,request})=>{
 await page.route('**/api/configured-models',r=>r.fulfill({json:{code:'0',message:'success',data:[{provider_id:'review-fixture',model_id:'review-judge',credential_ref:'env:REVIEW_TEST_KEY'}]}}))
 let id=''
 try{
  await page.goto('/#evaluators')
  await page.getByRole('button',{name:/LLM 评估器/}).click()
  await page.getByRole('button',{name:'新建评估器',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByLabel('名称',{exact:true}).fill('0914-guide-'+Date.now())
  await dialog.getByLabel('评估模型',{exact:true}).selectOption('0')
  await dialog.getByLabel('评分说明',{exact:true}).fill('回答应说明审批结果；未转人工复核时不得宣称已审批。')
  await expect(dialog.getByText('原有评分标准',{exact:true})).toHaveCount(0)
  const response=page.waitForResponse(r=>r.url().endsWith('/api/evaluators')&&r.request().method()==='POST')
  await dialog.getByRole('button',{name:'保存草稿',exact:true}).click()
  const result=await response;expect(result.ok()).toBeTruthy();id=(await result.json()).data.evaluator.id
  const draft=(await(await request.get('/api/evaluators/'+id+'/drafts/current')).json()).data
  expect(draft.config.rubric).toEqual({scoring_guide:'回答应说明审批结果；未转人工复核时不得宣称已审批。'})
  expect(draft.config.instruction).toBeTruthy()
  expect(draft.config.model.model_id).toBe('review-judge')
  expect(draft.severity).toBe('standard')
 }finally{if(id)await request.delete('/api/evaluators/'+id)}
})

test('evaluator unsaved edits survive rejected navigation and cancelled creation',async({page,request})=>{
 const builtin=(await(await request.get('/api/evaluators/skill-routing')).json()).data.latest
 const {kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}=builtin
 const created=(await(await request.post('/api/evaluators',{data:{name:'0914-editor-'+Date.now(),description:'原说明',draft:{kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}}})).json()).data
 const id=created.evaluator.id
 try{
  await page.goto('/#evaluators/'+id)
  await page.getByRole('button',{name:'配置与版本',exact:true}).click()
  await page.locator('.evaluator-panel').getByLabel('备注说明').fill('尚未保存')
  await Promise.all([page.waitForEvent('dialog').then(d=>d.dismiss()),page.locator('.sidebar').getByRole('link',{name:'评测集',exact:true}).click()])
  await expect(page.locator('.evaluator-panel').getByLabel('备注说明')).toHaveValue('尚未保存')
  await Promise.all([page.waitForEvent('dialog').then(d=>d.accept()),page.getByRole('button',{name:'新建评估器',exact:true}).click()])
  await page.getByRole('dialog').getByLabel('备注说明').fill('新建独立内容')
  await Promise.all([page.waitForEvent('dialog').then(d=>d.accept()),page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click()])
  await expect(page.locator('.evaluator-panel').getByLabel('备注说明')).toHaveValue('尚未保存')
  expect((await(await request.get('/api/evaluators/'+id)).json()).data.evaluator.description).toBe('原说明')
 }finally{await request.delete('/api/evaluators/'+id)}
})

test('ordinary task scheduling is visible, cancellable, and not offered for stability',async({page,request})=>{
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'新建评测任务'})
 await dialog.getByLabel('任务评测集',{exact:true}).selectOption('loan-risk-policy')
 await expect(dialog.getByLabel('任务评测集版本',{exact:true})).toHaveValue('1')
 await dialog.getByLabel('执行时间',{exact:true}).selectOption('scheduled')
 const date=new Date(Date.now()+10*60*1000);date.setSeconds(0,0)
 const localValue=await page.evaluate(value=>{const d=new Date(value);return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')+'T'+[String(d.getHours()).padStart(2,'0'),String(d.getMinutes()).padStart(2,'0')].join(':')},date.toISOString())
 await dialog.getByLabel('预约时间',{exact:true}).fill(localValue)
 const response=page.waitForResponse(r=>r.url().endsWith('/api/evaluations')&&r.request().method()==='POST')
 await dialog.getByRole('button',{name:'提交评测',exact:true}).click()
 const result=await response;expect(result.ok()).toBeTruthy();const id=(await result.json()).data.run_id
 try{
  const record=(await(await request.get('/api/runs/'+id+'/samples')).json()).data.run
  expect(record.status).toBe('scheduled')
  expect(new Date(record.scheduled_for).getTime()).toBe(date.getTime())
  await expect(page.getByRole('heading',{name:'已预约',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'取消任务',exact:true}).click()
  await page.getByRole('button',{name:'确认',exact:true}).click()
  await expect.poll(async()=> (await(await request.get('/api/runs/'+id+'/status')).json()).data.status).toBe('cancelled')
 }finally{await request.post('/api/runs/'+id+'/cancel')}
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 await dialog.locator('label').filter({hasText:'稳定性测试重复次数'}).locator('input').fill('2')
 await expect(dialog.getByLabel('执行时间',{exact:true})).toBeDisabled()
 await expect(dialog.getByLabel('执行时间',{exact:true})).toHaveValue('now')
})

test('isolated scheduler really dispatches due tasks with a frozen manifest',async({request})=>{
 const response=await request.post('/api/evaluations',{data:{version:'loan-agent-v1-risky',dataset_id:'loan-risk-policy',dataset_version:1,evaluator_ids:['skill-routing'],scheduled_for:new Date(Date.now()+15000).toISOString()}})
 expect(response.ok()).toBeTruthy();const id=(await response.json()).data.run_id
 const original=(await(await request.get('/api/runs/'+id+'/samples')).json()).data.run
 expect(original.status).toBe('scheduled')
 try{
  await expect.poll(async()=>(await(await request.get('/api/runs/'+id+'/status')).json()).data.status,{timeout:40000,intervals:[1000,2000]}).toBe('completed')
  expect((await(await request.get('/api/runs/'+id+'/samples')).json()).data.run.manifest).toEqual(original.manifest)
 }finally{await request.post('/api/runs/'+id+'/cancel')}
})

test('static finding routes explicit selected cases to the shared task form',async({page})=>{
 await page.route('**/api/skill-analysis/capability',r=>r.fulfill({json:{code:'0',message:'success',data:{configured:true}}}))
 await page.route('**/api/evaluations/skill-analysis',r=>r.fulfill({json:{code:'0',message:'success',data:{id:'fixture-report',findings:[{id:'fixture-finding',title:'审批边界需验证',skill_ids:['loan_approval'],reason:'测试契约',evidence:[],suggestions:['验证人工复核']}],errors:[]}}}))
 await page.goto('/#analysis')
 await page.getByLabel('检查对象',{exact:true}).selectOption('loan-agent-v1-risky')
 await page.getByRole('button',{name:'运行分析',exact:true}).click()
 await page.getByRole('button',{name:'选择验证用例',exact:true}).click()
 const chooser=page.getByRole('dialog',{name:'选择验证用例'})
 await chooser.getByLabel('验证评测集').selectOption('loan-risk-policy')
 await expect(chooser.getByLabel('验证发布版本')).toHaveValue('1')
 await chooser.locator('tbody input[type=checkbox]').first().check()
 await chooser.getByRole('button',{name:'配置验证任务 · 1 条'}).click()
 const task=page.getByRole('dialog',{name:'新建评测任务'})
 await expect(task).toContainText('指定 1 条用例')
 await expect(task.getByLabel('任务评测集',{exact:true})).toHaveValue('loan-risk-policy')
 await expect(task.getByLabel('任务评测集',{exact:true})).toBeDisabled()
 await expect(task.locator('select').nth(1)).toHaveValue('loan-agent-v1-risky')
})

test('results list separates verdict from execution and historical evaluator links select exact versions',async({page,request})=>{
 await page.goto('/#results')
 await expect(page.getByLabel('执行状态',{exact:true})).toHaveValue('completed')
 await expect(page.getByRole('columnheader',{name:'评估结论 / 得分'})).toBeVisible()
 const row=page.locator('tbody tr').first()
 await expect(row).not.toContainText('读取报告中…',{timeout:10000})
 await page.goto('/#evaluators/skill-routing?version=1')
 await expect(page.getByLabel('查看评估器历史版本')).toHaveValue('1')
 await expect(page.getByRole('button',{name:'保存草稿',exact:true})).toHaveCount(0)
 await expect(page.locator('.evaluator-panel')).toContainText('v1 · 已发布 · 只读')
})

test('AB history presents the frozen dataset and evaluators as read-only result details',async({page,request})=>{
 const runs=(await(await request.get('/api/runs?limit=200')).json()).data
 const source=runs.find((r:any)=>r.status==='completed'&&r.manifest.dataset.dataset_id==='loan-risk-policy')
 await page.goto('/#experiments')
 await selectHistoryTask(page,0,source.id)
 const side=page.getByTestId('ab-side').first()
 await expect(side).toContainText('高风险贷款策略评估 · v1')
 await expect(side.getByLabel('筛选历史评测集版本')).toHaveCount(0)
 await expect(side.getByLabel('筛选历史评估器')).toHaveCount(0)
 await side.locator('.evaluator-summary summary').click()
 for(const id of source.manifest.primary_evaluator_ids){
  const evaluator=source.manifest.evaluator_specs.find((e:any)=>e.id===id)
  await expect(side.locator('.evaluator-summary')).toContainText(evaluator.name+' · v'+evaluator.version)
 }
})

test('new AB pair cannot compare pending or failed sides',async({page})=>{
 await page.route('**/api/run-comparisons',r=>r.fulfill({status:202,json:{code:'0',message:'success',data:{baseline:{run_id:'pair-fixture-a'},candidate:{run_id:'pair-fixture-b'}}}}))
 await page.route('**/api/runs/pair-fixture-*/status',r=>r.fulfill({json:{code:'0',message:'success',data:{run_id:r.request().url().includes('fixture-a')?'pair-fixture-a':'pair-fixture-b',status:r.request().url().includes('fixture-a')?'completed':'failed'}}}))
 await page.goto('/#experiments')
 await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
 await page.getByLabel('共同评测集',{exact:true}).selectOption('loan-risk-policy')
 await expect(page.locator('.check-list input:checked').first()).toBeChecked()
 await page.getByRole('button',{name:'创建并运行两侧任务'}).click()
 await expect(page.getByRole('button',{name:'查看对比结果'})).toBeDisabled()
 await expect(page.getByRole('link',{name:/查看实验 B 执行进度/})).toContainText('执行异常')
})

test('local merge reads exact published versions without modifying either source',async({page,request})=>{
 const datasets=(await(await request.get('/api/datasets')).json()).data
 const sources=datasets.filter((d:any)=>d.version!==null).slice(0,2)
 expect(sources).toHaveLength(2)
 const before=await Promise.all(sources.map((d:any)=>request.get('/api/datasets/'+d.id+'/versions/'+d.version).then(r=>r.json().then(j=>j.data))))
 const writes:string[]=[];page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url())})
 await page.goto('/#dataset-merge')
 await page.getByLabel('合并预览数据').selectOption('local')
 for(const d of sources){
  const row=page.locator('tbody tr').filter({hasText:d.id})
  await row.locator('input[type=checkbox]').check()
  await row.locator('select').selectOption(String(d.version))
 }
 await page.getByRole('button',{name:'检查合并',exact:true}).click()
 await expect(page.getByRole('button',{name:'下一步',exact:true})).toBeEnabled()
 expect(writes).toEqual([])
 expect(await Promise.all(sources.map((d:any)=>request.get('/api/datasets/'+d.id+'/versions/'+d.version).then(r=>r.json().then(j=>j.data))))).toEqual(before)
})
test('task submission stays disabled until exact dataset configuration has loaded',async({page})=>{
 await page.goto('/#datasets/loan-risk-policy?version=1')
 await page.getByTestId('case-name').waitFor()
 let release!:()=>void
 const gate=new Promise<void>(resolve=>release=resolve)
 await page.route('**/api/datasets/loan-risk-policy',async route=>{await gate;await route.continue()})
 await page.getByTestId('run-single-case').click()
 const dialog=page.getByRole('dialog')
 await expect(dialog.getByRole('button',{name:'提交评测',exact:true})).toBeDisabled()
 release()
 await expect(page.getByLabel('任务评测集版本',{exact:true})).toHaveValue('1')
 await expect(dialog.getByRole('button',{name:'提交评测',exact:true})).toBeEnabled()
 expect(await dialog.locator('.el-dialog__body').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBeTruthy()
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
})
