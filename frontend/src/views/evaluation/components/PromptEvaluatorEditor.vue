<script setup lang="ts">
import { evaluatorDate } from '../utils/evaluator-display';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { request, type Definition, type EvaluatorDetail } from '../../../api/evaluations';
import { loadReviewAssets } from '../../../stores/review-assets';
import { modelRefLabel, type EvaluatorModelRef } from '../utils/evaluator-model';
import { copyEvaluatorDefinition } from '../utils/evaluator-group';
import {
  emptyPromptEvaluator,
  promptEvaluatorDefinition,
  promptEvaluatorError,
  promptModelOptions,
  promptVariableNames,
  readPromptEvaluator,
} from '../utils/evaluator-templates';

const props = defineProps<{
  initialDetail: EvaluatorDetail | null;
  templateDetail?: EvaluatorDetail | null;
  models: [string, EvaluatorModelRef][];
}>();
const emit = defineEmits<{
  close: [];
  dirtyChange: [value: boolean];
  launch: [id: string];
}>();
const detail = ref<EvaluatorDetail | null>(props.initialDetail);
const template = detail.value ? null : props.templateDetail;
const sourceDefinition =
  detail.value?.draft ?? detail.value?.latest ?? template?.draft ?? template?.latest ?? null;
const definition = ref<Definition | null>(
  template && sourceDefinition ? copyEvaluatorDefinition(sourceDefinition) : sourceDefinition,
);
const initialEvaluator = detail.value?.evaluator ?? template?.evaluator;
const form = ref(
  initialEvaluator && definition.value
    ? readPromptEvaluator(initialEvaluator, definition.value)
    : emptyPromptEvaluator(),
);
if (template && definition.value) {
  form.value.id = '';
  form.value.name = form.value.name.slice(0, 46) + '（副本）';
}
const editing = ref(!detail.value);
const viewingDraft = ref(!detail.value || !!detail.value.draft);
const baseline = ref(JSON.stringify(form.value));
const busy = ref(false),
  error = ref(''),
  notice = ref('');
const expanded = ref(false),
  advancedOpen = ref(false);
const historyOpen = ref(false),
  historyLoading = ref(false),
  historyError = ref('');
const versions = ref<Definition[]>([]);
const modelLoading = ref(false),
  modelError = ref('');
