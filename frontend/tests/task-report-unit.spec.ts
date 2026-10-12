import {test,expect} from '@playwright/test'
import {scoreColumns,columnScore,sampleSummary,csvCell,traceSeconds} from '../src/views/evaluation/utils/task-report'
import type {EvaluationResult} from '../src/api/client'
const result=(id:string,score:number|null,outcome='pass')=>({evaluator_id:id,score,outcome} as EvaluationResult)
test('columns follow pinned evaluators, not a hardcoded set',()=>{
 const columns=scoreColumns({primary_evaluator_ids:['a','b'],evaluator_specs:[{id:'a',name:'自定义规则',kind:'rule'},{id:'b',name:'贷款回答可信度',kind:'llm_judge',config:{rubric:{safety:'安全',correctness:'正确'}}},{id:'dependency',name:'依赖',kind:'rule'}]})
 expect(columns.map(c=>c.name)).toEqual(['自定义规则','贷款回答可信度'])
 expect(columnScore([result('a',0)],columns[0])).toBe(0)
 expect(columnScore([result('b',.79,'fail')],columns[1])).toBe(.79)
})
test('error is not converted to pass when other evaluators return 100',()=>{
 expect(sampleSummary([result('a',1),result('b',null,'error')],['a','b'])).toEqual({outcome:'error',score:1})
})
test('absent, skipped, failed and pending results keep distinct states',()=>{
 expect(sampleSummary([],['a']).outcome).toBe('pending')
 expect(sampleSummary([result('a',null,'not_applicable')],['a'])).toEqual({outcome:'not_applicable',score:null})
 expect(sampleSummary([result('a',0,'fail')],['a']).outcome).toBe('fail')
 expect(sampleSummary([result('a',1)],['a','b']).outcome).toBe('pending')
})
test('dependent evaluator scores never contribute to primary average',()=>{
 expect(sampleSummary([result('a',.8),result('b',.6),result('child',0)],['a','b']).score).toBe(.7)
})
test('CSV quotes newlines and prevents spreadsheet formula interpretation',()=>{
 expect(csvCell('=1+2')).toBe('"\'=1+2"')
 expect(csvCell('a,"b"\nc')).toBe('"a,""b""\nc"')
 expect(csvCell(0)).toBe('"0"')
 expect(csvCell(null)).toBe('""')
})
test('duration requires actual case span timestamps',()=>{
 expect(traceSeconds(null)).toBeNull()
 expect(traceSeconds({spans:[{operation_type:'case',started_at:'2026-09-19T00:00:00Z',ended_at:'2026-09-19T00:00:02Z'}]})).toBe(2)
 expect(traceSeconds({spans:[{operation_type:'case'}]})).toBeNull()
})

test('each LLM evaluator exposes its actual score without fabricating rubric scores',()=>{
 const columns=scoreColumns({primary_evaluator_ids:['judge-a','judge-b'],evaluator_specs:[{id:'judge-a',name:'事实评估',kind:'llm_judge',config:{rubric:{facts:'事实',reason:'原因'}}},{id:'judge-b',name:'安全评估',kind:'llm_judge',config:{rubric:{safety:'安全'}}}]})
 expect(columns).toHaveLength(2)
 const results=[result('judge-b',1),result('judge-a',0,'fail')]
 expect(columns.map(c=>columnScore(results,c))).toEqual([0,1])
 expect(columnScore([],columns[0])).toBeNull()
 expect(columnScore([result('judge-a',null,'error')],columns[0])).toBeNull()
})
