import {test,expect} from '@playwright/test'
test('delete draft, archive and restore published dataset, confirm run scope',async({page,request})=>{
 const name='生命周期-'+Date.now()
 const created=(await (await request.post('/api/datasets',{data:{name}})).json()).data;const id=created.dataset.id
 try{
  await page.goto('/#datasets');await page.getByLabel('搜索测评集',{exact:true}).fill(id)
  const row=page.getByTestId('dataset-item-'+id)
  await row.getByRole('button',{name:'删除',exact:true}).click()
  await page.getByRole('button',{name:'确定',exact:true}).click()
  await expect(row).toHaveCount(0)
  expect((await request.get('/api/datasets/'+id)).status()).toBe(404)
 }finally{await request.delete('/api/datasets/'+id+'/unpublished')}
 const copy=(await (await request.post('/api/datasets/loan-risk-policy/copy',{data:{name:name+'发布',source_version:1}})).json()).data
 const cid=copy.dataset.id
 try{
  expect((await request.post('/api/datasets/'+cid+'/drafts/publish',{headers:{'If-Match':copy.draft.content_sha256}})).ok()).toBeTruthy()
  expect((await request.delete('/api/datasets/'+cid+'/unpublished')).status()).toBe(409)
  await page.reload();await page.getByLabel('搜索测评集',{exact:true}).fill(cid)
  const row=page.getByTestId('dataset-item-'+cid)
  await row.getByRole('button',{name:'归档',exact:true}).click();await page.getByRole('button',{name:'确定',exact:true}).click()
  await expect(row).toHaveCount(0)
  await page.getByLabel('测评集状态',{exact:true}).selectOption('archived');await expect(row).toBeVisible()
  await row.getByRole('button',{name:'恢复',exact:true}).click();await expect(row).toHaveCount(0)
  await page.getByLabel('测评集状态',{exact:true}).selectOption('all')
  await row.getByRole('button',{name:'查看详情',exact:true}).click()
  await expect(page.getByTestId('create-draft')).toHaveText('基于 v1 创建草稿')
  await expect(page.locator('.dataset-run-bar')).toHaveCount(0)
  await page.goto('/#tasks')
  await page.getByRole('button',{name:'新建测评任务',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'新建测评任务'})
  await dialog.getByLabel('任务测评集',{exact:true}).selectOption(cid)
  await expect(dialog.getByLabel('任务测评集版本',{exact:true})).toHaveValue('1')
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
 }finally{await request.delete('/api/datasets/'+cid)}
})
