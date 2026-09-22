import {test,expect} from '@playwright/test'
import { passAuthGate } from './auth-gate';
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await passAuthGate(page);
});

test('upstream API: XLSX import, archive restore, scheduling, rerun and lineage',async({request})=>{
 test.setTimeout(60000)
 async function body(r:any){expect(r.ok(),await r.text()).toBeTruthy();return r.json().then(j=>j.data)}
 const xlsx=await request.get('/api/datasets/loan-risk-policy/versions/1/export/xlsx')
 expect(xlsx.ok()).toBeTruthy()
 const imported=await body(await request.post('/api/datasets/import/xlsx',{multipart:{name:'联调 Excel 导入 '+Date.now(),file:{name:'cases.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:await xlsx.body()}}}))
 const id=imported.dataset.id
 await body(await request.post('/api/datasets/'+id+'/drafts/publish'))
 const run=await body(await request.post('/api/evaluations',{data:{version:'loan-agent-v2-fixed',dataset_id:id,dataset_version:1,evaluator_ids:['skill-routing'],scheduled_for:new Date(Date.now()+3000).toISOString()}}))
 expect(run.status).toBe('scheduled')
 await expect.poll(async()=> (await body(await request.get('/api/runs/'+run.run_id+'/status'))).status,{timeout:45000,intervals:[1000]}).toBe('completed')
 const graph=await body(await request.get('/api/runs/'+run.run_id+'/lineage'));expect(graph).toBeTruthy()
 const rerun=await body(await request.post('/api/runs/'+run.run_id+'/rerun'))
 await expect.poll(async()=> (await body(await request.get('/api/runs/'+rerun.run_id+'/status'))).status,{timeout:20000}).toBe('completed')
 await body(await request.delete('/api/datasets/'+id))
 expect((await body(await request.get('/api/datasets/'+id))).dataset.archived).toBeTruthy()
 await body(await request.patch('/api/datasets/'+id,{data:{archived:false}}))
 expect((await body(await request.get('/api/datasets'))).some((d:any)=>d.id===id)).toBeTruthy()
})
test('active pages do not call old extension endpoints',async({page})=>{
 const failures:string[]=[],errors:string[]=[]
 page.on('pageerror',e=>errors.push(e.message))
 page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)failures.push(r.status()+' '+r.url())})
 for(const route of ['overview','datasets','evaluators','tasks','results','experiments','optimizer','analysis','settings']){
  await page.goto('/#'+route)
  await expect(page.locator('h1').first()).toBeVisible()
  await page.waitForTimeout(500)
 }
 expect(failures).toEqual([]);expect(errors).toEqual([])
})
