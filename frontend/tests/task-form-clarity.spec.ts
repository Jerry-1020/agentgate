import {test,expect} from '@playwright/test'
test('task form identifies agent, counts selected evaluators and explains execution parameters',async({page})=>{
 await page.goto('/#tasks')
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'新建评测任务'})
 await expect(dialog.getByLabel('智能体',{exact:true})).toContainText('贷款审批演示智能体')
 await expect(dialog.locator('option').filter({hasText:'旧方案 v1'})).toHaveCount(1)
 await expect(dialog.locator('.check-list input:checked').first()).toBeChecked()
 const selected=await dialog.locator('.check-list input:checked').count()
 await expect(dialog.getByText(`评估器 · 已选 ${selected} 个`,{exact:true})).toBeVisible()
 await dialog.locator('.check-list input:checked').first().uncheck()
 await expect(dialog.getByText(`评估器 · 已选 ${selected-1} 个`,{exact:true})).toBeVisible()
 for(const text of ['同时执行的用例上限','单次目标执行的等待时限','1 次为普通评测','仅对后端认可的可重试执行错误']){
  await expect(dialog.locator('small').filter({hasText:text})).toHaveCount(1)
 }
 await page.screenshot({path:'../runtime/browser-tests/task-form-clarity.png',fullPage:true})
})
