import {test,expect} from '@playwright/test'

test('metadata editing and explicit copy source preserve published snapshots',async({page,request})=>{
 const seed=await(await request.post('/api/datasets/loan-risk-policy/copy',{data:{name:'对齐测试-'+Date.now(),source_version:1}})).json()
 const id=seed.dataset.id
 let copied=''
 try{
  await page.goto('/#datasets/'+id)
  await expect(page.getByRole('button',{name:'复制评测集',exact:true})).toBeDisabled()
  const published=await request.post('/api/datasets/'+id+'/drafts/publish',{headers:{'If-Match':seed.draft.content_sha256}})
  expect(published.ok()).toBeTruthy()
  const snapshot=await published.json()
  await page.reload()
  await page.getByRole('button',{name:'编辑基本信息'}).click()
  await page.getByTestId('dataset-name').fill('已修改基本信息-'+id)
  await page.getByTestId('submit-dataset').click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  expect((await(await request.get('/api/datasets/'+id)).json()).dataset.name).toBe('已修改基本信息-'+id)
  expect(await(await request.get('/api/datasets/'+id+'/versions/1')).json()).toEqual(snapshot)
  await page.getByRole('button',{name:'复制评测集',exact:true}).click()
  await expect(page.getByLabel('复制来源版本')).toHaveValue('1')
  const response=page.waitForResponse(r=>r.url().endsWith('/datasets/'+id+'/copy')&&r.request().method()==='POST')
  await page.getByTestId('submit-dataset').click()
  const result=await response
  expect(result.request().postDataJSON().source_version).toBe(1)
  copied=(await result.json()).dataset.id
  await expect(page).toHaveURL(new RegExp(copied))
 }finally{
  if(copied)await request.delete('/api/datasets/'+copied+'/unpublished')
  await request.delete('/api/datasets/'+id)
 }
})

test('AB submits selected historical evaluator version, not latest',async({page,request})=>{
 const list=await(await request.get('/api/evaluators')).json()
 const source=list.find((e:any)=>e.implementation_id==='skill_routing')
 const base=(await(await request.get('/api/evaluators/'+source.id)).json()).latest
 const {kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}=base
 const created=await(await request.post('/api/evaluators',{data:{name:'历史版本测试-'+Date.now(),draft:{kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}}})).json()
 const id=created.evaluator.id,name=created.evaluator.name
 try{
  const first=await(await request.post('/api/evaluators/'+id+'/drafts/publish')).json()
  expect((await request.post('/api/evaluators/'+id+'/drafts',{data:{based_on_version:first.version}})).ok()).toBeTruthy()
  expect((await request.post('/api/evaluators/'+id+'/drafts/publish')).ok()).toBeTruthy()
  expect((await request.patch('/api/evaluators/'+id,{data:{enabled:true}})).ok()).toBeTruthy()
  await page.goto('/#experiments')
  await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
  await page.getByLabel('共同评测集',{exact:true}).selectOption('loan-risk-policy')
  await expect(page.getByLabel('发布版本',{exact:true})).toHaveValue('1')
  await page.getByLabel(name,{exact:true}).check()
  await page.getByLabel(name+'的评估版本',{exact:true}).selectOption(first.version)
  await page.route('**/api/run-comparisons',async route=>{
   const body=route.request().postDataJSON()
   expect(body.evaluators.find((e:any)=>e.id===id).version).toBe(first.version)
   await route.fulfill({status:422,json:{detail:'测试已验证版本选择，不创建运行'}})
  })
  await page.getByRole('button',{name:'创建并运行两侧任务'}).click()
  await expect(page.getByRole('alert')).toContainText('测试已验证版本选择')
 }finally{await request.patch('/api/evaluators/'+id,{data:{enabled:false}})}
})
