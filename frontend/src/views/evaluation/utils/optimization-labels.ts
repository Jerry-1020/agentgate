// Localized descriptions of the server's deterministic recommendation targets.
const targets: Record<string, [string, string]> = {
  skill_description: [
    '明确 Skill 路由边界',
    '核对相关 Skill 的描述与路由边界，然后重新测评受影响的用例。',
  ],
  skill_routing: [
    '区分重叠的 Skill 路由',
    '核对相关 Skill 描述，使路由边界互斥，然后重新测评受影响的用例。',
  ],
  agent_routing: [
    '修正智能体路由行为',
    '针对期望与实际 Skill 不一致的证据，核对路由提示词与决策逻辑，然后重新测评受影响的用例。',
  ],
  agent_prompt: [
    '完善智能体提示词',
    '核对关联失败阶段的提示词指令，明确预期行为，然后重新测评受影响的用例。',
  ],
  retrieval_configuration: [
    '修正上下文检索行为',
    '核对检索来源、选择规则与上下文组装，然后重新测评受影响的用例。',
  ],
  tool_configuration: [
    '修正智能体工具使用行为',
    '核对工具选择、参数构造与执行处理，然后重新测评受影响的用例。',
  ],
  state_management: [
    '修正智能体状态处理',
    '核对状态流转逻辑与最终状态要求，然后重新测评受影响的用例。',
  ],
  agent_configuration: [
    '核对智能体配置',
    '核对关联失败阶段的配置，每次进行范围明确的修改，然后重新测评受影响的用例。',
  ],
};
export function chineseSuggestion(s: {
  target: string;
  target_id?: string;
  title: string;
  recommendation: string;
}) {
  const content = targets[s.target];
  return content
    ? { title: content[0] + (s.target_id ? ' · ' + s.target_id : ''), recommendation: content[1] }
    : { title: s.title, recommendation: s.recommendation };
}
