import {test,expect} from '@playwright/test'

test('review 0911 cards and explicit expected output persist to published backend condition',async({page,request})=>{
 page.on('pageerror',error=>console.log('UI ERROR',error.message))
 page.on('response',async r=>{if(r.status()>=400)console.log('HTTP ERROR',r.url(),await r.text())})
 const name='0911-output-'+Date.now();let id=''
 try{
 await page.goto('/#datasets')
 await expect(page.getByRole('button',{name:'导入测评集',exact:true})).toBeVisible()
 await page.getByTestId('create-dataset').click()
 await page.getByTestId('dataset-name').fill(name)
 await page.getByTestId('submit-dataset').click()
 await expect(page.getByRole('heading',{name,exact:true})).toBeVisible()
 await expect(page.getByTestId('run-dataset-version')).toBeDisabled()
 id=(await(await request.get('/api/datasets')).json()).data.find((d:any)=>d.name===name).id
 await page.getByRole('button',{name:'新增用例',exact:true}).click()
 await page.getByTestId('case-name').fill('期望输出持久化')
 await page.getByTestId('turn-input-0').fill('{"application_id":"TEST-0911","skill":"loan_approval","risk":"high","amount":80000}')
 await page.getByTestId('turn-output-0').fill('{"status":"pending_review"}')
 await page.getByTestId('save-case').click()
 await expect(page.getByText('用例已保存到草稿',{exact:true})).toBeVisible()
 const draft=(await(await request.get('/api/datasets/'+id+'/drafts/current')).json()).data
 const output=draft.cases[0].turns[0].expectations.find((e:any)=>e.kind==='output')
 expect(output.condition).toEqual({kind:'equals',expected:{status:'pending_review'}})
 await page.getByTestId('back-datasets').click()
 await page.getByLabel('搜索评测集',{exact:true}).fill(name)
 await expect(page.locator('.catalog-grid .dataset-tile')).toHaveCount(1)
 await page.getByTestId('dataset-item-'+id).getByRole('button',{name:'继续编辑草稿'}).click()
 await expect(page.getByTestId('turn-output-0')).toHaveValue(/pending_review/)
 await page.getByTestId('publish-draft').click()
 await expect(page.getByTestId('version-published-1')).toBeVisible()
 await expect(page.getByTestId('run-dataset-version')).toBeEnabled()
 await expect(page.locator('.dataset-run-bar')).toHaveCount(0)
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 await page.getByLabel('任务评测集',{exact:true}).selectOption(id)
 await expect(page.getByLabel('任务评测集版本',{exact:true})).toHaveValue('1')
 await page.getByRole('button',{name:/使用推荐的 1 个/}).click()
 await expect(page.getByText('评估器 · 已选 1 个',{exact:true})).toBeVisible()
 }finally{if(id)await request.delete('/api/datasets/'+id)}
})

test('known no-evidence run explains missing criteria and links exact dataset version',async({page})=>{
 const id='ca7ebd14-832e-4b1e-9a63-56b4d376174b'
 await page.goto('/#results/'+id)
 await expect(page.getByText('无有效评判依据',{exact:true})).toBeVisible()
 await page.getByText('本次任务配置与版本来源',{exact:true}).click()
 await page.getByText('关联资产',{exact:true}).click()
 await expect(page.getByRole('columnheader',{name:'本次引用版本'})).toBeVisible()
 await page.goto('/#optimizer/'+id)
 await expect(page.getByText('没有适用的评估检查',{exact:true})).toBeVisible()
 await expect(page.getByRole('link',{name:'查看评测集版本 →'})).toHaveAttribute('href',/version=1/)
})

test('overview has five honest metrics with interval switching',async({page})=>{
 await page.goto('/#overview')
 await expect(page.locator('.overview-metrics article')).toHaveCount(5)
 await expect(page.locator('.overview-metrics')).toContainText('当前未提供完整用量统计')
 const response=page.waitForResponse(r=>r.url().includes('/overview/period?')&&r.status()===200)
 await page.getByRole('button',{name:'今日',exact:true}).click()
 await response
 await expect(page.getByRole('button',{name:'今日',exact:true})).toHaveAttribute('aria-pressed','true')
})

test('task creation refuses rules with no applicable expectations without submitting',async({page,request})=>{
 const created=(await(await request.post('/api/datasets',{data:{name:'0911-no-criteria-'+Date.now()}})).json()).data
 const id=created.dataset.id
 try{
 const added=await(await request.post('/api/datasets/'+id+'/drafts/cases',{headers:{'If-Match':created.draft.content_sha256},
 data:{id:'no-criteria',name:'无评判条件',turns:[{id:'turn',input:{query:'hello'},expectations:[]}],initial_state:{},category:'positive',difficulty:'easy',tags:[],notes:''}})).json()).data
 expect((await request.post('/api/datasets/'+id+'/drafts/publish',{headers:{'If-Match':added.content_sha256}})).ok()).toBeTruthy()
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 await page.getByLabel('任务评测集',{exact:true}).selectOption(id)
 await expect(page.getByLabel('任务评测集版本',{exact:true})).toHaveValue('1')
 let submissions=0
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/evaluations'))submissions++})
 await page.getByRole('button',{name:'提交评测',exact:true}).click()
 await expect(page.getByRole('dialog').getByRole('alert')).toContainText('没有适用检查')
 expect(submissions).toBe(0)
 }finally{await request.delete('/api/datasets/'+id)}
})

test('new AB invokes upstream pair launch endpoint with frozen common versions',async({page})=>{
 await page.goto('/#experiments')
 await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
 await page.getByLabel('共同评测集',{exact:true}).selectOption('loan-risk-policy')
 await expect(page.getByLabel('发布版本',{exact:true})).not.toHaveValue('')
 await expect(page.locator('.check-list input:checked').first()).toBeChecked()
 const response=page.waitForResponse(r=>r.url().endsWith('/api/run-comparisons')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'创建并运行两侧任务'}).click()
 const r=await response;expect(r.status()).toBe(202)
 const body=(await r.json()).data
 expect(body.baseline.run_id).not.toBe(body.candidate.run_id)
 await expect(page.getByRole('heading',{name:'两侧任务已提交'})).toBeVisible()
 await expect(page.getByRole('button',{name:'查看对比结果'})).toBeEnabled({timeout:30000})
 await page.getByRole('button',{name:'查看对比结果'}).click()
 await expect(page.getByTestId('ab-side').first().getByTestId('history-result')).toContainText(body.baseline.run_id)
 await expect(page.getByTestId('ab-side').last().getByTestId('history-result')).toContainText(body.candidate.run_id)
 await expect(page.getByRole('heading',{name:'指标对比',exact:true})).toBeVisible()
})
