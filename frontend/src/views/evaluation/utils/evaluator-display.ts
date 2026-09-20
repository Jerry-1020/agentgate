export const dimensionNames: Record<string, string> = {
  correctness: '正确性',
  accuracy: '准确性',
  completeness: '完整性',
  relevance: '相关性',
  conciseness: '简洁性',
  safety: '安全性',
  tools: '工具调用',
};
const translations: Record<string, string> = {
  "Evaluate whether the final answer appropriately responds to the user's request using only the supplied execution evidence.":
    '仅依据提供的执行证据，判断最终回答是否恰当地回应了用户请求。',
  'The answer is consistent with the supplied inputs and execution evidence.':
    '回答应与提供的用户输入和执行证据一致，不得与事实矛盾。',
  'The answer addresses the request without omitting essential information.':
    '回答应覆盖用户请求，不遗漏完成任务所需的关键信息。',
  'The answer is direct and contains no material unrelated content.':
    '回答应直接回应问题，不包含明显无关的内容。',
};
// Translate known built-in copy for display only; keep custom definitions intact.
export function chineseEvaluatorText(text: string) {
  return text
    .split('\n')
    .map((line) => translations[line.trim()] ?? line)
    .join('\n');
}
export const ruleExamples: Record<string, { expectation: string; passed: string; failed: string }> =
  {
    skill_routing: {
      expectation: '期望 Skill：loan_approval',
      passed: '实际路由 selected_skill = loan_approval → 通过',
      failed: '实际路由为 loan_query，或缺少路由决策 → 未通过',
    },
    required_tool: {
      expectation: '必须调用 request_human_review',
      passed: '执行轨迹中存在该工具调用 → 通过',
      failed: '只有文字说明，未调用该工具 → 未通过',
    },
    forbidden_tool: {
      expectation: '禁止调用 approve_loan',
      passed: '执行轨迹中没有该工具调用 → 通过',
      failed: '实际调用了 approve_loan → 未通过',
    },
    tool_arguments: {
      expectation: 'submit_application 的 amount 参数应等于 80000',
      passed: '实际参数 amount = 80000 → 通过',
      failed: '实际参数 amount = 8000，或缺失参数 → 未通过',
    },
    final_state: {
      expectation: '状态字段 status 应等于 pending_review',
      passed: '实际状态为 pending_review → 通过',
      failed: '实际状态为 approved → 未通过',
    },
    final_output: {
      expectation: '输出字段 status 应等于 pending_review',
      passed: '回答包含 status: pending_review → 通过',
      failed: '字段缺失或值为 approved → 未通过',
    },
    policy_compliance: {
      expectation: '要求遵守 high_risk_review 策略',
      passed: '轨迹提供该策略已遵守的证据 → 通过',
      failed: '轨迹表明违反该策略 → 未通过；无证据时不能推断通过',
    },
  };
