import {test,expect,type Page} from '@playwright/test'
import {seedSettings,visibleConnections,connectionState,validateConnection,validateCredential,settingsCapability} from '../src/views/evaluation/utils/settings-preview'

test('preview model scope is the intersection of model and credential authorization',()=>{
 const catalog=seedSettings(),model=catalog.connections[0]!,key=catalog.credentials[0]!
 expect(visibleConnections(catalog,'demo-research')).toHaveLength(1)
 expect(visibleConnections(catalog,'demo-quality')).toHaveLength(1)
 expect(visibleConnections(catalog,'unknown')).toHaveLength(0)
 key.enabled=false
 expect(connectionState(model,catalog)).toBe('credential_disabled')
 expect(visibleConnections(catalog,'demo-quality')).toHaveLength(0)
 key.enabled=true;model.allowedTeamIds=[]
 expect(visibleConnections(catalog,'demo-quality')).toHaveLength(0)
 model.allowedTeamIds=['missing']
 expect(connectionState(model,catalog)).toBe('invalid')
 expect(settingsCapability).toEqual({persistentModelManagement:false,teamAuthorization:false,connectionTest:false})
})

test('connection validation rejects unsafe address metadata and incompatible credentials',()=>{
 const catalog=seedSettings(),model={...catalog.connections[0]!}
 expect(validateConnection(model,catalog)).toBe('')
 for(const baseUrl of ['http://example.com/v1','https://name:secret@example.com/v1','https://example.com/v1?key=demo','https://example.com/v1#secret','not-a-url']){
  expect(validateConnection({...model,baseUrl},catalog)).toContain('HTTPS')
 }
 expect(validateConnection({...model,baseUrl:'https://example.com/v1/chat/completions/'},catalog)).toContain('不要包含')
 expect(validateConnection({...model,id:'new'},catalog)).toContain('同名')
 expect(validateConnection({...model,credentialId:'absent'},catalog)).toContain('匹配')
 expect(validateConnection({...model,allowedTeamIds:['missing']},catalog)).toContain('授权范围')
 catalog.credentials[0]!.enabled=false
 expect(validateConnection(model,catalog)).toContain('已停用')
})

test('credential authorization cannot invalidate an existing connection even if disabled',()=>{
 const catalog=seedSettings(),key={...catalog.credentials[0]!,allowedTeamIds:[]}
 expect(validateCredential(key,catalog)).toContain('先调整')
 catalog.connections[0]!.enabled=false
 expect(validateCredential(key,catalog)).toContain('先调整')
 catalog.connections[0]!.allowedTeamIds=[]
 expect(validateCredential(key,catalog)).toBe('')
 expect(validateCredential({...key,id:'new'},catalog)).toContain('同名')
 expect(JSON.stringify(catalog)).not.toContain('api_key')
 expect(JSON.stringify(catalog)).not.toContain('demo-key-for-ui-preview')
})

async function start(page:Page){
 await page.route('**/api/configured-models',route=>route.fulfill({json:[]}))
 await page.goto('/#settings')
 await expect(page.getByRole('heading',{name:'配置',exact:true})).toBeVisible()
}
async function confirm(page:Page){
 const box=page.getByRole('dialog',{name:'确认预览操作',exact:true})
 await box.getByRole('button',{name:'确认',exact:true}).click()
 await expect(box).not.toBeVisible()
}
async function save(page:Page){
 const dialog=page.getByRole('dialog').filter({has:page.getByRole('button',{name:'保存预览',exact:true})})
 await dialog.getByRole('button',{name:'保存预览',exact:true}).click()
 await expect(dialog).not.toBeVisible()
}
async function teamView(page:Page,id='demo-quality'){
 await page.getByRole('tab',{name:'团队授权',exact:true}).click()
 await page.getByTestId('team-'+id).getByRole('button',{name:'预览成员可选模型'}).click()
 return page.getByRole('dialog',{name:'团队使用视图（预览）',exact:true})
}

