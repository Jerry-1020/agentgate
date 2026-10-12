import {test,expect} from '@playwright/test'
import { passAuthGate } from './auth-gate';
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await passAuthGate(page);
});

test('unified tasks, legacy reports and optimizer return path',async({page,request})=>{
 const runs=(await (await request.get('/api/runs?limit=200')).json()).data
 const run=runs.find((r:any)=>r.status==='completed')
 expect(run).toBeTruthy()
 await page.goto('/#tasks')
 await expect(page.locator('.sidebar').getByText('结果中心',{exact:true})).toHaveCount(0)
 await expect(page.getByRole('columnheader',{name:'评估结论 / 得分'})).toBeVisible()
 await expect(page.getByLabel('评估结论筛选')).toBeVisible()
 await page.goto('/#results/'+run.id)
 await expect(page.getByRole('heading',{name:'测评任务详情',exact:true})).toBeVisible()
 await expect(page.getByRole('heading',{name:'评估结论',exact:true})).toBeVisible()
 await page.goto('/#optimizer/'+run.id)
 const back=page.getByRole('link',{name:'← 返回来源测评任务',exact:true})
 await expect(back).toHaveAttribute('href','#tasks/'+run.id)
 await page.reload()
 await back.click()
 await expect(page).toHaveURL(new RegExp('#tasks/'+run.id+'$'))
 await expect(page.getByRole('heading',{name:'评估结论',exact:true})).toBeVisible()
 await page.goto('/#optimizer')
 await expect(page.getByRole('link',{name:'返回任务列表',exact:true})).toBeVisible()
})

