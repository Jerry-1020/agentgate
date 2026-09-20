import type { EvaluatorSummary } from '../../../api/evaluations';

export const evaluatorScenarios: Record<string, string> = {
  skill_routing: '检查实际路由是否命中样本期望的 Skill。',
  required_tool: '检查业务要求的工具是否被调用。',
  forbidden_tool: '检查是否调用了样本明确禁止的工具。',
  tool_arguments: '检查工具调用参数是否符合样本约束。',
  final_output: '检查输出字段、格式及内容是否符合样本约束。',
  final_state: '检查执行结束状态是否符合业务期望。',
  policy_compliance: '检查 Trace 记录的业务策略是否得到遵守。',
  answer_quality: '依据评分标准与执行证据，通过模型评价回答质量。',
  composite: '组合规则和模型评分；阻断项失败不能被高分抵消。',
};

// 详情页说明适用条件，不代表已针对某个评测集做出推荐。
export const evaluatorRecommendationReasons: Record<string, string> = {
  skill_routing: '样本要求命中特定 Skill 时推荐使用，可发现路由错误，避免后续业务走错分支。',
  required_tool: '业务流程有必需动作时推荐使用，可发现漏调工具，例如未发起人工复核。',
  forbidden_tool: '业务有明确禁止动作时推荐使用，可发现越权或违规调用，例如高风险申请被直接批准。',
  tool_arguments: '工具参数影响业务结果时推荐使用，可发现工具选对了但传参错误的问题。',
  final_output: '对输出字段、格式或内容有明确约束时推荐使用，可检查最终回答是否满足交付要求。',
  final_state: '业务完成后有明确状态要求时推荐使用，可发现回答看似正确、实际状态却更新错误的问题。',
  policy_compliance:
    '样本定义了业务策略约束且 Trace 有对应记录时推荐使用，可检查执行过程是否遵守策略。',
  answer_quality:
    '需要判断回答的准确性、完整性等语义质量时推荐使用；应先明确评分标准，补充规则检查难以覆盖的判断。',
  composite:
    '需要汇总多个评估维度时可考虑使用；须先确认后端支持该组合实现，并明确子评估器、权重和通过条件。',
};

export function recommendEvaluators(
  evaluators: EvaluatorSummary[],
  cases: { turns: { expectations: { kind: string; mode?: string }[] }[] }[],
): string[] {
  const checks = cases.flatMap((c) => c.turns.flatMap((t) => t.expectations));
  const relevant = new Set(
    checks.map((e) =>
      e.kind === 'tool_call'
        ? e.mode === 'forbidden'
          ? 'forbidden_tool'
          : 'required_tool'
        : (
            {
              skill_route: 'skill_routing',
              tool_argument: 'tool_arguments',
              output: 'final_output',
              state: 'final_state',
              policy: 'policy_compliance',
            } as Record<string, string>
          )[e.kind],
    ),
  );
  return evaluators
    .filter((e) => e.kind === 'rule' && relevant.has(e.implementation_id))
    .map((e) => e.id);
}

export function recommendationReason(
  evaluator: EvaluatorSummary,
  cases: Parameters<typeof recommendEvaluators>[1],
): string {
  if (evaluator.kind !== 'rule')
    return (
      '当前 ' +
      cases.length +
      ' 条用例可作为模型评审输入；是否适用需结合提示词、评分维度与运行模型判断，不按规则期望数量判定。'
    );
  const count = cases.filter((item) => recommendEvaluators([evaluator], [item]).length > 0).length;
  return `当前 ${cases.length} 条用例中，${count} 条包含该规则对应的期望条件。`;
}

export function evaluatorTechnicalChecks(evaluator: EvaluatorSummary, cases: any[]): string[] {
  const checks = cases.flatMap((c) => c.turns.flatMap((t: any) => t.expectations ?? []));
  const spec: Record<string, [string, string, string]> = {
    skill_routing: [
      'skill_route',
      '读取 routing span 的 selected_skill，与每轮期望 Skill 比较。',
      '检查意图分派是否命中指定 Skill；不是对工具调用次数评分。',
    ],
    required_tool: [
      'tool_call',
      '读取 tool span 的名称，检查 required 工具是否实际出现。',
      '定位未执行的业务动作，保留对应轮次和工具证据。',
    ],
    forbidden_tool: [
      'tool_call',
      '匹配 forbidden 工具名称；一旦实际调用即记录违规。',
      '检查越权调用，不以最终回答正常替代过程合规。',
    ],
    tool_arguments: [
      'tool_argument',
      '按工具名和参数路径读取 tool span attributes。',
      '使用样本 condition 校验参数值、类型或范围。',
    ],
    final_state: [
      'state',
      '读取 Trace 的轮次状态和最终状态。',
      '按样本 path 和 condition 检查业务状态，而非回答措辞。',
    ],
    final_output: [
      'output',
      '读取轮次输出，按样本 path 提取待检查内容。',
      '依据 condition 校验字段、格式或内容。',
    ],
    policy_compliance: [
      'policy',
      '结合样本策略约束及 Trace 中的策略证据。',
      '缺少可用证据时不能推断策略已通过。',
    ],
  };
  if (evaluator.kind === 'llm_judge')
    return [
      '按已发布配置的 input_selection 读取输出、工具或完整轨迹。',
      '通过 instruction 与 rubric 生成评分和判断依据；使用配置中的模型与阈值。',
    ];
  const item = spec[evaluator.implementation_id];
  if (!item) return [evaluator.description || '依据该评估器已发布定义执行检查。'];
  const relevant = checks.filter(
    (e) =>
      e.kind === item[0] &&
      (item[0] !== 'tool_call' ||
        (evaluator.implementation_id === 'forbidden_tool'
          ? e.mode === 'forbidden'
          : e.mode !== 'forbidden')),
  );
  const names = [
    ...new Set(
      relevant.flatMap((e) =>
        [e.tool, e.condition?.expected, e.path].filter((v) => typeof v === 'string' && v),
      ),
    ),
  ];
  return [
    item[1],
    item[2],
    ...(names.length ? ['样本约束：' + names.slice(0, 10).join('、')] : []),
  ];
}