const connections = ref<{ configured: boolean; provider_id?: string; model: string }[]>([]);
const own = computed(() => detail.value?.evaluator.source === 'user');
const dirty = computed(() => editing.value && JSON.stringify(form.value) !== baseline.value);
const modelOptions = computed(() => promptModelOptions(connections.value, props.models));
const promptVariables = computed(() =>
  promptVariableNames(form.value.instruction, form.value.userPrompt),
);
const currentModelMissing = computed(
  () => form.value.modelKey && !modelOptions.value.some(([key]) => key === form.value.modelKey),
);
const canLaunch = computed(
  () =>
    !editing.value &&
    !viewingDraft.value &&
    detail.value?.evaluator.enabled &&
    definition.value?.version === detail.value?.latest?.version,
);
const originalRubric = computed(() => {
  const rubric = definition.value?.config.rubric as Record<string, unknown> | undefined;
  return rubric &&
    JSON.stringify(rubric) !== JSON.stringify({ overall: '按照提示词中的评分标准评估。' })
    ? rubric
    : null;
});
watch([dirty, busy], ([changed, pending]) => emit('dirtyChange', changed || pending));

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
function clearPrompts() {
  form.value.instruction = '';
  form.value.userPrompt = null;
  notice.value = '';
}
function showDefinition(value: EvaluatorDetail, source: Definition, draft: boolean) {
  detail.value = value;
  definition.value = source;
  form.value = readPromptEvaluator(value.evaluator, source);
  viewingDraft.value = draft;
  editing.value = false;
  baseline.value = JSON.stringify(form.value);
}
function close() {
  if (busy.value || (dirty.value && !window.confirm('放弃未保存的评估器修改？'))) return;
  emit('close');
}
function beginEdit() {
  editing.value = true;
  error.value = '';
  notice.value = '';
  baseline.value = JSON.stringify(form.value);
}
async function edit() {
  if (busy.value) return;
  if (!own.value) {
    form.value.id = '';
    form.value.name = (form.value.name.slice(0, 46) + '（副本）').slice(0, 50);
    detail.value = null;
    viewingDraft.value = true;
    beginEdit();
    return;
  }
  if (detail.value!.draft) {
    showDefinition(detail.value!, detail.value!.draft, true);
    beginEdit();
    return;
  }
  busy.value = true;
  error.value = '';
  try {
    const draft = await request<Definition>(
      '/evaluators/' + encodeURIComponent(form.value.id) + '/drafts',
      'POST',
      { based_on_version: definition.value?.version },
    );
    showDefinition({ ...detail.value!, draft }, draft, true);
    beginEdit();
    await loadReviewAssets();
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function save() {
  if (busy.value) return;
  error.value = promptEvaluatorError(form.value);
  if (error.value) return;
  busy.value = true;
  notice.value = '';
  try {
    const draft = promptEvaluatorDefinition(form.value, definition.value);
    if (!form.value.id) {
      const created = await request<Omit<EvaluatorDetail, 'latest'>>('/evaluators', 'POST', {
        name: form.value.name.trim(),
        description: form.value.description,
        draft,
      });
      showDefinition({ ...created, latest: null }, created.draft!, true);
    } else {
      const path = '/evaluators/' + encodeURIComponent(form.value.id);
      if (
        form.value.name !== detail.value?.evaluator.name ||
        form.value.description !== detail.value?.evaluator.description
      ) {
        const evaluator = await request<EvaluatorDetail['evaluator']>(path, 'PATCH', {
          name: form.value.name.trim(),
          description: form.value.description,
        });
        detail.value = { ...detail.value!, evaluator };
      }
      const saved = await request<Definition>(path + '/drafts/current', 'PUT', draft);
      showDefinition({ ...detail.value!, draft: saved }, saved, true);
    }
    await loadReviewAssets();
    notice.value = '草稿已保存；发布并启用后可被测评任务选中。';
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function publish() {
  if (busy.value || editing.value || !detail.value?.draft) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  let published: Definition | null = null;
  try {
    const path = '/evaluators/' + encodeURIComponent(form.value.id);
    published = await request<Definition>(path + '/drafts/publish', 'POST');
    showDefinition({ ...detail.value, latest: published, draft: null }, published, false);
    if (!detail.value!.evaluator.enabled) {
      await request(path, 'PATCH', { enabled: true });
      detail.value!.evaluator.enabled = true;
    }
    await loadReviewAssets();
    notice.value = `v${published.version} 已发布并启用，可用于测评。`;
  } catch (cause) {
    error.value = published
      ? `v${published.version} 已发布，但启用或刷新失败：${String(cause)}。可重试启用。`
      : String(cause);
  } finally {
    busy.value = false;
  }
}
async function enable() {
  if (!detail.value || busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    await request('/evaluators/' + encodeURIComponent(form.value.id), 'PATCH', { enabled: true });
    detail.value.evaluator.enabled = true;
    await loadReviewAssets();
    notice.value = '评估器已启用。';
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function showHistory() {
  historyOpen.value = true;
  historyLoading.value = true;
  historyError.value = '';
  try {
    versions.value = await request<Definition[]>(
      '/evaluators/' + encodeURIComponent(form.value.id) + '/versions',
    );
  } catch (cause) {
    historyError.value = String(cause);
  } finally {
    historyLoading.value = false;
  }
}
async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(form.value.instruction);
    notice.value = 'System Prompt 已复制。';
  } catch {
    error.value = '复制失败，请选中提示词后手动复制。';
  }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || busy.value) {
    event.preventDefault();
    event.returnValue = '';
  }
}
onMounted(() => {
  void loadModels();
  window.addEventListener('beforeunload', beforeUnload);
});
onUnmounted(() => {
  window.removeEventListener('beforeunload', beforeUnload);
  emit('dirtyChange', false);
});
</script>

<template>
  <section class="prompt-evaluator" aria-label="LLM 评估器表单">
    <header class="prompt-page-header">
      <button class="back-button" aria-label="返回评估器列表" :disabled="busy" @click="close">
        ←
      </button>
      <h1>{{ detail ? '评估器详情' : '新建评估器' }}</h1>
      <span v-if="detail" class="version-tag">{{
        viewingDraft ? '草稿' : 'v' + definition?.version
      }}</span>
      <div v-if="!editing" class="header-actions">
        <button v-if="detail?.latest" class="plain-button" :disabled="busy" @click="showHistory">
          版本历史
        </button>
        <button class="secondary-button" :disabled="busy" @click="edit">
          {{ own ? (detail?.draft ? '编辑草稿' : '创建新版本草稿') : '复制并编辑' }}
        </button>
      </div>
    </header>
    <div v-if="detail" class="prompt-metadata">
      <span>{{ detail.evaluator.enabled ? '已启用' : '已停用' }}</span>
      <span>创建时间：{{ evaluatorDate(detail.evaluator.created_at) }}</span>
      <span>更新时间：{{ evaluatorDate(detail.evaluator.updated_at) }}</span>
    </div>
    <div class="prompt-form-body">
      <fieldset :disabled="busy">
        <section class="form-section">
          <h2>基础信息</h2>
          <label class="prompt-field" for="prompt-evaluator-name">名称 <em>*</em></label>
          <div class="counted-field">
            <input
              id="prompt-evaluator-name"
              v-model="form.name"
              aria-label="评估器名称"
              maxlength="50"
              placeholder="请输入名称"
              :readonly="!editing"
            />
            <span>{{ form.name.length }}/50</span>
          </div>
          <label class="prompt-field" for="prompt-evaluator-description">描述</label>
          <div class="counted-field description-field">
            <textarea
              id="prompt-evaluator-description"
              v-model="form.description"
              aria-label="评估器描述"
              maxlength="200"
              placeholder="请输入描述"
              :readonly="!editing"
              rows="4"
            />
            <span>{{ form.description.length }}/200</span>
          </div>
        </section>
        <section class="form-section">
          <h2>配置信息</h2>
          <label class="prompt-field" for="prompt-evaluator-model">模型选择 <em>*</em></label>
          <div class="model-select-row">
            <select
              v-if="editing"
              id="prompt-evaluator-model"
              v-model="form.modelKey"
              aria-label="评估器模型"
            >
              <option value="">{{ modelLoading ? '正在读取模型…' : '请选择模型' }}</option>
              <option v-if="currentModelMissing" :value="form.modelKey">
                {{ modelRefLabel(form.modelKey) }}（原配置）
              </option>
              <option v-for="[key, model] in modelOptions" :key="key" :value="key">
                {{ model.model_id }} · {{ model.provider_id }}
              </option>
            </select>
            <div v-else class="model-readonly">{{ modelRefLabel(form.modelKey) }}</div>
            <button
              class="settings-button"
              aria-label="高级设置"
              :aria-expanded="advancedOpen"
              @click="advancedOpen = !advancedOpen"
            >
              ⚙
            </button>
          </div>
          <p v-if="modelError" class="field-help" role="alert">
            {{ modelError }} <button class="text-button" @click="loadModels">重试</button>
          </p>
          <p v-else-if="!modelLoading && !modelOptions.length && editing" class="field-help">
            暂无可选模型，请先在配置中接入模型。 <a href="#/settings">前往配置</a>
          </p>
          <div v-if="advancedOpen" class="advanced-settings">
            <label class="prompt-field"
              >通过分数（0.0—1.0）<input
                v-model.number="form.threshold"
                type="number"
                aria-label="评估器通过分数"
                min="0"
                max="1"
                step="0.05"
                :readonly="!editing"
            /></label>
            <p>得分达到此值时评估通过。模型连接由本地服务配置管理。</p>
            <p
              v-if="
                definition?.config.input_selection &&
                definition.config.input_selection !== 'final_output'
              "
            >
              此版本保留原有的评审输入范围。
            </p>
            <div v-if="originalRubric">
              <p>此版本原有评分标准（保留用于执行）：</p>
              <pre>{{ JSON.stringify(originalRubric, null, 2) }}</pre>
            </div>
          </div>
        </section>
        <section class="form-section prompt-section">
          <div class="prompt-toolbar">
            <h2>Prompt <em>*</em></h2>
            <div v-if="editing" class="toolbar-actions">
              <button class="text-button" @click="clearPrompts">清空</button>
            </div>
          </div>
          <div class="prompt-editor">
            <header>
              <strong>System</strong>
              <div>
                <button
                  class="icon-button"
                  aria-label="展开 System Prompt"
                  @click="expanded = true"
                >
                  ⤢</button
                ><button class="icon-button" aria-label="复制 System Prompt" @click="copyPrompt">
                  ⧉
                </button>
              </div>
            </header>
            <textarea
              v-model="form.instruction"
              aria-label="System Prompt"
              :readonly="!editing"
              :placeholder="'请输入内容，支持按此格式书写变量：{{input}}、{{output}}'"
              spellcheck="false"
              rows="16"
            />
          </div>
          <div v-if="form.userPrompt !== null" class="prompt-editor user-prompt-editor">
            <header>
              <strong>User</strong
              ><button v-if="editing" class="text-button" @click="form.userPrompt = null">
                移除 User Prompt
              </button>
            </header>
            <textarea
              v-model="form.userPrompt"
              aria-label="User Prompt"
              :readonly="!editing"
              :placeholder="'请输入内容，支持 {{input}}、{{output}}'"
              rows="6"
              spellcheck="false"
            />
          </div>
          <button v-else-if="editing" class="add-user-button" @click="form.userPrompt = ''">
            ＋ 添加 User Prompt
          </button>
          <p v-if="promptVariables.length" class="field-help" aria-label="Prompt 变量">
            变量
            <template v-for="(variable, index) in promptVariables" :key="variable">
              <span v-if="index">；</span>
              <code v-text="'{{ ' + variable + ' }}'"></code>
              <span v-if="variable === 'input'"> 为用例输入</span>
              <span v-else-if="variable === 'output'"> 为被测 Agent 的最终回答</span>
            </template>
          </p>
        </section>
        <section class="output-description">
          <h2>输出 <span class="info-symbol" title="每条测评结果包含得分和原因">ⓘ</span></h2>
          <p>
            <strong>得分：</strong>最终得分，必须输出一个数字，表示满足 Prompt
            中评分标准的程度。得分范围为 0.0 到 1.0，1.0 表示完全满足评分标准，0.0
            表示完全不满足评分标准。
          </p>
          <p><strong>原因：</strong>对得分的可读解释，说明评分依据与扣分原因。</p>
        </section>
      </fieldset>
      <p v-if="notice" class="notice-message" role="status">{{ notice }}</p>
      <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    </div>
    <footer class="prompt-page-footer">
      <button class="secondary-button" :disabled="busy" @click="close">
        {{ editing ? '取消' : '返回列表' }}
      </button>
      <button v-if="editing" class="primary-button" :disabled="busy" @click="save">
        {{ busy ? '保存中…' : '保存草稿' }}
      </button>
      <button
        v-if="!editing && viewingDraft && own"
        class="primary-button"
        :disabled="busy"
        @click="publish"
      >
        发布并启用
      </button>
      <button
        v-if="!editing && detail?.latest && !detail.evaluator.enabled && own"
        class="primary-button"
        :disabled="busy"
        @click="enable"
      >
        启用
      </button>
      <button
        v-if="canLaunch"
        class="primary-button"
        :disabled="busy"
        @click="emit('launch', form.id)"
      >
        打开测评配置
      </button>
    </footer>
  </section>

  <el-dialog v-model="expanded" title="System Prompt" width="min(1100px,94vw)">
    <textarea
      v-model="form.instruction"
      aria-label="展开的 System Prompt"
      class="expanded-prompt"
      :readonly="!editing"
      :disabled="busy"
      spellcheck="false"
    />
  </el-dialog>
  <el-dialog v-model="historyOpen" title="已发布版本" width="540px">
    <p>已发布版本只读，历史任务保留运行时使用的版本。</p>
    <p v-if="historyLoading">正在读取版本…</p>
    <p v-if="historyError" role="alert">{{ historyError }}</p>
    <p v-for="version in versions" :key="version.version">
      <button
        class="text-button"
        @click="
          showDefinition(detail!, version, false);
          historyOpen = false;
          notice = '正在查看历史版本，编辑会创建草稿。';
        "
      >
        查看 v{{ version.version }}
      </button>
    </p>
  </el-dialog>
</template>

<style scoped>
.prompt-evaluator {
  background: #fff;
  color: #303544;
  min-height: calc(100vh - 110px);
  border: 1px solid #e7e9f0;
  border-radius: 14px;
  overflow: hidden;
}
.prompt-page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 25px 32px;
  border-bottom: 1px solid #f0f1f6;
}
.prompt-metadata {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  padding: 0 32px 16px;
  color: var(--text-muted, #73829a);
  font-size: 13px;
}
.prompt-page-header h1 {
  font-size: 25px;
  margin: 0;
  font-weight: 600;
}
.back-button {
  border: 0;
  background: none;
  font-size: 29px;
  color: inherit;
  cursor: pointer;
  padding: 0 3px;
}
.header-actions {
  display: flex;
  gap: 12px;
  margin-left: auto;
}
.version-tag {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary-dark-2);
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
}
.prompt-form-body {
  max-width: 1040px;
  margin: 0 auto;
  padding: 40px 42px 26px;
}
fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  min-width: 0;
}
.form-section {
  margin-bottom: 40px;
}
.form-section h2,
.output-description h2 {
  font-size: 19px;
  font-weight: 600;
  margin: 0 0 26px;
}
.prompt-field {
  display: block;
  color: #3f4454;
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 12px;
}
em {
  color: #f05d4b;
  font-style: normal;
  margin-left: 4px;
}
.counted-field {
  position: relative;
  margin-bottom: 26px;
}
.counted-field input,
.counted-field textarea,
.model-select-row select,
.model-readonly,
.advanced-settings input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cfd3e2;
  background: #fff;
  border-radius: 8px;
  padding: 13px 15px;
  font-size: 15px;
  color: #3f4454;
  font-family: inherit;
  outline: none;
}
.counted-field input {
  padding-right: 72px;
}
.counted-field textarea {
  display: block;
  resize: vertical;
  min-height: 145px;
  padding-bottom: 35px;
  line-height: 1.7;
}
.counted-field > span {
  position: absolute;
  right: 14px;
  bottom: 14px;
  color: #969aab;
  font-size: 13px;
}
.prompt-evaluator input:focus,
.prompt-evaluator textarea:focus,
.prompt-evaluator select:focus {
  border-color: var(--el-color-primary);
}
.prompt-evaluator input::placeholder,
.prompt-evaluator textarea::placeholder {
  color: #adb2c5;
}
.model-select-row {
  display: flex;
  align-items: stretch;
  border: 1px solid #cfd3e2;
  border-radius: 8px;
  overflow: hidden;
}
.model-select-row select,
.model-readonly {
  border: 0;
  background: transparent;
  flex: 1;
  min-width: 0;
}
.settings-button {
  border: 0;
  border-left: 1px solid #eeeef5;
  padding: 0 15px;
  color: #83879b;
  font-size: 21px;
  background: white;
  cursor: pointer;
}
.field-help {
  color: #8a8fa3;
  font-size: 12px;
  line-height: 1.8;
  margin: 10px 0 0;
}
.field-help code {
  color: #696078;
  background: #f4f2f9;
  border-radius: 4px;
  padding: 2px 4px;
}
.field-help a {
  color: var(--el-color-primary);
}
.advanced-settings {
  margin-top: 14px;
  padding: 20px;
  background: #f8f8fc;
  border-radius: 8px;
  font-size: 13px;
  color: #73798f;
}
.advanced-settings input {
  display: block;
  max-width: 200px;
  margin-top: 10px;
}
.advanced-settings pre {
  white-space: pre-wrap;
}
.prompt-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 16px;
}
.prompt-toolbar h2 {
  margin: 0;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.text-button,
.plain-button,
.icon-button {
  background: none;
  border: 0;
  color: #55566c;
  cursor: pointer;
  font-size: 14px;
  padding: 4px 0;
  font-family: inherit;
}
.text-button:hover,
.icon-button:hover {
  color: var(--el-color-primary);
}
.prompt-editor {
  border: 1px solid #cfd3e2;
  border-radius: 8px;
  overflow: hidden;
}
.prompt-editor header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  border-bottom: 1px solid #e7e8ef;
  color: #a0a5b9;
  font-size: 15px;
}
.prompt-editor header > div {
  display: flex;
  gap: 24px;
}
.icon-button {
  font-size: 22px;
  padding: 0;
  line-height: 1;
}
.prompt-editor textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  border: 0;
  border-radius: 0;
  outline: none;
  resize: vertical;
  padding: 20px;
  line-height: 1.8;
  font-size: 14px;
  font-family: inherit;
  color: #40465a;
  min-height: 340px;
  background: white;
}
.user-prompt-editor {
  margin-top: 16px;
}
.user-prompt-editor textarea {
  min-height: 150px;
}
.add-user-button {
  width: 100%;
  border: 0;
  background: var(--el-color-primary-light-9);
  color: #414153;
  padding: 15px;
  margin-top: 14px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 9px;
  cursor: pointer;
}
.add-user-button:hover {
  background: var(--el-color-primary-light-7);
}
.output-description {
  color: #85899d;
  font-size: 14px;
  line-height: 1.9;
}
.output-description h2 {
  color: #45495b;
  margin-bottom: 12px;
}
.output-description p {
  margin: 10px 0;
}
.info-symbol {
  color: #8d91a7;
  font-size: 16px;
  font-weight: 400;
}
.prompt-page-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 18px 32px;
  background: white;
  border-top: 1px solid #e9eaf2;
  position: sticky;
  bottom: 0;
  z-index: 2;
}
.primary-button,
.secondary-button {
  border: 1px solid var(--el-color-primary);
  border-radius: 7px;
  background: var(--el-color-primary);
  color: white;
  font-size: 14px;
  padding: 10px 18px;
  cursor: pointer;
  font-family: inherit;
}
.secondary-button {
  background: white;
  color: #575c70;
  border-color: #d9dce8;
}
.primary-button:hover {
  background: var(--el-color-primary-dark-2);
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.notice-message {
  color: #28795e;
  background: #f0faf5;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
}
.error-message {
  color: #b34949;
  background: #fff3f3;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
}
.expanded-prompt {
  width: 100%;
  min-height: 62vh;
  box-sizing: border-box;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.9;
  padding: 20px;
  border: 1px solid #d8dbe7;
  border-radius: 8px;
  resize: vertical;
}
@media (max-width: 900px) {
  .prompt-form-body {
    padding: 30px 25px 24px;
  }
}
@media (max-width: 600px) {
  .prompt-page-header {
    flex-wrap: wrap;
    padding: 20px;
  }
  .header-actions {
    margin-left: 0;
  }
  .prompt-page-footer {
    flex-wrap: wrap;
  }
}
</style>
