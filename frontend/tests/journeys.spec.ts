import {test,expect} from '@playwright/test'

test('all menu routes, unknown route recovery and task form validation',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/')
 for(const [name,heading] of [['评测总览','评测总览'],['评测集','评测集'],['评估器','评估器'],['评测任务','评测任务'],['结果中心','结果中心'],['A/B 实验','A/B 实验'],['调优中心','调优中心'],['Skill 静态分析','Skill 静态分析']]){
  await page.locator('.sidebar').getByRole('link',{name,exact:true}).click()
  await expect(page.getByRole('heading',{name:heading,exact:true}).first()).toBeVisible()
  await expect(page.locator('.sidebar .nav-item.active')).toHaveText(name)
 }
 await page.goto('/#missing-page')
 await page.getByRole('link',{name:'返回总览',exact:true}).click()
 await expect(page).toHaveURL(/#overview$/)
 await page.locator('.sidebar').getByRole('link',{name:'评测任务',exact:true}).click()
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 const dialog=page.getByRole('dialog')
 await expect(dialog.locator('select').first().locator('option').first()).toBeAttached()
 let submissions=0
 page.on('request',req=>{if(req.method()==='POST'&&req.url().includes('/api/evaluations'))submissions++})
 await dialog.locator('label').filter({hasText:'稳定性测试重复次数'}).locator('input').fill('0')
 await dialog.getByRole('button',{name:'提交评测',exact:true}).click()
 await expect(dialog.getByRole('alert')).toContainText('稳定性测试重复次数必须为 1—20 的整数')
 expect(submissions).toBe(0)
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
 await expect(dialog.locator('label').filter({hasText:'稳定性测试重复次数'}).locator('input')).toHaveValue('1')
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.getByRole('textbox',{name:'搜索任务',exact:true}).fill('不存在的任务-测试')
 await expect(page.getByText('暂无符合条件的任务',{exact:true})).toBeVisible()
 await page.locator('.sidebar').getByRole('link',{name:'结果中心',exact:true}).click()
 await expect(page.getByRole('textbox',{name:'搜索任务',exact:true})).toHaveValue('')
 expect(errors).toEqual([])
})

test('desktop layouts keep page content inside the viewport',async({page})=>{
 for(const width of [1440,1280]){
  await page.setViewportSize({width,height:800})
  for(const route of ['datasets','evaluators','tasks','experiments','optimizer','analysis']){
   await page.goto('/#'+route)
   await expect(page.locator('main h1').first()).toBeVisible()
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy()
  }
 }
 await page.screenshot({path:'../runtime/browser-tests/journey-layout.png',fullPage:true})
})

