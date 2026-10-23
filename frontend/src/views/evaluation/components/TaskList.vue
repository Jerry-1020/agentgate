<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { request, statusLabel, score } from '../../../api/evaluations';
import {
  getTaskSummaries,
  type TaskListSummary,
  type TaskKind,
  type TaskAction,
} from '../../../api/evaluation-summaries';
import { useAuthStore } from '../../../stores/modules/auth';
import { useSummaryQuery } from '../composables/use-summary-query';
import { dayWindow, taskPath, hasActiveRuns, evaluatorStrategy } from '../utils/summary-query';
const props = defineProps<{ refreshToken?: number }>();
const emit = defineEmits<{
  connection: [online: boolean | null];
  create: [];
  navigate: [path: string];
  action: [action: TaskAction];
}>();
const auth = useAuthStore();
const days = ref(7),
  taskTab = ref<TaskKind | ''>(''),
  query = ref(''),
  keyword = ref(''),
  page = ref(1),
  checked = ref<string[]>([]);
let debounce: ReturnType<typeof setTimeout> | undefined;
watch(query, (value) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    keyword.value = value;
  }, 300);
});
watch(
  [days, taskTab, keyword],
  () => {
    page.value = 1;
    checked.value = [];
  },
  { flush: 'sync' },
);
watch(
  () => [auth.loginMode, auth.teamId, auth.userId, auth.token, auth.platformReady],
  () => {
    page.value = 1;
    checked.value = [];
  },
  { flush: 'sync' },
);
watch(page, () => {
  checked.value = [];
});
const queryState = useSummaryQuery({
  source: () => [days.value, taskTab.value, keyword.value, page.value, props.refreshToken],
  identity: () => [auth.loginMode, auth.teamId, auth.userId, auth.token, auth.platformReady],
  ready: () => auth.authenticated,
  load: (signal) =>
    getTaskSummaries(
      {
        ...dayWindow(days.value),
        page: page.value,
        page_size: 20,
        keyword: keyword.value,
        ...(taskTab.value ? { kind: taskTab.value } : {}),
      },
      signal,
    ),
  poll: (value) => hasActiveRuns(value.items),
});
const { data, error, loading: busy, reload: load } = queryState;
watch([data, error], () => emit('connection', error.value ? false : data.value ? true : null));
const rows = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);
watch(data, (value) => {
  if (!value) return;
  const last = Math.max(1, Math.ceil(value.total / 20));
  if (page.value > last) page.value = last;
  checked.value = checked.value.filter((id) => value.items.some((row) => row.id === id));
});
const identityColumns = ['target', 'dataset'] as const;
function comparisonSides(row: TaskListSummary, column: (typeof identityColumns)[number]) {
  return row.runs.map((run, index) => ({
    id: run.run_id,
    label: index === 0 ? 'A' : 'B',
    name: (column === 'target' ? run.target_name : run.dataset_name) ?? '—',
    version:
      column === 'target'
        ? (run.target_version ?? '—')
        : run.dataset_version === null
          ? '—'
          : `v${run.dataset_version}`,
  }));
}
const done = (row: TaskListSummary) => row.total_cases === null || row.completed_cases === null
  ? null : ({ done: row.completed_cases, total: row.total_cases });
