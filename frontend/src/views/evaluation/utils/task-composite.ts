import { request, type EvaluatorSummary } from '../../../api/evaluations';
import { weightError } from './evaluator-design';
export async function createTaskComposite(
  items: EvaluatorSummary[],
  weights: Record<string, number>,
  name: string,
) {
  if (items.length < 2) throw Error('复合评估器至少需要两个子评估器。');
  if (!items.some((e) => e.kind === 'rule') || !items.some((e) => e.kind === 'llm_judge'))
    throw Error('复合评估器需要同时包含规则和 LLM 评估器；普通多选请独立执行。');
  const error = weightError(items.map((e) => ({ weight: weights[e.id] })));
  if (error) throw Error(error);
  if (items.some((e) => !e.enabled || !e.latest_version || e.kind === 'hybrid'))
    throw Error('只能组合已启用且已发布的规则或 LLM 评估器。');
  const created = await request<{ evaluator: { id: string } }>('/evaluators', 'POST', {
    name,
    description: '从测评任务创建的加权组合；固定子评估器版本。',
    draft: {
      kind: 'hybrid',
      dimension: 'answer',
      metric: 'task_composite_score',
      severity: 'standard',
      implementation_id: 'composite',
      implementation_version: '1',
      config: { pass_threshold: 0.8 },
      combination: 'weighted_score',
      children: items.map((e) => ({
        evaluator_id: e.id,
        evaluator_version: e.latest_version,
        weight: weights[e.id] / 100,
      })),
    },
  });
  const id = created.evaluator.id;
  try {
    const published = await request<{ version: string }>(
      `/evaluators/${encodeURIComponent(id)}/drafts/publish`,
      'POST',
    );
    await request(`/evaluators/${encodeURIComponent(id)}`, 'PATCH', { enabled: true });
    return { id, version: published.version };
  } catch (e) {
    throw Error(
      '复合评估器已创建，但发布或启用未确认。请勿重复创建；保留 ID ' + id + '。' + String(e),
    );
  }
}
