import {test,expect} from '@playwright/test'
import { passAuthGate } from './auth-gate';
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await passAuthGate(page);
});

test('September 15 UI: menu, version deletion boundaries, graph and evaluator copy',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/#datasets')
 await expect(page.getByRole('button',{name:'按 ID 打开',exact:true})).toHaveCount(0)
 await expect(page.locator('.tile-icon')).toHaveCount(0)
 const card=page.locator('.dataset-tile').first()
 await card.getByRole('button',{name:'更多操作',exact:false}).click()
 await expect(page.getByRole('menuitem',{name:'查看详情',exact:true})).toBeVisible()
 await page.getByRole('menuitem',{name:'删除',exact:true}).click()
 const deletion=page.getByRole('dialog',{name:'删除测评集版本'})
 await expect(deletion.getByLabel('待删除版本')).toBeVisible()
 await expect(deletion.getByRole('button',{name:'删除草稿',exact:true})).toBeDisabled()
 await deletion.getByRole('button',{name:'取消',exact:true}).click()
 await page.goto('/#datasets/loan-risk-policy')
 await page.getByTestId('version-published-1').click()
 await expect(page.getByTestId('run-single-case')).toHaveCount(0)
 await expect(page.getByTestId('continue-draft')).toHaveCount(0)
 await page.getByTestId('run-dataset-version').click()
 const dialog=page.getByRole('dialog',{name:'新建测评任务'})
 await expect(dialog.getByRole('button',{name:'推荐评估器',exact:true})).toBeVisible()
 await dialog.locator('summary').filter({hasText:'查看所选智能体'}).click()
 await expect(dialog.getByLabel('Agent 与 Skill 关联图')).toBeVisible()
 await expect(dialog.getByLabel('Agent 与 Skill 关联图').getByText('Loan Approval',{exact:true})).toBeVisible()
 await page.screenshot({path:'../runtime/ux-0915-agent-graph.png'})
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.goto('/#evaluators/skill-routing')
 await expect(page.getByRole('button',{name:'复制为自定义草稿',exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'禁用',exact:true})).toBeEnabled()
 await page.getByRole('button',{name:'复制为自定义草稿',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'新建评估器草稿'})).toBeVisible()
 expect(errors).toEqual([])
})
