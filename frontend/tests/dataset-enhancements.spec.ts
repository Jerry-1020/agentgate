import {test,expect} from '@playwright/test'
test('published single case creates a scoped run',async({page})=>{
 await page.goto('/#datasets/loan-risk-policy?version=1')
 await page.getByTestId('run-single-case').click()
 await expect(page.getByRole('dialog')).toContainText('运行范围：指定 1 条用例')
 const response=page.waitForResponse(r=>r.url().endsWith('/api/evaluations')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'提交测评',exact:true}).click()
 const r=await response;expect(r.ok()).toBeTruthy();expect(r.request().postDataJSON().case_ids).toHaveLength(1)
 await expect(page).toHaveURL(new RegExp('#tasks/'+(await r.json()).data.run_id+'$'))
})
test('Excel export can be imported as a draft with counts',async({page,request})=>{
 const exported=await request.get('/api/datasets/loan-risk-policy/versions/1/export/xlsx')
 expect(exported.ok()).toBeTruthy()
 expect((await request.get('/api/datasets/template/xlsx')).ok()).toBeTruthy()
 const name='Excel-roundtrip-'+Date.now();let id=''
 try{
 await page.goto('/#datasets')
 await page.getByRole('button',{name:'导入测评集',exact:true}).click()
 await page.getByLabel('导入测评集名称').fill(name)
 await page.getByLabel('导入文件').setInputFiles({name:'roundtrip.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:await exported.body()})
 const pending=page.waitForResponse(r=>r.url().endsWith('/datasets/import/xlsx'))
 await page.getByRole('button',{name:'确认导入'}).click()
 const r=await pending;expect(r.ok()).toBeTruthy();id=(await r.json()).data.dataset.id
 await expect(page.getByRole('heading',{name,exact:true})).toBeVisible()
 await expect(page.getByTestId('run-single-case')).toBeDisabled()
 await page.getByTestId('back-datasets').click()
 await page.getByLabel('搜索测评集',{exact:true}).fill(name)
 await expect(page.getByTestId('dataset-item-'+id)).toContainText('当前草稿：1 条用例')
 }finally{if(id)await request.delete('/api/datasets/'+id+'/unpublished')}
})

test('Excel validation errors stay in import dialog without creating data',async({page})=>{
 await page.goto('/#datasets')
 await page.getByRole('button',{name:'导入测评集',exact:true}).click()
 await page.getByLabel('导入测评集名称').fill('invalid-upload')
 await page.getByLabel('导入文件').setInputFiles({name:'invalid.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('not an xlsx')})
 await page.getByRole('button',{name:'确认导入'}).click()
 await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
 await expect(page.getByRole('columnheader',{name:'问题',exact:true})).toBeVisible()
})
