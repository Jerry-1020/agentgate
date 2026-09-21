<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { request, type TargetDescriptor } from '../../../api/evaluations';
import type { EvaluationRun } from '../../evaluation/types/run';
import type { Trace } from '../../../api/client';
import { datasetApi } from '../../../api/datasets';

type Mode = 'base' | 'workflow' | 'cloudshrimp';
type Descriptor = TargetDescriptor & {
  skills: (TargetDescriptor['skills'][number] & { prompt?: string })[];
  tools?: { name: string; description?: string; input_schema?: unknown }[];
  input_schema?: {
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
};
type Target = {
  descriptor: Descriptor;
  snapshot: { invocation_config: { mode: Mode } };
  git_branch_url?: string | null;
};
const emit = defineEmits<{ close: []; created: [id: string, withImport: boolean] }>();
const saving = ref(false),
  createdId = ref('');
const modeNames: Record<Mode, string> = {
  base: '基础编排',
  workflow: '工作流',
  cloudshrimp: '云虾',
};
const mode = ref<Mode>('base'),
  targets = ref<Target[]>([]),
  loading = ref(false),
  loadError = ref('');
const agentId = ref(''),
  version = ref(''),
  branch = ref(''),
  pinned = ref<Target | null>(null);
const name = ref(''),
  description = ref(''),
  tags = ref<string[]>([]),
  icon = ref('🗂️'),
  error = ref('');
const tab = ref('prompt');
const runs = ref<EvaluationRun[]>([]),
  runsLoading = ref(false),
  runsError = ref('');
const runId = ref(''),
  caseId = ref(''),
  trace = ref<Trace | null>(null),
  traceLoading = ref(false),
  traceError = ref('');
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const modeTargets = computed(() =>
  targets.value.filter((t) => t.snapshot.invocation_config.mode === mode.value),
);
const agents = computed(() =>
  Array.from(
    new Map(modeTargets.value.map((t) => [t.descriptor.ref.external_target_id, t])).values(),
  ),
);
const agentTargets = computed(() =>
  modeTargets.value.filter((t) => t.descriptor.ref.external_target_id === agentId.value),
);
const branches = computed(() =>
  Array.from(
    new Set(agentTargets.value.map((t) => t.git_branch_url).filter((b): b is string => !!b)),
  ),
);
const versionTargets = computed(() =>
  agentTargets.value.filter(
    (t) =>
      mode.value !== 'cloudshrimp' || !branches.value.length || t.git_branch_url === branch.value,
  ),
);
const selected = computed(() =>
  versionTargets.value.find((t) => t.descriptor.ref.external_version_id === version.value),
);
const descriptor = computed(() => pinned.value?.descriptor);
const variables = computed(() => Object.entries(descriptor.value?.input_schema?.properties ?? {}));
const nodes = computed(
  () =>
    (
      descriptor.value?.metadata.topology as
        | {
            nodes?: {
              id: string;
              kind: string;
              label: string;
              description?: string;
              prompt?: string;
            }[];
          }
        | undefined
    )?.nodes ?? [],
);
const activeRun = computed(() => runs.value.find((r) => r.id === runId.value));
const cases = computed(
  () =>
    activeRun.value?.manifest.dataset.cases.filter(
      (c) =>
        !activeRun.value?.manifest.selected_case_ids ||
        activeRun.value.manifest.selected_case_ids.includes(c.id),
    ) ?? [],
);
let contextSequence = 0,
  traceSequence = 0;
function invalidate() {
  contextSequence++;
  traceSequence++;
  pinned.value = null;
  runs.value = [];
  runsError.value = '';
  runsLoading.value = false;
  runId.value = '';
  caseId.value = '';
  trace.value = null;
  traceError.value = '';
  traceLoading.value = false;
  error.value = '';
}
watch(
  mode,
  () => {
    agentId.value = '';
    branch.value = '';
    version.value = '';
    invalidate();
  },
  { flush: 'sync' },
);
watch(
  agentId,
  () => {
    branch.value = '';
    version.value = '';
    invalidate();
  },
  { flush: 'sync' },
);
watch(
  branch,
  () => {
    version.value = '';
    invalidate();
  },
  { flush: 'sync' },
);
watch(version, invalidate, { flush: 'sync' });
watch(runId, () => {
  caseId.value = '';
  trace.value = null;
  traceError.value = '';
  traceSequence++;
  traceLoading.value = false;
});
async function loadTargets() {
  loading.value = true;
  loadError.value = '';
  invalidate();
  targets.value = [];
  agentId.value = '';
  version.value = '';
  branch.value = '';
  try {
    targets.value = await request<Target[]>('/bank-targets');
  } catch {
    loadError.value = '智能体目录读取失败，请检查新版服务后重试。';
  } finally {
    loading.value = false;
  }
}
async function confirmTarget() {
  if (!selected.value) {
    error.value = '请选择智能体及已登记版本。云虾分支必须匹配服务端返回的选项。';
    return;
  }
  const ticket = ++contextSequence;
  pinned.value = clone(selected.value);
  error.value = '';
  tab.value = 'prompt';
  runsLoading.value = true;
  runsError.value = '';
  runs.value = [];
  try {
    const all = await request<EvaluationRun[]>('/runs?limit=200');
    if (ticket !== contextSequence) return;
    const target = pinned.value!.descriptor.ref;
    runs.value = all.filter((r) => {
      const ref = r.manifest.target.ref;
      return (
        ref.source_id === target.source_id &&
        ref.target_type === target.target_type &&
        ref.external_target_id === target.external_target_id &&
        ref.external_version_id === target.external_version_id
      );
    });
  } catch {
    if (ticket === contextSequence)
      runsError.value = '历史评测记录读取失败，不能据此判断没有会话。';
  } finally {
    if (ticket === contextSequence) runsLoading.value = false;
  }
}
async function loadTrace() {
  const ticket = ++traceSequence;
  trace.value = null;
  traceError.value = '';
  if (!runId.value || !caseId.value) {
    traceLoading.value = false;
    return;
  }
  traceLoading.value = true;
  try {
    const result = await request<Trace>(
      `/runs/${encodeURIComponent(runId.value)}/traces/${encodeURIComponent(caseId.value)}`,
    );
    if (ticket === traceSequence) trace.value = result;
  } catch {
    if (ticket === traceSequence) traceError.value = '该样本暂未提供可读取的 Trace，或读取失败。';
  } finally {
    if (ticket === traceSequence) traceLoading.value = false;
  }
}
function autoDescription() {
  if (descriptor.value)
    description.value =
      `用于评测${modeNames[mode.value]}智能体「${descriptor.value.display_name}」的 ${descriptor.value.ref.external_version_id} 版本，核查回答质量、执行过程与工具调用。`.slice(
        0,
        512,
      );
}
function validate() {
  error.value = '';
  if (!pinned.value) error.value = '请先确认智能体，读取版本定义。';
  else if (!name.value.trim()) error.value = '请输入数据集名称。';
  else if (!description.value.trim()) error.value = '请输入数据集描述。';
  else if (!tags.value.length) error.value = '请至少选择或输入一个场景标签。';
  return !error.value;
}
async function create(withImport: boolean) {
  if (!validate() || saving.value) return;
  saving.value = true;
  try {
    if (!createdId.value) {
      const result = await datasetApi.create(name.value.trim(), description.value.trim());
      createdId.value = result.dataset.id;
    }
    emit('created', createdId.value, withImport);
  } catch (e) {
    error.value = String(e);
  } finally {
    saving.value = false;
  }
}
function close() {
  if (saving.value) return;
  if ((name.value || description.value) && !window.confirm('关闭后将丢弃未保存的信息，确定关闭？'))
    return;
  emit('close');
}
onMounted(loadTargets);
</script>

<template>
  <el-dialog
    :model-value="true"
    title="创建数据集"
    width="min(1060px,96vw)"
    top="3vh"
    class="dataset-create-v2"
    :close-on-click-modal="false"
    :before-close="close"
    :show-close="!saving"
    :close-on-press-escape="!saving"
  >
    <template v-if="true">
      <h3><span class="step-number">01</span>关联智能体</h3>
      <div class="target-fields" :class="{ cloud: mode === 'cloudshrimp' }">
        <label
          >智能体模式 <em>*</em
          ><select v-model="mode" aria-label="数据集智能体模式">
            <option value="base">基础编排 · Dify</option>
            <option value="workflow">工作流 · Dify</option>
            <option value="cloudshrimp">云虾 · DeepAgent</option>
          </select></label
        >
        <label
          >智能体 ID / 名称 <em>*</em
          ><select v-model="agentId" aria-label="数据集智能体" :disabled="loading">
            <option value="">请选择智能体</option>
            <option
              v-for="t in agents"
              :key="t.descriptor.ref.external_target_id"
              :value="t.descriptor.ref.external_target_id"
            >
              {{ t.descriptor.ref.external_target_id }} · {{ t.descriptor.display_name }}
            </option>
          </select></label
        >
        <label v-if="mode === 'cloudshrimp'"
          >Git 仓库分支地址<input
            v-model="branch"
            aria-label="数据集 Git 分支"
            list="dataset-branches"
            placeholder="填写或选择已登记分支"
            :disabled="!agentId || !branches.length" /><datalist id="dataset-branches">
            <option v-for="b in branches" :key="b" :value="b" /></datalist
        ></label>
        <label
          >智能体版本 <em>*</em
          ><select v-model="version" aria-label="数据集智能体版本" :disabled="!agentId">
            <option value="">请选择版本</option>
            <option
              v-for="t in versionTargets"
              :key="t.descriptor.content_sha256"
              :value="t.descriptor.ref.external_version_id"
            >
              {{ t.descriptor.ref.external_version_id }}
            </option>
          </select></label
        >
      </div>
      <p v-if="mode === 'cloudshrimp' && agentId && !branches.length" class="warning">
        当前部署未提供 Git 分支；只能预览当前部署版本，不能确认分支绑定。本演示不会虚构客户分支。
      </p>
      <p v-if="loadError" role="alert" class="warning">{{ loadError }}</p>
      <div class="target-actions">
        <button type="button" class="secondary" :disabled="loading" @click="loadTargets">
          {{ loading ? '读取目录中…' : '刷新智能体目录' }}</button
        ><button
          type="button"
          class="primary"
          :disabled="!selected || loading || runsLoading"
          @click="confirmTarget"
        >
          {{
            runsLoading ? '读取上下文中…' : pinned ? '重新读取定义与会话' : '确认并读取定义与会话'
          }}
        </button>
      </div>
      <section v-if="descriptor" class="definition" aria-label="关联智能体只读信息">
        <div class="definition-title">
          <b>{{ descriptor.display_name }} · {{ descriptor.ref.external_version_id }}</b
          ><span>只读版本快照</span>
        </div>
        <div class="context-tabs" role="tablist">
          <button
            v-for="t in [
              { id: 'prompt', name: '提示词' },
              { id: 'skills', name: 'Skill / Tool' },
              { id: 'nodes', name: '节点结构' },
              { id: 'sessions', name: '已有会话' },
            ]"
            :key="t.id"
            type="button"
            role="tab"
            :aria-selected="tab === t.id"
            @click="tab = t.id"
          >
            {{ t.name }}
          </button>
        </div>
        <div class="context-body">
          <template v-if="tab === 'prompt'"
            ><h4>{{ mode === 'workflow' ? '工作流服务提供的提示词' : '智能体系统提示词' }}</h4>
            <pre>{{ descriptor.prompt || '服务端未提供提示词' }}</pre>
            <template v-if="descriptor.metadata.summary_prompt"
              ><h4>回答汇总提示词</h4>
              <pre>{{ descriptor.metadata.summary_prompt }}</pre>
            </template>
            <p v-if="mode === 'workflow'" class="note">
              此处不是全部节点提示词；未提供的节点提示词不会自动补写。
            </p></template
          >
          <template v-else-if="tab === 'skills'"
            ><h4>Skill · {{ descriptor.skills.length }}</h4>
            <article v-for="s in descriptor.skills" :key="s.external_skill_id">
              <b>{{ s.name }}</b>
              <p>{{ s.description || '未提供描述' }}</p>
              <details v-if="s.prompt">
                <summary>Skill 提示词（只读）</summary>
                <pre>{{ s.prompt }}</pre>
              </details>
            </article>
            <p v-if="!descriptor.skills.length" class="note">该版本未声明 Skill。</p>
            <h4>Tool · {{ descriptor.tools?.length ?? 0 }}</h4>
            <article v-for="(t, i) in descriptor.tools" :key="i">
              <b>{{ t.name }}</b>
              <p>{{ t.description || '未提供描述' }}</p>
            </article></template
          >
          <template v-else-if="tab === 'nodes'"
            ><article v-for="node in nodes" :key="node.id">
              <b>{{ node.kind }} · {{ node.label }}</b>
              <p>{{ node.description || '未提供描述' }}</p>
              <pre v-if="node.prompt">{{ node.prompt }}</pre>
              <small v-else-if="node.kind === 'workflow'">未提供独立节点提示词</small>
            </article>
            <p v-if="!nodes.length">服务端未提供节点结构。</p></template
          >
          <template v-else>
            <p class="note">
              从最近 200 条评测中按来源、应用 ID
              与版本匹配。这里是已有评测会话，不等同于客户平台全部在线会话；复制到新版的历史记录也不代表新版已重跑。历史运行使用当时的定义快照，同一版本名不代表与当前定义摘要相同。
            </p>
            <p v-if="activeRun" class="fingerprint">
              历史目标摘要：{{ activeRun.manifest.target.descriptor_sha256 }}
            </p>
            <p v-if="runsLoading" role="status">正在读取历史评测…</p>
            <p v-else-if="runsError" role="alert">{{ runsError }}</p>
            <p v-else-if="!runs.length">暂无匹配的历史评测会话。</p>
            <template v-else
              ><div class="session-selects">
                <label
                  >来源评测<select v-model="runId" aria-label="来源评测">
                    <option value="">请选择评测</option>
                    <option v-for="r in runs" :key="r.id" :value="r.id">
                      {{ r.id.slice(0, 8) }} · {{ r.status }} · {{ r.created_at }}
                    </option>
                  </select></label
                ><label
                  >样本会话<select
                    v-model="caseId"
                    aria-label="样本会话"
                    :disabled="!runId"
                    @change="loadTrace"
                  >
                    <option value="">请选择会话</option>
                    <option v-for="c in cases" :key="c.id" :value="c.id">{{ c.name }}</option>
                  </select></label
                >
              </div>
              <p v-if="traceLoading" role="status">读取 Trace…</p>
              <p v-if="traceError" role="alert">{{ traceError }}</p>
              <template v-if="trace"
                ><p class="fingerprint">Trace：{{ trace.trace_id }}</p>
                <article v-for="(turn, id) in trace.turn_outcomes" :key="id">
                  <b>轮次 {{ id }}</b>
                  <h4>用户输入</h4>
                  <pre>{{ JSON.stringify(turn.input, null, 2) }}</pre>
                  <h4>实际输出（不是期望答案）</h4>
                  <pre>{{ JSON.stringify(turn.output, null, 2) }}</pre>
                </article>
                <p v-if="!Object.keys(trace.turn_outcomes ?? {}).length">
                  该 Trace 未提供分轮对话，不能推断完整会话。
                </p></template
              ></template
            >
          </template>
        </div>
        <p class="fingerprint">定义摘要：{{ descriptor.content_sha256 }}</p>
      </section>
      <h3><span class="step-number">02</span>数据集基本信息</h3>
      <label
        >头像 &amp; 数据集名称 <em>*</em>
        <div class="name-row">
          <select v-model="icon" aria-label="数据集头像">
            <option>🗂️</option>
            <option>💬</option>
            <option>🤖</option>
            <option>📋</option></select
          ><input
            v-model="name"
            maxlength="128"
            aria-label="数据集名称"
            placeholder="例如：贷款智能体·高风险申请回归集"
          /></div
      ></label>
      <div class="description-title">
        <label for="v2-dataset-description">描述 <em>*</em></label
        ><button type="button" class="text-button" :disabled="!descriptor" @click="autoDescription">
          ✦ 按智能体信息填写
        </button>
      </div>
      <textarea
        id="v2-dataset-description"
        v-model="description"
        maxlength="512"
        rows="3"
        placeholder="请简要说明评测内容与业务场景"
      />
      <div class="counter">{{ description.length }} / 512 · 自动填写使用元数据，不调用模型</div>
      <label class="tags-label"
        >场景标签 <em>*</em
        ><el-select
          v-model="tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="选择标签，或输入后按回车新增"
          aria-label="数据集场景标签"
          ><el-option
            v-for="t in ['贷款申请', '风险审核', '进度查询', '工具调用', '多轮对话', '安全合规']"
            :key="t"
            :label="t"
            :value="t" /></el-select
      ></label>
      <h3>变量定义 <span class="readonly-chip">自动读取 · 不可编辑</span></h3>
      <p v-if="!descriptor" class="empty-context">确认智能体版本后自动呈现。</p>
      <template v-else
        ><p class="note">当前展示服务端 input_schema 的输入字段，不代表已取得客户所有配置变量。</p>
        <table v-if="variables.length">
          <thead>
            <tr>
              <th>变量名</th>
              <th>类型</th>
              <th>必填</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[key, field] in variables" :key="key">
              <td>{{ key }}</td>
              <td>{{ field.type ?? '未提供' }}</td>
              <td>{{ descriptor.input_schema?.required?.includes(key) ? '是' : '否' }}</td>
              <td>{{ field.description || '未提供' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-context">服务端未提供变量定义。</p></template
      >
    </template>
    <template #footer
      ><p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="footer-actions">
        <span>关联信息不随数据集保存</span
        ><button type="button" class="secondary" :disabled="saving" @click="close">取消</button
        ><button type="button" class="secondary" :disabled="saving" @click="create(false)">
          创建空数据集</button
        ><button type="button" class="primary" :disabled="saving" @click="create(true)">
          {{ saving ? '正在保存…' : '创建并导入' }}
        </button>
      </div></template
    >
  </el-dialog>
</template>

<style scoped>
label {
  display: block !important;
}
label > input,
label > select,
label > .name-row,
label > :deep(.el-select) {
  margin-top: 9px;
}
.target-fields label {
  line-height: 1.6;
}
.target-actions {
  flex-wrap: wrap;
}
.target-actions button {
  white-space: normal;
}
.v2-scope {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #eef3ff;
  border: 1px solid #dce6ff;
  color: #55709c;
  border-radius: 10px;
  font-size: 12px;
  margin-bottom: 24px;
}
.v2-scope b {
  color: #2864dd;
}
h3 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 24px 0 18px;
  font-size: 17px;
  color: #243247;
}
.step-number {
  background: #edf2ff;
  color: #2968ee;
  font-size: 13px;
  padding: 7px;
  border-radius: 7px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 9px;
  font-size: 14px;
  color: #364459;
}
em {
  color: #ec5869;
  font-style: normal;
}
input,
select,
textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #d9dfeb;
  background: white;
  color: #263650;
  border-radius: 8px;
  padding: 11px 12px;
  font: inherit;
  outline: none;
}
input:focus,
select:focus,
textarea:focus {
  border-color: #3774ff;
  box-shadow: 0 0 0 3px #3774ff12;
}
select:disabled {
  background: #f4f6fa;
  color: #98a1b1;
}
textarea {
  resize: vertical;
}
.target-fields {
  display: grid;
  grid-template-columns: 0.8fr 1.8fr 0.8fr;
  gap: 14px;
  align-items: end;
}
.target-fields.cloud {
  grid-template-columns: 0.7fr 1.3fr 1.5fr 0.65fr;
}
.target-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}
.definition {
  margin-top: 20px;
  border: 1px solid #dce4f0;
  border-radius: 12px;
  overflow: hidden;
}
.definition-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  background: #f7f9fe;
}
.definition-title span,
.readonly-chip {
  font-size: 12px;
  color: #71819a;
}
.context-tabs {
  display: flex;
  gap: 4px;
  padding: 0 12px;
  border-bottom: 1px solid #e5eaf2;
}
.context-tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: white;
  color: #6a7890;
  padding: 12px;
  cursor: pointer;
}
.context-tabs button[aria-selected='true'] {
  color: #2869f3;
  border-bottom-color: #2869f3;
}
.context-body {
  padding: 16px 18px;
  max-height: 300px;
  overflow: auto;
}
.context-body h4 {
  margin: 0 0 10px;
  font-size: 13px;
}
.context-body article {
  border-bottom: 1px solid #e7ebf2;
  padding: 12px 0;
  font-size: 13px;
}
.context-body article p {
  line-height: 1.6;
}
.context-body pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f6f8fc;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
}
.fingerprint {
  font: 11px monospace;
  color: #8591a4;
  overflow-wrap: anywhere;
  padding: 0 18px;
}
.session-selects {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.name-row {
  display: flex;
  gap: 10px;
}
.name-row select {
  width: 65px;
}
.description-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 20px 0 10px;
}
.text-button {
  border: 0;
  background: transparent;
  color: #326fed;
  cursor: pointer;
}
.text-button:disabled {
  color: #a3acba;
  cursor: default;
}
.counter {
  text-align: right;
  font-size: 11px;
  color: #8591a4;
  margin-top: 6px;
}
.tags-label {
  margin-top: 20px;
}
.tags-label :deep(.el-select) {
  width: 100%;
}
.tags-label :deep(.el-select__wrapper) {
  min-height: 42px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th,
td {
  text-align: left;
  padding: 11px 14px;
  border-bottom: 1px solid #e7edf5;
}
th {
  background: #f7f9fc;
  color: #77869d;
}
.note,
.empty-context {
  color: #77869d;
  font-size: 12px;
  line-height: 1.7;
}
.empty-context {
  padding: 20px;
  text-align: center;
  border: 1px dashed #dce4f0;
  border-radius: 8px;
}
.warning {
  font-size: 12px;
  line-height: 1.7;
  color: #95691f;
  background: #fff9e9;
  border: 1px solid #f4e4bf;
  border-radius: 8px;
  padding: 10px 14px;
}
.form-error {
  color: #c8404b;
  text-align: left;
  font-size: 13px;
  background: #fff1f2;
  padding: 10px;
  border-radius: 6px;
}
.footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.footer-actions > span {
  margin-right: auto;
  font-size: 11px;
  color: #8994a7;
}
.primary {
  background: #008b76 !important;
  border-color: #008b76 !important;
  color: white;
}
.secondary {
  border-color: #d7deeb !important;
  background: white !important;
  color: #52617b !important;
}
.wizard-steps {
  display: flex;
  justify-content: center;
  gap: 20px;
  align-items: center;
  padding: 30px 0 40px;
  font-size: 14px;
  color: #96a0b1;
}
.wizard-steps b {
  color: #008b76;
}
.import-methods {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}
.import-methods button {
  display: flex;
  flex-direction: column;
  gap: 14px;
  border: 1px solid #e0e5ef;
  border-radius: 12px;
  background: white;
  padding: 24px;
  text-align: left;
  color: #425169;
}
.import-methods strong {
  font-size: 17px;
}
.import-methods span {
  font-size: 13px;
}
.import-methods small {
  font-size: 11px;
  color: #8a96aa;
}
.import-methods .chosen {
  border-color: #008b76;
  background: #f4f7ff;
}
.import-methods button:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.sample-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.sample-tabs button {
  padding: 10px 14px;
  background: #f7f9fd;
  border: 1px solid #dce4f1;
  border-radius: 7px;
  color: #60718b;
  cursor: pointer;
}
.sample-tabs .chosen {
  background: #eef4ff;
  border-color: #3774ff;
  color: #008b76;
}
.sample-block {
  margin: 20px 0;
  padding: 0 16px 16px;
  border: 1px solid #e0e6f2;
  border-top: 3px solid #8aaeff;
  border-radius: 10px;
}
.sample-block.expected {
  border-top-color: #83d8bd;
}
.complete-mark {
  margin: 30px auto 18px;
  width: 60px;
  height: 60px;
  line-height: 60px;
  border-radius: 50%;
  background: #edf7f3;
  text-align: center;
  color: #1c9a71;
  font-size: 30px;
}
.complete-title,
.complete-subtitle {
  text-align: center;
}
.complete-subtitle {
  color: #8692a5;
  font-size: 13px;
}
.preview-summary {
  margin: 24px 0;
  border: 1px solid #e2e8f1;
  border-radius: 12px;
  padding: 12px 20px;
}
.preview-summary > div {
  display: grid;
  grid-template-columns: 150px 1fr;
  padding: 12px 0;
  gap: 12px;
  font-size: 13px;
}
.preview-summary span {
  color: #8994a7;
}
.preview-summary b {
  color: #3f506b;
  overflow-wrap: anywhere;
}
@media (max-width: 760px) {
  .target-fields,
  .target-fields.cloud,
  .session-selects,
  .import-methods {
    grid-template-columns: 1fr;
  }
  .context-tabs {
    overflow: auto;
    white-space: nowrap;
  }
  .preview-summary > div {
    grid-template-columns: 110px 1fr;
  }
  .footer-actions > span {
    width: 100%;
  }
  .wizard-steps {
    gap: 10px;
  }
}
</style>
