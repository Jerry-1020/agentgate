<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  api,
  request,
  type Definition,
  type EvaluatorDetail,
  type EvaluatorSummary,
} from '../../../api/evaluations';
import CodeRuleEditor from './CodeRuleEditor.vue';
import EvaluatorVersions from './EvaluatorVersions.vue';
import EvaluatorTaskHistory from './EvaluatorTaskHistory.vue';
import { traceBuiltinRuleCode } from '../utils/code-rule-templates';

const props = defineProps<{ initialId?: string; presets?: EvaluatorSummary[] }>();
const emit = defineEmits<{
  close: [];
  changed: [];
  launch: [id: string];
  dirtyChange: [value: boolean];
}>();
const detail = ref<EvaluatorDetail | null>(null),
  historical = ref<Definition | null>(null);
const name = ref(''),
  description = ref(''),
  busy = ref(false),
  error = ref(''),
  baseline = ref('');
const value = ref<Definition>({
  kind: 'rule',
  dimension: 'tool_use',
  metric: `custom_code_${crypto.randomUUID().replaceAll('-', '')}`,
  severity: 'standard',
  implementation_id: 'code_rule',
  implementation_version: '1',
  children: [],
  combination: null,
  config: {
    language: 'python-subset-v1',
    input_format: 'trace-v1',
    pass_threshold: 1,
    source: `def exec_evaluation(trace):
    # 替换为 Agent 实际上报的必需工具名
    required_tool_name = "credit_inquiry"
    spans = trace["spans"]
    matched = [s for s in spans if s.get("operation_type") == "tool" and s.get("name") == required_tool_name]
    if len(matched) > 0:
        return EvalOutput(score=1, reason="已调用必需工具", span_ids=[s["span_id"] for s in matched])
    return EvalOutput(score=0, reason="未调用必需工具：" + required_tool_name)
`,
  },
});
const readOnly = computed(() => !!historical.value || (!!detail.value && !detail.value.draft));
const presetIds = ref<string[]>([]);
let customDefinition = JSON.parse(JSON.stringify(value.value)) as Definition;
let presetSnapshot = presetFields();
let presetName = '',
  presetDescription = '';