test('full preview creation chain keeps metadata in memory and never sends secrets or writes',async({page})=>{
 const writes:string[]=[],external:string[]=[]
 page.on('request',r=>{
  if(r.url().includes('/api/')&&!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(r.url())
  if(r.url().startsWith('https://model.example.com'))external.push(r.url())
 })
 await start(page)
 const initialStorage=await page.evaluate(()=>({local:{...localStorage},session:{...sessionStorage}}))
 await page.getByRole('tab',{name:'团队授权',exact:true}).click()
 await page.getByRole('button',{name:'新增团队',exact:true}).click()
 await page.getByLabel('团队名称',{exact:true}).fill('前端验收团队')
 await save(page)
 const team=page.locator('.team-grid article').filter({hasText:'前端验收团队'})
 await expect(team).toBeVisible()
 const id=(await team.getAttribute('data-testid'))!.slice(5)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await page.getByRole('button',{name:'新增 API Key',exact:true}).click()
 await page.getByLabel('凭据名称',{exact:true}).fill('前端验收凭据')
 await page.getByLabel('凭据所属团队',{exact:true}).selectOption(id)
 await page.getByLabel('示例 API Key',{exact:true}).fill('not-an-actual-secret-fixture')
 await expect(page.getByLabel('示例 API Key',{exact:true})).toHaveValue('')
 await expect(page.getByRole('alert').filter({hasText:'请勿输入真实密钥'})).toBeVisible()
 await page.getByRole('button',{name:'填入示例密钥',exact:true}).click()
 await expect(page.getByLabel('示例 API Key',{exact:true})).toHaveAttribute('type','password')
 await save(page)
 await expect(page.locator('tr').filter({hasText:'前端验收凭据'})).toContainText('不含真实密钥')
 await page.getByRole('tab',{name:'模型连接',exact:true}).click()
 await page.getByRole('button',{name:'新增模型连接',exact:true}).click()
 await page.getByLabel('连接名称',{exact:true}).fill('团队专用评分')
 await page.getByLabel('模型所属团队',{exact:true}).selectOption(id)
 await page.getByLabel('模型 ID',{exact:true}).fill('example-quality')
 await page.getByLabel('BaseURL',{exact:true}).fill('https://model.example.com/v1')
 await page.getByLabel('模型 API Key',{exact:true}).selectOption({label:'前端验收凭据'})
 await save(page)
 const view=await teamView(page,id)
 await expect(view.getByLabel('成员可选模型').locator('option')).toHaveText(['请选择','团队专用评分 · example-quality'])
 await view.getByLabel('成员可选模型').selectOption({label:'团队专用评分 · example-quality'})
 await expect(view).not.toContainText('demo-key-for-ui-preview')
 await view.getByRole('button',{name:'关闭',exact:true}).click()
 // SPA navigation retains the preview but never mixes it into the live evaluator model catalog.
 await page.getByRole('link',{name:'评估器',exact:true}).click()
 await page.getByRole('button',{name:'新建评估器',exact:true}).click()
 await page.getByLabel('评估器类型').selectOption('llm_judge')
 expect(await page.getByLabel('评估模型').locator('option').allTextContents()).not.toEqual(expect.arrayContaining([expect.stringContaining('example-quality')]))
 page.once('dialog',d=>d.accept())
 await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click()
 await page.getByRole('link',{name:'配置',exact:true}).click()
 await expect(page.locator('tr').filter({hasText:'团队专用评分'})).toBeVisible()
 expect(await page.evaluate(()=>({local:{...localStorage},session:{...sessionStorage}}))).toEqual(initialStorage)
 expect(await page.content()).not.toContain('demo-key-for-ui-preview')
 expect(writes).toEqual([]);expect(external).toEqual([])
 await page.reload()
 await expect(page.locator('tr').filter({hasText:'团队专用评分'})).toHaveCount(0)
 await expect(page.getByTestId('connection-demo-model-quality')).toBeVisible()
})

test('disabling a referenced credential removes models from the member picker and restoring reinstates them',async({page})=>{
 await start(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 const row=page.getByTestId('credential-demo-key-shared')
 await row.getByRole('button',{name:'停用',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'确认预览操作'})).toContainText('关联的 1 个模型')
 await confirm(page)
 await page.getByRole('tab',{name:'模型连接',exact:true}).click()
 await expect(page.getByTestId('connection-demo-model-quality')).toContainText('凭据已停用')
 let view=await teamView(page)
 await expect(view.getByLabel('成员可选模型').locator('option')).toHaveText(['请选择'])
 await expect(view).toContainText('当前团队没有预览可用模型')
 await view.getByRole('button',{name:'关闭',exact:true}).click()
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await row.getByRole('button',{name:'启用',exact:true}).click()
 await confirm(page)
 view=await teamView(page)
 await expect(view.getByLabel('成员可选模型').locator('option')).toHaveText(['请选择','通用质量评分（示例） · example-judge'])
})

test('scope edits prevent orphaned permissions and revocation takes effect after the model grant is removed',async({page})=>{
 await start(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await page.getByTestId('credential-demo-key-shared').getByRole('button',{name:'编辑与授权'}).click()
 let dialog=page.getByRole('dialog',{name:'编辑凭据与授权',exact:true})
 await dialog.getByRole('checkbox',{name:'质量评测团队（演示）'}).uncheck()
 await dialog.getByRole('button',{name:'保存预览'}).click()
 await expect(dialog.getByRole('alert')).toContainText('先调整对应模型')
 page.once('dialog',d=>d.accept())
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.getByRole('tab',{name:'模型连接',exact:true}).click()
 await page.getByTestId('connection-demo-model-quality').getByRole('button',{name:'编辑与授权'}).click()
 dialog=page.getByRole('dialog',{name:'编辑模型连接与授权',exact:true})
 await dialog.getByRole('checkbox',{name:'质量评测团队（演示）'}).uncheck()
 await save(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await page.getByTestId('credential-demo-key-shared').getByRole('button',{name:'编辑与授权'}).click()
 await page.getByRole('dialog').getByRole('checkbox',{name:'质量评测团队（演示）'}).uncheck()
 await save(page)
 const view=await teamView(page)
 await expect(view.getByLabel('成员可选模型').locator('option')).toHaveText(['请选择'])
})

test('referenced key and team deletion are blocked, then deleting the connection allows key deletion',async({page})=>{
 await start(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 const row=page.getByTestId('credential-demo-key-shared')
 await row.getByRole('button',{name:'删除',exact:true}).click()
 await expect(page.getByText('仍被 1 个模型引用，请先更换模型凭据或删除对应预览连接。',{exact:true})).toBeVisible()
 await expect(row).toBeVisible()
 await page.getByRole('tab',{name:'团队授权',exact:true}).click()
 await page.getByTestId('team-demo-research').getByRole('button',{name:'删除',exact:true}).click()
 await expect(page.getByText(/该团队仍有配置或授权/)).toBeVisible()
 await page.getByRole('tab',{name:'模型连接',exact:true}).click()
 await page.getByTestId('connection-demo-model-quality').getByRole('button',{name:'删除',exact:true}).click()
 await confirm(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await row.getByRole('button',{name:'删除',exact:true}).click()
 await confirm(page)
 await expect(row).toHaveCount(0)
 await page.getByRole('tab',{name:'团队授权',exact:true}).click()
 await page.getByTestId('team-demo-research').getByRole('button',{name:'删除',exact:true}).click()
 await confirm(page)
 await expect(page.getByTestId('team-demo-research')).toHaveCount(0)
})

test('key replacement preserves model references and clears the example input',async({page})=>{
 await start(page)
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 const row=page.getByTestId('credential-demo-key-shared')
 await row.getByRole('button',{name:'替换密钥',exact:true}).click()
 await page.getByRole('button',{name:'保存预览'}).click()
 await expect(page.getByRole('dialog').getByRole('alert')).toContainText('请填入 demo-')
 await page.getByRole('button',{name:'填入示例密钥'}).click()
 await save(page)
 await expect(row).toContainText('修订 2')
 await expect(row).toContainText('通用质量评分（示例）')
 await row.getByRole('button',{name:'替换密钥',exact:true}).click()
 await expect(page.getByLabel('示例 API Key')).toHaveValue('')
 await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click()
 await page.getByRole('tab',{name:'模型连接',exact:true}).click()
 await expect(page.getByTestId('connection-demo-model-quality')).toContainText('预览启用')
})

test('connection samples show four feedback states without changing real verification or making requests',async({page})=>{
 const external:string[]=[]
 page.on('request',r=>{if(r.url().includes('model.example.com'))external.push(r.url())})
 await start(page)
 await page.getByTestId('connection-demo-model-quality').getByRole('button',{name:'测试结果样例'}).click()
 const dialog=page.getByRole('dialog',{name:'连接测试结果样例',exact:true})
 for(const [value,title] of [['success','示例：连接成功'],['unauthorized','示例：凭据无效（401）'],['missing','示例：模型不可用（404）'],['timeout','示例：请求超时']]){
  await dialog.getByLabel('测试结果场景').selectOption(value)
  await expect(dialog.getByText(title,{exact:true})).toBeVisible()
 }
 await expect(dialog.getByRole('button',{name:'真实连接测试 · 待接入'})).toBeDisabled()
 await dialog.getByRole('button',{name:'关闭',exact:true}).click()
 await expect(page.getByTestId('connection-demo-model-quality')).toContainText('未进行真实连接测试')
 expect(external).toEqual([])
})

test('cancel and route navigation protect unsaved settings form changes',async({page})=>{
 await start(page)
 await page.getByRole('button',{name:'新增模型连接',exact:true}).click()
 await page.getByLabel('连接名称',{exact:true}).fill('未保存连接')
 page.once('dialog',d=>d.dismiss())
 await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click()
 await expect(page.getByLabel('连接名称',{exact:true})).toHaveValue('未保存连接')
 page.once('dialog',d=>d.dismiss())
 await page.evaluate(()=>{location.hash='datasets'})
 await expect(page).toHaveURL(/#settings$/)
 await expect(page.getByLabel('连接名称',{exact:true})).toHaveValue('未保存连接')
 page.once('dialog',d=>d.accept())
 await page.evaluate(()=>{location.hash='datasets'})
 await expect(page).toHaveURL(/#datasets$/)
 await page.getByRole('link',{name:'配置',exact:true}).click()
 await expect(page.locator('tr').filter({hasText:'未保存连接'})).toHaveCount(0)
})

test('live catalog read failures and recovery remain separate from preview changes',async({page})=>{
 await page.route('**/api/configured-models',r=>r.fulfill({status:503,json:{detail:'not configured'}}))
 await page.goto('/#settings')
 await expect(page.getByRole('alert').filter({hasText:'无法读取模型配置'})).toBeVisible()
 await expect(page.getByTestId('connection-demo-model-quality')).toBeVisible()
 await page.route('**/api/configured-models',r=>r.fulfill({json:[{provider_id:'live-fixture',model_id:'live-judge'}]}))
 await page.getByRole('button',{name:'刷新',exact:true}).click()
 await expect(page.locator('.live-models')).toContainText('live-judge')
 await expect(page.locator('.live-models')).toContainText('服务端配置 · 只读')
 await expect(page.locator('.live-models')).not.toContainText('example-judge')
})

test('settings tables and dialogs fit desktop viewport sizes',async({page})=>{
 await start(page)
 await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'})
 for(const width of [1440,1280]){
  await page.setViewportSize({width,height:1000})
  for(const name of ['模型连接','API Key','团队授权']){
   await page.getByRole('tab',{name,exact:true}).click()
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
  }
  await page.getByRole('tab',{name:'模型连接',exact:true}).click()
  await page.getByRole('button',{name:'新增模型连接',exact:true}).click()
  await expect(page.getByRole('dialog').getByLabel('连接名称',{exact:true})).toBeVisible()
  const rect=await page.getByRole('dialog').boundingBox()
  expect(rect).not.toBeNull()
  expect(rect!.x).toBeGreaterThanOrEqual(0)
  expect(rect!.x+rect!.width).toBeLessThanOrEqual(width)
  expect(rect!.y+rect!.height).toBeLessThanOrEqual(1000)
  await page.screenshot({path:'../runtime/visual-review/settings-connection-'+width+'.png',fullPage:true,animations:'disabled'})
  await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
 }
 await page.screenshot({path:'../runtime/visual-review/settings-models.png',fullPage:true})
 await page.getByRole('tab',{name:'API Key',exact:true}).click()
 await page.screenshot({path:'../runtime/visual-review/settings-keys.png',fullPage:true})
 await page.getByRole('tab',{name:'团队授权',exact:true}).click()
 await page.screenshot({path:'../runtime/visual-review/settings-teams.png',fullPage:true})
})
