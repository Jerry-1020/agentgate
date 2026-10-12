import {staticChinese} from '../src/views/evaluation/utils/static-chinese'
import {test,expect} from '@playwright/test'
import { passAuthGate } from './auth-gate';
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await passAuthGate(page);
});

test('static analysis renders partial report findings and errors',async({page,request})=>{
 const list=(await (await request.get('/api/skill-analysis/reports?target_descriptor_sha256=5a5e3c9cc8c3f6faa7108dd82e771f1e7c86b127dc8b936033f3a2111e3539bd')).json()).data
 const report=list[0]
 expect(report.findings.length).toBeGreaterThan(0)
 await page.route('**/api/skill-analysis/reports',route=>route.fulfill({json:{code:'0',message:'success',data:report}}))
 await page.goto('/#analysis')
 await page.getByRole('combobox',{name:'分析对象'}).selectOption({label:'旧方案'})
 await expect(page.getByRole('heading',{name:'第三步：查看问题与修改建议',exact:true})).toBeVisible()
 await expect(page.getByRole('combobox',{name:'筛选问题 Skill'})).toBeVisible()
 for(const finding of report.findings)await expect(page.getByText(staticChinese(finding.reason),{exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'保存复核',exact:true})).toHaveCount(report.findings.length)
 await page.getByText('查看检查异常（'+report.errors.length+'）',{exact:true}).click()
 await expect(page.getByText(/模型输出未通过校验/).first()).toBeVisible()
 await expect(page.getByRole('button',{name:'选择验证用例',exact:true})).toHaveCount(0)
 await expect(page.getByRole('button',{name:/配置验证任务/})).toHaveCount(0)
})
test('annotation writeback preserves source checks and adds notes after confirmation',async({page,request})=>{
 const id='9a3ff83e-96b6-4e10-9e61-7f1aa38df47b'
 const report=(await (await request.get('/api/runs/'+id)).json()).data
 const caseId=report.results.find((r:any)=>r.outcome==='fail').case_id
 const source=(await (await request.get('/api/runs/'+id+'/cases/'+caseId)).json()).data
 let payload:any=null
 await page.route('**/api/runs/'+id+'/cases/'+caseId+'/writeback',route=>{payload=route.request().postDataJSON();return route.fulfill({json:{code:'0',message:'success',data:{source_dataset_id:source.dataset_id}}})})
 await page.goto('/#optimizer/'+id)
 await page.getByText('查看期望与实际执行证据',{exact:true}).first().click()
 const annotation=page.getByRole('complementary',{name:'人工标注'}).first()
 await expect(annotation.getByRole('button',{name:'加入测评集草稿'})).toBeDisabled()
 await annotation.getByRole('textbox').fill('核对人工复核分支，保留原始期望。')
 await annotation.getByRole('button',{name:'加入测评集草稿'}).click()
 expect(payload).toBeNull()
 await page.getByRole('button',{name:'确认加入',exact:true}).click()
 await expect(annotation.getByRole('status')).toContainText('已加入草稿')
 expect(payload.case.turns).toEqual(source.case.turns)
 expect(payload.case.notes).toContain('核对人工复核分支，保留原始期望。')
 expect(payload.case.id).toBe(caseId)
})
test('optimizer loads evidence without a model entry or request',async({page})=>{
 let calls=0
 page.on('request',r=>{if(r.url().includes('/optimization'))calls++})
 await page.goto('/#optimizer/9a3ff83e-96b6-4e10-9e61-7f1aa38df47b')
 await expect(page.getByRole('heading',{name:'分析结果',exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'模型补充分析',exact:true})).toHaveCount(0)
 expect(calls).toBe(0)
})
test('builtin browser disable persists and excludes new task and AB choices',async({page})=>{
 const patches:string[]=[]
 page.on('request',r=>{if(r.method()==='PATCH'&&r.url().includes('/evaluators/skill-routing'))patches.push(r.url())})
 await page.goto('/#evaluators/skill-routing')
 await page.getByRole('button',{name:'禁用',exact:true}).click()
 await expect(page.getByRole('button',{name:'启用',exact:true})).toBeEnabled()
 await expect(page.getByRole('button',{name:'发起测评',exact:true})).toBeDisabled()
 await page.reload()
 await expect(page.getByRole('button',{name:'启用',exact:true})).toBeEnabled()
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'发起测评',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'新建测评任务'})
 await expect(dialog.getByRole('button',{name:'推荐评估器',exact:true})).toBeVisible()
 await expect(dialog.getByRole('checkbox',{name:/^Skill Routing/})).toHaveCount(0)
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.goto('/#experiments')
 await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
 await expect(page.getByRole('checkbox',{name:'Skill Routing',exact:true})).toHaveCount(0)
 await page.goto('/#evaluators/skill-routing')
 await page.getByRole('button',{name:'启用',exact:true}).click()
 await expect(page.getByRole('button',{name:'禁用',exact:true})).toBeEnabled()
 expect(patches).toEqual([])
})
test('real report suggestions and sample popup remain available',async({page,request})=>{
 const id='9a3ff83e-96b6-4e10-9e61-7f1aa38df47b'
 const report=(await (await request.get('/api/runs/'+id)).json()).data
 expect(report.results.some((r:any)=>r.outcome==='fail')).toBeTruthy()
 await page.goto('/#optimizer/'+id)
 const analysis=page.getByRole('region',{name:'基于真实报告的规则分析'})
 await expect(analysis.getByRole('heading',{name:'分析结果'})).toBeVisible()
 const suggestions=page.getByRole('region',{name:'基于失败证据的改进建议'})
 await expect(suggestions).toHaveCount(0)
 await page.locator('.improvement-card').filter({hasText:'调用了禁用工具（'}).getByRole('button',{name:'查看关联原因与建议',exact:true}).click()
 await expect(suggestions.getByRole('heading',{name:'改进建议',exact:true})).toBeVisible()
 await expect(suggestions.getByText('限制禁用工具的调用路径',{exact:true})).toBeVisible()
 await expect(suggestions.getByRole('heading',{name:'怎么改',exact:true})).toHaveCount(0)
 await expect(suggestions.getByText('对应根因尚未确认；以上为规则建议，并非模型结论。',{exact:true})).toHaveCount(0)
 await expect(suggestions.locator(':scope > p').first()).toContainText('优先级：')
 await expect(suggestions.getByRole('heading',{name:'如何验证',exact:true}).first()).toBeVisible()
 await expect(analysis.getByRole('heading',{name:'失败聚类',exact:true})).toHaveCount(0)
 const before=page.url()
 await analysis.getByRole('button',{name:/查看报告/}).first().click()
 const dialog=page.getByRole('dialog',{name:'样本测评报告'})
 await expect(dialog.getByTestId('case-report')).toBeVisible()
 expect(page.url()).toBe(before)
 await page.keyboard.press('Escape')
 await expect(dialog).toBeHidden()
 const failedNames=[...new Set(report.results.filter((r:any)=>r.outcome==='fail').map((r:any)=>r.evaluator_name))]
 expect(failedNames.length).toBeGreaterThan(0)
 await analysis.getByText('查看期望与实际执行证据',{exact:true}).first().click()
 await expect(analysis.getByRole('columnheader',{name:'期望',exact:true}).first()).toBeVisible()
 await expect(analysis.getByRole('columnheader',{name:'实际',exact:true}).first()).toBeVisible()
 await expect(page.getByRole('button',{name:'模型补充分析',exact:true})).toHaveCount(0)
})
