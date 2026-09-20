import { ref, watch } from 'vue';
import { defineStore } from 'pinia';
import {
  api,
  request,
  type EvaluatorSummary,
  type EvaluatorDetail,
  type EvaluationRun,
  type Trace,
} from '../../api/evaluations';
export type Criterion = { key: string; text: string };
export type ScoringTemplate = {
  id: string;
  name: string;
  description: string;
  instruction: string;
  criteria: Criterion[];
  dimension: string;
  metric: string;
  version: string;
  preview: boolean;
  evaluatorId?: string;
};
export type AnnotationTemplate = {
  id: string;
  name: string;
  description: string;
  message: Criterion[];
  tools: Criterion[];
  messageTags: string[];
  toolTags: string[];
  min: number;
  max: number;
};
export type AnnotationTask = {
  id: string;
  name: string;
  description: string;
  deletedAt?: string;
  example?: boolean;
  skippedConversations?: string[];
  app: { source_id: string; target_type: string; external_target_id: string; name: string };
  template: AnnotationTemplate;
  annotations: Record<
    string,
    { scores: Record<string, number | null>; tags: string[]; note: string; expected: string }
  >;
};
export type JudgeDraft = {
  id: string;
  name: string;
  template: ScoringTemplate;
  model: string;
  provider: string;
  scope: string;
  threshold: number;
};
export const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));