async function deleteTask(id: string) {
  try {
    await ElMessageBox.confirm(
      '删除后任务及其运行记录、Trace 和结果将不可恢复。确定删除？',
      '删除任务',
      { type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  try {
    await request(`/evaluation-tasks/${encodeURIComponent(id)}`, 'DELETE');
    ElMessage.success('任务已删除');
    await load();
  } catch (cause) {
    ElMessage.error('删除失败：' + String(cause));
  }
}
onUnmounted(() => clearTimeout(debounce));
</script>
<template>
  <div class="page-head">
    <div style="display: flex; align-items: flex-end; gap: 16px">
      <h1 class="page-title">测评任务</h1>
      <div class="tabs" role="group" aria-label="任务时间范围">
        <button
          v-for="d in [1, 7, 30, 0]"
          :key="d"
          :class="['tab', { active: days === d }]"
          :aria-pressed="days === d"
          @click="days = d"
        >
          {{ d === 0 ? '全部' : d === 1 ? '今日' : '近' + d + '天' }}
        </button>
      </div>
    </div>
  </div>
  <section class="card tasks-list">
    <p v-if="error" role="alert">{{ error }} <button class="link" @click="load">重试</button></p>
    <div class="list-toolbar">
      <nav class="tabs">
        <button class="tab" :class="{ active: !taskTab }" @click="taskTab = ''">全部</button>
        <button
          v-for="t in [
            ['single', '单任务'],
            ['ab', 'A/B试验'],
          ]"
          :key="'tt-' + t[0]"
          class="tab"
          :class="{ active: taskTab === t[0] }"
          @click="taskTab = t[0] as TaskKind"
        >
          {{ t[1] }}
        </button>
      </nav>
      <div class="filters-right">
        <input
          class="input search-input"
          v-model="query"
          aria-label="搜索任务名称"
          placeholder="搜索任务名称或 ID"
        />
        <button class="primary" @click="emit('create')">新建测评任务</button>
      </div>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <colgroup>
          <col style="width: 3%" />
          <col style="width: 17%" />
          <col style="width: 8%" />
          <col style="width: 13%" />
          <col style="width: 15%" />
          <col style="width: 18%" />
          <col style="width: 10%" />
          <col style="width: 8%" />
          <col style="width: 8%" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="选择本页任务"
                :checked="!!rows.length && rows.every((r) => checked.includes(r.id))"
                @change="
                  checked = ($event.target as HTMLInputElement).checked ? rows.map((r) => r.id) : []
                "
              />
            </th>
            <th>任务名称</th>
            <th>任务类型</th>
            <th>被测Agent</th>
            <th>测评集</th>
            <th>评估方式</th>
            <th>进度与状态</th>
            <th>得分</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>
              <input
                type="checkbox"
                v-model="checked"
                :value="r.id"
                :aria-label="'选择任务 ' + r.id"
              />
            </td>
            <td class="name-cell">
              <button class="link" :title="r.name" @click="emit('navigate', taskPath(r))">
                {{ r.name }}</button
              ><small>{{ new Date(r.created_at).toLocaleString() }}</small>
              <small v-if="r.summary_pending" role="status">{{ r.runs.length > 1 ? '部分摘要待更新' : '摘要待更新' }}</small>
              <small v-if="r.previous_run_count">已重跑 {{ r.previous_run_count }} 次</small>
            </td>
            <td>
              <span>{{
                r.kind === 'ab' ? 'A/B试验' : r.kind === 'stability' ? '稳定性测试' : '单任务'
              }}</span>
            </td>
            <td v-for="column in identityColumns" :key="column">
              <el-tooltip
                v-if="r.kind === 'ab'"
                placement="top"
                effect="light"
                :trigger="['hover', 'focus']"
                :enterable="false"
                :hide-after="0"
              >
                <template #content>
                  <div class="ab-tooltip">
                    <div
                      v-for="side in comparisonSides(r, column)"
                      :key="side.id"
                      class="ab-tooltip-row"
                    >
                      <span class="ab-side">{{ side.label }}</span>
                      <div>
                        <div>{{ side.name }}</div>
                        <div class="ab-tooltip-version">{{ side.version }}</div>
                      </div>
                    </div>
                  </div>
                </template>
                <div class="ab-summary" tabindex="0">
                  <span
                    v-for="side in comparisonSides(r, column)"
                    :key="side.id"
                    class="primary-text"
                  >
                    {{ side.label }}：{{ side.name }}（{{ side.version }}）
                  </span>
                </div>
              </el-tooltip>
              <template v-else>
                <span
                  class="primary-text"
                  :title="(column === 'target' ? r.runs[0].target_name : r.runs[0].dataset_name) ?? undefined"
                  >{{ (column === 'target' ? r.runs[0].target_name : r.runs[0].dataset_name) ?? '—' }}</span
                ><small>{{
                  column === 'target'
                    ? (r.runs[0].target_version ?? '—')
                    : r.runs[0].dataset_version === null
                      ? '—'
                      : `v${r.runs[0].dataset_version}`
                }}</small>
              </template>
            </td>
            <td>
              <span>{{ evaluatorStrategy(r.runs[0].evaluator_kinds) || '—' }}</span>
            </td>
            <td class="progress-cell">
              <template v-if="done(r)"
                ><div>
                  {{ done(r)!.done }}/{{ done(r)!.total }}
                  <b
                    >{{
                      done(r)!.total ? Math.round((done(r)!.done / done(r)!.total) * 100) : 0
                    }}%</b
                  >
                </div>
                <progress
                  :value="done(r)!.done"
                  :max="done(r)!.total || 1"
                  :class="{ failed: r.status === 'failed' }" /></template
              ><span v-else>—</span><small>{{ statusLabel(r.status) }}</small>
            </td>
            <td class="task-score">
              <template v-if="r.summary_pending">—</template><template v-else-if="r.kind === 'ab'"
                ><p v-for="(id, i) in r.runs.map((run) => run.run_id)" :key="id">
                  {{ i === 0 ? 'A' : 'B' }}
                  {{ score(r.runs.find((run) => run.run_id === id)?.overall_score ?? null) }}
                </p></template
              ><template v-else>{{ score(r.runs[0].overall_score) }}</template
              ><small v-if="r.runs[0].gate_reason === 'evaluator_error'" class="danger"
                >评估器异常</small
              >
            </td>
            <td class="row-actions">
              <button
                v-if="
                  (r.kind ?? 'single') === 'single' &&
                  ['pending', 'running', 'scheduled'].includes(r.status)
                "
                class="link"
                @click="
                  emit('action', { runId: r.runs[0].run_id, taskId: r.task_id, action: 'cancel' })
                "
              >
                取消
              </button>
              <button
                v-if="
                  (r.kind ?? 'single') === 'single' &&
                  ['completed', 'failed', 'cancelled'].includes(r.status)
                "
                class="link"
                @click="
                  emit('action', { runId: r.runs[0].run_id, taskId: r.task_id, action: 'rerun' })
                "
              >
                重跑
              </button>
              <button
                v-if="r.kind === 'ab' && ['completed', 'failed', 'cancelled'].includes(r.status)"
                type="button"
                class="link"
              >
                重跑
              </button>
              <button class="link danger" @click="deleteTask(r.task_id ?? r.runs[0].run_id)">
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!rows.length" class="empty">{{ busy ? '正在加载…' : '暂无符合条件的任务' }}</p>
    <footer>
      <span>共 {{ total }} 个任务</span
      ><button class="secondary" :disabled="page === 1" @click="page--">上一页</button
      ><span>{{ page }} / {{ Math.max(1, Math.ceil(total / 20)) }}</span
      ><button class="secondary" :disabled="page * 20 >= total" @click="page++">下一页</button>
    </footer>
  </section>
</template>
<style scoped>
.search-input {
  width: 160px !important;
}
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.list-toolbar .tabs {
  margin-bottom: 0;
}
.filters-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.filters-right .input {
  width: 200px;
}
.tab-sep {
  color: var(--el-border-color);
  margin: 0 4px;
  user-select: none;
}
.tasks-list {
  padding: 16px;
}
.filters {
  gap: 12px;
  margin: 24px 0;
  flex-wrap: wrap;
}
.filters > .input:first-child {
  width: 240px;
}
.filters select {
  width: 145px;
}
.filters > .primary {
  margin-left: auto;
}
.date-range {
  display: flex;
  align-items: center;
  border: 1px solid #d9e2de;
  padding: 8px;
  border-radius: 7px;
  gap: 4px;
}
.date-range input {
  border: 0;
  background: none;
  color: #687d71;
  width: 110px;
  min-width: 0;
  font: inherit;
  font-size: 13px;
}
.data-table {
  width: 100%;
  min-width: 1100px;
  table-layout: fixed;
  font-size: 13px;
}
.data-table th {
  padding: 10px 6px;
  white-space: nowrap;
}
.primary-text,
.name-cell .link {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.name-cell .link {
  text-align: left;
  font-weight: 500;
  line-height: inherit;
}
.data-table small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  color: #81928a;
  margin-top: 8px;
}
.data-table td {
  vertical-align: top;
  white-space: nowrap;
  line-height: 22px;
  padding: 16px 6px;
}
.ab-summary {
  cursor: default;
}
.ab-summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.ab-tooltip {
  max-width: min(420px, calc(100vw - 48px));
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 22px;
}
.ab-tooltip-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
}
.ab-tooltip-row + .ab-tooltip-row {
  margin-top: 10px;
}
.ab-side {
  text-align: center;
  border-radius: 4px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.ab-tooltip-version {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.data-table .row-actions {
  white-space: normal;
}
.row-actions button {
  margin: 0 8px 0 0;
  height: auto;
  padding: 0;
  border: 0;
  font-size: 12px;
  line-height: inherit;
}
.progress-cell {
  min-width: 0;
}
.progress-cell > div {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.progress-cell progress {
  width: 100%;
  height: 7px;
  margin-top: 8px;
  border: 0;
  accent-color: #00af8e;
  border-radius: 8px;
  overflow: hidden;
}
progress::-webkit-progress-bar {
  background: #edf1ef;
}
progress::-webkit-progress-value {
  background: #0ab292;
}
progress.failed::-webkit-progress-value {
  background: #e2646e;
}
.task-score {
  font-size: 14px;
  font-weight: 650;
  color: #00a584;
}
.task-score p {
  margin: 0;
  font: inherit;
  white-space: nowrap;
}
.task-score .danger {
  color: #c45454;
}
footer {
  display: flex;
  justify-content: flex-end;
  gap: 18px;
  align-items: center;
  padding-top: 22px;
  font-size: 13px;
  color: #81928a;
}
footer > span:first-child {
  margin-right: auto;
}
</style>
