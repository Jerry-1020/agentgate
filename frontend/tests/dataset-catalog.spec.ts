import {test,expect} from '@playwright/test'

test('persisted Mock datasets remain accessible as cards',async({page,request})=>{
 const all=(await(await request.get('/api/datasets')).json()).data
 const mocks=all.filter((d:any)=>d.description.startsWith('[Mock:'))
 expect(mocks.length).toBeGreaterThan(0)
 await page.goto('/#datasets')
 await page.getByLabel('评测集来源',{exact:true}).selectOption('mock')
 await expect(page.locator('.catalog-grid .dataset-tile')).toHaveCount(Math.min(10,mocks.length))
 const selected=mocks[0]
 await page.getByTestId('dataset-item-'+selected.id).locator('.tile-open').click()
 await expect(page.getByRole('heading',{name:selected.name,exact:true})).toBeVisible()
 await expect(page.getByTestId('turn-input-0')).toBeVisible()
})

test('saved unpublished datasets can be found, resumed, published and edited without duplicate assets',async({page,request})=>{
 const name='草稿管理验收-'+Date.now();let id=''
 try {
  await page.goto('/#datasets')
  await expect(page.getByTestId('dataset-catalog')).toBeVisible()
  await page.getByTestId('create-dataset').click()
  await page.getByTestId('dataset-name').fill(name)
  await page.getByTestId('submit-dataset').click()
  await expect(page.getByRole('heading',{name,exact:true})).toBeVisible()
  id=(await (await request.get('/api/datasets')).json()).data.find((x:any)=>x.name===name).id
  await page.getByTestId('publish-draft').click()
  await expect(page.locator('.validation-alert')).toContainText('评测集至少需要一个用例')
  await page.getByRole('button',{name:'新增用例',exact:true}).click()
  await page.getByTestId('case-name').fill('手动输入样本')
  await page.getByTestId('turn-input-0').fill('{"query":"查询订单"}')
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿',{exact:true})).toBeVisible()
  await page.getByTestId('back-datasets').click()
  await page.getByLabel('评测集状态',{exact:true}).selectOption('unpublished')
  await page.getByLabel('搜索评测集',{exact:true}).fill(name)
  const row=page.getByTestId('dataset-item-'+id)
  await expect(row).toContainText('未发布')
  await page.reload()
  await page.getByLabel('搜索评测集',{exact:true}).fill(name)
  await row.getByRole('button',{name:'继续编辑草稿',exact:true}).click()
  await expect(page.getByTestId('case-name')).toHaveValue('手动输入样本')
  await page.getByTestId('publish-draft').click()
  await expect(page.getByTestId('version-published-1')).toBeVisible()
  await page.getByTestId('create-draft').click()
  await page.getByTestId('version-published-1').click()
  await expect(page.getByTestId('continue-draft')).toBeEnabled()
  await page.getByTestId('continue-draft').click()
  await expect(page.getByTestId('save-case')).toBeVisible()
  await page.getByTestId('back-datasets').click()
  await page.getByLabel('评测集状态',{exact:true}).selectOption('changes')
  await page.getByLabel('搜索评测集',{exact:true}).fill(name)
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('有待发布修改')
  await page.screenshot({path:'../runtime/browser-tests/dataset-catalog.png',fullPage:true})
 } finally {if(id)await request.delete('/api/datasets/'+id)}
})
