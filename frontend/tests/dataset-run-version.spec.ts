import {test,expect} from '@playwright/test'

test('dataset launches the viewed published version through the shared task form',async({page})=>{
 await page.goto('/#datasets/loan-risk-policy?version=1')
 await expect(page.getByTestId('run-dataset-version')).toBeEnabled()
 await page.getByTestId('run-dataset-version').click()
 const dialog=page.getByRole('dialog')
 await expect(dialog.getByLabel('任务测评集',{exact:true})).toHaveValue('loan-risk-policy')
 await expect(dialog.getByLabel('任务测评集版本',{exact:true})).toHaveValue('1')
 await expect(dialog.getByLabel('任务测评集版本',{exact:true})).toBeDisabled()
 await expect(dialog.getByLabel('任务测评集',{exact:true})).toBeDisabled()
 await expect(dialog.getByLabel('智能体',{exact:true})).toBeVisible()
 const response=page.waitForResponse(r=>r.url().endsWith('/api/evaluations')&&r.request().method()==='POST')
 await dialog.getByRole('button',{name:'提交测评',exact:true}).click()
 const r=await response
 expect(r.ok()).toBeTruthy()
 expect(r.request().postDataJSON()).toMatchObject({dataset_id:'loan-risk-policy',dataset_version:1})
 const run=(await r.json()).data
 await expect(page).toHaveURL(new RegExp('#tasks/'+run.run_id+'$'))
})
