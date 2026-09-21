// Real-browser conformance run; no route mocking and no application changes.
import {chromium, expect} from '../frontend/node_modules/@playwright/test/index.mjs';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const out=resolve(process.argv[2] || 'runtime/bank-acceptance');
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const summary={started_at:new Date().toISOString(),runs:[],errors:[]};
const pages=[];
const save=()=>writeFile(out+'/browser.json',JSON.stringify(summary,null,2));
try {
 for(const mode of ['base','workflow','cloudshrimp']) {
  const page=await context.newPage();
  page.on('pageerror',e=>summary.errors.push({mode,error:e.message}));
  await page.goto('http://127.0.0.1:5197/#tasks');
  await page.getByRole('button',{name:'发起评测',exact:true}).click();
  const form=page.getByRole('dialog',{name:'新建评测任务'});
  await expect(form.getByRole('combobox',{name:'智能体',exact:true})).toBeEnabled();
  await form.getByRole('combobox',{name:'智能体',exact:true}).selectOption(mode);
  await expect(form.getByRole('combobox',{name:'任务评测集版本',exact:true})).toContainText('8 条样本');
  await form.getByRole('button',{name:'采用推荐并查看理由'}).click();
  const guide=form.getByRole('region',{name:'评估器选择',exact:true});
  for(const checkbox of await guide.getByRole('checkbox').all()) await checkbox.uncheck();
  for(const name of ['选择最终状态','选择必需工具','选择禁用工具']) await guide.getByRole('checkbox',{name,exact:true}).check();
  await form.getByRole('spinbutton',{name:'执行超时（秒）',exact:true}).fill('300');
  await page.screenshot({path:out+'/'+mode+'-form.png',fullPage:true});
  const created=page.waitForResponse(r=>r.url().endsWith('/api/bank-evaluations')&&r.request().method()==='POST');
  await form.getByRole('button',{name:'开始评测',exact:true}).click();
  const response=await created;
  const raw=await response.json();
  if(response.status()!==202) throw new Error(raw.message||JSON.stringify(raw));
  const body=raw.data;
  const entry={mode,run_id:body.run_id,launch:response.request().postDataJSON(),http_status:response.status(),created:body,statuses:[]};
  summary.runs.push(entry);await save();
  console.log('BROWSER_CREATED',mode,entry.run_id);
  await expect(page).toHaveURL(new RegExp('#tasks/'+entry.run_id));
  pages.push(page);
 }
 for(let round=0;round<240;round++) {
  let complete=true;
  for(let i=0;i<summary.runs.length;i++) {
   const r=summary.runs[i];if(r.finished)continue;
    const progress=await (await context.request.get('http://127.0.0.1:5197/api/runs/'+r.run_id+'/status')).json().then(j=>j.data);
   if(r.statuses.at(-1)?.status!==progress.status||r.statuses.at(-1)?.completed_cases!==progress.completed_cases) {
    r.statuses.push({...progress,observed_at:new Date().toISOString()});console.log('PROGRESS',r.mode,progress.status,progress.completed_cases);
   }
   if(['completed','failed','cancelled'].includes(progress.status)) {
    r.finished=true;r.status=progress.status;
     r.samples=await (await context.request.get('http://127.0.0.1:5197/api/runs/'+r.run_id+'/samples')).json().then(j=>j.data);
     if(progress.status==='completed')r.report=await(await context.request.get('http://127.0.0.1:5197/api/runs/'+r.run_id)).json().then(j=>j.data);
    await pages[i].reload();
    await expect(pages[i].getByRole('heading',{name:'任务结果总览',exact:true})).toBeVisible();
    await expect(pages[i].getByRole('heading',{name:'样本（8）',exact:true})).toBeVisible();
    const caseButton=pages[i].getByRole('button').filter({hasText:r.mode+'-multi'});
    await caseButton.click();
    const traceResponse=await context.request.get('http://127.0.0.1:5197/api/runs/'+r.run_id+'/traces/'+r.mode+'-multi');
    r.multiturn_trace_http_status=traceResponse.status();
    await writeFile(out+'/'+r.mode+'-multiturn-trace.json',await traceResponse.text());
    r.ui_text=await pages[i].locator('body').innerText();
    await pages[i].screenshot({path:out+'/'+r.mode+'-report.png',fullPage:true});
   } else complete=false;
  }
  await save();if(complete)break;
  await new Promise(r=>setTimeout(r,3000));
 }
 summary.finished_at=new Date().toISOString();await save();
 if(summary.runs.some(r=>!r.finished || r.status!=='completed'))throw new Error('evaluation failed or polling timed out; inspect browser.json');
 if(summary.errors.length)throw new Error('browser page errors; inspect browser.json');
 summary.case_views=[];
 for(let i=0;i<summary.runs.length;i++) {
  const r=summary.runs[i],page=pages[i];
  if(r.samples.results.some(result=>!['pass','not_applicable'].includes(result.outcome)))
   throw new Error('business evaluation did not pass; inspect report without coercing failures');
  for(const c of r.samples.run.manifest.dataset.cases) {
   await page.goto('http://127.0.0.1:5197/#tasks/'+r.run_id+'?case='+c.id);
   await expect(page.getByRole('heading',{name:'样本（8）',exact:true})).toBeVisible();
   const response=await context.request.get('http://127.0.0.1:5197/api/runs/'+r.run_id+'/traces/'+c.id);
   expect(response.ok()).toBeTruthy();
    const trace=await response.json().then(j=>j.data);
   await expect(page.getByTestId('actual-output')).toHaveCount(c.turns.length);
   for(let n=0;n<c.turns.length;n++) {
    const turn=trace.turn_outcomes[c.turns[n].id];
    await expect.poll(async()=>JSON.parse(await page.getByTestId('actual-output').nth(n).innerText())).toEqual(turn.output);
    await expect.poll(async()=>JSON.parse(await page.getByTestId('sample-input').nth(n).innerText())).toEqual(turn.input);
   }
   await page.getByRole('tab',{name:'执行 Trace',exact:true}).click();
   await expect.poll(async()=>JSON.parse(await page.getByRole('tabpanel').innerText())).toEqual(trace);
   summary.case_views.push({mode:r.mode,case_id:c.id,input_output_trace_match:true});
  }
 }
 if(summary.errors.length)throw new Error('browser page errors; inspect browser.json');
 summary.accepted=true;await save();
 console.log('FINISHED',summary.runs.map(r=>({mode:r.mode,id:r.run_id,status:r.status})),summary.errors);
} catch(e) {summary.errors.push({harness_error:String(e)});for(const r of summary.runs)delete r.page;await save();throw e;}
finally {await browser.close();}
