import type { Definition, EvaluatorIdentity } from '../../../api/evaluations';
import { modelRefError, readModelRef, type EvaluatorModelRef } from './evaluator-model';

export const concisenessPrompt = `您是一位专业的数据标注员，负责评估模型输出的简洁性。您的任务是根据以下评分标准给出评分：
<评分标准>
  完美简洁的答案应当：
  - 仅包含被请求的确切信息。
  - 使用最少的词汇来传达完整的答案。
  - 省略客套话、模棱两可的表述和不必要的背景信息。
  - 不包含关于答案或模型能力的元评论。
  - 避免冗余信息或重复表述。
  - 除非明确要求，否则不包含解释内容。

  在打分时，您应该扣除分数的情况有：
  - 诸如“我认为”“我觉得”或“答案是”之类的引导性短语。
  - 像“可能”“大概”或“据我所知”这样的模糊表述。
  - 不必要的背景或上下文信息。
  - 未被要求的解释内容。
  - 跟进问题或提供更多信息的提议。
  - 冗余信息或重复表述。
  - 像“希望这有帮助”或“如果您还需要其他信息请告诉我”这样的礼貌用语。
</评分标准>

<指导说明>
  - 仔细阅读输入的问题和模型的输出。
  - 全面检查输出中是否存在任何不必要的元素，尤其是上述<评分标准>中提到的那些。
  - 分数应反映输出在多大程度上遵循了评分标准，即仅包含所请求的必要信息。
</指导说明>

<提醒>
  目标是奖励那些提供完整答案且无任何多余信息的回复。
</提醒>

<输入>
{{input}}
</输入>

<输出>
{{output}}
</输出>`;

export const evaluatorTemplates = [
  {
    id: 'conciseness',
    name: '简洁性',
    description: '评估输出是否只包含必要信息，表达完整且无冗余内容。',
    tags: ['LLM', '文本', '内容质量', 'AIGC'],
    instruction: concisenessPrompt,
  },
  {
    id: 'relevance',
    name: '相关性',
    description: '评估回答是否紧扣用户问题，覆盖请求重点，避免偏题与无关内容。',
    tags: ['LLM', '文本', '内容质量', 'AIGC'],
    instruction: `您是一位专业的数据标注员，负责评估模型输出与用户输入的相关性。
<评分标准>
- 回答应直接回应用户的问题、目标和明确约束。
- 覆盖用户请求的关键内容，不用无关信息替代所需答案。
- 对偏离主题、答非所问、遗漏核心请求或过多无关扩展扣分。
- 本项仅评价相关性，不因措辞风格或回答长度本身扣分。
</评分标准>
<指导说明>
仔细阅读输入和输出，给出 0.0 到 1.0 的分数及具体依据。完全切题为 1.0，完全无关为 0.0；部分相关按覆盖程度评分。
</指导说明>
<输入>
{{input}}
</输入>
<输出>
{{output}}
</输出>`,
  },
  {
    id: 'accuracy',
    name: '准确性',
    description: '评估回答中的事实、数字与结论是否准确，是否符合输入提供的信息。',
    tags: ['LLM', '文本', '内容质量', 'AIGC'],
    instruction: `您是一位专业的数据标注员，负责评估模型输出的准确性。
<评分标准>
- 回答中的事实、数字、计算及引用应准确，并与输入信息一致。
- 结论应有可核对的依据，不应编造事实、来源或未提供的业务信息。
- 对事实错误、计算错误、自相矛盾及将推测说成确定事实扣分。
- 无法仅根据输入和可确认知识验证的内容应说明不确定性，不得凭空认定正确。
</评分标准>
<指导说明>
逐项核对关键断言，给出 0.0 到 1.0 的分数及具体依据。完全准确为 1.0，核心结论错误为 0.0；依据错误的重要性和覆盖范围评分。
</指导说明>
<输入>
{{input}}
</输入>
<输出>
{{output}}
</输出>`,
  },
  {
    id: 'reasonableness',
    name: '合理性',
    description: '评估推理与建议是否连贯、符合条件且可行，结论是否与依据一致。',
    tags: ['LLM', '文本', '内容质量', 'AIGC'],
    instruction: `您是一位专业的数据标注员，负责评估模型输出的合理性。
<评分标准>
- 推理过程应连贯，结论应由给定条件和已说明的依据支持。
- 建议应符合用户场景、限制和常识，并具有实际可行性。
- 对逻辑跳跃、前后矛盾、忽略关键约束及无法执行的建议扣分。
- 不要求用户未请求的解释；简短且合理的直接回答可以得满分。
</评分标准>
<指导说明>
检查输出的假设、推理和结论是否一致，给出 0.0 到 1.0 的分数及具体依据。完全合理为 1.0，存在根本逻辑问题为 0.0。
</指导说明>
<输入>
{{input}}
</输入>
<输出>
{{output}}
</输出>`,
  },
];

