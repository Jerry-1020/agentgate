import {test,expect} from '@playwright/test'
test('distinct checks retain identities, evidence and hypothesis links',async({page,request})=>{
 const runs=await (await request.get('/api/runs?limit=200')).json()
 const run=runs.find((r:any)=>r.status==='completed'&&r.manifest.target.ref.external_version_id==='loan-agent-v1-risky'&&r.manifest.dataset.dataset_name)
 expect(run).toBeTruthy()
 const report=await (await request.get('/api/runs/'+run.id+'/optimization')).json()
 await page.goto('/#optimizer/'+run.id)
 for(const c of report.clusters){
  const card=page.locator('#analysis-item-'+c.id)
  await expect(card).toBeVisible()
  await expect(card.locator('.toolbar>b')).toContainText(c.evaluator_id)
  await expect(card.getByText('实际失败证据',{exact:true})).toHaveCount(0)
  await expect(card.locator('.failure-evidence b')).toHaveCount(0)
  for(const m of c.members)await expect(card.locator('.failure-evidence')).toContainText(m.reason)
 }
 for(const s of report.suggestions){
  const h=report.hypotheses.find((h:any)=>s.hypothesis_ids.includes(h.id))
  await page.locator('#analysis-item-'+h.cluster_ids[0]).getByRole('button',{name:'查看关联原因与建议'}).click()
  const card=page.locator('#analysis-item-'+s.id)
  await expect(card).toBeVisible()
  for(const hid of s.hypothesis_ids){
   const h=report.hypotheses.find((h:any)=>h.id===hid)
   for(const cid of h.cluster_ids){
    const c=report.clusters.find((c:any)=>c.id===cid)
    await expect(card.locator('.toolbar>b')).toContainText(c.evaluator_id)
   }
  }
 }
 for(const h of report.hypotheses){
  await page.locator('#analysis-item-'+h.cluster_ids[0]).getByRole('button',{name:'查看关联原因与建议'}).click()
  const card=page.locator('#analysis-item-'+h.id)
  await expect(card.getByText('依据的失败聚类：',{exact:true})).toHaveCount(0)
  const links=card.getByRole('button',{name:/查看关联聚类/})
  await expect(links).toHaveCount(h.cluster_ids.length)
  if(h.cluster_ids.length){await links.first().click();await expect(page.locator('#analysis-item-'+h.cluster_ids[0])).toBeInViewport()}
 }
 const titles=await page.locator('[id^="analysis-item-failure-cluster-"] .toolbar>b').allTextContents()
 expect(new Set(titles).size).toBe(titles.length)
 const suggestion=report.suggestions[0]
 await page.locator('#analysis-item-'+report.hypotheses.find((h:any)=>suggestion.hypothesis_ids.includes(h.id)).cluster_ids[0]).getByRole('button',{name:'查看关联原因与建议'}).click()
 await page.locator('#analysis-item-'+suggestion.id).getByRole('button').filter({hasText:'待核对原因'}).click()
 await expect(page.locator('#analysis-item-'+suggestion.hypothesis_ids[0])).toBeInViewport()
})
