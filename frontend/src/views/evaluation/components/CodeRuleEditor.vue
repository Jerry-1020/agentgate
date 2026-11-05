<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { request, type Definition } from '../../../api/evaluations';
import { traceDataForLegacyRule, type CodeTraceData } from '../utils/code-rule-templates';
import JsonCodeEditor from '../../../components/JsonCodeEditor.vue';
import { useAuthStore } from '../../../stores/modules/auth';

const props = defineProps<{ modelValue: Definition; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: Definition] }>();
const checking = ref(false),
  feedback = ref(''),
  valid = ref(false);
const auth = useAuthStore();
const nativeTrace = computed(() => props.modelValue.config.input_format === 'trace-v1');
const testData = ref('');
let loadedTestData = '';
let restoringTraceSelection = false;
type TraceTarget = {
  source_id: string;
  target_id: string;
  version: string;
  name: string;
  branch: string;
  adapter_type: string;
};
type TraceChoice = { trace_id: string; run_id: string; case_id: string; created_at: string };
type ChoicePage<T> = { items: T[]; has_more: boolean };
const targets = ref<TraceTarget[]>([]),
  traces = ref<TraceChoice[]>([]);
const agentId = ref(''),
  branchId = ref(''),
  targetVersion = ref(''),
  traceId = ref('');
const targetLoading = ref(false),
  listLoading = ref(false),
  generating = ref(false),
  confirming = ref(false);
const traceLoading = computed(
  () => targetLoading.value || listLoading.value || generating.value || confirming.value,
);
const traceError = ref('');
const moreTargets = ref(false),
  moreTraces = ref(false);
const mode = computed(() => (auth.loginMode === 'external' ? 'external' : 'inbank'));
const agentKey = (t: TraceTarget) => JSON.stringify([t.adapter_type, t.target_id]);
const branchKey = (t: TraceTarget) => JSON.stringify([t.source_id, t.branch]);
const agents = computed(() => [...new Map(targets.value.map((t) => [agentKey(t), t])).values()]);
const branches = computed(() => [
  ...new Map(
    targets.value.filter((t) => agentKey(t) === agentId.value).map((t) => [branchKey(t), t]),
  ).values(),
]);
const versions = computed(() => [
  ...new Map(
    targets.value
      .filter((t) => agentKey(t) === agentId.value && branchKey(t) === branchId.value)
      .map((t) => [t.version, t]),
  ).values(),
]);
const selectedTarget = computed(() =>
  versions.value.find((t) => t.version === targetVersion.value),
);
const selectedTrace = computed(() => traces.value.find((t) => t.trace_id === traceId.value));
const testError = ref('');
const running = ref(false);
const trial = ref<{
  outcome: 'pass' | 'fail' | 'error' | 'not_applicable';
  score: number | null;
  reason: string;
  span_ids: string[];
  duration_ms: number;
} | null>(null);
const trialLabels = { pass: '通过', fail: '未通过', error: '执行异常', not_applicable: '不适用' };
let sourceRequest = 0;
let targetRequest = 0,
  listRequest = 0;
