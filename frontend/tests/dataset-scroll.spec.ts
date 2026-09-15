import {test,expect} from '@playwright/test'

test('dataset editor grows with all turns and the page can reach every field without clipping',async({page,request})=>{
 const response=await request.post('/api/datasets/loan-risk-policy/copy',{data:{name:'滚动验收-'+Date.now(),source_version:1}})
 expect(response.ok()).toBeTruthy()
 const created=await response.json(),id=created.dataset.id
 try{
  await page.goto('/#datasets/'+id)
  await expect(page.getByTestId('case-name')).toBeVisible()
  await page.getByTestId('add-turn').click()
  await page.getByTestId('add-turn').click()
  await expect(page.getByTestId('turn-input-2')).toHaveCount(1)
  for(const viewport of [{width:1440,height:1000},{width:1280,height:720},{width:760,height:900}]){
   await page.setViewportSize(viewport)
   await page.evaluate(()=>window.scrollTo(0,0))
   const editor=page.locator('.case-editor-panel')
   expect(await page.locator('.dataset-layout').evaluate(e=>getComputedStyle(e).maxHeight)).toBe('none')
   expect(await editor.evaluate(e=>e.scrollHeight<=e.clientHeight+2)).toBeTruthy()
   await page.getByTestId('turn-output-2').scrollIntoViewIfNeeded()
   await expect(page.getByTestId('turn-output-2')).toBeInViewport()
   expect(await page.evaluate(()=>window.scrollY)).toBeGreaterThan(0)
   const extra=page.locator('.other-expectations').nth(2)
   if(!await extra.evaluate(e=>e.hasAttribute('open')))await extra.locator('summary').click()
   await page.getByTestId('policy-rules-2').scrollIntoViewIfNeeded()
   await expect(page.getByTestId('policy-rules-2')).toBeInViewport()
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
   if(viewport.width>760)await expect(page.getByTestId('save-case')).toBeInViewport()
   await page.screenshot({path:'../runtime/visual-review/dataset-scroll-'+viewport.width+'.png',animations:'disabled'})
  }
  await page.getByTestId('turn-input-1').fill('{"question":"第二轮输入"}')
  await page.getByTestId('turn-input-2').fill('{"question":"第三轮输入可完整编辑"}')
  await page.getByTestId('turn-output-2').fill('"第三轮期望输出"')
  const saving=page.waitForResponse(r=>r.url().includes('/drafts/cases/')&&r.request().method()==='PUT')
  await page.getByTestId('save-case').click()
  const response=await saving
  expect(response.ok(),await response.text()).toBeTruthy()
  await expect(page.getByText('用例已保存到草稿',{exact:true})).toBeVisible()
  const saved=await(await request.get('/api/datasets/'+id+'/drafts/current')).json()
  expect(saved.cases[0].turns).toHaveLength(3)
  expect(saved.cases[0].turns[2].input).toEqual({question:'第三轮输入可完整编辑'})
 }finally{
  await request.delete('/api/datasets/'+id+'/unpublished')
 }
})
