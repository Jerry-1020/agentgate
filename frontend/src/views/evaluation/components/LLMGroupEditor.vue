<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { request } from '../../../api/evaluations';
import { loadReviewAssets } from '../../../stores/review-assets';
import { modelRefLabel, type EvaluatorModelRef } from '../utils/evaluator-model';
import {
  evaluatorTemplates,
  promptModelOptions,
  promptVariableNames,
} from '../utils/evaluator-templates';
import LLMGroupTemplateCard from './LLMGroupTemplateCard.vue';
import {
  emptyLLMGroup,
  equalLLMWeights,
  llmGroupDate,
  llmGroupError,
  llmGroupPayload,
  llmGroupTemplates,
  newLLMChild,
  newLLMGroupFromTemplate,
  readLLMGroup,
  type GroupDefinition,
  type LLMGroupDetail,
} from '../utils/evaluator-group';

const props = defineProps<{
  initialId?: string;
  chooseTemplateFirst?: boolean;
  models: [string, EvaluatorModelRef][];
}>();
const emit = defineEmits<{
  close: [];
  started: [];
  dirtyChange: [value: boolean];
  launch: [id: string];
}>();
const detail = ref<LLMGroupDetail | null>(null);
const form = ref(emptyLLMGroup());
const editing = ref(!props.initialId),
  loading = ref(!!props.initialId),
  busy = ref(false);
const selected = ref(''),
  error = ref(''),
  notice = ref('');
const baseline = ref(JSON.stringify(form.value));
const basicsOpen = ref(!props.initialId),
  advancedOpen = ref(false),
  expanded = ref(false);
const choosingStart = ref(!props.initialId && !!props.chooseTemplateFirst);
const templateOpen = ref(choosingStart.value);
const templateQuery = ref('');
const historyOpen = ref(false),
  historyLoading = ref(false),
  historyError = ref('');
const versions = ref<GroupDefinition[]>([]);
const modelLoading = ref(false),
  modelError = ref('');
const connections = ref<{ configured: boolean; provider_id?: string; model: string }[]>([]);
const active = computed(() => form.value.children.find((child) => child.key === selected.value));
const promptVariables = computed(() =>
  promptVariableNames(active.value?.instruction, active.value?.userPrompt),
);
const dirty = computed(() => editing.value && JSON.stringify(form.value) !== baseline.value);
const modelOptions = computed(() => promptModelOptions(connections.value, props.models));
const currentModelMissing = computed(
  () =>
    active.value?.modelKey && !modelOptions.value.some(([key]) => key === active.value?.modelKey),
);
const currentTemplate = computed(() =>
  evaluatorTemplates.find((item) => item.id === active.value?.templateId),
);
const promptAdjusted = computed(
  () => currentTemplate.value && currentTemplate.value.instruction !== active.value?.instruction,
);
const visibleGroupTemplates = computed(() =>
  llmGroupTemplates.filter((template) =>
    (template.name + template.description).includes(templateQuery.value.trim()),
  ),
);
const totalWeight = computed(() =>
  Number(
    form.value.children.reduce((sum, child) => sum + (Number(child.weight) || 0), 0).toFixed(6),
  ),
);
const canLaunch = computed(
  () =>
    !editing.value &&
    !detail.value?.viewing_draft &&
    detail.value?.evaluator.enabled &&
    detail.value.definition.version === detail.value.latest_version,
);
const stateLabel = computed(() =>
  detail.value?.viewing_draft || editing.value
    ? '草稿'
    : detail.value?.evaluator.enabled
      ? '已启用'
      : '已停用',
);
const originalRubric = computed(() => {
  const rubric = active.value?.original?.config.rubric;
  return rubric &&
    JSON.stringify(rubric) !== JSON.stringify({ overall: '按照提示词中的评分标准评估。' })
    ? rubric
    : null;
});
watch([dirty, busy], ([changed, pending]) => emit('dirtyChange', changed || pending));

