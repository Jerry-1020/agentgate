import {test,expect} from '@playwright/test'

test('bank targets use real catalog, database datasets and capability limits',async({page,request})=>{
 const targets=(await(await request.get('/api/bank-targets')).json()).data
 expect(targets).toHaveLength(3)
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'发起评测',exact:true}).click()
 const form=page.getByRole('dialog',{name:'新建评测任务'})
 await expect(form.getByRole('combobox',{name:'智能体',exact:true})).toHaveValue('base')
 await expect(form.getByRole('checkbox',{name:/Skill 静态分析/})).toBeDisabled()
 await expect(form.getByRole('button',{name:'A/B 实验',exact:true})).toBeDisabled()
 await expect(form.getByRole('spinbutton',{name:'并发样本数'})).toHaveValue('1')
 await expect(form.getByRole('spinbutton',{name:'失败重试次数'})).toBeDisabled()
 await form.getByRole('combobox',{name:'智能体',exact:true}).selectOption('workflow')
 await expect(form.getByRole('combobox',{name:'任务评测集',exact:true})).toHaveValue('da84514d-e5a2-4926-ba8a-9b353ccc304e')
 await form.getByRole('combobox',{name:'智能体',exact:true}).selectOption('cloudshrimp')
 await expect(form.getByRole('combobox',{name:'任务评测集',exact:true})).toHaveValue('bd721296-34f4-455a-b9c6-424646e5f7c6')
 await expect(form.getByRole('checkbox',{name:/Skill 静态分析/})).toBeEnabled()
 await form.getByRole('button',{name:'采用推荐并查看理由'}).click()
 await expect(form.getByRole('region',{name:'智能体内部推荐依据'})).toContainText('loan_application')
 await form.getByRole('checkbox',{name:/Skill 静态分析/}).check()
 await expect(form.getByLabel('Skill 静态分析模型配置')).toContainText('后端已配置')
 await expect(form.getByRole('textbox',{name:'API Key'})).toHaveCount(0)
 expect(errors).toEqual([])
})

test('model metadata is server-backed and does not expose credentials',async({page,request})=>{
 const response=await request.get('/api/model-runtime');expect(response.ok()).toBeTruthy()
 const body=(await response.json()).data
 expect(body.connections).toHaveLength(6)
 expect(JSON.stringify(body)).not.toMatch(/sk-sp-|api_key|Authorization/)
 await page.goto('/#settings')
 await expect(page.getByRole('heading',{name:'服务端实际模型配置'})).toBeVisible()
 await expect(page.getByText('被测智能体 · cloudshrimp',{exact:true})).toBeVisible()
 await expect(page.getByText('deepseek-v3.2',{exact:true}).first()).toBeVisible()
})

test('failed execution retains completed samples and the original error',async({page,request})=>{
 const id='d28ecaca-4b94-4e9a-99e9-7cd199ec9c62'
 const samples=(await(await request.get('/api/runs/'+id+'/samples')).json()).data
 expect(samples.results.length).toBeGreaterThan(0)
 await page.goto('/#tasks/'+id)
 await expect(page.getByText('SDK trace output differs from request result',{exact:false})).toBeVisible()
 await expect(page.getByRole('heading',{name:'样本（5）'})).toBeVisible()
 await expect(page.getByText('cloudshrimp-blocked',{exact:true}).first()).toBeVisible()
})

test('base report does not offer a fake Skill analysis',async({page})=>{
 await page.goto('/#tasks/bb2a96d8-f18a-4897-b304-8cbb245c4f32')
 await page.getByRole('button',{name:'Skill 静态分析',exact:true}).click()
 await expect(page.getByText('该评测对象未声明 Skill，静态分析不适用。',{exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'运行分析',exact:true})).toBeDisabled()
 await expect(page.getByLabel('本次任务评测对象')).toContainText('基础编排')
})
