<script setup lang="ts">
import { shallowRef, computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { request, type EvaluationRun } from '../../../api/evaluations';
import type { Trace } from '../../../api/client';
import AnnotationV2Workspace from './AnnotationV2Workspace.vue';
import AgentTargetPicker, { type AgentTargetSelection } from './AgentTargetPicker.vue';
import { agentDirectory, localAgentDirectory } from '../../../api/agent-platform';
import { useAuthStore } from '../../../stores/modules/auth';
import {
  annotatedCase,
  defaultOutputPath,
  matchesAnnotationTarget,
  scoresComplete,
  toolCalls,
  type RawCase,
  type ToolCall,
} from '../utils/annotation-feedback';
import {
  useReviewStore,
  type ToolAnnotation,
  type MessageAnnotation,
} from '../../../stores/modules/review';
import {
  annotationTemplates,
  annotationTasks,
  annotationStorageError,
  copy,
  validateCriteria,
  type AnnotationTemplate,
  type AnnotationTask,
} from '../../../stores/review-assets';
import '../../../styles/review-assets.scss';
import { annotationProgress } from '../utils/annotation-progress';
import { displayValue } from '../utils/task-report';
const auth = useAuthStore();
const review = useReviewStore();
const platformSelection = ref<AgentTargetSelection | null>(null);
const historicalMode = ref(false),
  historicalRunId = ref('');
const historicalRuns = ref<EvaluationRun[]>([]);
const platformDirectory = computed(() => (auth.isBank ? agentDirectory : localAgentDirectory));
const platformToken = computed(() => (auth.isBank ? auth.token : 'local'));
const platformTeam = computed(() => (auth.isBank ? auth.teamId : ''));
const props = defineProps<{ templates?: boolean; taskId?: string }>(),
  emit = defineEmits<{ dirtyChange: [value: boolean]; navigate: [path: string] }>();
const query = ref(''),
  error = ref(''),
  form = ref(false),
  templateDetail = ref<AnnotationTemplate | null>(null),
  taskDetail = ref<AnnotationTask | null>(null);
const templateEdit = ref<AnnotationTemplate>(copy(annotationTemplates.value[0]));
const filteredTemplates = computed(() =>
  annotationTemplates.value.filter((t) => `${t.name} ${t.description}`.includes(query.value)),
);
const showDeleted = ref(false),
  cardMenu = ref(''),
  basicEdit = ref<AnnotationTask | null>(null),
  basicName = ref(''),
  basicDescription = ref(''),
  basicError = ref('');
const filteredTasks = computed(() =>
  annotationTasks.value.filter(
    (t) =>
      Boolean(t.deletedAt) === showDeleted.value && `${t.name} ${t.app.name}`.includes(query.value),
  ),
);
function openBasic(t: AnnotationTask) {
  basicEdit.value = t;
  basicName.value = t.name;
  basicDescription.value = t.description;
  basicError.value = '';
  cardMenu.value = '';
}
function saveBasic() {
  if (!basicEdit.value) return;
  if (!basicName.value.trim()) {
    basicError.value = '请输入模板名称。';
    return;
  }
  if (annotationStorageError.value) {
    basicError.value = annotationStorageError.value;
    return;
  }
  const t = basicEdit.value;
  t.name = basicName.value.trim();
  t.description = basicDescription.value.trim();
  t.template.name = t.name;
  t.template.description = t.description;
  if (annotationStorageError.value) {
    basicError.value = annotationStorageError.value;
    return;
  }
  basicEdit.value = null;
}
function deleteTemplate(t: AnnotationTask) {
  cardMenu.value = '';
  if (annotationStorageError.value) {
    error.value = annotationStorageError.value;
    return;
  }
  if (!window.confirm(`删除“${t.name}”？模板将从列表中移除。已有标注和原始测评会话会保留。`))
    return;
  t.deletedAt = new Date().toISOString();
}
function restoreTemplate(t: AnnotationTask) {
  if (annotationStorageError.value) {
    error.value = annotationStorageError.value;
    return;
  }
  delete t.deletedAt;
  showDeleted.value = false;
}
function enterTemplate(t: AnnotationTask) {
  if (t.deletedAt) return;
  if (t.template.v2) templateDetail.value = t.template;
  else emit('navigate', 'annotations/' + t.id);
}
const v2Groups = [
  { key: 'dataset', title: '测评集人工标注' },
  { key: 'evaluator', title: '评估器人工标注' },
  { key: 'agent', title: '智能体人工标注' },
] as const;
function openCreate(source?: AnnotationTemplate, version: 'v1' | 'v2' = 'v1') {
  error.value = '';
  historicalMode.value = false;
  historicalRunId.value = '';
  templateEdit.value = copy(source ?? annotationTemplates.value[0]);
  if (!source && version === 'v2') {
    const defaults = templateEdit.value;
    defaults.v2 = {
      dataset: {
        enabled: false,
        criteria: copy(defaults.message),
        tags: [...defaults.messageTags],
      },
      evaluator: { enabled: false, criteria: copy(defaults.tools), tags: [...defaults.toolTags] },
      agent: { enabled: false, criteria: copy(defaults.message), tags: [...defaults.messageTags] },
    };
    defaults.min = 0;
    defaults.max = 100;
    defaults.message = [];
    defaults.tools = [];
    defaults.messageTags = [];
    defaults.toolTags = [];
  }
  if (templateEdit.value.v2 && !templateEdit.value.v2.agent) {
    const defaults = annotationTemplates.value[0];
    templateEdit.value.v2.agent = {
      enabled: false,
      criteria: copy(defaults.message),
      tags: [...defaults.messageTags],
    };
  }
  templateEdit.value.id = crypto.randomUUID();
  templateEdit.value.name = source ? source.name + '（副本）' : '';
  templateDetail.value = null;
  form.value = true;
  platformSelection.value = null;
}
function closeForm() {
  if (!window.confirm('放弃当前未保存的配置？')) return;
  form.value = false;
}
function save() {
  if (templateEdit.value.v2) return;
  error.value = '';
  {
    const t = templateEdit.value;
    error.value = !t.name.trim()
      ? '请输入模板名称。'
      : validateCriteria(t.message, true) || validateCriteria(t.tools, false);
    if (!Number.isFinite(t.min) || !Number.isFinite(t.max) || t.max <= t.min)
      error.value = '评分上限必须大于下限。';
    if (error.value) return;
  }
  const selected = platformSelection.value;
  const historical = historicalMode.value
    ? historicalRuns.value.find((r) => r.id === historicalRunId.value)
    : null;
  if (!selected && !historical) {
    error.value = '请选择关联智能体、分支和版本，或选择已完成测评。';
    return;
  }
  const t = templateEdit.value;
  const task: AnnotationTask = {
    id: crypto.randomUUID(),
    name: t.name.trim(),
    description: t.description,
    app: historical
      ? { ...historical.manifest.target.ref, name: historical.manifest.target.display_name }
      : {
          source_id: selected?.localTarget?.descriptor.ref.source_id ?? 'platform',
          target_type: 'agent',
          external_target_id: selected!.agentId,
          name: selected!.agentName,
        },
    target: selected
      ? {
          loginMode: auth.loginMode,
          teamId: selected.teamId,
          agentId: selected.agentId,
          agentName: selected.agentName,
          typeGroup: selected.typeGroup,
          branchId: selected.branchId,
          agentVersion: selected.agentVersion,
          ...(selected.localTarget ? { localExecution: { sourceId: selected.localTarget.descriptor.ref.source_id, adapterType: selected.localTarget.adapter_type } } : {}),
        }
      : undefined,
    template: copy(t),
    annotations: {},
    toolAnnotations: {},
  };
  try {
    review.saveAnnotationTask(task);
  } catch (e) {
    error.value = String(e);
    return;
  }
  form.value = false;
}
// V2 owns its validation and creation; the store only persists the completed record.
function confirmV2Template() {
  if (!form.value || !templateEdit.value.v2) return;
  error.value = '';
  const draft = copy(templateEdit.value);
  const name = draft.name.trim();
  if (!name) {
    error.value = '请输入模板名称。';
    return;
  }
  if (!Number.isFinite(draft.min) || !Number.isFinite(draft.max) || draft.max <= draft.min) {
    error.value = '评分上限必须大于下限。';
    return;
  }
  for (const { key, title } of v2Groups) {
    const section = draft.v2![key];
    if (!section?.enabled) continue;
    if (!section.criteria.length) {
      error.value = title + '：至少保留一个评分维度。';
      return;
    }
    if (section.criteria.some((d) => !d.key.trim() || !d.text.trim())) {
      error.value = title + '：请填写每个维度的标识与说明。';
      return;
    }
    if (new Set(section.criteria.map((d) => d.key.trim())).size !== section.criteria.length) {
      error.value = title + '：评分维度标识不能重复。';
      return;
    }
  }
  const selected = platformSelection.value;
  if (!selected) {
    error.value = '请选择关联智能体、分支和版本。';
    return;
  }
  const template: AnnotationTemplate = {
    id: crypto.randomUUID(),
    name,
    description: draft.description,
    min: draft.min,
    max: draft.max,
    v2: draft.v2,
    message: [],
    tools: [],
    messageTags: [],
    toolTags: [],
  };
  const created: AnnotationTask = {
    id: crypto.randomUUID(),
    name,
    description: draft.description,
    app: {
      source_id: selected?.localTarget?.descriptor.ref.source_id ?? 'platform',
      target_type: 'agent',
      external_target_id: selected.agentId,
      external_version_id: selected.agentVersion,
      name: selected.agentName,
    },
    target: {
      loginMode: auth.loginMode,
      teamId: selected.teamId,
      agentId: selected.agentId,
      agentName: selected.agentName,
      typeGroup: selected.typeGroup,
      branchId: selected.branchId,
      agentVersion: selected.agentVersion,
          ...(selected.localTarget ? { localExecution: { sourceId: selected.localTarget.descriptor.ref.source_id, adapterType: selected.localTarget.adapter_type } } : {}),
    },
    template,
    annotations: {},
    toolAnnotations: {},
  };
  try {
    review.saveAnnotationTask(created);
  } catch (cause) {
    error.value = String(cause);
    return;
  }
  query.value = '';
  showDeleted.value = false;
  form.value = false;
  if (props.templates) emit('navigate', 'annotations');
}
const runs = shallowRef<EvaluationRun[]>([]),
  runsLoading = ref(false),
  runId = ref(''),
  caseId = ref(''),
  trace = shallowRef<Trace | null>(null),
  traceError = ref(''),
  traceLoading = ref(false),
  saved = ref('');
const activeRun = computed(() => runs.value.find((r) => r.id === runId.value));
const cases = computed(
  () =>
    activeRun.value?.manifest.dataset.cases.filter(
      (c) =>
        !activeRun.value?.manifest.selected_case_ids ||
        activeRun.value.manifest.selected_case_ids.includes(c.id),
    ) ?? [],
);
type Row = {
  id: string;
  input: unknown;
  output: unknown;
  scores: Record<string, number | null>;
  tags: string[];
  note: string;
  expected: string;
  expectedMode?: MessageAnnotation['expectedMode'];
  expectedPath?: string;
};
const rows = ref<Row[]>([]);
const toolRows = ref<(ToolCall & { review: ToolAnnotation })[]>([]);
const baseline = ref('[]');
const toolBaseline = ref('[]');
const annotationDirty = computed(
  () =>
    JSON.stringify(rows.value) !== baseline.value ||
    JSON.stringify(toolRows.value) !== toolBaseline.value,
);
function resetTools() {
  toolRows.value = [];
  toolBaseline.value = '[]';
}

watch([form, annotationDirty, basicEdit], ([formDirty, rowDirty, basic]) =>
  emit('dirtyChange', formDirty || rowDirty || !!basic),
);
function canLeave() {
  if (feedbackBusy.value) return false;
  return !annotationDirty.value || window.confirm('当前会话有未保存的标注，确定放弃？');
}
function closeTask() {
  if (!canLeave()) return;
  taskDetail.value = null;
  rows.value = [];
  baseline.value = '[]';
  resetTools();
  runSequence++;
  sequence++;
  emit('navigate', 'annotations');
}
function chooseRun(event: Event) {
  const select = event.target as HTMLSelectElement;
  if (!canLeave()) {
    select.value = runId.value;
    return;
  }
  runId.value = select.value;
}
function chooseCase(event: Event) {
  const select = event.target as HTMLSelectElement;
  if (!canLeave()) {
    select.value = caseId.value;
    return;
  }
  caseId.value = select.value;
  void readConversation();
}
let sequence = 0,
  runSequence = 0;
watch(runId, () => {
  caseId.value = '';
  trace.value = null;
  rows.value = [];
  baseline.value = '[]';
  resetTools();
  traceError.value = '';
  saved.value = '';
  sequence++;
  traceLoading.value = false;
});
const conversations = ref<
  { key: string; run: EvaluationRun; caseId: string; name: string; trace?: Trace; error?: string }[]
>([]);
const conversationQuery = ref(''),
  conversationStatus = ref(''),
  conversationPage = ref(1),
  editingConversation = ref(false),
  ready = ref(false);
const statusNames: Record<string, string> = {
  pending: '待标注',
  partial: '标注中',
  done: '已标注',
  skipped: '已跳过',
};
function progressFor(c: (typeof conversations.value)[number]) {
  const t = taskDetail.value;
  const progress = annotationProgress(
    Object.keys(c.trace?.turn_outcomes ?? {}),
    t?.annotations ?? {},
    c.key,
    t?.template.message.map((d) => d.key) ?? [],
    t?.template.min ?? 0,
    t?.template.max ?? 5,
    t?.skippedConversations?.includes(c.key),
  );
  const calls = c.trace ? toolCalls(c.trace) : [];
  const dims = t?.template.tools.map((d) => d.key) ?? [];
  const toolsDone = calls.filter((call) =>
    scoresComplete(
      t?.toolAnnotations?.[c.key + '/' + call.span_id]?.scores,
      dims,
      t?.template.min ?? 0,
      t?.template.max ?? 5,
    ),
  ).length;
  if (dims.length && toolsDone < calls.length && progress.status !== 'skipped')
    progress.status = progress.done || toolsDone ? 'partial' : 'pending';
  return { ...progress, toolsDone, toolsTotal: calls.length };
}
const conversationStats = computed(() =>
  conversations.value.reduce(
    (acc, c) => {
      const p = progressFor(c);
      acc.done += p.status === 'done' ? 1 : 0;
      acc.turns += p.total;
      acc.marked += p.done;
      acc.tools += (c.trace?.spans ?? []).filter((s) => s.operation_type === 'tool').length;
      return acc;
    },
    { done: 0, turns: 0, marked: 0, tools: 0 },
  ),
);
const filteredConversations = computed(() =>
  conversations.value.filter(
    (c) =>
      c.name.toLowerCase().includes(conversationQuery.value.toLowerCase()) &&
      (!conversationStatus.value || progressFor(c).status === conversationStatus.value),
  ),
);
const visibleConversations = computed(() =>
  filteredConversations.value.slice((conversationPage.value - 1) * 20, conversationPage.value * 20),
);
watch([conversationQuery, conversationStatus], () => (conversationPage.value = 1));
async function openTask(task: AnnotationTask) {
  taskDetail.value = task;
  if (task.template.v2) return;
  checkedConversations.value = [];
  feedbackSaved.value = '';
  feedbackError.value = '';
  editingConversation.value = false;
  conversationPage.value = 1;
  conversationQuery.value = '';
  conversationStatus.value = '';
  conversations.value = [];
  runId.value = '';
  caseId.value = '';
  trace.value = null;
  rows.value = [];
  baseline.value = '[]';
  resetTools();
  saved.value = '';
  runs.value = [];
  traceError.value = '';
  runsLoading.value = true;
  const ticket = ++runSequence;
  try {
    const list = await request<EvaluationRun[]>('/runs?status=completed&limit=200');
    if (ticket !== runSequence) return;
    runs.value = list.filter((r) => {
      if (task.target) return matchesAnnotationTarget(r, task.target);
      const a = r.manifest.target.ref;
      return (
        r.status === 'completed' &&
        a.source_id === task.app.source_id &&
        a.target_type === task.app.target_type &&
        a.external_target_id === task.app.external_target_id &&
        (!task.app.external_version_id || a.external_version_id === task.app.external_version_id)
      );
    });
    conversations.value = runs.value.flatMap((run) =>
      run.manifest.dataset.cases
        .filter(
          (c) => !run.manifest.selected_case_ids || run.manifest.selected_case_ids.includes(c.id),
        )
        .map((c) => ({ key: run.id + '/' + c.id, run, caseId: c.id, name: c.name })),
    );
    let cursor = 0;
    await Promise.all(
      Array.from({ length: Math.min(4, conversations.value.length) }, async () => {
        while (ticket === runSequence) {
          const c = conversations.value[cursor++];
          if (!c) break;
          try {
            const t = await request<Trace>(`/runs/${c.run.id}/traces/${c.caseId}`);
            if (ticket === runSequence) c.trace = t;
          } catch {
            if (ticket === runSequence) c.error = '会话轨迹读取失败';
          }
        }
      }),
    );
  } catch {
    if (ticket === runSequence) traceError.value = '读取关联测评失败，请重试。';
  } finally {
    if (ticket === runSequence) runsLoading.value = false;
  }
}
async function beginAnnotation(c: (typeof conversations.value)[number]) {
  if (!canLeave() || !c.trace) return;
  runId.value = c.run.id;
  await nextTick();
  caseId.value = c.caseId;
  editingConversation.value = true;
  await readConversation();
}
function backToConversations() {
  if (!canLeave()) return;
  editingConversation.value = false;
  rows.value = [];
  baseline.value = '[]';
  resetTools();
  sequence++;
  traceLoading.value = false;
  saved.value = '';
  traceError.value = '';
}
function skipConversation(key: string) {
  const task = taskDetail.value;
  if (!task) return;
  const skipped = new Set(task.skippedConversations ?? []);
  skipped.has(key) ? skipped.delete(key) : skipped.add(key);
  task.skippedConversations = [...skipped];
}
function routeTask() {
  if (!ready.value) return;
  if (props.taskId) {
    const task = annotationTasks.value.find((t) => t.id === props.taskId && !t.deletedAt);
    if (task) void openTask(task);
    else {
      taskDetail.value = null;
      error.value = '标注模板不存在或已删除。';
    }
  } else {
    taskDetail.value = null;
    rows.value = [];
    baseline.value = '[]';
    resetTools();
    runSequence++;
    sequence++;
  }
}
watch(() => props.taskId, routeTask);
onUnmounted(() => {
  runSequence++;
  sequence++;
});
async function readConversation() {
  const ticket = ++sequence;
  trace.value = null;
  rows.value = [];
  baseline.value = '[]';
  resetTools();
  traceError.value = '';
  saved.value = '';
  traceLoading.value = false;
  if (!runId.value || !caseId.value || !taskDetail.value) return;
  traceLoading.value = true;
  try {
    const t = await request<Trace>(
      `/runs/${encodeURIComponent(runId.value)}/traces/${encodeURIComponent(caseId.value)}`,
    );
    if (ticket !== sequence) return;
    trace.value = t;
    rows.value = Object.entries(t.turn_outcomes ?? {}).map(([id, outcome]) => {
      const existing = taskDetail.value!.annotations[`${runId.value}/${caseId.value}/${id}`];
      return {
        id,
        input: outcome.input,
        output: outcome.output,
        ...(existing
          ? copy(existing)
          : {
              scores: Object.fromEntries(
                taskDetail.value!.template.message.map((d) => [d.key, null]),
              ),
              tags: [],
              note: '',
              expected: '',
              expectedMode: 'equals' as const,
              expectedPath: defaultOutputPath(outcome.output),
            }),
      };
    });
    toolRows.value = toolCalls(t).map((call) => ({
      ...call,
      review: copy(
        taskDetail.value!.toolAnnotations?.[`${runId.value}/${caseId.value}/${call.span_id}`] ?? {
          scores: Object.fromEntries(taskDetail.value!.template.tools.map((d) => [d.key, null])),
          tags: [],
          note: '',
          expectation: 'none' as const,
          argumentsExpected: '',
          argumentsPath: 'arguments',
          occurrence: 'all' as const,
        },
      ),
    }));
    toolBaseline.value = JSON.stringify(toolRows.value);
    baseline.value = JSON.stringify(rows.value);
  } catch {
    if (ticket === sequence) traceError.value = '会话 Trace 暂不可读；未生成占位对话。';
  } finally {
    if (ticket === sequence) traceLoading.value = false;
  }
}
function saveAnnotations() {
  const task = taskDetail.value;
  if (!task || !rows.value.length) return;
  const { min, max } = task.template;
  if (
    rows.value.some((r) =>
      task.template.message.some((d) => {
        const s = r.scores[d.key];
        return s == null || !Number.isFinite(s) || s < min || s > max;
      }),
    )
  ) {
    traceError.value = `请将每个消息维度填写为 ${min}—${max} 的分数。`;
    return;
  }
  if (
    toolRows.value.some(
      (r) =>
        !scoresComplete(
          r.review.scores,
          task.template.tools.map((d) => d.key),
          min,
          max,
        ),
    )
  ) {
    traceError.value = `请将每次工具调用的全部评分维度填写为 ${min}—${max} 的分数。`;
    return;
  }
  const edited = copy(task);
  for (const r of rows.value)
    edited.annotations[`${runId.value}/${caseId.value}/${r.id}`] = copy({
      scores: r.scores,
      tags: r.tags,
      note: r.note,
      expected: r.expected,
      expectedMode: r.expectedMode,
      expectedPath: r.expectedPath,
    });
  edited.toolAnnotations ??= {};
  for (const r of toolRows.value)
    edited.toolAnnotations[`${runId.value}/${caseId.value}/${r.span_id}`] = copy(r.review);
  edited.skippedConversations = edited.skippedConversations?.filter(
    (key) => key !== runId.value + '/' + caseId.value,
  );
  try {
    review.saveAnnotationTask(edited);
    taskDetail.value = annotationTasks.value.find((t) => t.id === edited.id)!;
  } catch (e) {
    traceError.value = String(e);
    saved.value = '';
    return;
  }
  toolBaseline.value = JSON.stringify(toolRows.value);
  baseline.value = JSON.stringify(rows.value);
  traceError.value = '';
  saved.value = '已保存到本浏览器；原始 Trace 未修改。';
}
function tagsFrom(value: string) {
  return [
    ...new Set(
      value
        .split(/[，,]/)
        .map((x) => x.trim())
        .filter(Boolean),
    ),
  ];
}
type Draft = {
  id: string;
  content_sha256: string;
  cases: RawCase[];
  version: number | null;
  status: string;
};
const checkedConversations = ref<string[]>([]);
const feedbackBusy = ref(false);
watch(feedbackBusy, (value) =>
  emit('dirtyChange', value || form.value || annotationDirty.value || !!basicEdit.value),
);
const feedbackError = ref('');
const feedbackSaved = ref('');
const feedback = ref<{
  mode: 'new' | 'writeback';
  name: string;
  cases: RawCase[];
  datasetId: string;
  draftHash: string | null;
  basedOn: number | null;
  receiptKey: string;
} | null>(null);
async function previewFeedback(mode: 'new' | 'writeback', keys: string[]) {
  feedbackError.value = '';
  feedbackSaved.value = '';
  if (annotationDirty.value) {
    feedbackError.value = '请先保存当前会话标注。';
    return;
  }
  if (!keys.length || (mode === 'writeback' && keys.length !== 1)) {
    feedbackError.value = '请选择会话；回写原测评集每次处理一条会话。';
    return;
  }
  const task = taskDetail.value;
  if (!task || feedbackBusy.value) return;
  const snapshot = copy(task);
  feedbackBusy.value = true;
  try {
    const casesToWrite: RawCase[] = [];
    let datasetId = '',
      draftHash: string | null = null,
      basedOn: number | null = null;
    for (const key of keys) {
      const c = conversations.value.find((c) => c.key === key);
      if (!c?.trace || progressFor(c).status !== 'done')
        throw Error('只能导出已完整标注且未跳过的会话。');
      const source = await request<{ case: RawCase; dataset_id: string; dataset_version: number }>(
        `/runs/${encodeURIComponent(c.run.id)}/cases/${encodeURIComponent(c.caseId)}`,
      );
      let original = source.case;
      if (mode === 'writeback') {
        datasetId = source.dataset_id;
        const detail = await request<{ dataset: { archived: boolean }; versions: Draft[] }>(
          `/datasets/${encodeURIComponent(datasetId)}`,
        );
        if (detail.dataset.archived) throw Error('原测评集已归档，不能回写。');
        const draft = detail.versions.find((v) => v.status === 'draft');
        const latest = detail.versions
          .filter((v) => v.version !== null)
          .sort((a, b) => b.version! - a.version!)[0];
        draftHash = draft?.content_sha256 ?? null;
        basedOn = latest?.version ?? source.dataset_version;
        const current = (draft ?? latest)?.cases.find((item) => item.id === c.caseId);
        if (!current) throw Error('原测评集已移除该样本，请导出为新测评集，避免恢复已删除内容。');
        original = current;
        if (
          JSON.stringify(original.turns.map((t) => [t.id, t.input])) !==
          JSON.stringify(source.case.turns.map((t) => [t.id, t.input]))
        )
          throw Error('原测评集的输入或轮次已变化，请导出新测评集后人工合并。');
      }
      const item = annotatedCase(original, c.trace, snapshot, key);
      if (mode === 'new') {
        item.id = c.run.id + '-' + c.caseId;
        item.name += ' · ' + c.run.id.slice(0, 8);
      }
      casesToWrite.push(item);
    }
    const receiptKey = keys.slice().sort().join('|');
    feedback.value = {
      mode,
      name: snapshot.name + ' · 人工回归',
      cases: casesToWrite,
      datasetId: mode === 'new' ? (snapshot.exports?.[receiptKey] ?? '') : datasetId,
      draftHash,
      basedOn,
      receiptKey,
    };
  } catch (e) {
    feedbackError.value = String(e);
  } finally {
    feedbackBusy.value = false;
  }
}
async function applyFeedback() {
  const plan = feedback.value,
    task = taskDetail.value;
  if (!plan || !task || feedbackBusy.value || !plan.name.trim()) return;
  feedbackBusy.value = true;
  feedbackError.value = '';
  let written = 0;
  try {
    if (plan.mode === 'new' && !plan.datasetId) {
      const created = await request<{ dataset: { id: string } }>('/datasets', 'POST', {
        name: plan.name.trim(),
        description: '人工标注导出；请审核草稿规则后发布。',
      });
      plan.datasetId = created.dataset.id;
      task.exports ??= {};
      task.exports[plan.receiptKey] = plan.datasetId;
      // Store the destination before adding cases so retries reuse this draft.
      review.saveAnnotationTask(task);
      taskDetail.value = annotationTasks.value.find((t) => t.id === task.id)!;
    }
    const detail = await request<{ dataset: { archived: boolean }; versions: Draft[] }>(
      `/datasets/${encodeURIComponent(plan.datasetId)}`,
    );
    if (detail.dataset.archived) throw Error('目标测评集已归档。');
    let draft = detail.versions.find((v) => v.status === 'draft');
    if (plan.mode === 'writeback' && (draft?.content_sha256 ?? null) !== plan.draftHash)
      throw Error('草稿在预览后发生变化，请关闭预览并重新生成。');
    if (!draft) {
      if (plan.mode === 'new')
        throw Error('导出草稿已发布或删除，请进入测评集查看；不会自动覆盖已发布版本。');
      draft = await request<Draft>(
        `/datasets/${encodeURIComponent(plan.datasetId)}/drafts`,
        'POST',
        { based_on_version: plan.basedOn },
      );
    }
    for (const item of plan.cases) {
      await request(`/datasets/${encodeURIComponent(plan.datasetId)}/drafts/cases`, 'POST', item);
      written++;
    }
    feedbackSaved.value = plan.datasetId;
    feedback.value = null;
  } catch (e) {
    feedbackError.value = `已写入 ${written}/${plan.cases.length} 条。${String(e)}`;
    if (plan.datasetId) feedbackSaved.value = plan.datasetId;
  } finally {
    feedbackBusy.value = false;
  }
}
onMounted(() => {
  ready.value = true;
  routeTask();
});
</script>
<template>
  <section v-if="!taskDetail" class="review-assets">
    <div class="asset-heading">
      <div>
        <h1>{{ templates ? '标注模板' : '人工标注' }}</h1>
        <p>
          {{
            templates
              ? '独立配置消息/工具评分维度和标签，供标注任务引用。'
              : '关联应用与已有测评会话，依据标注模板进行人工评审。'
          }}
        </p>
      </div>
      <button v-if="templates" class="asset-secondary" @click="emit('navigate', 'annotations')">
        返回人工标注
      </button>
      <button class="asset-primary" @click="openCreate()">＋ 创建标注模版v1.0</button>
      <button class="asset-primary" @click="openCreate(undefined, 'v2')">
        ＋ 创建标注模版 v2.0
      </button>
    </div>
    <p v-if="error || annotationStorageError" class="asset-error" role="alert">
      {{ error || annotationStorageError }}
    </p>
    <div class="asset-filters">
      <input
        v-model="query"
        aria-label="搜索标注模板"
        :placeholder="templates ? '搜索模板名称或描述' : '搜索模板名称或关联智能体'"
      />
    </div>
    <div class="asset-grid">
      <template v-if="templates"
        ><article v-for="t in filteredTemplates" :key="t.id" class="asset-card">
          <span class="asset-chip preview">{{
            t.id === 'annotation-default-ux' ? '默认模板' : '本地模板'
          }}</span>
          <h2>{{ t.name }}<small v-if="t.v2"> · v2.0</small></h2>
          <p>{{ t.description || '暂无描述' }}</p>
          <div class="asset-chips">
            <template v-if="t.v2"
              ><span v-for="group in v2Groups" :key="group.key" class="asset-chip"
                >{{ group.title }}
                {{
                  t.v2[group.key]?.enabled ? t.v2[group.key]?.criteria.length + ' 项' : '未启用'
                }}</span
              ></template
            >
            <template v-else
              ><span class="asset-chip">消息 {{ t.message.length }} 项</span
              ><span class="asset-chip">工具 {{ t.tools.length }} 项</span></template
            >
            <span class="asset-chip">{{ t.min }}—{{ t.max }} 分</span>
          </div>
          <div class="asset-card-actions">
            <button class="asset-link" @click="templateDetail = t">查看模板</button
            ><button class="asset-link" @click="openCreate(t)">复制并编辑</button>
          </div>
        </article></template
      ><template v-else
        ><article
          v-for="t in filteredTasks"
          :key="t.id"
          class="asset-card annotation-card"
          role="button"
          tabindex="0"
          @click="enterTemplate(t)"
          @keydown.enter.self="enterTemplate(t)"
          @keydown.space.self.prevent="enterTemplate(t)"
        >
          <div class="template-menu" @click.stop @keydown.stop>
            <button
              v-if="!t.deletedAt"
              class="asset-link menu-trigger"
              :aria-label="'管理模板 ' + t.name"
              :aria-expanded="cardMenu === t.id"
              @click="cardMenu = cardMenu === t.id ? '' : t.id"
            >
              ···
            </button>
            <div v-if="cardMenu === t.id" class="template-menu-items">
              <button @click="openBasic(t)">编辑基本信息</button
              ><button class="delete-action" @click="deleteTemplate(t)">删除</button>
            </div>
            <button v-if="t.deletedAt" class="asset-link" @click="restoreTemplate(t)">恢复</button>
          </div>
          <span class="asset-chip preview">{{
            t.deletedAt ? '已删除' : t.example ? '演示样例' : '人工标注模板'
          }}</span>
          <h2>{{ t.name }}<small v-if="t.template.v2"> · v2.0</small></h2>
          <p v-if="t.description">{{ t.description }}</p>
          <p>{{ t.app.name }} · {{ t.app.external_target_id }}</p>
          <p v-if="t.target">
            {{ t.target.branchId || '无分支' }} · 版本 {{ t.target.agentVersion }}
          </p>
          <p v-if="!t.template.v2">
            模板：{{ t.template.name }} · 已存 {{ Object.keys(t.annotations).length }} 条消息标注
          </p>
          <div v-else class="v2-card-actions" @click.stop @keydown.stop>
            <button class="asset-secondary" @click="templateDetail = t.template">模版详情</button>
            <button
              class="asset-primary"
              :disabled="!!t.deletedAt"
              @click="emit('navigate', 'annotations/' + t.id)"
            >
              开始标注
            </button>
          </div>
        </article></template
      >
    </div>
    <p v-if="templates ? !filteredTemplates.length : !filteredTasks.length" class="asset-empty">
      {{ templates ? '暂无匹配模板' : '暂无标注模板，请先创建并关联智能体。' }}
    </p>
  </section>
  <el-dialog
    :model-value="!!basicEdit"
    @close="basicEdit = null"
    title="编辑基本信息"
    width="min(560px,94vw)"
    :close-on-click-modal="false"
    class="asset-dialog"
    ><label>模板名称 *<input v-model="basicName" aria-label="编辑模板名称" maxlength="128" /></label
    ><label
      >描述<textarea
        v-model="basicDescription"
        aria-label="编辑模板描述"
        maxlength="512"
        rows="4"
      />
    </label>
    <p v-if="basicEdit" class="asset-small">关联智能体：{{ basicEdit.app.name }}</p>
    <p v-if="basicError" class="asset-error" role="alert">{{ basicError }}</p>
    <template #footer
      ><button class="asset-secondary" @click="basicEdit = null">取消</button
      ><button class="asset-primary" @click="saveBasic">保存</button></template
    ></el-dialog
  >
  <el-dialog
    :model-value="!!templateDetail"
    @close="templateDetail = null"
    title="标注模板详情"
    width="min(820px,95vw)"
    class="asset-dialog"
    ><template v-if="templateDetail"
      ><h2>{{ templateDetail.name }}</h2>
      <p class="asset-small">评分范围：{{ templateDetail.min }}—{{ templateDetail.max }}</p>
      <template v-if="templateDetail.v2">
        <section v-for="group in v2Groups" :key="group.key" class="asset-panel">
          <h3>
            {{ group.title }} · {{ templateDetail.v2[group.key]?.enabled ? '已启用' : '未启用' }}
          </h3>
          <template v-if="templateDetail.v2[group.key]?.enabled">
            <p v-for="d in templateDetail.v2[group.key]?.criteria" :key="d.key">
              {{ d.key }} · {{ d.text }}
            </p>
            <div class="asset-chips">
              <span
                v-for="tag in templateDetail.v2[group.key]?.tags"
                :key="tag"
                class="asset-chip"
                >{{ tag }}</span
              >
            </div>
          </template>
        </section>
      </template>
      <template v-else>
        <section v-for="group in ['message', 'tools'] as const" :key="group" class="asset-panel">
          <h3>{{ group === 'message' ? '消息' : '工具' }}评分维度</h3>
          <p v-for="d in templateDetail[group]" :key="d.key">{{ d.key }} · {{ d.text }}</p>
          <div class="asset-chips">
            <span
              v-for="tag in templateDetail[group === 'message' ? 'messageTags' : 'toolTags']"
              :key="tag"
              class="asset-chip"
              >{{ tag }}</span
            >
          </div>
        </section>
      </template> </template
    ><template #footer
      ><button class="asset-secondary" @click="templateDetail = null">关闭</button
      ><button v-if="templateDetail" class="asset-primary" @click="openCreate(templateDetail)">
        复制并编辑
      </button></template
    ></el-dialog
  >
  <el-dialog
    :model-value="form"
    :before-close="closeForm"
    :title="templateEdit.v2 ? '创建标注模版 v2.0' : '创建标注模版v1.0'"
    width="min(1080px,96vw)"
    :close-on-click-modal="false"
    class="asset-dialog"
  >
    <div class="asset-two-column">
      <section>
        <h3>① 基础信息与关联智能体</h3>
        <label
          >模板名称 *<input v-model="templateEdit.name" aria-label="标注模板名称" maxlength="128"
        /></label>
        <label>描述<textarea v-model="templateEdit.description" rows="4" maxlength="512" /></label>
        <p class="asset-small">数据源：{{ auth.modeLabel }}。按所选版本和分支关联会话。</p>
        <label v-if="historicalMode"
          >已完成测评<select v-model="historicalRunId" aria-label="模板来源测评">
            <option value="">请选择</option>
            <option v-for="r in historicalRuns" :key="r.id" :value="r.id">
              {{ r.manifest.target.display_name }} ·
              {{ r.manifest.target.ref.external_version_id }} · {{ r.id.slice(0, 8) }}
            </option>
          </select></label
        >
        <AgentTargetPicker
          v-if="form && !historicalMode"
          :directory="platformDirectory"
          :token="platformToken"
          :team-id="platformTeam"
          @selection-change="platformSelection = $event"
        />
        <div class="asset-form-grid">
          <label
            >最低分<input
              v-model.number="templateEdit.min"
              type="number"
              aria-label="标注最低分" /></label
          ><label
            >最高分<input v-model.number="templateEdit.max" type="number" aria-label="标注最高分"
          /></label>
        </div>
      </section>
      <section>
        <h3>② {{ templateEdit.v2 ? '标注对象' : '评分配置' }}</h3>
        <template v-if="templateEdit.v2">
          <section
            v-for="group in v2Groups"
            :key="group.key"
            class="asset-panel annotation-v2-section"
            :class="{ 'is-disabled': !templateEdit.v2[group.key]!.enabled }"
          >
            <div class="annotation-v2-heading">
              <h3>{{ group.title }}</h3>
              <input
                v-model="templateEdit.v2[group.key]!.enabled"
                type="checkbox"
                :aria-label="'启用' + group.title"
              />
            </div>
            <template v-if="templateEdit.v2[group.key]!.enabled">
              <div
                v-for="(d, i) in templateEdit.v2[group.key]!.criteria"
                :key="i"
                class="criterion-row"
              >
                <input v-model="d.key" :aria-label="group.title + '维度标识 ' + (i + 1)" />
                <input v-model="d.text" :aria-label="group.title + '维度名称 ' + (i + 1)" />
                <button @click="templateEdit.v2[group.key]!.criteria.splice(i, 1)">移除</button>
              </div>
              <button
                class="asset-link"
                @click="templateEdit.v2[group.key]!.criteria.push({ key: '', text: '' })"
              >
                ＋ 添加维度
              </button>
              <label
                >标签（逗号分隔）<textarea
                  :aria-label="group.title + '标签'"
                  :value="templateEdit.v2[group.key]!.tags.join('，')"
                  rows="2"
                  @input="
                    templateEdit.v2[group.key]!.tags = tagsFrom(
                      ($event.target as HTMLTextAreaElement).value,
                    )
                  "
                />
              </label>
            </template>
          </section>
        </template>
        <template v-else>
          <section v-for="group in ['message', 'tools'] as const" :key="group" class="asset-panel">
            <h3>{{ group === 'message' ? '消息评分维度 · 至少 1 项' : '工具评分维度 · 选填' }}</h3>
            <div v-for="(d, i) in templateEdit[group]" :key="i" class="criterion-row">
              <input v-model="d.key" :aria-label="group + '维度标识 ' + (i + 1)" /><input
                v-model="d.text"
                :aria-label="group + '维度名称 ' + (i + 1)"
              /><button @click="templateEdit[group].splice(i, 1)">移除</button>
            </div>
            <button class="asset-link" @click="templateEdit[group].push({ key: '', text: '' })">
              ＋ 添加维度</button
            ><label
              >标签（逗号分隔）<textarea
                :value="templateEdit[group === 'message' ? 'messageTags' : 'toolTags'].join('，')"
                rows="2"
                @input="
                  templateEdit[group === 'message' ? 'messageTags' : 'toolTags'] = tagsFrom(
                    ($event.target as HTMLTextAreaElement).value,
                  )
                "
              />
            </label>
          </section>
        </template>
      </section>
    </div>
    <template #footer
      ><p v-if="error" role="alert" class="asset-error">{{ error }}</p>
      <div class="asset-footer">
        <span class="asset-footnote">本浏览器保存</span
        ><button class="asset-secondary" @click="closeForm">取消</button
        ><button v-if="templateEdit.v2" class="asset-primary" @click="confirmV2Template">
          确定
        </button>
        <button v-else class="asset-primary" @click="save">创建标注模版v1.0</button>
      </div></template
    ></el-dialog
  >

  <el-dialog
    :model-value="!!feedback"
    title="确认人工期望与自动规则"
    width="min(900px,96vw)"
    :close-on-click-modal="false"
    :show-close="!feedbackBusy"
    :close-on-press-escape="!feedbackBusy"
    @close="!feedbackBusy && (feedback = null)"
  >
    <template v-if="feedback">
      <p>
        {{
          feedback.mode === 'new' ? '创建独立测评集草稿' : '更新原测评集草稿中的当前用例'
        }}；已发布版本和历史结果不变。
      </p>
      <p>
        输出规则替换同路径旧输出期望；工具规则替换同名工具的对应约束，其余期望保留。人工分数、评语写入备注。
      </p>
      <label v-if="feedback.mode === 'new'"
        >新测评集名称<input
          v-model="feedback.name"
          :disabled="feedbackBusy || !!feedback.datasetId"
          aria-label="导出测评集名称"
          maxlength="128"
      /></label>
      <pre class="feedback-preview">{{ JSON.stringify(feedback.cases, null, 2) }}</pre>
      <p v-if="feedbackError" role="alert">{{ feedbackError }}</p>
    </template>
    <template #footer
      ><button class="asset-secondary" :disabled="feedbackBusy" @click="feedback = null">
        取消</button
      ><button
        class="asset-primary"
        :disabled="feedbackBusy || !!annotationStorageError"
        @click="applyFeedback"
      >
        {{ feedbackBusy ? '正在写入…' : '确认写入草稿' }}
      </button></template
    >
  </el-dialog>
  <AnnotationV2Workspace v-if="taskDetail?.template.v2" :task="taskDetail" @back="closeTask" />
  <section v-else-if="taskDetail" class="annotation-workspace asset-dialog">
    <nav class="annotation-crumbs">
      <button class="asset-link" @click="closeTask">人工标注</button><span>/</span
      ><button class="asset-link" @click="backToConversations">{{ taskDetail.name }}</button
      ><template v-if="editingConversation"><span>/</span><span>会话标注</span></template>
    </nav>
    <header class="annotation-heading">
      <div>
        <h1>
          {{ editingConversation ? cases.find((c) => c.id === caseId)?.name : taskDetail.name }}
        </h1>
        <p>
          {{ taskDetail.app.name }} · {{ taskDetail.template.name }}
          <span class="asset-chip">本浏览器保存</span>
        </p>
      </div>
      <button
        v-if="!editingConversation"
        class="asset-secondary"
        :disabled="runsLoading"
        @click="openTask(taskDetail)"
      >
        刷新会话</button
      ><button v-else class="asset-secondary" @click="backToConversations">返回会话列表</button>
    </header>
    <p v-if="annotationStorageError" role="alert" class="asset-error">
      {{ annotationStorageError }}
    </p>
    <div class="feedback-actions">
      <button
        class="asset-secondary"
        :disabled="
          feedbackBusy || annotationDirty || (!editingConversation && !checkedConversations.length)
        "
        @click="
          previewFeedback(
            'new',
            editingConversation ? [runId + '/' + caseId] : checkedConversations,
          )
        "
      >
        导出为新测评集草稿
      </button>
      <button
        class="asset-secondary"
        :disabled="
          feedbackBusy ||
          annotationDirty ||
          (!editingConversation && checkedConversations.length !== 1)
        "
        @click="
          previewFeedback(
            'writeback',
            editingConversation ? [runId + '/' + caseId] : checkedConversations,
          )
        "
      >
        回写原测评集期望
      </button>
      <p class="asset-small">
        仅处理已完整保存的标注。预览后写入草稿，审核发布后可使用 Final Output /
        工具规则评估器自动评分。
      </p>
      <p v-if="feedbackError" role="alert" class="asset-error">{{ feedbackError }}</p>
      <p v-if="feedbackSaved" role="status">
        目标测评集草稿：<a
          :href="'#datasets/' + encodeURIComponent(feedbackSaved) + '?version=draft'"
          >查看草稿并发布 / 发起自动测评</a
        >
      </p>
    </div>
    <template v-if="!editingConversation">
      <section class="annotation-kpis">
        <article>
          <span>会话数</span><b>{{ conversations.length }}</b>
        </article>
        <article>
          <span>已标注会话</span><b>{{ conversationStats.done }}</b>
        </article>
        <article>
          <span>标注轮次</span
          ><b
            >{{ conversationStats.marked }} <small>/ {{ conversationStats.turns }}</small></b
          ><progress :value="conversationStats.marked" :max="conversationStats.turns || 1" />
        </article>
        <article>
          <span>工具调用</span><b>{{ runsLoading ? '读取中…' : conversationStats.tools }}</b>
        </article>
      </section>
      <div class="annotation-filters">
        <input
          v-model="conversationQuery"
          aria-label="搜索会话名称"
          placeholder="搜索会话名称"
        /><select v-model="conversationStatus" aria-label="标注状态">
          <option value="">全部标注状态</option>
          <option v-for="(label, key) in statusNames" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>
      <p v-if="runsLoading" role="status" class="asset-small">正在读取已完成任务的会话…</p>
      <p v-if="traceError" role="alert" class="asset-error">{{ traceError }}</p>
      <div class="table-wrap">
        <table class="data-table annotation-table">
          <thead>
            <tr>
              <th>选择</th>
              <th>会话名称</th>
              <th>标注状态</th>
              <th>消息数</th>
              <th>进度</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in visibleConversations" :key="c.key">
              <td>
                <input
                  type="checkbox"
                  v-model="checkedConversations"
                  :value="c.key"
                  :disabled="progressFor(c).status !== 'done' || feedbackBusy"
                  :aria-label="'选择会话 ' + c.name"
                />
              </td>
              <td>
                <b>{{ c.name }}</b
                ><small
                  >{{ c.run.manifest.target.ref.external_version_id }} ·
                  {{ c.run.id.slice(0, 8) }}</small
                >
              </td>
              <td>
                <span
                  class="asset-chip"
                  :class="{ preview: progressFor(c).status === 'pending' }"
                  >{{
                    c.error ? '读取失败' : !c.trace ? '读取中' : statusNames[progressFor(c).status]
                  }}</span
                >
              </td>
              <td>
                {{
                  c.trace
                    ? Object.values(c.trace.turn_outcomes ?? {}).reduce(
                        (sum, t) => sum + (t.input != null ? 1 : 0) + (t.output != null ? 1 : 0),
                        0,
                      )
                    : '—'
                }}
              </td>
              <td>
                <template v-if="c.trace"
                  ><span class="marked">{{ progressFor(c).done }} 已标</span> ·
                  {{ progressFor(c).pending }} 待标 · {{ progressFor(c).ignored }} 已忽略
                  <small
                    >工具：{{ progressFor(c).toolsDone }}/{{ progressFor(c).toolsTotal }}</small
                  ></template
                ><span v-else>—</span>
              </td>
              <td>{{ new Date(c.run.created_at).toLocaleString() }}</td>
              <td>
                <div class="annotation-actions">
                  <button
                    class="asset-link"
                    :disabled="!c.trace || !progressFor(c).total"
                    @click="beginAnnotation(c)"
                  >
                    {{ progressFor(c).status === 'done' ? '查看标注' : '开始标注' }}</button
                  ><button
                    class="asset-link"
                    :disabled="!c.trace || progressFor(c).status === 'done'"
                    @click="skipConversation(c.key)"
                  >
                    {{ progressFor(c).status === 'skipped' ? '恢复会话' : '跳过会话' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!runsLoading && !filteredConversations.length" class="asset-empty">
        暂无符合条件的已完成会话
      </p>
      <footer class="annotation-pagination">
        <span>共 {{ filteredConversations.length }} 条会话</span
        ><button
          class="asset-secondary"
          :disabled="conversationPage === 1"
          @click="conversationPage--"
        >
          上一页</button
        ><span
          >{{ conversationPage }} /
          {{ Math.max(1, Math.ceil(filteredConversations.length / 20)) }}</span
        ><button
          class="asset-secondary"
          :disabled="conversationPage * 20 >= filteredConversations.length"
          @click="conversationPage++"
        >
          下一页
        </button>
      </footer>
    </template>
    <template v-else>
      <p v-if="traceLoading" role="status">正在读取会话…</p>
      <section v-for="(r, index) in rows" :key="r.id" class="annotation-editor">
        <div class="annotation-dialogue">
          <h3>第 {{ index + 1 }} 轮</h3>
          <h4>用户输入</h4>
          <pre tabindex="0">{{ displayValue(r.input) }}</pre>
          <h4>实际回答</h4>
          <pre tabindex="0">{{ displayValue(r.output) }}</pre>
        </div>
        <div class="annotation-scoring">
          <h3>人工评分</h3>
          <div class="asset-form-grid">
            <label v-for="d in taskDetail.template.message" :key="d.key"
              >{{ d.text }}（{{ taskDetail.template.min }}—{{ taskDetail.template.max }}）<input
                v-model.number="r.scores[d.key]"
                type="number"
                :min="taskDetail.template.min"
                :max="taskDetail.template.max"
                :aria-label="'标注分数 ' + d.key + ' ' + r.id"
            /></label>
          </div>
          <div class="asset-chips">
            <label v-for="tag in taskDetail.template.messageTags" :key="tag"
              ><input type="checkbox" v-model="r.tags" :value="tag" /> {{ tag }}</label
            >
          </div>
          <label>评语<textarea v-model="r.note" rows="3" /></label>
          <label
            >输出比较方式<select v-model="r.expectedMode" :aria-label="'输出比较方式 ' + r.id">
              <option value="equals">文本完全相等</option>
              <option value="contains">包含指定文本</option>
              <option value="matches_pattern">正则匹配</option>
              <option value="json">JSON 相等</option>
            </select></label
          >
          <label
            >输出字段路径<input
              v-model="r.expectedPath"
              :aria-label="'输出字段路径 ' + r.id"
              placeholder="例如 output；留空表示完整输出，需选择 JSON 相等"
          /></label>
          <label
            >人工期望输出<textarea
              v-model="r.expected"
              :aria-label="'人工期望输出 ' + r.id"
              rows="3"
              placeholder="人工填写，不从实际回答自动复制"
            />
          </label>
        </div>
      </section>
      <h2>工具调用标注</h2>
      <p v-if="!toolRows.length" class="asset-small">本会话没有工具调用证据；不生成虚构调用。</p>
      <section
        v-for="tool in toolRows"
        :key="tool.span_id"
        class="annotation-editor"
        :aria-label="'工具标注 ' + tool.name + ' ' + tool.span_id"
      >
        <div class="annotation-dialogue">
          <h3>{{ tool.name }}</h3>
          <p>轮次：{{ tool.turnId || '未关联' }} · {{ tool.span_id }}</p>
          <h4>调用参数</h4>
          <pre>{{
            displayValue(
              tool.attributes.arguments ??
                tool.attributes['trace_sdk.input'] ??
                tool.attributes.input,
            )
          }}</pre>
          <details>
            <summary>原始工具调用证据</summary>
            <pre>{{ JSON.stringify(tool.attributes, null, 2) }}</pre>
          </details>
          <h4>调用结果</h4>
          <pre>{{
            displayValue(
              tool.attributes['trace_sdk.output'] ??
                tool.attributes.output ??
                tool.attributes.result,
            )
          }}</pre>
        </div>
        <div class="annotation-scoring">
          <label v-for="d in taskDetail.template.tools" :key="d.key"
            >{{ d.text }}（{{ taskDetail.template.min }}—{{ taskDetail.template.max }}）
            <input
              type="number"
              v-model.number="tool.review.scores[d.key]"
              :min="taskDetail.template.min"
              :max="taskDetail.template.max"
              :aria-label="'工具分数 ' + d.key + ' ' + tool.span_id"
            />
          </label>
          <div class="asset-chips">
            <label v-for="tag in taskDetail.template.toolTags" :key="tag"
              ><input type="checkbox" v-model="tool.review.tags" :value="tag" />{{ tag }}</label
            >
          </div>
          <label
            >工具评语<textarea
              v-model="tool.review.note"
              :aria-label="'工具评语 ' + tool.span_id"
            />
          </label>
          <p class="asset-small">以下为可选自动规则；分数与评语仅作为人工审核记录。</p>
          <label
            >调用期望<select
              v-model="tool.review.expectation"
              :disabled="!tool.turnId"
              :aria-label="'调用期望 ' + tool.span_id"
            >
              <option value="none">不生成调用规则</option>
              <option value="required">必须调用</option>
              <option value="forbidden">禁止调用</option>
            </select></label
          >
          <label
            >参数匹配范围<select
              v-model="tool.review.occurrence"
              :disabled="!tool.turnId"
              :aria-label="'参数匹配范围 ' + tool.span_id"
            >
              <option value="all">该轮所有同名调用</option>
              <option value="any">该轮任意同名调用</option>
              <option value="first">第一次同名调用</option>
              <option value="last">最后一次同名调用</option>
            </select></label
          >
          <label
            >参数字段路径<input
              v-model="tool.review.argumentsPath"
              :disabled="!tool.turnId || tool.review.expectation === 'forbidden'"
              :aria-label="'参数字段路径 ' + tool.span_id"
              placeholder="arguments 或具体字段 application_id"
          /></label>
          <label
            >人工期望参数（JSON，选填）<textarea
              v-model="tool.review.argumentsExpected"
              :disabled="!tool.turnId || tool.review.expectation === 'forbidden'"
              :aria-label="'人工期望参数 ' + tool.span_id"
              placeholder='例如 {"amount":100}；不从实际参数自动复制'
            />
          </label>
        </div>
      </section>
      <p v-if="traceError" role="alert" class="asset-error">{{ traceError }}</p>
      <p v-if="saved" role="status" class="asset-small">{{ saved }}</p>
      <footer class="annotation-save">
        <button class="asset-secondary" @click="backToConversations">返回列表</button
        ><button
          class="asset-primary"
          :disabled="!rows.length || traceLoading || !!annotationStorageError"
          @click="saveAnnotations"
        >
          保存标注
        </button>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.v2-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: auto;
  padding-top: 18px;
}

.annotation-v2-section.is-disabled {
  background: #f3f4f6;
  border-color: #e2e5e8;
  color: #929aa3;
}
.annotation-v2-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.annotation-v2-heading h3 {
  color: inherit;
}
.annotation-v2-heading input[type='checkbox'] {
  width: 18px;
  height: 18px;
  margin: 0;
  flex: 0 0 18px;
  cursor: pointer;
  accent-color: #00aa8c;
}

.feedback-actions {
  margin: 16px 0;
}
.feedback-actions > button {
  margin-right: 12px;
}
.feedback-preview {
  max-height: 55vh;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.annotation-card {
  cursor: pointer;
  position: relative;
  padding-top: 42px;
}
.template-menu {
  position: absolute;
  top: 10px;
  right: 16px;
  z-index: 2;
}
.menu-trigger {
  font-size: 24px;
  line-height: 24px;
  padding: 0 8px;
}
.template-menu-items {
  position: absolute;
  right: 0;
  top: 30px;
  min-width: 150px;
  padding: 6px;
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 9px;
  box-shadow: 0 8px 28px #203f2720;
}
.template-menu-items button {
  display: block;
  border: 0;
  background: white;
  padding: 10px 14px;
  width: 100%;
  text-align: left;
  cursor: pointer;
  color: #34483e;
}
.template-menu-items button:hover {
  background: #f1f8f5;
}
.template-menu-items .delete-action {
  color: #ce4855;
}
.annotation-card:focus-visible {
  outline: 2px solid #00a88b;
  outline-offset: 3px;
}
.annotation-workspace {
  min-width: 0;
}
.annotation-crumbs {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
  color: #74897e;
}
.annotation-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
}
.annotation-heading h1 {
  font-size: 24px;
  margin: 0 0 12px;
}
.annotation-heading p {
  color: #7c8c85;
  font-size: 13px;
  margin: 0;
}
.annotation-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin: 20px 0;
}
.annotation-kpis article {
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.annotation-kpis span {
  font-size: 13px;
  color: #7d8e85;
}
.annotation-kpis b {
  font-size: 28px;
}
.annotation-kpis small {
  font-size: 20px;
  font-weight: 400;
  color: #95a29c;
}
.annotation-kpis progress {
  width: 100%;
  height: 6px;
  accent-color: #00aa8c;
}
.annotation-filters {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-bottom: 20px;
}
.annotation-filters input {
  max-width: 320px;
}
.annotation-filters select {
  max-width: 180px;
}
.annotation-table {
  background: white;
  min-width: 880px;
}
.annotation-table small {
  display: block;
  margin-top: 8px;
  color: #88988f;
  font-size: 12px;
}
.annotation-actions {
  display: flex;
  gap: 16px;
  white-space: nowrap;
}
.marked {
  color: #009f81;
}
.annotation-pagination {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 22px;
}
.annotation-pagination > span:first-child {
  margin-right: auto;
  color: #819188;
  font-size: 13px;
}
.annotation-editor {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 12px;
  margin-bottom: 20px;
  overflow: hidden;
}
.annotation-dialogue,
.annotation-scoring {
  padding: 24px;
  min-width: 0;
}
.annotation-scoring {
  border-left: 1px solid #e4ece7;
  background: #fbfdfc;
}
.annotation-dialogue pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 50vh;
  overflow: auto;
  background: #f4f8f6;
  padding: 18px;
  border-radius: 8px;
  line-height: 1.8;
  font-size: 13px;
}
.annotation-save {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  position: sticky;
  bottom: 0;
  background: #fff;
  border-top: 1px solid #dce7e1;
  padding: 16px;
}
@media (max-width: 900px) {
  .annotation-kpis {
    grid-template-columns: 1fr 1fr;
  }
  .annotation-editor {
    grid-template-columns: 1fr;
  }
  .annotation-scoring {
    border: 0;
    border-top: 1px solid #e4ece7;
  }
}
</style>
