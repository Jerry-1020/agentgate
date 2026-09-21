<script lang="ts">
export type AgentTypeGroup = 'base/workflow' | 'abcclaw';
export interface PlatformTeam {
  teamId: string;
  teamName: string;
}
export interface PlatformAgent {
  agentId: string;
  agentName: string;
  typeGroup: AgentTypeGroup | null;
  platformAgentType: string | null;
  platformArrangeType: string | null;
}
export interface PlatformBranch {
  branchId: string;
  branchName: string | null;
  children: readonly PlatformBranch[];
}
export interface PlatformVersion {
  agentVersion: string;
  status?: string;
}
export interface AgentTargetSelection extends PlatformTeam {
  agentId: string;
  agentName: string;
  typeGroup: AgentTypeGroup;
  platformAgentType: string | null;
  platformArrangeType: string | null;
  branchId: string | null;
  branchName: string | null;
  agentVersion: string;
}
// Providers return complete, normalized lists; HTTP and pagination stay outside the UI.
export interface AgentDirectory {
  getTeams(input: { token: string }): Promise<readonly PlatformTeam[]>;
  getAgents(input: { token: string; teamId: string }): Promise<readonly PlatformAgent[]>;
  getBranches(input: { token: string; agentId: string }): Promise<readonly PlatformBranch[]>;
  getAgentVersions(input: { token: string; agentId: string }): Promise<readonly PlatformVersion[]>;
  getBranchVersions(input: {
    token: string;
    agentId: string;
    branchId: string;
  }): Promise<readonly PlatformVersion[]>;
}
</script>

