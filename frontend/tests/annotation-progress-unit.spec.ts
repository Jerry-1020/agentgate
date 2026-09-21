import {test,expect} from '@playwright/test'
import {annotationProgress} from '../src/views/evaluation/utils/annotation-progress'
import {chineseEvaluatorText,ruleExamples} from '../src/views/evaluation/utils/evaluator-display'
const calculate=(records:any,skipped=false)=>annotationProgress(['t1','t2'],records,'run/case',['accuracy','safety'],0,5,skipped)
test('annotation progress requires every configured dimension and accepts zero',()=>{
 expect(calculate({'run/case/t1':{scores:{accuracy:0,safety:5}}})).toEqual({done:1,total:2,pending:1,ignored:0,status:'partial'})
 expect(calculate({'run/case/t1':{scores:{accuracy:5}}}).done).toBe(0)
 expect(calculate({'run/case/t1':{scores:{accuracy:6,safety:5}}}).done).toBe(0)
 expect(calculate({'run/case/t1':{scores:{accuracy:NaN,safety:5}}}).done).toBe(0)
})
test('skip is reversible without erasing existing annotation',()=>{
 const records={'run/case/t1':{scores:{accuracy:4,safety:5}}}
 expect(calculate(records,true)).toEqual({done:1,total:2,pending:0,ignored:1,status:'skipped'})
 expect(calculate(records).status).toBe('partial')
})
test('completion never inferred from empty or another run trace',()=>{
 expect(calculate({'another/case/t1':{scores:{accuracy:5,safety:5}}}).done).toBe(0)
 expect(annotationProgress([],{},'run/case',['accuracy'],0,5).status).toBe('pending')
 expect(calculate({'run/case/t1':{scores:{accuracy:5,safety:5}},'run/case/t2':{scores:{accuracy:4,safety:4}}}).status).toBe('done')
})
test('known instructions are localized without rewriting custom prompts',()=>{
 expect(chineseEvaluatorText('The answer is direct and contains no material unrelated content.')).toContain('直接回应问题')
 expect(chineseEvaluatorText('Custom prompt: do not change me.')).toBe('Custom prompt: do not change me.')
 expect(ruleExamples.skill_routing.failed).toContain('缺少路由决策')
})