test('create dataset, retain unsaved edits, handle conflict, publish and run',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 const name='链路验收-'+Date.now()
 let datasetId=''
 try{
  await page.goto('/#datasets')
  await expect(page.getByRole('button',{name:'创建',exact:true})).toBeInViewport()
  await expect(page.locator('.workspace-heading .workspace-status')).toHaveCount(0)
  const heading=await page.locator('.workspace-heading').boundingBox()
  const actions=await page.locator('.workspace-heading .actions').boundingBox()
  expect(actions!.x+actions!.width).toBeGreaterThan(heading!.x+heading!.width-40)
  await page.getByTestId('create-dataset').click()
  await expect(page.getByRole('dialog').getByRole('button',{name:'保存草稿',exact:true})).toBeVisible()
  await page.getByRole('dialog').getByRole('textbox',{name:'名称',exact:true}).fill(name)
  await page.getByTestId('submit-dataset').click()
  await expect(page.getByRole('heading',{name,exact:true})).toBeVisible()
  const listed=await (await request.get('/api/datasets')).json()
  datasetId=listed.find((d:any)=>d.name===name).id
  await page.getByRole('button',{name:'新增用例',exact:true}).click()
  await page.getByTestId('turn-input-0').fill('{"application_id":"A-100","query":"查询申请"}')
  await page.getByTestId('turn-output-0').fill('"待核对"')
  await expect(page.getByText('初始状态（JSON）',{exact:true})).toHaveCount(0)
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿',{exact:true})).toBeVisible()
  await page.getByRole('textbox',{name:'用例名称',exact:true}).fill('未保存的修改')
  page.once('dialog',d=>d.dismiss())
  await page.locator('.sidebar').getByRole('link',{name:'评测任务',exact:true}).click()
  await expect(page.getByRole('textbox',{name:'用例名称',exact:true})).toHaveValue('未保存的修改')
  await page.route('**/api/datasets/*/drafts/cases/*',route=>route.request().method()==='PUT'?route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'conflict'})}):route.continue())
  await page.getByTestId('save-case').click()
  await expect(page.getByText(/其他用户已修改此草稿/)).toBeVisible()
  await expect(page.getByRole('textbox',{name:'用例名称',exact:true})).toHaveValue('未保存的修改')
  await page.unroute('**/api/datasets/*/drafts/cases/*')
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿',{exact:true}).last()).toBeVisible()
  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1',{exact:true})).toBeVisible()
  await expect(page.locator('.dataset-run-bar')).toHaveCount(0)
  await page.goto('/#tasks')
  await page.getByRole('button',{name:'新建评测任务',exact:true}).click()
  await page.getByLabel('任务评测集',{exact:true}).selectOption(datasetId)
  await expect(page.getByLabel('任务评测集版本',{exact:true})).toHaveValue('1')
  await page.getByRole('button',{name:/使用推荐的 1 个/}).click()
  await page.getByRole('button',{name:'提交评测',exact:true}).click()
  await expect(page).toHaveURL(/#tasks\//)
  await expect(page.getByRole('heading',{name:'未保存的修改',exact:true})).toBeVisible({timeout:30000})
  await expect(page.getByTestId('input-match')).toBeVisible()
  await expect(page.locator('.report-layout pre:visible').filter({hasText:'A-100'}).first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading',{name:'未保存的修改',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'← 返回任务列表',exact:true}).click()
  await expect(page).toHaveURL(/#tasks$/)
  expect(errors).toEqual([])
 }finally{if(datasetId)await request.delete('/api/datasets/'+datasetId)}
})

test('two editors cannot overwrite each other with the same draft revision',async({request})=>{
 const response=await request.post('/api/datasets',{data:{name:'并发验收-'+Date.now()}})
 expect(response.ok()).toBeTruthy()
 const created=await response.json(),id=created.dataset.id
 try{
  const source=await (await request.get('/api/datasets/loan-risk-policy')).json()
  const sample=structuredClone(source.versions.find((v:any)=>v.status==='published').cases[0])
  sample.id='concurrent-'+Date.now()
  const added=await request.post('/api/datasets/'+id+'/drafts/cases',{headers:{'If-Match':created.draft.content_sha256},data:sample})
  expect(added.ok()).toBeTruthy()
  const draft=await added.json(),headers={'If-Match':draft.content_sha256}
  const first=await request.put('/api/datasets/'+id+'/drafts/cases/'+sample.id,{headers,data:{...sample,name:'编辑者甲已保存'}})
  expect(first.ok()).toBeTruthy()
  const second=await request.put('/api/datasets/'+id+'/drafts/cases/'+sample.id,{headers,data:{...sample,name:'编辑者乙过期修改'}})
  expect(second.status()).toBe(409)
  const actual=await (await request.get('/api/datasets/'+id)).json()
  expect(actual.versions.find((v:any)=>v.status==='draft').cases[0].name).toBe('编辑者甲已保存')
 }finally{await request.delete('/api/datasets/'+id)}
})

test('service failure is visible and retry returns to real data',async({page})=>{
 await page.route('**/api/overview',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'验收：服务不可用'})}))
 await page.goto('/#overview')
 await expect(page.getByRole('alert')).toContainText('验收：服务不可用')
 await expect(page.locator('.topbar')).toContainText('服务未连接')
 await page.unroute('**/api/overview')
 await page.getByRole('button',{name:'重试',exact:true}).click()
 await expect(page.locator('.topbar')).toContainText('UX 后端已连接')
 await expect(page.getByRole('alert')).toHaveCount(0)
})
