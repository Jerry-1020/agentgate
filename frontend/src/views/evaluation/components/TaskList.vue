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
import { useTaskTimings } from '../composables/use-task-timings';
import { dayWindow, taskPath, hasActiveRuns, evaluatorStrategy } from '../utils/summary-query';
import { formatTaskTime, taskTiming } from '../utils/task-timing';
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
  page = ref(1);
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
  },
  { flush: 'sync' },
);
watch(
  () => [auth.loginMode, auth.teamId, auth.userId, auth.token, auth.platformReady],
  () => {
    page.value = 1;
  },
  { flush: 'sync' },
);
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
const { entries: timingEntries, retry: retryTimings } = useTaskTimings(rows, () => [
  auth.loginMode,
  auth.teamId,
  auth.userId,
  auth.token,
  auth.platformReady,
]);
const timings = computed(
  () => new Map(rows.value.map((row) => [row.id, taskTiming(row, timingEntries.value)])),
);
const timingError = computed(() =>
  Object.values(timingEntries.value).some((entry) => entry.state === 'error'),
);
const timeColumns = ['start', 'end'] as const;
function timeFor(row: TaskListSummary, column: (typeof timeColumns)[number]) {
  return timings.value.get(row.id)![column];
}
function timeTooltip(row: TaskListSummary, column: (typeof timeColumns)[number]) {
  return timings.value
    .get(row.id)!
    .sides.map((side) => {
      const value = side[column],
        formatted = formatTaskTime(value.value);
      return `${side.label}：${formatted ? `${formatted.date} ${formatted.time}` : value.label}`;
    })
    .join('\n');
}
const total = computed(() => data.value?.total ?? 0);
watch(data, (value) => {
  if (!value) return;
  const last = Math.max(1, Math.ceil(value.total / 20));
  if (page.value > last) page.value = last;
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
const done = (row: TaskListSummary) =>
  row.total_cases === null || row.completed_cases === null
    ? null
    : { done: row.completed_cases, total: row.total_cases };
async function deleteTask(id: string) {
  const historical = rows.value.find((row) => row.id === id)?.historical_comparison;
  try {
    await ElMessageBox.confirm(
      historical
        ? '删除此历史对比任务？两侧原单任务及其结果会保留。'
        : '删除后任务及其运行记录、Trace 和结果将不可恢复。已被历史对比引用的单任务需先删除关联对比。确定删除？',
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
  <div class="task-list-view">
    <div class="page-head">
      <div class="task-page-heading">
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
            <col style="width: 20%" />
            <col style="width: 20%" />
            <col style="width: 10%" />
            <col style="width: 14%" />
            <col style="width: 10%" />
            <col style="width: 10%" />
            <col style="width: 6%" />
            <col style="width: 10%" />
          </colgroup>
          <thead>
            <tr>
              <th>被测Agent</th>
              <th>测评集</th>
              <th>评估方式</th>
              <th>进度与状态</th>
              <th title="平台实际开始执行的时间；A/B 取两侧最早启动时间。北京时间。">启动时间</th>
              <th title="平台记录完成、失败或取消的时间；A/B 两侧都结束后取最晚时间。北京时间。">
                结束时间
              </th>
              <th>得分</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id">
              <td
                v-for="column in identityColumns"
                :key="column"
                :class="'identity-' + column"
                :data-label="column === 'target' ? '被测Agent' : '测评集'"
              >
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
                    :title="
                      (column === 'target' ? r.runs[0].target_name : r.runs[0].dataset_name) ??
                      undefined
                    "
                    >{{
                      (column === 'target' ? r.runs[0].target_name : r.runs[0].dataset_name) ?? '—'
                    }}</span
                  ><small>{{
                    column === 'target'
                      ? (r.runs[0].target_version ?? '—')
                      : r.runs[0].dataset_version === null
                        ? '—'
                        : `v${r.runs[0].dataset_version}`
                  }}</small>
                </template>
              </td>
              <td class="method-cell" data-label="评估方式">
                <span
                  v-for="method in (evaluatorStrategy(r.runs[0].evaluator_kinds) || '—').split(
                    ' + ',
                  )"
                  :key="method"
                  >{{ method }}</span
                >
              </td>
              <td class="progress-cell" data-label="进度与状态">
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
                ><span v-else>—</span>
                <div class="status-line">
                  <span class="task-kind">{{
                    r.kind === 'ab' ? 'A/B试验' : r.kind === 'stability' ? '稳定性测试' : '单任务'
                  }}</span>
                  <small>{{ statusLabel(r.status) }}</small>
                </div>
                <small v-if="r.summary_pending" role="status">{{
                  r.runs.length > 1 ? '部分摘要待更新' : '摘要待更新'
                }}</small>
                <small v-if="r.previous_run_count">已重跑 {{ r.previous_run_count }} 次</small>
              </td>
              <td
                v-for="column in timeColumns"
                :key="column"
                :class="['time-cell', 'time-' + column]"
                :data-label="column === 'start' ? '启动时间' : '结束时间'"
              >
                <el-tooltip
                  :disabled="r.kind !== 'ab'"
                  placement="top"
                  effect="light"
                  :trigger="['hover', 'focus']"
                  :enterable="false"
                  :hide-after="0"
                >
                  <template #content
                    ><div class="time-tooltip">{{ timeTooltip(r, column) }}</div></template
                  >
                  <div class="time-value" :tabindex="r.kind === 'ab' ? 0 : undefined">
                    <time v-if="timeFor(r, column).value" :datetime="timeFor(r, column).value!">
                      <span>{{ formatTaskTime(timeFor(r, column).value)!.date }}</span>
                      <small>{{ formatTaskTime(timeFor(r, column).value)!.time }}</small>
                    </time>
                    <span v-else class="time-empty">{{ timeFor(r, column).label }}</span>
                  </div>
                </el-tooltip>
              </td>
              <td class="task-score" data-label="得分">
                <template v-if="r.summary_pending">—</template
                ><template v-else-if="r.kind === 'ab'"
                  ><p v-for="(id, i) in r.runs.map((run) => run.run_id)" :key="id">
                    {{ i === 0 ? 'A' : 'B' }}
                    {{ score(r.runs.find((run) => run.run_id === id)?.overall_score ?? null) }}
                  </p></template
                ><template v-else>{{ score(r.runs[0].overall_score) }}</template
                ><small v-if="r.runs[0].gate_reason === 'evaluator_error'" class="danger"
                  >评估器异常</small
                >
              </td>
              <td class="row-actions" data-label="操作">
                <button
                  class="link"
                  :aria-label="'查看任务 ' + r.name"
                  @click="emit('navigate', taskPath(r))"
                >
                  查看
                </button>
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
                    ['single', 'ab'].includes(r.kind ?? 'single') &&
                    !r.historical_comparison &&
                    ['completed', 'failed', 'cancelled'].includes(r.status)
                  "
                  class="link"
                  @click="
                    emit('action', { runId: r.runs[0].run_id, taskId: r.task_id, action: 'rerun' })
                  "
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
        <span>共 {{ total }} 个任务</span><span class="time-zone">北京时间</span>
        <button v-if="timingError" class="link" @click="retryTimings">重试时间</button>
        <button class="secondary" :disabled="page === 1" @click="page--">上一页</button
        ><span>{{ page }} / {{ Math.max(1, Math.ceil(total / 20)) }}</span
        ><button class="secondary" :disabled="page * 20 >= total" @click="page++">下一页</button>
      </footer>
    </section>
  </div>
</template>
<style scoped>
.task-list-view {
  min-width: 0;
  container-type: inline-size;
}
.task-page-heading {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 16px;
  min-width: 0;
}
.task-page-heading .tabs {
  flex-wrap: wrap;
}
.task-kind {
  display: inline-block;
  margin-bottom: 5px;
  padding: 0 5px;
  border-radius: 4px;
  color: #687d71;
  background: #f1f6f3;
  font-size: 11px;
}
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
  flex-wrap: wrap;
  min-width: 0;
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
  min-width: 0;
}
.tasks-list .table-wrap {
  overflow: visible;
  min-width: 0;
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
  min-width: 0;
  table-layout: fixed;
  font-size: 13px;
}
.data-table th {
  padding: 10px 4px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.primary-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  padding: 14px 4px;
  min-width: 0;
}
.method-cell span {
  display: block;
  white-space: normal;
  overflow-wrap: anywhere;
}
.time-cell {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.time-cell time > span {
  display: block;
}
.time-cell small {
  margin-top: 2px;
  font-size: 12px;
}
.time-empty {
  color: #687d71;
  font-size: 12px;
}
.time-tooltip {
  white-space: pre-line;
  font-variant-numeric: tabular-nums;
}
.time-value:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
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
  margin: 0 6px 0 0;
  height: auto;
  padding: 0;
  border: 0;
  font-size: 12px;
  line-height: inherit;
}
.row-actions button:last-child {
  margin-right: 0;
}
.progress-cell {
  min-width: 0;
}
.progress-cell > div {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.progress-cell .status-line {
  justify-content: flex-start;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 6px;
  margin-top: 8px;
}
.status-line .task-kind {
  margin-bottom: 0;
}
.status-line small {
  margin-top: 0;
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
  flex-wrap: wrap;
  padding-top: 22px;
  font-size: 13px;
  color: #81928a;
}
footer > span:first-child {
  margin-right: auto;
}
@container (max-width: 700px) {
  .data-table,
  .data-table tbody {
    display: block;
  }
  .data-table colgroup {
    display: none;
  }
  .data-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .data-table tbody tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 14px 0;
    border-bottom: 1px solid #e3ebe7;
  }
  .data-table td {
    padding: 0;
    border: 0;
    white-space: normal;
  }
  .data-table td[data-label]::before {
    content: attr(data-label);
    display: block;
    margin-bottom: 3px;
    color: #687d71;
    font-size: 11px;
    font-weight: 400;
  }
  .row-actions {
    grid-area: 4 / 2;
  }
  .identity-target {
    grid-area: 1 / 1;
  }
  .identity-dataset {
    grid-area: 1 / 2;
  }
  .method-cell {
    grid-area: 2 / 1;
  }
  .progress-cell {
    grid-area: 2 / 2;
  }
  .time-start {
    grid-area: 3 / 1;
  }
  .time-end {
    grid-area: 3 / 2;
  }
  .task-score {
    grid-area: 4 / 1;
  }
  .task-score p {
    display: inline-block;
    margin-right: 12px;
  }
  footer {
    gap: 10px;
  }
  .time-zone {
    margin-left: auto;
  }
}
</style>
