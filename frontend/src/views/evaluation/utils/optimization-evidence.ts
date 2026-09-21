import { improvement, stageName } from './optimization-copy';
type Row = Record<string, any>;
export function relatedClusters(key: string, row: Row, data: Row | null): Row[] {
  const clusters: Row[] = data?.clusters ?? [];
  if (key === 'clusters') return [row];
  const ids =
    key === 'hypotheses'
      ? (row.cluster_ids ?? [])
      : (data?.hypotheses ?? [])
          .filter((h: Row) => (row.hypothesis_ids ?? []).includes(h.id))
          .flatMap((h: Row) => h.cluster_ids ?? []);
  return clusters.filter((c) => ids.includes(c.id));
}
const checks: Record<string, [string, string, string, string]> = {
  forbidden_tool_compliance: [
    '调用了禁用工具',
    '限制禁用工具的调用路径',
    '根据下列失败证据，核对被禁止工具的触发条件，在对应业务分支阻止调用。',
    '重跑关联样本，确认禁用工具不再出现，并检查其他必需动作是否执行。',
  ],
  tool_coverage: [
    '缺少必需工具',
    '补齐必需工具调用',
    '根据下列失败证据，检查缺失工具的触发条件与执行分支，补齐调用步骤。',
    '重跑关联样本，确认列出的必需工具均被调用；再核对调用参数和返回结果。',
  ],
  policy_compliance: [
    '业务策略未满足',
    '修正业务策略执行',
    '对照下列策略失败原因逐项修改业务分支，同时核对禁止动作和要求达到的业务状态。',
    '重跑关联策略样本，逐项确认策略检查通过，不以单个工具调用成功代替策略通过。',
  ],
  final_state_match: [
    '最终状态不符合期望',
    '修正最终业务状态',
    '打开关联样本的状态检查项，对照期望值和实际值修正状态更新条件。',
    '确认每个失败状态字段达到期望，并检查状态更新前置动作是否正确。',
  ],
  tool_argument_accuracy: [
    '工具参数不符合期望',
    '修正工具参数构造',
    '对照关联样本的工具参数检查项，修正对应参数字段和取值来源。',
    '核对失败参数的期望与实际值，并确认工具调用成功。',
  ],
  skill_routing_accuracy: [
    'Skill 路由不符合期望',
    '修正 Skill 路由条件',
    '对照样本期望 Skill 与实际路由，核对候选 Skill 的触发条件和职责边界。',
    '重跑路由样本，确认实际 Skill 符合期望，并回归相邻场景。',
  ],
};
export function clusterName(c: Row): string {
  return (
    (checks[c.metric]?.[0] ??
      (stageName[c.failure_stage] ?? '未定位阶段') + ' · ' + (c.metric ?? '未标注指标')) +
    '（' +
    (c.evaluator_id ?? '未标注评估器') +
    '）'
  );
}
export function analysisTitle(key: string, row: Row, data: Row | null): string {
  const cs = relatedClusters(key, row, data);
  if (key === 'clusters') return clusterName(row);
  if (key === 'hypotheses')
    return '待核对原因 · ' + (cs.map(clusterName).join('；') || row.title || '未关联失败证据');
  if (key === 'suggestions')
    return cs.length
      ? cs
          .map(
            (c) =>
              (checks[c.metric]?.[1] ?? improvement[row.target]?.[0] ?? '核对执行配置') +
              '（' +
              c.evaluator_id +
              '）',
          )
          .join('；')
      : (row.title ?? '未关联失败证据的建议');
  return row.title ?? row.label ?? row.category ?? '分析项';
}
export function guidance(c: Row, target: string): [string, string] {
  const rule = checks[c.metric];
  return rule
    ? [rule[2], rule[3]]
    : [
        improvement[target]?.[1] ?? '核对下方原始建议及关联证据。',
        improvement[target]?.[2] ?? '修改后重跑关联样本。',
      ];
}
