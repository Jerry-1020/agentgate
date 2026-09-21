// Display guidance keyed by the backend's stable target enum. Raw evidence is preserved.
export const improvement: Record<string, [string, string, string]> = {
  skill_description: [
    '明确 Skill 职责边界',
    '修改关联 Skill 的描述，写清处理哪些请求、不处理哪些请求，补充正反例。',
    '使用原路由失败样本重跑，核对实际 Skill 与期望是否一致。',
  ],
  skill_routing: [
    '消除多个 Skill 的职责重叠',
    '对关联 Skill 的触发条件作区分，避免同一请求同时符合多个职责。',
    '重跑受影响的路由样本，并检查相邻业务场景是否退化。',
  ],
  agent_routing: [
    '修正智能体路由选择',
    '核对失败样本的期望 Skill 和实际 Skill，调整路由指令或判断条件。',
    '重跑关联样本，查看路由检查项与 Trace。',
  ],
  agent_prompt: [
    '补充智能体执行指令',
    '对照关联样本中未满足的期望，在提示词中明确处理步骤、限制和输出要求。',
    '发布新版本后重跑受影响样本，再与原任务对比。',
  ],
  retrieval_configuration: [
    '调整检索内容与规则',
    '核对失败样本需要的资料，检查知识来源、筛选规则和上下文拼接是否遗漏。',
    '检查新 Trace 的检索证据及最终回答是否满足期望。',
  ],
  tool_configuration: [
    '修正工具选择与调用参数',
    '打开关联样本，核对必需工具、禁用工具和实际参数，调整工具选择、参数构造及异常处理。',
    '重跑后检查工具选择和参数检查项；不能只看最终回答。',
  ],
  state_management: [
    '修正业务状态转换',
    '对照样本期望状态与实际状态，检查状态写入条件和执行顺序，补齐必要的转换。',
    '重跑关联样本，确认最终状态与期望一致。',
  ],
  agent_configuration: [
    '核对智能体配置',
    '结合关联失败阶段，逐项核对路由、提示词、工具与状态配置；一次修改一个明确问题。',
    '发布新版本并重跑回归样本，使用 A/B 检查是否改善及有无退化。',
  ],
};
export const stageName: Record<string, string> = {
  routing: '路由选择',
  task_understanding: '任务理解',
  planning: '执行规划',
  context_retrieval: '上下文检索',
  tool_selection: '工具选择',
  tool_arguments: '工具参数',
  tool_execution: '工具执行',
  result_interpretation: '结果理解',
  final_output: '最终输出',
  final_state: '最终状态',
  unknown: '未定位阶段',
};
