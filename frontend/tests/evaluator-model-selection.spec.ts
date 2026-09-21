import {test,expect} from '@playwright/test'
test('LLM form selects configured models and hides internal fields',async({page})=>{
 await page.route('**/api/configured-models',r=>r.fulfill({json:{code:'0',message:'success',data:[{provider_id:'test-service',model_id:'test-judge',credential_ref:'env:TEST_KEY'}]}}))
 await page.goto('/#evaluators')
 await page.getByRole('button',{name:'新建评估器',exact:true}).click()
 await page.getByLabel('评估器类型').selectOption('llm_judge')
 const dialog=page.getByRole('dialog')
 await expect(dialog.getByText('质量维度',{exact:true})).toHaveCount(0)
 await expect(dialog.getByText('指标标识',{exact:true})).toHaveCount(0)
 await expect(dialog.getByText('失败影响',{exact:true})).toHaveCount(0)
 await expect(dialog.getByText('凭据引用',{exact:true})).toHaveCount(0)
 await dialog.getByLabel('评估模型').selectOption({label:'test-judge · test-service'})
 await expect(dialog.getByLabel('评估模型')).toHaveValue('0')
})
test('configuration reports an empty connected-model catalog honestly',async({page})=>{
 await page.route('**/api/configured-models',r=>r.fulfill({json:{code:'0',message:'success',data:[]}}))
 await page.goto('/#settings')
 await expect(page.getByText('暂无已接入模型',{exact:true})).toBeVisible()
})