export const useReviewStore = defineStore('review', () => {
  const scoringDrafts = ref<ScoringTemplate[]>([]);
  const annotationTemplates = ref<AnnotationTemplate[]>([
    {
      id: 'annotation-default-ux',
      name: '通用会话标注模板',
      description: '截图默认维度的 UX 起点；不是后端已发布资产。评分范围可在复制后的模板中修改。',
      message: [
        { key: 'accuracy', text: '准确性' },
        { key: 'completeness', text: '完整性' },
        { key: 'usefulness', text: '有用性' },
        { key: 'safety', text: '安全性' },
      ],
      tools: [
        { key: 'paramCorrectness', text: '参数正确性' },
        { key: 'resultAccuracy', text: '结果正确性' },
        { key: 'resultUtilization', text: '结果利用度' },
      ],
      messageTags: ['回答正确', '流程清晰', '信息冗余', '遗漏信息', '语气不当', '幻觉'],
      toolTags: ['参数完整', '冗余调用', '参数错误', '结果幻觉'],
      min: 0,
      max: 5,
    },
  ]);
  const annotationStorageError = ref('');
  const annotationStorageKey = 'agentgate-ux-5198-annotations-v1';
  function readAnnotations(): AnnotationTask[] {
    try {
      const raw = localStorage.getItem(annotationStorageKey);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (
        !Array.isArray(parsed) ||
        parsed.some((t) => !t.id || !t.template?.message || !t.app || !t.annotations)
      )
        throw Error('invalid');
      return parsed;
    } catch {
      annotationStorageError.value = '本地标注读取失败，未覆盖已有记录。';
      return [];
    }
  }
  const annotationTasks = ref<AnnotationTask[]>(readAnnotations());
  watch(
    annotationTasks,
    (value) => {
      if (annotationStorageError.value) return;
      try {
        localStorage.setItem(annotationStorageKey, JSON.stringify(value));
      } catch {
        annotationStorageError.value = '浏览器存储空间不足，请导出标注记录。';
      }
    },
    { deep: true, flush: 'sync' },
  );
  let annotationExamplePending: Promise<void> | null = null;
  function ensureAnnotationExample() {
    if (
      annotationTasks.value.some((t) => t.id === 'annotation-example-20260919') ||
      annotationStorageError.value
    )
      return Promise.resolve();
    if (annotationExamplePending) return annotationExamplePending;
    annotationExamplePending = (async () => {
      const runs = await request<EvaluationRun[]>('/runs?limit=200');
      const run = runs.find(
        (r) => r.id === 'be9b9e0e-2a17-432b-8e64-cf2a161896b0' && r.status === 'completed',
      );
      if (!run) throw Error('标注样例依赖的 Demo 运行记录不存在。');
      const c = run.manifest.dataset.cases.find(
        (c) => !run.manifest.selected_case_ids || run.manifest.selected_case_ids.includes(c.id),
      );
      if (!c) throw Error('示例运行没有样本。');
      const trace = await request<Trace>(`/runs/${run.id}/traces/${c.id}`);
      const turn = c.turns.find((t) => trace.turn_outcomes?.[t.id]);
      if (!turn) throw Error('示例 Trace 没有完整对话。');
      const template = copy(annotationTemplates.value[0]);
      template.id = 'annotation-example-template-20260919';
      template.name = '贷款流程人工复核 · 示例';
      template.description = '基于内置 Demo 执行记录的标注练习。';
      annotationTasks.value.unshift({
        id: 'annotation-example-20260919',
        name: '人工标注样例 · 贷款流程',
        description: '对话来自已执行 Demo；评分和评语为演示标注，不是人工验收结论。',
        example: true,
        app: { ...run.manifest.target.ref, name: run.manifest.target.display_name },
        template,
        annotations: {
          [`${run.id}/${c.id}/${turn.id}`]: {
            scores: { accuracy: 5, completeness: 4, usefulness: 4, safety: 5 },
            tags: ['回答正确', '流程清晰'],
            note: '示例标注：高风险申请进入人工复核，未直接审批通过；可补充后续处理说明。',
            expected: '高风险申请应进入人工复核，不能直接批准。',
          },
        },
      });
    })().finally(() => (annotationExamplePending = null));
    return annotationExamplePending;
  }
  const judgeDrafts = ref<JudgeDraft[]>([]);
  const evaluatorCatalog = ref<EvaluatorSummary[]>([]);
  const evaluatorDetails = ref<Record<string, EvaluatorDetail>>({});
  const extractedTemplates = ref<ScoringTemplate[]>([]);
  const assetsError = ref(''),
    assetsLoading = ref(false);
  let pending: Promise<void> | null = null;
  function loadReviewAssets() {
    if (pending) return pending;
    assetsLoading.value = true;
    assetsError.value = '';
    pending = (async () => {
      try {
        const catalog = await api.evaluators();
        const results = await Promise.all(
          catalog
            .filter((e) => e.latest_version)
            .map(async (e) => ({ id: e.id, detail: await api.evaluator(e.id) })),
        );
        evaluatorCatalog.value = catalog;
        evaluatorDetails.value = Object.fromEntries(results.map((r) => [r.id, r.detail]));
        extractedTemplates.value = results.flatMap(({ id, detail }) => {
          const d = detail.latest;
          if (d?.kind !== 'llm_judge') return [];
          return [
            {
              id: `evaluator:${id}@${d.version}`,
              name: `${detail.evaluator.name} · 评分模板`,
              description:
                detail.evaluator.description || '从已发布 LLM 评估器读取，不另存一套评分内容。',
              instruction: String(d.config.instruction ?? ''),
              criteria: Object.entries((d.config.rubric as Record<string, string>) ?? {}).map(
                ([key, text]) => ({ key, text: String(text) }),
              ),
              dimension: d.dimension,
              metric: d.metric,
              version: String(d.version ?? ''),
              preview: false,
              evaluatorId: id,
            },
          ];
        });
      } catch {
        assetsError.value = '读取后端评估器配置失败。请重试；未用示例模型或提示词替代。';
      } finally {
        assetsLoading.value = false;
        pending = null;
      }
    })();
    return pending;
  }
  function validateCriteria(rows: Criterion[], required: boolean) {
    if (required && !rows.length) return '至少保留一个评分维度。';
    if (rows.some((r) => !r.key.trim() || !r.text.trim())) return '请填写每个维度的标识与说明。';
    if (new Set(rows.map((r) => r.key.trim())).size !== rows.length)
      return '评分维度标识不能重复。';
    return '';
  }
  function exportUx(value: unknown, filename: string) {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { format: 'agentgate-review-ux-v1', persisted: false, data: value },
            null,
            2,
          ),
        ],
        { type: 'application/json' },
      ),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return {
    scoringDrafts,
    annotationTemplates,
    annotationStorageError,
    annotationTasks,
    judgeDrafts,
    evaluatorCatalog,
    evaluatorDetails,
    extractedTemplates,
    assetsError,
    assetsLoading,
    ensureAnnotationExample,
    loadReviewAssets,
    validateCriteria,
    exportUx,
  };
});
