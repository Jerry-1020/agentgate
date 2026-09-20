import type { EvaluatorSummary } from './api'

export const evaluatorScenarios:Record<string,string>={
 skill_routing:'检查实际路由是否命中样本期望的 Skill。',
 required_tool:'检查业务要求的工具是否被调用。',
 forbidden_tool:'检查是否调用了样本明确禁止的工具。',
 tool_arguments:'检查工具调用参数是否符合样本约束。',
 final_output:'检查输出字段、格式及内容是否符合样本约束。',
 final_state:'检查执行结束状态是否符合业务期望。',
 policy_compliance:'检查 Trace 记录的业务策略是否得到遵守。',
 answer_quality:'依据评分标准与执行证据，通过模型评价回答质量。',
 composite:'组合规则和模型评分；阻断项失败不能被高分抵消。',
}

// 详情页说明适用条件，不代表已针对某个评测集做出推荐。
export const evaluatorRecommendationReasons:Record<string,string>={
 skill_routing:'样本要求命中特定 Skill 时推荐使用，可发现路由错误，避免后续业务走错分支。',
 required_tool:'业务流程有必需动作时推荐使用，可发现漏调工具，例如未发起人工复核。',
 forbidden_tool:'业务有明确禁止动作时推荐使用，可发现越权或违规调用，例如高风险申请被直接批准。',
 tool_arguments:'工具参数影响业务结果时推荐使用，可发现工具选对了但传参错误的问题。',
 final_output:'对输出字段、格式或内容有明确约束时推荐使用，可检查最终回答是否满足交付要求。',
 final_state:'业务完成后有明确状态要求时推荐使用，可发现回答看似正确、实际状态却更新错误的问题。',
 policy_compliance:'样本定义了业务策略约束且 Trace 有对应记录时推荐使用，可检查执行过程是否遵守策略。',
 answer_quality:'需要判断回答的准确性、完整性等语义质量时推荐使用；应先明确评分标准，补充规则检查难以覆盖的判断。',
 composite:'需要汇总多个评估维度时可考虑使用；须先确认后端支持该组合实现，并明确子评估器、权重和通过条件。',
}

export function recommendEvaluators(
 evaluators:EvaluatorSummary[],
 cases:{turns:{expectations:{kind:string;mode?:string}[]}[]}[],
):string[]{
 const checks=cases.flatMap(c=>c.turns.flatMap(t=>t.expectations))
 const relevant=new Set(checks.map(e=>e.kind==='tool_call'
  ?(e.mode==='forbidden'?'forbidden_tool':'required_tool')
  :({skill_route:'skill_routing',tool_argument:'tool_arguments',output:'final_output',state:'final_state',policy:'policy_compliance'} as Record<string,string>)[e.kind]))
 return evaluators.filter(e=>e.kind==='rule'&&relevant.has(e.implementation_id)).map(e=>e.id)
}

export function recommendationReason(evaluator:EvaluatorSummary,cases:Parameters<typeof recommendEvaluators>[1]):string{
 const count=cases.filter(item=>recommendEvaluators([evaluator],[item]).length>0).length
 return `当前 ${cases.length} 条用例中，${count} 条包含该规则对应的期望条件。`
}