function presetFields() {
  return JSON.stringify(value.value);
}
function togglePreset(id: string, event: Event) {
  const input = event.target as HTMLInputElement;
  const checked = input.checked;
  // Keep the committed selection visible if replacement is cancelled or fails.
  input.checked = id ? presetIds.value.includes(id) : !presetIds.value.length;
  void applyPresets(
    id ? (checked ? [...presetIds.value, id] : presetIds.value.filter((item) => item !== id)) : [],
  );
}
async function applyPresets(nextIds: string[]) {
  if (busy.value || JSON.stringify(nextIds) === JSON.stringify(presetIds.value)) return;
  const selected = (props.presets ?? []).filter((item) => nextIds.includes(item.id));
  if (selected.length !== nextIds.length) return;
  if (
    presetFields() !== presetSnapshot &&
    !window.confirm(
      '切换创建方式将替换当前规则配置。自定义代码会暂存，选择“不使用预置模板”可恢复；手动填写的名称和描述会保留。是否继续？',
    )
  ) {
    return;
  }
  busy.value = true;
  error.value = '';
  try {
    const sources = await Promise.all(
      selected.map(async (preset) => {
        const source = (await api.evaluator(preset.id)).latest;
        if (!source) throw new Error('该预置评估器没有可用的发布版本，请刷新后重试。');
        return source;
      }),
    );
    const source = sources[0];
    if (!presetIds.value.length) customDefinition = JSON.parse(JSON.stringify(value.value));
    value.value = source
      ? {
          ...JSON.parse(JSON.stringify(customDefinition)),
          dimension: source.dimension,
          severity: sources.some((item) => item.severity === 'blocking')
            ? 'blocking'
            : source.severity,
          config: {
            language: 'python-subset-v1',
            input_format: 'trace-v1',
            source: traceBuiltinRuleCode(sources.map((item) => item.implementation_id)),
            pass_threshold: 1,
          },
        }
      : JSON.parse(JSON.stringify(customDefinition));
    const nextName = selected.map((item) => item.name).join(' + ');
    const nextDescription = selected
      .map((item) => item.description)
      .filter(Boolean)
      .join('；');
    if (!name.value.trim() || name.value === presetName) name.value = nextName;
    if (!description.value.trim() || description.value === presetDescription)
      description.value = nextDescription;
    presetName = nextName;
    presetDescription = nextDescription;
    presetIds.value = selected.map((item) => item.id);
    presetSnapshot = presetFields();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
function snapshot() {
  return JSON.stringify([name.value, description.value, value.value]);
}
const dirty = computed(() => !readOnly.value && snapshot() !== baseline.value);
watch([dirty, busy], ([d, b]) => emit('dirtyChange', d || b));
function selectVersion(version: Definition | null) {
  historical.value = version;
  const source = version ?? detail.value?.draft ?? detail.value?.latest;
  if (source) value.value = JSON.parse(JSON.stringify(source));
  baseline.value = snapshot();
}
async function load(id: string) {
  detail.value = await api.evaluator(id);
  name.value = detail.value.evaluator.name;
  description.value = detail.value.evaluator.description;
  selectVersion(null);
}
async function action(work: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    await work();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
async function refresh() {
  if (!detail.value) return;
  // Version controls own their mutation lock; refresh must not skip because of it.
  try {
    await load(detail.value.evaluator.id);
    emit('changed');
  } catch (e) {
    error.value = String(e);
  }
}
async function save() {
  await action(async () => {
    if (!name.value.trim() || !value.value.metric.trim()) throw new Error('请填写名称和指标标识。');
    const {
      kind,
      dimension,
      metric,
      severity,
      implementation_id,
      implementation_version,
      config,
      children,
      combination,
    } = value.value;
    const draft = {
      kind,
      dimension,
      metric,
      severity,
      implementation_id,
      implementation_version,
      config,
      children,
      combination,
    };
    if (!detail.value) {
      const created = await request<EvaluatorDetail>('/evaluators', 'POST', {
        name: name.value.trim(),
        description: description.value,
        draft,
      });
      // Retain the identity even if the following refresh fails; retries never create duplicates.
      detail.value = { ...created, latest: null };
    } else {
      const path = '/evaluators/' + encodeURIComponent(detail.value.evaluator.id);
      await request(path, 'PATCH', { name: name.value.trim(), description: description.value });
      await request(path + '/drafts/current', 'PUT', draft);
    }
    await load(detail.value.evaluator.id);
    emit('changed');
    ElMessage.success('草稿已保存，发布并启用后可在评测任务中选用');
  });
}
async function publish() {
  await action(async () => {
    if (!detail.value || dirty.value) throw new Error('请先保存草稿');
    const id = detail.value.evaluator.id,
      path = '/evaluators/' + encodeURIComponent(id);
    await request(path + '/drafts/publish', 'POST');
    await load(id);
    emit('changed');
    await request(path, 'PATCH', { enabled: true });
    await load(id);
    emit('changed');
    ElMessage.success('已发布并启用，可在评测任务中选择此评估器');
  });
}
async function toggle() {
  await action(async () => {
    if (!detail.value) return;
    const id = detail.value.evaluator.id;
    await request('/evaluators/' + encodeURIComponent(id), 'PATCH', {
      enabled: !detail.value.evaluator.enabled,
    });
    await load(id);
    emit('changed');
  });
}
function close() {
  if (busy.value || (dirty.value && !window.confirm('放弃未保存的规则修改？'))) return;
  emit('close');
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || busy.value) {
    event.preventDefault();
    event.returnValue = '';
  }
}
onMounted(async () => {
  baseline.value = snapshot();
  window.addEventListener('beforeunload', beforeUnload);
  if (props.initialId) await action(() => load(props.initialId!));
});
onUnmounted(() => {
  window.removeEventListener('beforeunload', beforeUnload);
  emit('dirtyChange', false);
});
</script>

<template>
  <el-dialog
    class="code-rule-dialog"
    :model-value="true"
    :title="initialId ? '规则评估器' : '新建规则评估器'"
    width="min(1280px,96vw)"
    :before-close="close"
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :show-close="!busy"
  >
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <template v-if="!initialId || detail">
      <EvaluatorTaskHistory
        :evaluator-id="detail?.evaluator.id ?? ''"
        :latest-version="detail?.latest?.version"
        :current-version="historical?.version"
        :enabled="!!detail"
        divider
      >
        <p v-if="detail" class="muted">
          {{
            historical
              ? 'v' + historical.version + ' · 只读'
              : detail.draft
                ? '当前草稿'
                : 'v' + detail.latest?.version + ' · 已发布'
          }}
          ·
          {{
            detail.evaluator.enabled ? '已启用' : '未启用'
          }}。任务冻结发布版本，修改草稿不影响历史结果。
        </p>
        <EvaluatorVersions
          v-if="detail"
          :key="
            detail.evaluator.id +
            String(detail.draft?.content_sha256) +
            String(detail.latest?.version)
          "
          :item="detail"
          :allow-create="true"
          :unsaved="dirty"
          :disabled="busy"
          :active-version="historical?.version"
          @select="selectVersion"
          @busy="busy = $event"
          @refresh="refresh"
          @removed="
            emit('changed');
            emit('close');
          "
        />
        <fieldset :disabled="busy" class="code-fields">
          <div class="form-grid">
            <label class="field full"
              >名称<input
                class="input"
                v-model="name"
                aria-label="规则评估器名称"
                maxlength="128"
                :readonly="readOnly"
            /></label>
            <label class="field full"
              >描述<textarea
                class="input"
                v-model="description"
                aria-label="规则评估器描述"
                rows="2"
                :readonly="readOnly"
              />
            </label>
            <div v-if="!initialId && !detail" class="field full">
              基于预置评估器创建（可选）
              <div class="preset-options" role="group" aria-label="基于预置评估器创建">
                <label class="preset-option">
                  <input
                    type="checkbox"
                    :checked="!presetIds.length"
                    :disabled="busy"
                    @change="togglePreset('', $event)"
                  />
                  不使用预置模板
                </label>
                <label v-for="preset in presets" :key="preset.id" class="preset-option">
                  <input
                    type="checkbox"
                    :checked="presetIds.includes(preset.id)"
                    :disabled="busy"
                    @change="togglePreset(preset.id, $event)"
                  />
                  {{ preset.name }}
                </label>
              </div>
              <span class="muted"
                >可多选，生成一份可编辑 Python，全部检查通过得 100 分，否则得 0 分。
                组合统一归类到首个模板的维度；包含阻断模板时沿用阻断检查，可在下方修改。
                请调整工具名、字段和期望值，最终评分以保存的代码为准。</span
              >
            </div>
          </div>
          <CodeRuleEditor v-model="value" :disabled="readOnly || busy" />
        </fieldset>
      </EvaluatorTaskHistory>
    </template>
    <template #footer>
      <button class="secondary" :disabled="busy" @click="close">关闭</button>
      <button
        v-if="(!initialId || detail) && !readOnly"
        class="secondary"
        :disabled="busy"
        @click="save"
      >
        保存草稿
      </button>
      <button
        v-if="detail?.draft && !historical"
        class="primary"
        :disabled="busy || dirty"
        @click="publish"
      >
        发布并启用
      </button>
      <button v-if="detail?.latest" class="secondary" :disabled="busy || dirty" @click="toggle">
        {{ detail.evaluator.enabled ? '停用' : '启用' }}
      </button>
      <button
        v-if="detail?.latest && detail.evaluator.enabled && !historical"
        class="primary"
        :disabled="busy || dirty"
        @click="emit('launch', detail.evaluator.id)"
      >
        打开测评配置
      </button>
    </template>
  </el-dialog>
</template>

<style scoped>
.preset-options {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  padding: 12px;
  border: 1px solid #dce1e9;
  border-radius: 6px;
}
.preset-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.preset-option input {
  accent-color: #0aa58f;
}
.code-fields {
  border: 0;
  padding: 0;
  margin-top: 16px;
  min-width: 0;
}
</style>

<style>
.el-overlay .el-dialog.code-rule-dialog:not(.is-fullscreen) {
  margin-top: 3vh;
  max-height: 94vh;
}
.el-overlay .el-dialog.code-rule-dialog:not(.is-fullscreen) .el-dialog__body {
  max-height: calc(94vh - 140px);
}
</style>