function groupPath() {
  return '/evaluators/' + encodeURIComponent(form.value.id || props.initialId || '') + '/llm-group';
}
function show(value: LLMGroupDetail) {
  detail.value = value;
  form.value = readLLMGroup(value);
  if (!form.value.children.some((child) => child.key === selected.value))
    selected.value = form.value.children[0]?.key ?? '';
  baseline.value = JSON.stringify(form.value);
  editing.value = false;
  basicsOpen.value = false;
}
async function load(version?: string) {
  loading.value = true;
  error.value = '';
  try {
    show(
      await request<LLMGroupDetail>(
        groupPath() + (version ? '?version=' + encodeURIComponent(version) : ''),
      ),
    );
  } catch (cause) {
    error.value = String(cause);
  } finally {
    loading.value = false;
  }
}
async function loadModels() {
  modelLoading.value = true;
  modelError.value = '';
  try {
    const result = await request<{ connections: typeof connections.value }>('/model-runtime');
    connections.value = result.connections;
  } catch {
    modelError.value = '暂时无法读取模型配置，请重试。';
  } finally {
    modelLoading.value = false;
  }
}
async function edit() {
  if (busy.value || loading.value) return;
  if (detail.value?.has_draft && !detail.value.viewing_draft) {
    await load();
    if (error.value) return;
  }
  editing.value = true;
  baseline.value = JSON.stringify(form.value);
  error.value = '';
  notice.value = '';
}
function close() {
  if (busy.value || (dirty.value && !window.confirm('放弃未保存的评估器修改？'))) return;
  emit('close');
}
function cancelEdit() {
  if (busy.value || (dirty.value && !window.confirm('放弃未保存的评估器修改？'))) return;
  if (!detail.value) emit('close');
  else show(detail.value);
}
async function save(publishAfter = false) {
  if (busy.value || loading.value) return;
  error.value = llmGroupError(form.value);
  if (error.value) return;
  busy.value = true;
  notice.value = '';
  let saved = false;
  try {
    const value = await request<LLMGroupDetail>(
      form.value.id ? groupPath() + '/draft' : '/evaluators/llm-groups',
      form.value.id ? 'PUT' : 'POST',
      llmGroupPayload(form.value, detail.value),
    );
    show(value);
    saved = true;
    if (publishAfter) {
      show(
        await request<LLMGroupDetail>(groupPath() + '/publish', 'POST', {
          expected_draft_id: detail.value!.definition.id,
          expected_draft_updated_at: detail.value!.definition.updated_at,
        }),
      );
      notice.value = `v${detail.value!.definition.version} 已发布并启用，所有子评估器版本已固定。`;
    } else notice.value = '草稿已保存。发布并启用后可被测评任务选中。';
    await loadReviewAssets();
  } catch (cause) {
    error.value = saved ? '草稿已保存，但发布未完成：' + String(cause) : String(cause);
    if (saved) await loadReviewAssets();
  } finally {
    busy.value = false;
  }
}
async function publish() {
  if (busy.value || editing.value || !detail.value?.viewing_draft) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    show(
      await request<LLMGroupDetail>(groupPath() + '/publish', 'POST', {
        expected_draft_id: detail.value.definition.id,
        expected_draft_updated_at: detail.value.definition.updated_at,
      }),
    );
    await loadReviewAssets();
    notice.value = `v${detail.value!.definition.version} 已发布并启用，所有子评估器版本已固定。`;
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function setEnabled() {
  if (busy.value || !detail.value?.latest_version) return;
  busy.value = true;
  error.value = '';
  try {
    const enabled = !detail.value.evaluator.enabled;
    await request('/evaluators/' + encodeURIComponent(form.value.id), 'PATCH', { enabled });
    detail.value.evaluator.enabled = enabled;
    await loadReviewAssets();
    notice.value = enabled ? '评估器已启用。' : '评估器已停用。';
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function deleteDraft() {
  if (
    busy.value ||
    !detail.value?.viewing_draft ||
    !window.confirm('删除此评估器草稿？已发布版本及历史任务不会改变。')
  )
    return;
  busy.value = true;
  error.value = '';
  try {
    await request(groupPath() + '/draft', 'DELETE', {
      expected_draft_id: detail.value.definition.id,
      expected_draft_updated_at: detail.value.definition.updated_at,
    });
    await loadReviewAssets();
    emit('close');
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function showHistory() {
  if (!detail.value || busy.value) return;
  historyOpen.value = true;
  historyLoading.value = true;
  historyError.value = '';
  try {
    versions.value = await request<GroupDefinition[]>(
      '/evaluators/' + encodeURIComponent(form.value.id) + '/versions',
    );
  } catch (cause) {
    historyError.value = String(cause);
  } finally {
    historyLoading.value = false;
  }
}
async function viewVersion(version: string) {
  await load(version);
  if (!error.value) {
    historyOpen.value = false;
    notice.value = '正在查看已发布版本及其固定的子评估器配置。';
  }
}
function startForm() {
  if (choosingStart.value) {
    choosingStart.value = false;
    emit('started');
  }
  templateOpen.value = false;
}
function addChild() {
  const child = newLLMChild(crypto.randomUUID(), null, form.value.children.length ? 0 : 100);
  form.value.children.push(child);
  selected.value = child.key;
  advancedOpen.value = false;
}
async function addCustomChild() {
  if (busy.value || loading.value) return;
  if (!editing.value) await edit();
  if (!editing.value || busy.value) return;
  if (form.value.children.length >= 32) {
    error.value = '最多添加 32 个子评估器。';
    return;
  }
  error.value = '';
  addChild();
}
function applyGroupTemplate(id: string) {
  if (!choosingStart.value) return;
  form.value = newLLMGroupFromTemplate(id, crypto.randomUUID());
  selected.value = form.value.children[0].key;
  startForm();
}
function createCustom() {
  if (!choosingStart.value) return;
  addChild();
  startForm();
}
function closeTemplates() {
  if (choosingStart.value) emit('close');
}
function removeChild(key: string) {
  if (!editing.value || busy.value) return;
  const index = form.value.children.findIndex((item) => item.key === key);
  const child = form.value.children[index];
  if (!child || !window.confirm(`删除子评估器“${child.name || '未命名'}”？保存草稿后生效。`))
    return;
  form.value.children = form.value.children.filter((item) => item.key !== key);
  if (selected.value === key)
    selected.value =
      form.value.children[Math.min(index, form.value.children.length - 1)]?.key ?? '';
}
function equalize() {
  const weights = equalLLMWeights(form.value.children.length);
  form.value.children.forEach((child, index) => {
    child.weight = weights[index];
  });
  error.value = '';
}
function clearPrompts() {
  if (!active.value) return;
  active.value.instruction = '';
  active.value.userPrompt = null;
  active.value.templateId = null;
}
async function copyPrompt() {
  if (!active.value) return;
  try {
    await navigator.clipboard.writeText(active.value.instruction);
    notice.value = '提示词已复制。';
  } catch {
    notice.value = '无法访问剪贴板，请在提示词编辑框中选择并复制。';
  }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value && !busy.value) return;
  event.preventDefault();
  event.returnValue = '';
}
onMounted(() => {
  if (props.initialId) void load();
  else if (!choosingStart.value) addChild();
  void loadModels();
  window.addEventListener('beforeunload', beforeUnload);
});
onUnmounted(() => {
  window.removeEventListener('beforeunload', beforeUnload);
  emit('dirtyChange', false);
});
</script>

<template>
  <section v-if="!choosingStart" class="llm-group-editor" aria-label="LLM 子评估器表单">
    <header class="group-toolbar">
      <button class="text-button" :disabled="busy" @click="close">← 返回评估器列表</button>
      <div v-if="detail && !editing" class="actions">
        <button
          v-if="detail.latest_version"
          class="secondary-button"
          :disabled="busy || loading"
          @click="showHistory"
        >
          版本历史
        </button>
        <button class="primary-button" :disabled="busy || loading" @click="edit">
          {{ detail.has_draft ? '编辑草稿' : '编辑新版本' }}
        </button>
      </div>
    </header>
    <p v-if="loading" class="loading-state" role="status">正在读取评估器及子评估器配置…</p>
    <template v-else>
      <section class="group-overview" aria-label="评估器基本信息">
        <div v-if="detail" class="group-identity">
          <span class="group-symbol" aria-hidden="true">◇</span>
          <div class="group-title">
            <div class="title-row">
              <h1>{{ form.name || '新建评估器' }}</h1>
              <span class="status-tag" :class="{ muted: stateLabel === '已停用' }">{{
                stateLabel
              }}</span
              ><span class="kind-tag">LLM 评估器</span
              ><span v-if="detail && !detail.viewing_draft" class="kind-tag"
                >v{{ detail.definition.version }}</span
              >
            </div>
            <p>{{ form.description || '添加备注描述，说明此评估器的用途。' }}</p>
            <div class="metadata">
              <span>{{ form.children.length }} 个子评估器</span
              ><span>创建日期：{{ llmGroupDate(detail?.evaluator.created_at) }}</span
              ><span>更新日期：{{ llmGroupDate(detail?.evaluator.updated_at) }}</span>
            </div>
          </div>
          <button
            class="text-button"
            :disabled="busy"
            :aria-expanded="basicsOpen"
            @click="basicsOpen = !basicsOpen"
          >
            {{ basicsOpen ? '收起基本信息' : '基本信息' }}
          </button>
        </div>
        <fieldset v-if="!detail || basicsOpen" class="basic-fields" :disabled="busy">
          <label
            >评估器名称 <em>*</em
            ><input
              v-model="form.name"
              aria-label="评估器名称"
              maxlength="50"
              :readonly="!editing"
              placeholder="请输入评估器名称"
            /><small>{{ form.name.length }}/50</small></label
          >
          <label class="description-field"
            >备注描述<input
              v-model="form.description"
              aria-label="评估器备注描述"
              maxlength="200"
              :readonly="!editing"
              placeholder="请输入备注描述"
            /><small>{{ form.description.length }}/200</small></label
          >
        </fieldset>
      </section>

      <div class="group-workspace">
        <aside class="child-sidebar" aria-label="子评估器列表">
          <header>
            <h2>
              子评估器 <small>{{ form.children.length }}</small>
            </h2>
            <button
              class="text-button"
              :disabled="busy || loading || form.children.length >= 32"
              @click="addCustomChild"
            >
              ＋ 新增
            </button>
          </header>
          <p class="sidebar-help">每个子评估器独立配置模型和评分标准。</p>
          <div
            v-for="child in form.children"
            :key="child.key"
            class="child-row"
            :class="{ active: selected === child.key }"
          >
            <button
              class="child-select"
              :aria-label="'配置子评估器 ' + (child.name || '未命名')"
              :aria-pressed="selected === child.key"
              :disabled="busy"
              @click="
                selected = child.key;
                advancedOpen = false;
              "
            >
              <span class="child-name">{{ child.name || '未命名子评估器' }}</span
              ><small>{{ child.templateId ? '预置子项' : '自定义' }}</small>
            </button>
            <label v-if="editing" class="weight-input"
              ><input
                v-model.number="child.weight"
                type="number"
                min="0.01"
                max="100"
                step="0.01"
                :disabled="busy"
                :aria-label="(child.name || '未命名') + '权重'"
              />%</label
            ><span v-else class="weight-label">{{ child.weight }}%</span>
            <button
              v-if="editing"
              class="text-button danger child-delete"
              :disabled="busy"
              :aria-label="'删除子评估器 ' + (child.name || '未命名')"
              @click="removeChild(child.key)"
            >
              删除
            </button>
          </div>
          <p v-if="!form.children.length" class="empty-state">
            还没有子评估器<br />点击“新增”直接创建子评估器。
          </p>
          <section class="aggregation">
            <div class="weight-total">
              <span>权重合计</span
              ><strong :class="{ invalid: totalWeight !== 100 }">{{ totalWeight }}%</strong>
            </div>
            <button
              v-if="editing && form.children.length > 1"
              class="text-button"
              :disabled="busy"
              @click="equalize"
            >
              均分权重
            </button>
            <p>综合得分 = 各子评估器得分按权重加权平均。权重合计须为 100%。</p>
            <label
              >综合通过分数<input
                v-model.number="form.threshold"
                aria-label="综合通过分数"
                type="number"
                min="0"
                max="1"
                step="0.05"
                :readonly="!editing"
                :disabled="busy"
            /></label>
          </section>
        </aside>

        <fieldset v-if="active" class="child-configuration" :disabled="busy">
          <header class="child-heading">
            <div>
              <h2>{{ active.name || '配置子评估器' }}</h2>
              <p>
                {{
                  currentTemplate
                    ? '综合模板子项：' +
                      currentTemplate.name +
                      (promptAdjusted ? ' · 提示词已调整' : '')
                    : '自定义子评估器'
                }}
              </p>
            </div>
          </header>
          <div class="child-basics">
            <label
              >子评估器名称 <em>*</em
              ><input
                v-model="active.name"
                aria-label="子评估器名称"
                maxlength="50"
                :readonly="!editing"
                placeholder="请输入子评估器名称" /></label
            ><label
              >备注描述<input
                v-model="active.description"
                aria-label="子评估器备注描述"
                maxlength="200"
                :readonly="!editing"
                placeholder="描述此评估维度"
            /></label>
          </div>
          <label class="field-label" for="group-child-model">模型选择 <em>*</em></label>
          <div class="model-row">
            <select
              v-if="editing"
              id="group-child-model"
              v-model="active.modelKey"
              aria-label="子评估器模型"
            >
              <option value="">{{ modelLoading ? '正在读取模型…' : '请选择模型' }}</option>
              <option v-if="currentModelMissing" :value="active.modelKey">
                {{ modelRefLabel(active.modelKey) }}（原配置）
              </option>
              <option v-for="[key, model] in modelOptions" :key="key" :value="key">
                {{ model.model_id }} · {{ model.provider_id }}
              </option>
            </select>
            <div v-else class="model-readonly">{{ modelRefLabel(active.modelKey) }}</div>
            <button
              class="settings-button"
              aria-label="子评估器高级设置"
              :aria-expanded="advancedOpen"
              @click="advancedOpen = !advancedOpen"
            >
              ⚙
            </button>
          </div>
          <p v-if="modelError" class="help-text" role="alert">
            {{ modelError }} <button class="text-button" @click="loadModels">重试</button>
          </p>
          <p v-else-if="!modelLoading && !modelOptions.length && editing" class="help-text">
            暂无可选模型，请先在配置中接入模型。<a href="#/settings">前往配置</a>
          </p>
          <div v-if="advancedOpen" class="advanced-settings">
            <label
              >通过分数（0.0—1.0）<input
                v-model.number="active.threshold"
                aria-label="子评估器通过分数"
                type="number"
                min="0"
                max="1"
                step="0.05"
                :readonly="!editing"
            /></label>
            <p>子评估器按此阈值判定通过；综合得分使用左侧的权重和综合通过分数。</p>
            <p
              v-if="
                active.original?.config.input_selection &&
                active.original.config.input_selection !== 'final_output'
              "
            >
              此版本保留原有的评审输入范围。
            </p>
            <details v-if="originalRubric">
              <summary>此版本保留的评分标准</summary>
              <pre>{{ JSON.stringify(originalRubric, null, 2) }}</pre>
            </details>
          </div>

          <div class="prompt-toolbar">
            <h3>Prompt <em>*</em></h3>
            <div v-if="editing" class="actions">
              <button class="text-button" @click="clearPrompts">清空</button>
            </div>
          </div>
          <div class="prompt-editor">
            <header>
              <strong>System</strong>
              <div class="actions">
                <button
                  class="text-button"
                  aria-label="展开 System Prompt"
                  @click="expanded = true"
                >
                  ⤢ 全屏</button
                ><button class="text-button" aria-label="复制 System Prompt" @click="copyPrompt">
                  ⧉ 复制
                </button>
              </div>
            </header>
            <textarea
              v-model="active.instruction"
              aria-label="System Prompt"
              :readonly="!editing"
              :placeholder="'请输入内容，支持 {{input}}、{{output}}'"
              spellcheck="false"
              rows="15"
            />
          </div>
          <div v-if="active.userPrompt !== null" class="prompt-editor user-prompt">
            <header>
              <strong>User</strong
              ><button v-if="editing" class="text-button" @click="active.userPrompt = null">
                移除 User Prompt
              </button>
            </header>
            <textarea
              v-model="active.userPrompt"
              aria-label="User Prompt"
              :readonly="!editing"
              rows="5"
              :placeholder="'请输入内容，支持 {{input}}、{{output}}'"
              spellcheck="false"
            />
          </div>
          <button v-else-if="editing" class="add-user-button" @click="active.userPrompt = ''">
            ＋ 添加 User Prompt
          </button>
          <p v-if="promptVariables.length" class="help-text" aria-label="Prompt 变量">
            变量
            <template v-for="(variable, index) in promptVariables" :key="variable">
              <span v-if="index">；</span>
              <code v-text="'{{ ' + variable + ' }}'"></code>
              <span v-if="variable === 'input'"> 为用例输入</span>
              <span v-else-if="variable === 'output'"> 为被测 Agent 的最终回答</span>
            </template>
          </p>
          <section class="output-description">
            <h3>输出</h3>
            <p><strong>得分：</strong>0.0—1.0，表示满足评分标准的程度。</p>
            <p><strong>原因：</strong>说明评分依据与扣分原因。任务保留每个子评估器的得分和原因。</p>
          </section>
        </fieldset>
        <section v-else class="child-configuration empty-configuration">
          <h2>添加第一个子评估器</h2>
          <p>新增子评估器，填写名称、模型和评分标准。</p>
          <button class="primary-button" :disabled="busy" @click="addCustomChild">
            ＋ 新增子评估器
          </button>
        </section>
      </div>
    </template>
    <p v-if="notice" class="notice-message" role="status">{{ notice }}</p>
    <p v-if="error" class="error-message" role="alert">
      {{ error
      }}<button
        v-if="loading === false && initialId && !detail"
        class="text-button"
        @click="load()"
      >
        重试
      </button>
    </p>
    <footer class="group-footer">
      <p>测评任务选择整个评估器，结果保留综合得分与各子评估器结论。</p>
      <div class="actions">
        <button v-if="editing" class="secondary-button" :disabled="busy" @click="cancelEdit">
          取消编辑
        </button>
        <button
          v-else-if="detail?.viewing_draft"
          class="text-button danger"
          :disabled="busy"
          @click="deleteDraft"
        >
          删除草稿
        </button>
        <button
          v-if="editing"
          class="secondary-button"
          :disabled="busy || loading"
          @click="save(false)"
        >
          {{ busy ? '处理中…' : '保存草稿' }}
        </button>
        <button
          v-if="editing"
          class="primary-button"
          :disabled="busy || loading"
          @click="save(true)"
        >
          发布并启用
        </button>
        <button
          v-else-if="detail?.viewing_draft"
          class="primary-button"
          :disabled="busy"
          @click="publish"
        >
          发布并启用
        </button>
        <button
          v-if="!editing && detail?.latest_version"
          class="secondary-button"
          :disabled="busy"
          @click="setEnabled"
        >
          {{ detail.evaluator.enabled ? '停用' : '启用' }}
        </button>
        <button
          v-if="canLaunch"
          class="primary-button"
          :disabled="busy"
          @click="emit('launch', form.id)"
        >
          打开测评配置
        </button>
      </div>
    </footer>
  </section>

  <el-dialog
    v-model="templateOpen"
    title="评估器模板"
    width="min(1180px,94vw)"
    class="llm-group-template-dialog llm-group-create-template-dialog"
    :close-on-click-modal="false"
    @close="closeTemplates"
  >
    <div class="group-template-layout start-template-layout">
      <aside class="template-sidebar">
        <h3>类型</h3>
        <span class="selected-type">LLM</span>
        <h3>场景</h3>
        <p>评估对象</p>
        <span class="filter-tag">文本</span>
        <p>评估目标</p>
        <span class="filter-tag">内容质量</span>
        <p>业务场景</p>
        <span class="filter-tag">AIGC</span>
      </aside>
      <div class="template-main">
        <div class="template-search">
          <input
            v-model="templateQuery"
            aria-label="搜索评估器模板"
            placeholder="搜索评估器模板"
          /><button class="llm-template-create-button" @click="createCustom">
            ＋ 自定义创建 LLM 评估器
          </button>
        </div>
        <p class="template-help">选择综合评估器模板，应用后可配置、删除或新增其中的子评估器。</p>
        <div class="template-cards">
          <LLMGroupTemplateCard
            v-for="template in visibleGroupTemplates"
            :key="template.id"
            :template="template"
            :disabled="busy"
            @apply="applyGroupTemplate"
          />
        </div>
        <p v-if="!visibleGroupTemplates.length" class="empty-state">没有匹配的模板，请调整搜索。</p>
        <div class="template-bottom">
          <span>共计 {{ visibleGroupTemplates.length }} 项</span>
        </div>
      </div>
    </div>
  </el-dialog>
  <el-dialog v-model="expanded" title="System Prompt" width="min(1100px,94vw)">
    <textarea
      v-if="active"
      v-model="active.instruction"
      class="expanded-prompt"
      aria-label="展开的 System Prompt"
      :readonly="!editing"
      :disabled="busy"
      spellcheck="false"
    />
  </el-dialog>
  <el-dialog v-model="historyOpen" title="已发布版本" width="540px"
    ><p>已发布版本只读，历史任务保留父评估器及其全部子评估器的版本。</p>
    <p v-if="historyLoading">正在读取版本…</p>
    <p v-if="historyError" role="alert">{{ historyError }}</p>
    <p v-for="version in versions" :key="version.version">
      <button class="text-button" :disabled="loading" @click="viewVersion(version.version!)">
        查看 v{{ version.version }}
      </button>
    </p></el-dialog
  >
</template>

<style scoped>
.llm-group-editor {
  color: var(--el-text-color-primary);
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  overflow: hidden;
}
.group-toolbar,
.group-footer,
.actions,
.title-row,
.metadata,
.child-heading,
.prompt-toolbar,
.prompt-editor header,
.template-search,
.template-bottom {
  display: flex;
  align-items: center;
  gap: 12px;
}
.group-toolbar {
  padding: 18px 24px;
  justify-content: space-between;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
button,
input,
textarea,
select {
  font: inherit;
  box-sizing: border-box;
}
button {
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.primary-button,
.secondary-button {
  border: 1px solid var(--el-color-primary);
  border-radius: 7px;
  padding: 9px 14px;
  white-space: nowrap;
  background: var(--el-color-primary);
  color: var(--el-color-white);
}
.primary-button:hover:not(:disabled) {
  background: var(--el-color-primary-dark-2);
}
.secondary-button {
  color: var(--el-text-color-regular);
  border-color: var(--el-border-color);
  background: var(--el-bg-color);
}
.text-button {
  padding: 3px 0;
  border: 0;
  color: var(--el-color-primary);
  background: none;
  font-size: 13px;
}
.text-button.danger {
  color: var(--el-color-danger);
}
.group-overview {
  margin: 20px 24px;
  padding: 24px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}
.group-identity {
  display: flex;
  gap: 18px;
  align-items: flex-start;
}
.group-symbol {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  flex-shrink: 0;
  border-radius: 12px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 36px;
}
.group-title {
  flex: 1;
  min-width: 0;
}
.title-row {
  flex-wrap: wrap;
  gap: 8px;
}
h1 {
  font-size: 23px;
  margin: 0 6px 0 0;
  overflow-wrap: anywhere;
}
.group-title > p {
  margin: 10px 0 14px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.status-tag,
.kind-tag {
  padding: 3px 8px;
  border-radius: 5px;
  font-size: 12px;
  white-space: nowrap;
}
.status-tag {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.kind-tag,
.status-tag.muted {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
}
.metadata {
  flex-wrap: wrap;
  gap: 6px 20px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
fieldset {
  border: 0;
  min-width: 0;
  margin: 0;
  padding: 0;
}
.basic-fields {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(240px, 2fr);
  gap: 20px;
}
.group-identity + .basic-fields {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 22px;
  padding-top: 20px;
}
label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
label > input,
label > textarea {
  display: block;
  width: 100%;
  margin-top: 8px;
}
label small {
  display: block;
  text-align: right;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
input,
textarea,
select,
.model-readonly {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  min-width: 0;
}
input:focus,
textarea:focus,
select:focus {
  outline: 1px solid var(--el-color-primary);
  border-color: var(--el-color-primary);
}
input[readonly],
textarea[readonly] {
  background: var(--el-fill-color-extra-light);
}
textarea {
  resize: vertical;
  line-height: 1.7;
}
em {
  color: var(--el-color-danger);
  font-style: normal;
}
.group-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 20px;
  margin: 0 24px 24px;
  align-items: start;
}
.child-sidebar,
.child-configuration {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 20px;
  min-width: 0;
}
.child-sidebar > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
h2 {
  font-size: 16px;
  margin: 0;
}
h2 small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: normal;
}
.sidebar-help,
.aggregation p {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}
.child-row {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
  padding: 10px 8px 10px 12px;
  margin-top: 8px;
}
.child-row.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-fill-color-light);
}
.child-delete {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.child-select {
  border: 0;
  background: transparent;
  padding: 0;
  min-width: 0;
  text-align: left;
  flex: 1;
  color: var(--el-text-color-primary);
}
.child-select small {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 10px;
  margin-top: 5px;
}
.child-name {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
}
.weight-input {
  display: flex;
  gap: 3px;
  align-items: center;
  font-size: 11px;
}
.weight-input input {
  width: 60px;
  padding: 6px 3px;
  margin: 0;
  text-align: right;
  font-size: 12px;
}
.weight-label {
  font-size: 13px;
}
.aggregation {
  margin-top: 22px;
  padding-top: 17px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.weight-total {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
}
.invalid {
  color: var(--el-color-danger);
}
.aggregation label input {
  padding: 8px 10px;
  max-width: 100%;
}
.child-configuration {
  padding: 24px;
}
.child-heading {
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 22px;
  padding-bottom: 18px;
}
.child-heading h2 {
  font-size: 18px;
}
.child-heading p {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 7px 0 0;
}
.child-basics {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 18px;
  margin-bottom: 24px;
}
.field-label {
  font-weight: 600;
  margin-bottom: 9px;
}
.model-row {
  display: flex;
  border: 1px solid var(--el-border-color);
  border-radius: 7px;
  overflow: hidden;
}
.model-row select,
.model-readonly {
  border: 0;
  border-radius: 0;
  flex: 1;
  width: 0;
  font-size: 14px;
}
.model-readonly {
  background: var(--el-fill-color-extra-light);
}
.settings-button {
  border: 0;
  border-left: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  color: var(--el-text-color-secondary);
  padding: 0 14px;
  font-size: 20px;
}
.advanced-settings {
  margin-top: 12px;
  padding: 16px;
  background: var(--el-fill-color-extra-light);
  border-radius: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.advanced-settings input {
  width: 140px;
}
.advanced-settings pre {
  white-space: pre-wrap;
}
.prompt-toolbar {
  justify-content: space-between;
  margin: 26px 0 12px;
  flex-wrap: wrap;
}
h3 {
  font-size: 14px;
  margin: 0;
}
.prompt-editor {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
}
.prompt-editor header {
  justify-content: space-between;
  background: var(--el-fill-color-extra-light);
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.prompt-editor textarea {
  width: 100%;
  display: block;
  border: 0;
  border-radius: 0;
  padding: 18px;
  font-size: 13px;
  min-height: 300px;
  line-height: 1.85;
}
.user-prompt {
  margin-top: 14px;
}
.user-prompt textarea {
  min-height: 130px;
}
.add-user-button {
  width: 100%;
  margin-top: 12px;
  padding: 12px;
  border: 0;
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.help-text {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.8;
}
.help-text code {
  padding: 2px 4px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.help-text a {
  color: var(--el-color-primary);
}
.output-description {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 20px;
  padding-top: 18px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.7;
}
.output-description h3 {
  color: var(--el-text-color-regular);
}
.group-footer {
  position: sticky;
  bottom: 0;
  justify-content: space-between;
  padding: 16px 24px;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
  z-index: 2;
}
.group-footer > p {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.6;
  margin: 0;
  max-width: 320px;
}
.notice-message,
.error-message {
  padding: 12px 16px;
  margin: 0 24px 18px;
  font-size: 13px;
  border-radius: 6px;
  overflow-wrap: anywhere;
}
.notice-message {
  color: var(--el-color-primary-dark-2);
  background: var(--el-color-primary-light-9);
}
.error-message {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.loading-state,
.empty-state {
  padding: 30px 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.8;
  text-align: center;
}
.empty-configuration {
  display: grid;
  place-items: center;
  gap: 18px;
  min-height: 330px;
  text-align: center;
  color: var(--el-text-color-secondary);
}
.empty-configuration p {
  font-size: 13px;
  line-height: 1.8;
  max-width: 340px;
}
.group-template-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  min-height: min(680px, 65vh);
}
:global(.el-overlay .el-dialog.llm-group-create-template-dialog:not(.is-fullscreen)) {
  height: min(calc(73.333vh + 106px), 92vh);
  max-height: 92vh;
  margin: 4vh auto !important;
}
:global(
    .el-overlay .el-dialog.llm-group-create-template-dialog:not(.is-fullscreen) .el-dialog__body
  ) {
  flex: 1;
  max-height: none;
  display: flex;
  flex-direction: column;
}
.group-template-layout.start-template-layout {
  flex: 1;
  min-height: 0;
}
.template-sidebar {
  padding: 12px 22px 20px 4px;
  border-right: 1px solid var(--el-border-color-lighter);
}
.template-sidebar h3 {
  margin: 6px 0 18px;
}
.template-sidebar h3:not(:first-child) {
  margin-top: 30px;
}
.template-sidebar p {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 20px 0 10px;
}
.selected-type {
  display: block;
  padding: 10px;
  text-align: center;
  border-radius: 7px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.filter-tag {
  font-size: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 7px 12px;
  display: inline-block;
}
.template-main {
  padding: 10px 0 0 22px;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.template-search input {
  flex: 1;
  width: 0;
}
.template-help {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 14px 0;
}
.template-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 320px));
  gap: 18px;
  align-content: start;
}
.template-bottom {
  justify-content: space-between;
  margin-top: auto;
  padding: 25px 0 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.expanded-prompt {
  display: block;
  width: 100%;
  min-height: 60vh;
  font-size: 14px;
  padding: 18px;
}
@media (max-width: 1100px) {
  .group-workspace {
    grid-template-columns: 230px minmax(0, 1fr);
    gap: 14px;
  }
  .child-sidebar {
    padding: 15px;
  }
  .child-configuration {
    padding: 20px;
  }
  .child-basics {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .group-footer {
    flex-wrap: wrap;
  }
  .group-footer > p {
    max-width: none;
  }
}
@media (max-width: 760px) {
  .group-overview {
    margin: 14px;
    padding: 18px;
  }
  .group-toolbar {
    padding: 14px;
    flex-wrap: wrap;
  }
  .group-identity {
    flex-wrap: wrap;
    gap: 12px;
  }
  .group-symbol {
    display: none;
  }
  .group-identity > .text-button {
    margin-left: auto;
  }
  .group-workspace {
    display: block;
    margin: 0 14px 14px;
  }
  .child-sidebar {
    margin-bottom: 14px;
  }
  .basic-fields {
    grid-template-columns: 1fr;
  }
  .group-footer {
    padding: 14px;
  }
  .group-footer .actions {
    flex-wrap: wrap;
  }
  .group-template-layout {
    grid-template-columns: 1fr;
    min-height: 60vh;
  }
  .template-sidebar {
    display: none;
  }
  .template-main {
    padding: 0;
  }
  .template-search {
    flex-wrap: wrap;
  }
  .template-search input {
    min-width: 180px;
  }
}
</style>