<script setup lang="ts">
import { computed, getCurrentInstance, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { ElOption, ElSelect } from 'element-plus';

const props = withDefaults(defineProps<{ directory: AgentDirectory; disabled?: boolean }>(), {
  disabled: false,
});
const emit = defineEmits<{ 'selection-change': [selection: AgentTargetSelection | null] }>();
type ListKey = 'team' | 'agent' | 'branch' | 'version';
type FieldKey = ListKey | 'type';
type LoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';
const prefix = `agent-target-${getCurrentInstance()!.uid}`;
const tokenDraft = ref('');
const lockedToken = ref('');
const loginError = ref('');
const selected = reactive({ team: '', type: '', agent: '', branch: '', version: '' });
const teams = ref<readonly PlatformTeam[]>([]);
const agents = ref<readonly PlatformAgent[]>([]);
const branches = ref<readonly (PlatformBranch & { depth: number })[]>([]);
const versions = ref<readonly PlatformVersion[]>([]);
const states = reactive<Record<ListKey, LoadState>>({
  team: 'idle',
  agent: 'idle',
  branch: 'idle',
  version: 'idle',
});
const errors = reactive<Record<ListKey, string>>({ team: '', agent: '', branch: '', version: '' });
const sequence: Record<ListKey, number> = { team: 0, agent: 0, branch: 0, version: 0 };
let session = 0;
let disposed = false;
const loggedIn = computed(() => !!lockedToken.value);
const currentTeam = computed(() => teams.value.find((item) => item.teamId === selected.team));
const currentAgent = computed(() => agents.value.find((item) => item.agentId === selected.agent));
const currentBranch = computed(() =>
  branches.value.find((item) => item.branchId === selected.branch),
);
const currentVersion = computed(() =>
  versions.value.find((item) => item.agentVersion === selected.version),
);
const typeError = computed(() => {
  if (!currentAgent.value) return '';
  if (!currentAgent.value.typeGroup) return '该智能体类型未知或存在冲突，暂不支持选择。';
  return currentAgent.value.typeGroup !== selected.type
    ? '所选类型与该智能体不一致，请调整选择。'
    : '';
});
const teamAvailable = computed(
  () => loggedIn.value && states.team === 'ready' && !!currentTeam.value,
);
const agentAvailable = computed(
  () =>
    teamAvailable.value &&
    states.agent === 'ready' &&
    !!currentAgent.value &&
    !!selected.type &&
    !typeError.value,
);
const branchAvailable = computed(
  () => agentAvailable.value && states.branch === 'ready' && !!currentBranch.value,
);
const selection = computed<AgentTargetSelection | null>(() => {
  if (disposed || !agentAvailable.value || states.version !== 'ready' || !currentVersion.value)
    return null;
  if (selected.type === 'abcclaw' && !branchAvailable.value) return null;
  const agent = currentAgent.value!;
  return {
    teamId: currentTeam.value!.teamId,
    teamName: currentTeam.value!.teamName,
    agentId: agent.agentId,
    agentName: agent.agentName,
    typeGroup: agent.typeGroup!,
    platformAgentType: agent.platformAgentType,
    platformArrangeType: agent.platformArrangeType,
    branchId: selected.type === 'abcclaw' ? currentBranch.value!.branchId : null,
    branchName: selected.type === 'abcclaw' ? currentBranch.value!.branchName : null,
    agentVersion: currentVersion.value.agentVersion,
  };
});
watch(selection, (value) => emit('selection-change', value ? { ...value } : null), {
  immediate: true,
  flush: 'sync',
});

function clearList(key: ListKey) {
  sequence[key]++;
  states[key] = 'idle';
  errors[key] = '';
  selected[key] = '';
  if (key === 'team') teams.value = [];
  if (key === 'agent') agents.value = [];
  if (key === 'branch') branches.value = [];
  if (key === 'version') versions.value = [];
}
function clearAfter(key: FieldKey) {
  if (key === 'team') selected.type = '';
  if (key === 'team' || key === 'type') clearList('agent');
  if (key !== 'branch' && key !== 'version') clearList('branch');
  if (key !== 'version') clearList('version');
}
function logout() {
  session++;
  lockedToken.value = '';
  tokenDraft.value = '';
  loginError.value = '';
  clearList('team');
  clearAfter('team');
}
function login() {
  if (props.disabled || loggedIn.value) return;
  const token = tokenDraft.value;
  if (!token.trim() || token.length > 512 || /\s/.test(token) || /^Bearer\b/i.test(token)) {
    loginError.value = '请填写不含空白、换行或 Bearer 前缀的原始 token，最多 512 个字符。';
    return;
  }
  session++;
  lockedToken.value = token;
  loginError.value = '';
}
function selectField(key: FieldKey, value: string) {
  if (props.disabled || fields.value.find((field) => field.key === key)?.disabled) return;
  if (selected[key] === value) return;
  clearAfter(key);
  selected[key] = value;
}
function context(key: ListKey) {
  return JSON.stringify([
    session,
    key === 'team' ? '' : selected.team,
    key === 'team' ? '' : selected.type,
    key === 'branch' || key === 'version' ? selected.agent : '',
    key === 'version' ? selected.branch : '',
  ]);
}
async function loadList<T>(
  key: ListKey,
  fetch: () => Promise<readonly T[]>,
  accept: (items: readonly T[]) => void,
) {
  if (props.disabled || states[key] === 'loading') return;
  const ticket = ++sequence[key];
  const start = context(key);
  states[key] = 'loading';
  errors[key] = '';
  const active = () => !disposed && ticket === sequence[key] && start === context(key);
  try {
    const items = await fetch();
    if (!active()) return;
    accept(items);
    states[key] = items.length ? 'ready' : 'empty';
  } catch (error) {
    if (!active()) return;
    const status = (error as { status?: unknown } | null)?.status;
    errors[key] =
      status === 401 || status === 403
        ? 'Token 无效或无权访问，请取消登录后重新填写。'
        : '查询失败，请重试。';
    states[key] = 'error';
  }
}
function loadTeams() {
  if (!loggedIn.value) return;
  return loadList(
    'team',
    () => props.directory.getTeams({ token: lockedToken.value }),
    (items) => {
      teams.value = items;
      if (selected.team && !currentTeam.value) {
        selected.team = '';
        clearAfter('team');
      }
    },
  );
}
function loadAgents() {
  if (!teamAvailable.value || !selected.type) return;
  return loadList(
    'agent',
    () => props.directory.getAgents({ token: lockedToken.value, teamId: selected.team }),
    (items) => {
      agents.value = items;
      if (selected.agent && (!currentAgent.value || typeError.value)) {
        selected.agent = '';
        clearAfter('agent');
      }
    },
  );
}
function flattenBranches(
  items: readonly PlatformBranch[],
  depth = 0,
): (PlatformBranch & { depth: number })[] {
  return items.flatMap((item) => [
    { ...item, depth },
    ...flattenBranches(item.children, depth + 1),
  ]);
}
function loadBranches() {
  if (!agentAvailable.value || selected.type !== 'abcclaw') return;
  return loadList(
    'branch',
    () => props.directory.getBranches({ token: lockedToken.value, agentId: selected.agent }),
    (items) => {
      branches.value = flattenBranches(items);
      if (selected.branch && !currentBranch.value) {
        selected.branch = '';
        clearAfter('branch');
      }
    },
  );
}
function loadVersions() {
  if (!agentAvailable.value || (selected.type === 'abcclaw' && !branchAvailable.value)) return;
  return loadList(
    'version',
    () => {
      const input = { token: lockedToken.value, agentId: selected.agent };
      return selected.type === 'abcclaw'
        ? props.directory.getBranchVersions({ ...input, branchId: selected.branch })
        : props.directory.getAgentVersions(input);
    },
    (items) => {
      versions.value = items;
      if (!currentVersion.value) selected.version = '';
    },
  );
}
const loaders = { team: loadTeams, agent: loadAgents, branch: loadBranches, version: loadVersions };
const fields = computed(() => [
  {
    key: 'team' as const,
    label: '选择团队',
    placeholder: loggedIn.value ? '请选择团队' : '请先登录',
    disabled: !loggedIn.value,
    options: teams.value.map((item) => ({
      value: item.teamId,
      label: `${item.teamName} · ${item.teamId}`,
    })),
  },
  {
    key: 'type' as const,
    label: '智能体类型',
    placeholder: '请选择智能体类型',
    disabled: !teamAvailable.value,
    options: [
      { value: 'base/workflow', label: 'base/workflow' },
      { value: 'abcclaw', label: 'abcclaw' },
    ],
  },
  {
    key: 'agent' as const,
    label: '选择智能体',
    placeholder: selected.type ? '请选择智能体' : '请先选择团队和类型',
    disabled: !teamAvailable.value || !selected.type,
    options: agents.value.map((item) => ({
      value: item.agentId,
      label: `${item.agentName} · ${item.agentId}`,
    })),
  },
  {
    key: 'branch' as const,
    label: 'branchId',
    placeholder: selected.type === 'base/workflow' ? '不适用（base/workflow）' : '请选择 branchId',
    disabled: !agentAvailable.value || selected.type !== 'abcclaw',
    options: branches.value.map((item) => ({
      value: item.branchId,
      label: `${'↳ '.repeat(item.depth)}${item.branchName || item.branchId} · ${item.branchId}`,
    })),
  },
  {
    key: 'version' as const,
    label: '智能体版本',
    placeholder:
      selected.type === 'abcclaw' && !selected.branch ? '请先选择 branchId' : '请选择版本',
    disabled: !agentAvailable.value || (selected.type === 'abcclaw' && !branchAvailable.value),
    options: versions.value.map((item) => ({
      value: item.agentVersion,
      label: item.status ? `${item.agentVersion} · ${item.status}` : item.agentVersion,
    })),
  },
]);
function openField(key: FieldKey, open: boolean) {
  if (open && key !== 'type') void loaders[key]();
}
function readSubmissionSelection(): { target: AgentTargetSelection; token: string } | null {
  return !disposed && selection.value
    ? { target: { ...selection.value }, token: lockedToken.value }
    : null;
}
defineExpose({ readSubmissionSelection });
watch(() => props.directory, logout);
onBeforeUnmount(() => {
  disposed = true;
  logout();
  emit('selection-change', null);
});
</script>

<template>
  <section class="agent-target-picker" aria-label="评测对象选择">
    <div class="token-field">
      <label :for="`${prefix}-token`">请填写token</label>
      <div class="token-row">
        <textarea
          :id="`${prefix}-token`"
          v-model="tokenDraft"
          maxlength="512"
          rows="2"
          :readonly="loggedIn"
          :disabled="disabled"
          autocomplete="off"
          spellcheck="false"
          placeholder="请填写token，最多 512 个字符"
          :aria-describedby="`${prefix}-token-help`"
          @input="loginError = ''"
        />
        <button
          type="button"
          :disabled="disabled || (!loggedIn && !tokenDraft.trim())"
          @click="loggedIn ? logout() : login()"
        >
          {{ loggedIn ? '取消登录' : '登录' }}
        </button>
      </div>
      <div :id="`${prefix}-token-help`" class="token-help">
        <span>{{ loggedIn ? '已登录 · Token 已锁定' : '未登录' }}</span>
        <span>{{ tokenDraft.length }} / 512</span>
      </div>
      <p v-if="loginError" role="alert" class="field-error">{{ loginError }}</p>
    </div>
    <div class="target-fields">
      <div
        v-for="field in fields"
        :key="field.key"
        class="target-field"
        :class="{ wide: field.key === 'agent' }"
      >
        <label :id="`${prefix}-${field.key}-label`" :for="`${prefix}-${field.key}`">{{
          field.label
        }}</label>
        <ElSelect
          :id="`${prefix}-${field.key}`"
          :model-value="selected[field.key]"
          :aria-label="field.label"
          :role="disabled || field.disabled ? 'combobox' : undefined"
          :aria-labelledby="disabled || field.disabled ? `${prefix}-${field.key}-label` : undefined"
          :aria-disabled="disabled || field.disabled ? true : undefined"
          :aria-expanded="disabled || field.disabled ? false : undefined"
          :placeholder="field.placeholder"
          :disabled="disabled || field.disabled"
          :loading="field.key !== 'type' && states[field.key] === 'loading'"
          loading-text="正在加载…"
          no-data-text="暂无可选项"
          :teleported="false"
          @visible-change="(open: boolean) => openField(field.key, open)"
          @change="(value: string) => selectField(field.key, value)"
        >
          <ElOption
            v-for="option in field.options"
            :key="option.value"
            :label="option.label"
            :value="option.value"
            :disabled="field.key !== 'type' && states[field.key] !== 'ready'"
          />
        </ElSelect>
        <template v-if="field.key !== 'type'">
          <p v-if="states[field.key] === 'loading'" role="status">
            正在加载{{ field.label.replace('选择', '') }}…
          </p>
          <p v-if="states[field.key] === 'empty'" role="status">
            暂无可选{{ field.label.replace('选择', '') }}。
          </p>
          <div v-if="states[field.key] === 'error'" class="field-error">
            <span role="alert">{{ errors[field.key] }}</span>
            <button
              type="button"
              :aria-label="`重试${field.label}`"
              :disabled="disabled || field.disabled"
              @click="loaders[field.key]()"
            >
              重试
            </button>
          </div>
        </template>
        <p v-if="field.key === 'agent' && typeError" role="alert" class="field-error">
          {{ typeError }}
        </p>
      </div>
    </div>
    <p class="target-status" role="status">
      {{
        selection
          ? `已选择：${selection.agentName} / ${selection.typeGroup}${selection.branchId ? ' / ' + selection.branchId : ''} / ${selection.agentVersion}`
          : '请完成评测对象选择。'
      }}
    </p>
  </section>
</template>

<style scoped>
.agent-target-picker {
  color: var(--el-text-color-primary);
}
.agent-target-picker * {
  box-sizing: border-box;
}
.token-field,
.target-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.token-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
textarea {
  width: 100%;
  min-width: 0;
  resize: vertical;
  font: inherit;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  color: inherit;
  background: var(--el-bg-color);
}
textarea[readonly],
textarea:disabled {
  background: var(--el-fill-color-light);
}
button {
  padding: 9px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-bg-color);
  color: var(--el-color-primary);
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}
button:disabled {
  color: var(--el-text-color-disabled);
  cursor: not-allowed;
}
.token-help {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.target-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  margin-top: 20px;
}
.target-field.wide {
  grid-column: 1 / -1;
}
.target-field :deep(.el-select) {
  width: 100%;
}
.target-field :deep(.el-select-dropdown__item) {
  max-width: 100%;
}
.target-field p,
.field-error {
  margin: 0;
  overflow-wrap: anywhere;
}
.field-error {
  color: var(--el-color-danger);
}
.field-error button {
  margin-left: 8px;
}
.target-status {
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  overflow-wrap: anywhere;
}
@media (max-width: 520px) {
  .target-fields {
    grid-template-columns: minmax(0, 1fr);
  }
  .token-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