export interface PromptEvaluatorDesign {
  id: string;
  name: string;
  description: string;
  modelKey: string;
  instruction: string;
  userPrompt: string | null;
  threshold: number;
}

export function emptyPromptEvaluator(): PromptEvaluatorDesign {
  return {
    id: '',
    name: '',
    description: '',
    modelKey: '',
    instruction: '',
    userPrompt: null,
    threshold: 0.8,
  };
}

export function promptVariableNames(...prompts: (string | null | undefined)[]): string[] {
  return [
    ...new Set(
      prompts
        .flatMap((prompt) =>
          Array.from((prompt ?? '').matchAll(/\{\{([^{}]*)\}\}/g), (match) => match[1].trim()),
        )
        .filter(Boolean),
    ),
  ];
}

export function isPromptEvaluator(definition: Definition | null) {
  return (
    definition?.kind === 'llm_judge' &&
    definition.implementation_id === 'answer_quality' &&
    definition.implementation_version === '1'
  );
}

export function readPromptEvaluator(
  evaluator: Pick<EvaluatorIdentity, 'id' | 'name' | 'description'>,
  definition: Definition,
): PromptEvaluatorDesign {
  return {
    id: evaluator.id,
    name: evaluator.name,
    description: evaluator.description,
    modelKey: JSON.stringify(readModelRef(JSON.stringify(definition.config.model ?? {})) ?? {}),
    instruction: String(definition.config.instruction ?? ''),
    userPrompt:
      typeof definition.config.user_prompt === 'string' ? definition.config.user_prompt : null,
    threshold: Number(definition.config.pass_threshold ?? 0.8),
  };
}

export function promptEvaluatorError(design: PromptEvaluatorDesign) {
  if (!design.name.trim()) return '请输入评估器名称。';
  if (design.name.length > 50) return '评估器名称不能超过 50 字。';
  if (design.description.length > 200) return '评估器描述不能超过 200 字。';
  if (modelRefError(design.modelKey)) return '请选择有效的评审模型。';
  if (!design.instruction.trim()) return '请输入 System Prompt。';
  if (design.userPrompt !== null && !design.userPrompt.trim())
    return '请填写 User Prompt，或移除空白的 User Prompt。';
  const variables = [
    ...(design.instruction + '\n' + (design.userPrompt ?? '')).matchAll(/\{\{([^{}]*)\}\}/g),
  ]
    .map((match) => match[1].trim())
    .filter((name) => !['input', 'output'].includes(name));
  if (variables.length)
    return `不支持的变量：${[...new Set(variables)].join('、')}。仅支持 {{input}} 和 {{output}}。`;
  if (!Number.isFinite(design.threshold) || design.threshold < 0 || design.threshold > 1)
    return '通过分数须为 0.0—1.0。';
  return '';
}

export function promptEvaluatorDefinition(
  design: PromptEvaluatorDesign,
  base: Definition | null = null,
): Definition {
  const error = promptEvaluatorError(design);
  if (error) throw new Error(error);
  const original = isPromptEvaluator(base) ? base : null;
  const config: Record<string, unknown> = {
    input_selection: 'final_output',
    min_confidence: 0,
    timeout_seconds: 180,
    max_output_tokens: 6000,
    ...original?.config,
    render_template: true,
    instruction: design.instruction,
    rubric: original?.config.rubric ?? { overall: '按照提示词中的评分标准评估。' },
    model: readModelRef(design.modelKey),
    pass_threshold: design.threshold,
  };
  if (design.userPrompt === null) delete config.user_prompt;
  else config.user_prompt = design.userPrompt;
  return {
    kind: 'llm_judge',
    dimension: original?.dimension ?? 'answer',
    metric: original?.metric ?? 'answer_quality',
    severity: original?.severity ?? 'standard',
    implementation_id: 'answer_quality',
    implementation_version: '1',
    config,
    children: [],
    combination: null,
  };
}

export function promptModelOptions(
  connections: { configured: boolean; provider_id?: string; model: string }[],
  existing: [string, EvaluatorModelRef][],
): [string, EvaluatorModelRef][] {
  const refs = [
    ...connections
      .filter((c) => c.configured && c.provider_id && c.model)
      .map((c) => ({ provider_id: c.provider_id!, model_id: c.model })),
    ...existing.map(([, model]) => model),
  ];
  const unique = new Map<string, EvaluatorModelRef>();
  for (const model of refs) {
    const normalized = readModelRef(JSON.stringify(model));
    if (!normalized || modelRefError(JSON.stringify(normalized))) continue;
    const identity = { ...normalized };
    // This reference explicitly names the same server default used by the runtime row.
    if (identity.credential_ref === 'env:AGENTGATE_JUDGE_API_KEY') delete identity.credential_ref;
    unique.set(JSON.stringify(identity), normalized);
  }
  return [...unique.values()].map((model) => [JSON.stringify(model), model]);
}
