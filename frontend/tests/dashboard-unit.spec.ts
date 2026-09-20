import {test,expect} from '@playwright/test'
import {periodRuns,targetDistribution,sampleDistribution,averageScore,recentEvents,taskTitle} from '../src/views/evaluation/utils/dashboard-data'
const run=(id:string,status='completed',type='agent'):any=>({id,status,created_at:'2026-09-19T08:00:00+08:00',started_at:null,completed_at:null,manifest:{primary_evaluator_ids:['rule'],evaluator_specs:[{id:'rule',kind:'rule'}],target:{display_name:'Loan Agent',ref:{source_id:'demo',target_type:type,external_target_id:'loan',external_version_id:'v1'}},dataset:{cases:[{id:'c1'},{id:'c2'},{id:'c3'}]}}})
test('dashboard filters local calendar periods and target types',()=>{
 const now=new Date('2026-09-20T12:00:00+08:00'),records=[run('a'),run('b','completed','workflow')]
 expect(periodRuns(records,1,'',now)).toHaveLength(0)
 expect(periodRuns(records,7,'agent',now).map(r=>r.id)).toEqual(['a'])
 expect(periodRuns([...records,{...run('future'),created_at:'2026-10-01'}],30,'',now)).toHaveLength(2)
})
test('target distribution deduplicates versions, retaining source and type boundaries',()=>{
 expect(targetDistribution([run('a'),run('b'),run('c','completed','workflow')]).map(r=>r.value)).toEqual([1,1])
})
test('sample progress does not infer success from task completion or failure',()=>{
 const records=[run('a'),run('b','failed'),run('c','running')]
 const values=sampleDistribution(records,{b:{total_cases:3,completed_cases:1} as any,c:{total_cases:3,completed_cases:1} as any})
 expect(Object.fromEntries(values.map(v=>[v.key,v.value]))).toEqual({processed:2,running:2,pending:0,failed:2,cancelled:0,unknown:3})
 expect(values.reduce((sum,v)=>sum+v.value,0)).toBe(9)
})
test('average is unavailable when reports are missing, and evaluator errors excluded',()=>{
 const report=(score:number,reason='threshold_met'):any=>({metrics:[{level:'overall',score}],release_gate:{reason_code:reason}})
 expect(averageScore([run('a'),run('b')],{a:report(1)})).toBeNull()
 expect(averageScore([run('a'),run('b')],{a:report(0),b:report(1,'evaluator_error')})).toBe(0)
})
test('events use actual timestamps; readable title does not concatenate dataset jargon',()=>{
 const record=run('e7523744-1234');expect(recentEvents([record]).map(e=>e.label)).toEqual(['创建任务'])
 expect(taskTitle(record)).toBe('贷款智能体 · 规则评测 · e7523744')
 expect(taskTitle(record,'ab')).toContain('A/B 对比')
})
