import {test,expect} from '@playwright/test'

test('AB waits for initial catalogs before enabling dataset selection and does not overwrite it later',async({page})=>{
 let release!:()=>void,waiting=0
 const gate=new Promise<void>(resolve=>{release=resolve})
 await page.route('**/api/evaluators/*/versions',async route=>{waiting++;await gate;await route.continue()})
 try{
  await page.goto('/#experiments')
  await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
  await expect.poll(()=>waiting).toBeGreaterThan(0)
  await expect(page.getByLabel('共同评测集',{exact:true})).toBeDisabled()
  await expect(page.getByRole('button',{name:'创建并运行两侧任务'})).toBeDisabled()
  release()
  await expect(page.getByLabel('共同评测集',{exact:true})).toBeEnabled()
  await page.getByLabel('共同评测集',{exact:true}).selectOption('loan-risk-policy')
  await expect(page.getByLabel('发布版本',{exact:true})).toHaveValue('1')
  await expect(page.getByLabel('共同评测集',{exact:true})).toHaveValue('loan-risk-policy')
 }finally{release()}
})

test('AB lists three real published dataset versions and submits the exact selection for both sides',async({page,request})=>{
 const source=await(await request.get('/api/datasets/loan-risk-policy/versions/1')).json()
 const created=await(await request.post('/api/datasets',{data:{name:'A/B版本验收-'+Date.now()}})).json()
 const id=created.dataset.id,snapshots:any[]=[]
 let draft=created.draft
 try{
  for(let number=1;number<=3;number++){
   if(number>1)draft=await(await request.post('/api/datasets/'+id+'/drafts',{data:{based_on_version:number-1}})).json()
   const item=structuredClone(source.cases[0]);item.id='ab-version-test-'+number;item.name='版本新增样本 '+number
   item.turns[0].id='turn-'+number
   draft=await(await request.post('/api/datasets/'+id+'/drafts/cases',{headers:{'If-Match':draft.content_sha256},data:item})).json()
   const response=await request.post('/api/datasets/'+id+'/drafts/publish',{headers:{'If-Match':draft.content_sha256}})
   expect(response.ok()).toBeTruthy();snapshots.push(await response.json())
  }
  await page.goto('/#experiments')
  await page.getByRole('button',{name:'创建实验并运行',exact:true}).click()
  await page.getByLabel('共同评测集',{exact:true}).selectOption(id)
  const versions=page.getByLabel('发布版本',{exact:true})
  await expect(versions.locator('option')).toHaveText(['v3 · 3 条 · 最新发布','v2 · 2 条','v1 · 1 条'])
  await expect(versions).toHaveValue('3')
  let expectedVersion=3,submitted=0
  await page.route('**/api/run-comparisons',async route=>{
   const body=route.request().postDataJSON()
   expect(body.dataset_id).toBe(id)
   expect(body.dataset_version).toBe(expectedVersion)
   expect(body.baseline_version).not.toBe(body.candidate_version)
   expect(body.evaluators.length).toBeGreaterThan(0)
   submitted++
   await route.fulfill({status:422,json:{detail:'已核对 v'+expectedVersion+' 固定版本请求；测试未创建任务'}})
  })
  for(const number of [3,2,1]){
   expectedVersion=number
   await versions.selectOption(String(number))
   await expect(page.getByRole('link',{name:'查看 v'+number+' 用例',exact:true})).toHaveAttribute('href','#datasets/'+id+'?version='+number)
   await page.getByRole('button',{name:'创建并运行两侧任务',exact:true}).click()
   await expect(page.getByRole('alert')).toContainText('已核对 v'+number+' 固定版本请求')
  }
  expect(submitted).toBe(3)
  for(const version of snapshots){
   expect(await(await request.get('/api/datasets/'+id+'/versions/'+version.version)).json()).toEqual(version)
  }
 }finally{
  await request.delete('/api/datasets/'+id)
 }
})
