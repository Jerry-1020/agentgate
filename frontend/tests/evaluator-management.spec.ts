import {test,expect} from '@playwright/test'

async function createRule(request:any,name:string){
 const list=(await (await request.get('/api/evaluators')).json()).data
 const base=(await (await request.get('/api/evaluators/'+list.find((e:any)=>e.kind==='rule').id)).json()).data
 const {kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}=base.latest
 const response=await request.post('/api/evaluators',{data:{name,description:'界面自动化验证',draft:{kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}}})
 expect(response.ok()).toBeTruthy()
 return (await response.json()).data.evaluator.id
}

test('unpublished evaluator draft discard and deletion are confirmed',async({page,request})=>{
 const name='管理测试未发布-'+Date.now(),id=await createRule(request,name)
 try{
  await page.goto('/#evaluators')
  await page.getByRole('button').filter({has:page.getByText(name,{exact:true})}).click()
  await page.getByRole('button',{name:'丢弃草稿',exact:true}).click()
  await page.getByRole('button',{name:'取消',exact:true}).click()
  expect((await request.get('/api/evaluators/'+id+'/drafts/current')).ok()).toBeTruthy()
  await page.getByRole('button',{name:'丢弃草稿',exact:true}).click()
  await page.getByRole('button',{name:'确认丢弃',exact:true}).click()
  await expect(page.getByRole('button',{name:'丢弃草稿',exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'删除评估器',exact:true}).click()
  await page.getByRole('button',{name:'确认删除',exact:true}).click()
  await expect(page.getByText(name,{exact:true})).toHaveCount(0)
  expect((await request.get('/api/evaluators/'+id)).status()).toBe(404)
 }finally{await request.delete('/api/evaluators/'+id)}
})

test('published history is immutable and can seed a new draft',async({page,request})=>{
 const name='管理测试版本-'+Date.now(),id=await createRule(request,name)
 try{
  const published=await request.post('/api/evaluators/'+id+'/drafts/publish')
  expect(published.ok()).toBeTruthy()
  const snapshot=(await published.json()).data
  await page.goto('/#evaluators')
  await page.getByRole('button').filter({has:page.getByText(name,{exact:true})}).click()
  await expect(page.getByRole('button',{name:'删除评估器',exact:true})).toHaveCount(0)
  await page.getByLabel('查看评估器历史版本').selectOption(snapshot.version)
  await expect(page.getByRole('region',{name:'已发布版本详情（只读）'})).toBeVisible()
  await page.getByRole('button',{name:'配置与版本',exact:true}).click()
  await expect(page.locator('.evaluator-panel textarea').first()).toHaveAttribute('readonly','')
  await expect(page.getByRole('button',{name:'保存草稿',exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'基于此版本创建草稿'}).click()
  await expect(page.getByRole('button',{name:'丢弃草稿',exact:true})).toBeVisible()
  const draft=(await (await request.get('/api/evaluators/'+id+'/drafts/current')).json()).data
  expect(draft.based_on_version).toBe(snapshot.version)
  await page.getByRole('button',{name:'丢弃草稿',exact:true}).click()
  await page.getByRole('button',{name:'确认丢弃',exact:true}).click()
  await expect(page.getByRole('button',{name:'丢弃草稿',exact:true})).toHaveCount(0)
  expect((await (await request.get('/api/evaluators/'+id+'/versions/'+snapshot.version)).json()).data).toEqual(snapshot)
  expect((await request.delete('/api/evaluators/'+id)).status()).toBe(409)
 }finally{await request.patch('/api/evaluators/'+id,{data:{enabled:false}})}
})
