<script setup lang="ts">
import { shallowRef, computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { request, type BankTarget, type EvaluationRun } from '../../../api/evaluations';
import type { Trace } from '../../../api/client';
import {
  annotationTemplates,
  annotationTasks,
  annotationStorageError,
  ensureAnnotationExample,
  copy,
  validateCriteria,
  type AnnotationTemplate,
  type AnnotationTask,
} from '../../../stores/review-assets';
import '../../../styles/review-assets.scss';
import { annotationProgress } from '../utils/annotation-progress';
import { displayValue } from '../utils/task-report';
const props = defineProps<{ templates?: boolean; taskId?: string }>(),
  emit = defineEmits<{ dirtyChange: [value: boolean]; navigate: [path: string] }>();
const query = ref(''),
  error = ref(''),
  form = ref(false),
  busy = ref(false),
  templateDetail = ref<AnnotationTemplate | null>(null),
  taskDetail = ref<AnnotationTask | null>(null);
const templateEdit = ref<AnnotationTemplate>(copy(annotationTemplates.value[0]));
const taskName = ref(''),
  taskDescription = ref(''),
  application = ref(''),
  templateId = ref(annotationTemplates.value[0].id);
const targets = ref<BankTarget[]>([]),
  targetError = ref('');
const chosenTemplate = computed(() =>
  annotationTemplates.value.find((t) => t.id === templateId.value),
);
const appKey = (t: BankTarget) =>
  JSON.stringify([
    t.descriptor.ref.source_id,
    t.descriptor.ref.target_type,
    t.descriptor.ref.external_target_id,
  ]);
const apps = computed(() => Array.from(new Map(targets.value.map((t) => [appKey(t), t])).values()));
const filteredTemplates = computed(() =>
  annotationTemplates.value.filter((t) => `${t.name} ${t.description}`.includes(query.value)),
);
const showDeleted = ref(false),
  cardMenu = ref(''),
  basicEdit = ref<AnnotationTask | null>(null),
  basicName = ref(''),
  basicDescription = ref(''),
  basicError = ref('');
const deletedTasks = computed(() => annotationTasks.value.filter((t) => t.deletedAt));
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
  if (
    !window.confirm(`删除“${t.name}”？模板将移入已删除列表，可恢复。已有标注和原始评测会话会保留。`)
  )
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
  if (!t.deletedAt) emit('navigate', 'annotations/' + t.id);
}
async function loadTargets() {
  targetError.value = '';
  busy.value = true;
  try {
    targets.value = await request<BankTarget[]>('/bank-targets');
  } catch {
    targetError.value = '关联应用读取失败，请重试。';
  } finally {
    busy.value = false;
  }
}
function openCreate(source?: AnnotationTemplate) {
  error.value = '';
  templateEdit.value = copy(source ?? annotationTemplates.value[0]);
  templateEdit.value.id = crypto.randomUUID();
  templateEdit.value.name = source ? source.name + '（副本）' : '';
  taskName.value = '';
  taskDescription.value = '';
  application.value = '';
  templateId.value = annotationTemplates.value[0].id;
  templateDetail.value = null;
  form.value = true;
  void loadTargets();
}
function closeForm() {
  if (!window.confirm('放弃当前未保存的配置？')) return;
  form.value = false;
}
function save() {
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
  {
    const target = apps.value.find((t) => appKey(t) === application.value);
    if (!templateEdit.value.name.trim() || !target) {
      error.value = '请填写模板名称并选择关联智能体。';
      return;
    }
    annotationTasks.value.unshift({
      id: crypto.randomUUID(),
      name: templateEdit.value.name.trim(),
      description: templateEdit.value.description,
      app: { ...target.descriptor.ref, name: target.descriptor.display_name },
      template: copy(templateEdit.value),
      annotations: {},
    });
  }
  annotationTemplates.value.unshift(copy(templateEdit.value));
  form.value = false;
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
};
const rows = ref<Row[]>([]);
const baseline = ref('[]');
const annotationDirty = computed(() => JSON.stringify(rows.value) !== baseline.value);
watch([form, annotationDirty, basicEdit], ([formDirty, rowDirty, basic]) =>
  emit('dirtyChange', formDirty || rowDirty || !!basic),
);
function canLeave() {
  return !annotationDirty.value || window.confirm('当前会话有未保存的标注，确定放弃？');
}
function closeTask() {
  if (!canLeave()) return;
  taskDetail.value = null;
  rows.value = [];
  baseline.value = '[]';
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
  return annotationProgress(
    Object.keys(c.trace?.turn_outcomes ?? {}),
    t?.annotations ?? {},
    c.key,
    t?.template.message.map((d) => d.key) ?? [],
    t?.template.min ?? 0,
    t?.template.max ?? 5,
    t?.skippedConversations?.includes(c.key),
  );
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
  saved.value = '';
  runs.value = [];
  traceError.value = '';
  runsLoading.value = true;
  const ticket = ++runSequence;
  try {
    const list = await request<EvaluationRun[]>('/runs?limit=200');
    if (ticket !== runSequence) return;
    runs.value = list.filter((r) => {
      const a = r.manifest.target.ref;
      return (
        r.status === 'completed' &&
        a.source_id === task.app.source_id &&
        a.target_type === task.app.target_type &&
        a.external_target_id === task.app.external_target_id
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
    if (ticket === runSequence) traceError.value = '读取关联评测失败，请重试。';
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
            }),
      };
    });
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
  for (const r of rows.value)
    task.annotations[`${runId.value}/${caseId.value}/${r.id}`] = copy({
      scores: r.scores,
      tags: r.tags,
      note: r.note,
      expected: r.expected,
    });
  task.skippedConversations = task.skippedConversations?.filter(
    (key) => key !== runId.value + '/' + caseId.value,
  );
  if (annotationStorageError.value) {
    traceError.value = annotationStorageError.value;
    saved.value = '';
    return;
  }
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
onMounted(async () => {
  if (!props.templates) {
    void loadTargets();
    try {
      await ensureAnnotationExample();
    } catch (e) {
      error.value = String(e);
    }
  }
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
              : '关联应用与已有评测会话，依据标注模板进行人工评审。'
          }}
        </p>
      </div>
      <button class="asset-primary" @click="openCreate()">
        ＋ {{ templates ? '新建标注模板' : '创建标注模板' }}
      </button>
    </div>
    <p class="asset-note">保存在本浏览器 · 未入后端库</p>
    <p v-if="error || annotationStorageError" class="asset-error" role="alert">
      {{ error || annotationStorageError }}
    </p>
    <div class="asset-filters">
      <input
        v-model="query"
        aria-label="搜索标注模板"
        :placeholder="templates ? '搜索模板名称或描述' : '搜索模板名称或关联智能体'"
      /><button
        v-if="!templates"
        class="asset-link"
        @click="
          showDeleted = !showDeleted;
          cardMenu = '';
        "
      >
        {{ showDeleted ? '返回模板列表' : '已删除（' + deletedTasks.length + '）' }}
      </button>
    </div>
    <div class="asset-grid">
      <template v-if="templates"
        ><article v-for="t in filteredTemplates" :key="t.id" class="asset-card">
          <span class="asset-chip preview">{{
            t.id === 'annotation-default-ux' ? '默认模板 · UX' : 'UX 草稿 · 未入库'
          }}</span>
          <h2>{{ t.name }}</h2>
          <p>{{ t.description || '暂无描述' }}</p>
          <div class="asset-chips">
            <span class="asset-chip">消息 {{ t.message.length }} 项</span
            ><span class="asset-chip">工具 {{ t.tools.length }} 项</span
            ><span class="asset-chip">{{ t.min }}—{{ t.max }} 分</span>
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
          <h2>{{ t.name }}</h2>
          <p v-if="t.description">{{ t.description }}</p>
          <p>{{ t.app.name }} · {{ t.app.external_target_id }}</p>
          <p>
            模板：{{ t.template.name }} · 已存 {{ Object.keys(t.annotations).length }} 条消息标注
          </p>
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
      <p class="asset-small">
        评分范围：{{ templateDetail.min }}—{{ templateDetail.max }}；工具维度可选。
      </p>
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
      </section></template
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
    title="创建标注模板"
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
        <label
          >关联智能体 *<select v-model="application" aria-label="标注关联智能体" :disabled="busy">
            <option value="">请选择智能体</option>
            <option v-for="t in apps" :key="appKey(t)" :value="appKey(t)">
              {{ t.descriptor.ref.external_target_id }} · {{ t.descriptor.display_name }}
            </option>
          </select></label
        >
        <button class="asset-link" :disabled="busy" @click="loadTargets">刷新智能体</button>
        <p v-if="targetError" role="alert" class="asset-error">{{ targetError }}</p>
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
        <h3>② 评分配置</h3>
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
      </section>
    </div>
    <template #footer
      ><p v-if="error" role="alert" class="asset-error">{{ error }}</p>
      <div class="asset-footer">
        <span class="asset-footnote">本浏览器保存</span
        ><button class="asset-secondary" @click="closeForm">取消</button
        ><button class="asset-primary" @click="save">创建标注模板</button>
      </div></template
    ></el-dialog
  >

  <section v-if="taskDetail" class="annotation-workspace asset-dialog">
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
                  {{ progressFor(c).pending }} 待标 · {{ progressFor(c).ignored }} 已忽略</template
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
          <label>评语<textarea v-model="r.note" rows="3" /></label
          ><label
            >人工期望输出<textarea
              v-model="r.expected"
              rows="3"
              placeholder="人工填写，不从实际回答自动复制"
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