let trialRevision = 0;
let disposed = false;
function query(values: Record<string, string>) {
  return new URLSearchParams({ mode: mode.value, ...values }).toString();
}
async function loadTargets(append = false) {
  const ticket = ++targetRequest;
  targetLoading.value = true;
  traceError.value = '';
  if (!append) {
    targets.value = [];
    agentId.value = '';
  }
  try {
    const page = await request<ChoicePage<TraceTarget>>(
      '/evaluators/code/trace-targets?' +
        query({ offset: String(append ? targets.value.length : 0) }),
    );
    if (disposed || ticket !== targetRequest) return;
    targets.value = append ? [...targets.value, ...page.items] : page.items;
    moreTargets.value = page.has_more;
  } catch (e) {
    if (ticket === targetRequest) traceError.value = String(e);
  } finally {
    if (ticket === targetRequest) targetLoading.value = false;
  }
}
async function loadTraces(append = false) {
  const ticket = ++listRequest;
  if (!append) {
    traces.value = [];
    traceId.value = '';
  }
  listLoading.value = false;
  traceError.value = '';
  moreTraces.value = false;
  const t = selectedTarget.value;
  if (!t) return;
  listLoading.value = true;
  try {
    const page = await request<ChoicePage<TraceChoice>>(
      '/evaluators/code/traces?' +
        query({
          source_id: t.source_id,
          target_id: t.target_id,
          version: t.version,
          offset: String(append ? traces.value.length : 0),
        }),
    );
    if (disposed || ticket !== listRequest) return;
    traces.value = append ? [...traces.value, ...page.items] : page.items;
    moreTraces.value = page.has_more;
  } catch (e) {
    if (ticket === listRequest) traceError.value = String(e);
  } finally {
    if (ticket === listRequest) listLoading.value = false;
  }
}
onMounted(() => void loadTargets());
watch(agentId, () => {
  sourceRequest++;
  branchId.value = '';
  targetVersion.value = '';
  void loadTraces();
});
watch(branchId, () => {
  sourceRequest++;
  targetVersion.value = '';
  void loadTraces();
});
watch(targetVersion, () => {
  sourceRequest++;
  void loadTraces();
});
watch(traceId, async (next, previous) => {
  if (restoringTraceSelection) {
    restoringTraceSelection = false;
    return;
  }
  sourceRequest++;
  generating.value = false;
  if (!next) {
    if (testData.value === loadedTestData) {
      testData.value = '';
      loadedTestData = '';
    }
    return;
  }
  const selectionRevision = sourceRequest;
  const replace = await confirmTestReplacement();
  if (disposed || selectionRevision !== sourceRequest) return;
  if (!replace) {
    restoringTraceSelection = true;
    traceId.value = previous;
    return;
  }
  void generateTraceData();
});
async function confirmTestReplacement() {
  if (!testData.value.trim() || testData.value === loadedTestData) return true;
  confirming.value = true;
  try {
    await ElMessageBox.confirm(
      '测试数据已手动修改，是否用所选 Trace 替换？原始 Trace 和评估代码不会改变。',
      '替换测试数据',
      {
        confirmButtonText: '替换',
        cancelButtonText: '保留修改',
        type: 'warning',
      },
    );
    return true;
  } catch {
    return false;
  } finally {
    confirming.value = false;
  }
}
async function generateTraceData() {
  const t = selectedTrace.value;
  if (!t) return;
  if (disposed || t !== selectedTrace.value) return;
  const ticket = ++sourceRequest;
  const revision = trialRevision;
  generating.value = true;
  traceError.value = '';
  try {
    const response = await request<{ trace: CodeTraceData }>(
      '/evaluators/code/trace-data?' + query({ run_id: t.run_id, case_id: t.case_id }),
    );
    if (disposed || ticket !== sourceRequest || revision !== trialRevision) return;
    const data = nativeTrace.value ? response.trace : traceDataForLegacyRule(response.trace);
    testData.value = JSON.stringify(data, null, 2);
    loadedTestData = testData.value;
  } catch (e) {
    if (ticket === sourceRequest) traceError.value = String(e);
  } finally {
    if (ticket === sourceRequest) generating.value = false;
  }
}
function editTestData(value: string) {
  if (value === testData.value) return;
  testData.value = value;
}
watch([testData, () => JSON.stringify(props.modelValue.config)], () => {
  trialRevision++;
  trial.value = null;
  testError.value = '';
});
watch(
  () => [auth.loginMode, auth.token, auth.teamId, auth.userId],
  async () => {
    sourceRequest++;
    targetRequest++;
    listRequest++;
    agentId.value = '';
    branchId.value = '';
    targetVersion.value = '';
    traceId.value = '';
    targets.value = [];
    traces.value = [];
    moreTargets.value = false;
    moreTraces.value = false;
    targetLoading.value = false;
    listLoading.value = false;
    generating.value = false;
    traceError.value = '';
    testData.value = '';
    loadedTestData = '';
    trialRevision++;
    trial.value = null;
    await nextTick();
    if (!disposed) void loadTargets();
  },
);
onBeforeUnmount(() => {
  disposed = true;
  sourceRequest++;
  targetRequest++;
  listRequest++;
  trialRevision++;
});
async function tryRun() {
  if (running.value || checking.value) return;
  trial.value = null;
  testError.value = '';
  let data: unknown;
  try {
    data = JSON.parse(testData.value);
    if (!data || typeof data !== 'object' || Array.isArray(data))
      throw new Error('顶层必须是 JSON 对象。');
  } catch (e) {
    testError.value = '测试 JSON 无效：' + String(e);
    return;
  }
  running.value = true;
  const revision = trialRevision;
  try {
    const result = await request<NonNullable<typeof trial.value>>(
      '/evaluators/code/try-run',
      'POST',
      {
        config: props.modelValue.config,
        ...(nativeTrace.value ? { trace: data } : { turn_data: data }),
      },
    );
    if (!disposed && revision === trialRevision) trial.value = result;
  } catch (e) {
    if (!disposed && revision === trialRevision) testError.value = String(e);
  } finally {
    if (!disposed) running.value = false;
  }
}
watch(
  () => JSON.stringify(props.modelValue),
  () => {
    feedback.value = '';
  },
);
function setField(key: string, value: unknown, config = false) {
  if ((config ? props.modelValue.config[key] : props.modelValue[key as keyof Definition]) === value)
    return;
  const next = JSON.parse(JSON.stringify(props.modelValue));
  if (config) next.config[key] = value;
  else next[key] = value;
  emit('update:modelValue', next);
}
async function validate() {
  checking.value = true;
  feedback.value = '';
  const snapshot = JSON.stringify(props.modelValue.config);
  try {
    await request('/evaluators/code/validate', 'POST', { config: props.modelValue.config });
    if (snapshot !== JSON.stringify(props.modelValue.config)) return;
    valid.value = true;
    feedback.value = '静态检查通过。未执行代码；实际评分将在评测任务中产生。';
  } catch (e) {
    if (snapshot !== JSON.stringify(props.modelValue.config)) return;
    valid.value = false;
    feedback.value = String(e);
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <section class="code-rule-editor" aria-label="Code 规则配置">
    <p class="muted">编写或生成代码 → 检查语法 → 构造测试数据并试运行 → 保存草稿 → 发布并启用</p>
    <div class="form-grid">
      <label class="field"
        >评估维度<select
          class="input"
          aria-label="评估维度"
          :disabled="disabled"
          :value="modelValue.dimension"
          @change="setField('dimension', ($event.target as HTMLSelectElement).value)"
        >
          <option value="tool_use">工具调用</option>
          <option value="routing">技能路由</option>
          <option value="state">业务状态</option>
          <option value="answer">回答质量</option>
          <option value="safety">安全合规</option>
        </select></label
      >
      <label class="field"
        >通过分数（0—100）<input
          class="input"
          type="number"
          min="0"
          max="100"
          aria-label="Code 通过分数"
          :disabled="disabled"
          :value="Number(modelValue.config.pass_threshold) * 100"
          @input="
            setField(
              'pass_threshold',
              Number(($event.target as HTMLInputElement).value) / 100,
              true,
            )
          "
      /></label>
    </div>
    <p class="muted">评估维度用于结果分类。通过分数默认 100，达到该分数即通过。</p>
    <details>
      <summary>
        高级设置 · {{ modelValue.severity === 'blocking' ? '阻断检查' : '普通检查' }}
      </summary>
      <div class="form-grid">
        <label class="field"
          >指标标识<input
            class="input"
            aria-label="指标标识"
            :disabled="disabled"
            :value="modelValue.metric"
            @input="setField('metric', ($event.target as HTMLInputElement).value)"
        /></label>
        <label class="field"
          >失败影响<select
            class="input"
            aria-label="失败影响"
            :disabled="disabled"
            :value="modelValue.severity"
            @change="setField('severity', ($event.target as HTMLSelectElement).value)"
          >
            <option value="standard">普通检查</option>
            <option value="blocking">阻断检查</option>
          </select></label
        >
      </div>
      <p class="muted">
        新建时自动生成独立指标标识，一般无需修改。同名指标会合并统计，不同维度请使用不同标识。
      </p>
      <p class="muted">
        普通检查参与评分；阻断检查失败会导致发布门禁不通过，不会立即中断 Agent 执行。
      </p>
    </details>
    <div class="code-workbench">
      <section class="code-pane" aria-label="Python 评估代码编辑区">
        <div class="editor-header">
          <span>执行函数体：</span><span class="language-badge">Python</span>
        </div>
        <JsonCodeEditor
          label="评估代码"
          language="python"
          :disabled="disabled"
          :model-value="String(modelValue.config.source ?? '')"
          @update:model-value="setField('source', $event, true)"
        />
      </section>
      <section class="trial-panel" aria-label="测试数据编辑区">
        <div class="editor-header trace-header">
          <span class="trace-label">Trace 数据：</span>
          <div class="trace-selectors">
            <select
              v-model="agentId"
              class="input"
              aria-label="Trace 智能体"
              :disabled="traceLoading"
            >
              <option value="">智能体名称</option>
              <option v-for="t in agents" :key="agentKey(t)" :value="agentKey(t)">
                {{ t.name }} · {{ t.target_id }}
              </option>
            </select>
            <select
              v-model="branchId"
              class="input"
              aria-label="Trace 分支"
              :disabled="traceLoading || !agentId"
            >
              <option value="">智能体分支</option>
              <option v-for="t in branches" :key="branchKey(t)" :value="branchKey(t)">
                {{ t.branch || '无分支记录' }}
              </option>
            </select>
            <select
              v-model="targetVersion"
              class="input"
              aria-label="Trace 智能体版本"
              :disabled="traceLoading || !branchId"
            >
              <option value="">智能体版本</option>
              <option v-for="t in versions" :key="t.version" :value="t.version">
                {{ t.version }}
              </option>
            </select>
            <select
              v-model="traceId"
              class="input"
              aria-label="Trace 选择"
              :disabled="traceLoading || !targetVersion"
            >
              <option value="">Trace 选择</option>
              <option v-for="t in traces" :key="t.trace_id" :value="t.trace_id">
                {{ t.case_id }} · {{ new Date(t.created_at).toLocaleString() }} · {{ t.trace_id }}
              </option>
            </select>
          </div>
        </div>
        <JsonCodeEditor
          :model-value="testData"
          label="测试数据 JSON"
          @update:model-value="editTestData"
        />
      </section>
    </div>
    <div class="trace-actions">
      <div v-if="moreTargets || moreTraces" class="actions">
        <button
          v-if="moreTargets"
          type="button"
          class="secondary"
          :disabled="traceLoading"
          @click="loadTargets(true)"
        >
          加载更多智能体版本
        </button>
        <button
          v-if="moreTraces"
          type="button"
          class="secondary"
          :disabled="traceLoading"
          @click="loadTraces(true)"
        >
          加载更多 Trace
        </button>
      </div>
      <p v-if="traceLoading" class="muted" role="status">正在读取 Trace…</p>
      <p v-else-if="!targets.length && !traceError" class="muted">
        当前团队及登录模式暂无已保存的 Agent Trace。
      </p>
      <p v-else-if="targetVersion && !traces.length && !traceError" class="muted">
        该版本暂无可用 Trace。
      </p>
      <p v-if="traceError" role="alert" class="notice error">{{ traceError }}</p>
    </div>
    <div class="trial-controls">
      <p v-if="!testData" class="muted">
        暂无测试数据。选中 Trace 后自动填入，可在右侧编辑测试副本。
      </p>
      <div class="actions">
        <button
          type="button"
          class="primary"
          :disabled="running || checking || traceLoading || !testData.trim()"
          @click="tryRun"
        >
          {{ running ? '试运行中…' : '试运行' }}
        </button>
        <span class="muted">仅运行当前测试 JSON，不创建任务、不调用 Agent。</span>
      </div>
      <p v-if="testError" role="alert" class="notice error">{{ testError }}</p>
      <section
        v-if="trial"
        role="status"
        aria-label="试运行结果"
        :class="[
          'notice',
          trial.outcome === 'pass' ? 'success' : trial.outcome === 'error' ? 'error' : '',
        ]"
      >
        <strong
          >{{ trialLabels[trial.outcome] }} ·
          {{ trial.score === null ? '无分数' : (trial.score * 100).toFixed(1) + ' / 100' }}</strong
        >
        <p>{{ trial.reason }}</p>
        <p class="muted">
          耗时 {{ trial.duration_ms.toFixed(1) }} ms · 证据 {{ trial.span_ids.length }} 条
        </p>
        <p v-if="trial.span_ids.length" class="evidence-ids">{{ trial.span_ids.join('、') }}</p>
      </section>
    </div>
    <p class="muted">
      返回 EvalOutput(score=0～1, reason="评分说明", span_ids=["证据 ID"])；span_ids
      可选。低于通过分数为失败，运行异常为 ERROR，不按 0 分处理。
    </p>
    <div v-if="!disabled" class="actions">
      <button type="button" class="secondary" :disabled="checking" @click="validate">
        {{ checking ? '检查中…' : '检查语法' }}
      </button>
      <span class="muted">语法检查不执行代码；试运行仅使用右侧测试 JSON。</span>
    </div>
    <p v-if="feedback" role="status" :class="['notice', valid ? 'success' : 'error']">
      {{ feedback }}
    </p>
  </section>
</template>

<style scoped>
.code-rule-editor {
  display: grid;
  gap: 12px;
}
.code-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.code-pane,
.trial-panel,
.test-source-panel {
  min-width: 0;
  border: 1px solid #dce1e9;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.editor-header {
  display: flex;
  align-items: center;
  gap: 14px;
  height: 84px;
  padding: 12px 16px;
  box-sizing: border-box;
  border-bottom: 1px solid #dce1e9;
  color: #46536a;
  font-size: 14px;
  font-weight: 600;
}
.editor-header .input {
  width: auto;
  min-width: 120px;
  max-width: 100%;
}
.language-badge {
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid #e6e9ef;
  background: #f7f8fa;
  color: #68758a;
  font-weight: 400;
}
.test-source-controls,
.trial-controls {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
}
.test-source-controls {
  border-bottom: 1px solid #e6e9ef;
  background: #fafbfc;
}
.trial-controls {
  border-top: 1px solid #e6e9ef;
}
.trial-panel p,
.test-source-panel p,
.trial-controls p {
  margin: 0;
}
.trace-label {
  white-space: nowrap;
}
.trace-header {
  gap: 8px;
}
.trace-selectors {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.trace-selectors .input {
  width: 100%;
  min-width: 0;
  padding: 6px;
  font-size: 13px;
  text-overflow: ellipsis;
}
.trace-actions {
  display: grid;
  gap: 8px;
}
.trace-actions p {
  margin: 0;
}
@media (max-width: 650px) {
  .editor-header {
    height: 112px;
  }
  .trace-selectors {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.evidence-warning {
  padding: 10px;
  border-radius: 6px;
  background: #fff8e6;
  color: #745717;
}
.evidence-ids {
  overflow-wrap: anywhere;
}
.code-workbench :deep(.cm-editor) {
  background: #fff;
  color: #243b35;
}
.code-workbench :deep(.json-code-editor) {
  margin-top: 0;
  border: 0;
  border-radius: 0;
}
.code-workbench :deep(.cm-gutters) {
  background: #fff;
  color: #528098;
  border-right: 1px solid #edf0f5;
}
.code-workbench :deep(.cm-lineNumbers .cm-gutterElement) {
  min-width: 36px;
  padding: 0 10px 0 6px;
}
.code-workbench :deep(.cm-content) {
  padding: 14px 0;
}
.code-workbench :deep(.cm-scroller) {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.6;
  height: 360px;
  min-height: 360px !important;
  max-height: 360px !important;
  overflow: auto;
}
@media (max-width: 900px) {
  .code-workbench {
    grid-template-columns: 1fr;
  }
}
summary {
  cursor: pointer;
}
</style>
