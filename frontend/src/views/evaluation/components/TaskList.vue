<script setup lang="ts">
import { shallowRef, computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  api,
  request,
  statusLabel,
  score,
  type EvaluationRun,
  type Report,
  type RunProgress,
} from '../../../api/evaluations';
import { refreshTaskLinks, type TaskLink } from '../utils/task-links';
import { downloadCsv } from '../utils/task-report';
import { taskTitle } from '../utils/dashboard-data';
const emit = defineEmits<{
  create: [];
  navigate: [path: string];
  action: [id: string, action: 'cancel' | 'rerun'];
}>();
const runs = shallowRef<EvaluationRun[]>([]),
  links = ref<TaskLink[]>([]),
  reports = ref<Record<string, Report>>({}),
  progress = ref<Record<string, RunProgress>>({}),
  error = ref(''),
  busy = ref(false);
const status = ref(''),
  days = ref(7),
  taskTab = ref(''),
  query = ref(''),
  from = ref(''),
  to = ref(''),
  kind = ref(''),
  page = ref(1),
  checked = ref<string[]>([]);
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false;
const link = (id: string) => links.value.find((t) => t.runIds.includes(id));
const title = (r: EvaluationRun) => taskTitle(r, link(r.id)?.kind, link(r.id)?.name);
function state(r: EvaluationRun) {
  const states = (link(r.id)?.runIds ?? [r.id]).map(
    (id) => runs.value.find((x) => x.id === id)?.status,
  );
  return states.includes('failed')
    ? 'failed'
    : states.includes('cancelled')
      ? 'cancelled'
      : states.every((s) => s === 'completed')
        ? 'completed'
        : states.includes('running') || states.includes('completed')
          ? 'running'
          : r.status;
}
const filtered = computed(() =>
  runs.value.filter(
    (r) =>
      (!link(r.id) || link(r.id)?.runIds[0] === r.id) &&
      (!status.value ||
        (status.value === 'pending'
          ? ['pending', 'scheduled'].includes(state(r))
          : state(r) === status.value)) &&
      (!taskTab.value || (link(r.id)?.kind ?? 'single') === taskTab.value) &&
      (!kind.value || (link(r.id)?.kind ?? 'single') === kind.value) &&
      `${title(r)} ${r.id}`.toLowerCase().includes(query.value.toLowerCase()) &&
      (!from.value || Date.parse(r.created_at) >= Date.parse(from.value + 'T00:00:00')) &&
      (!to.value || Date.parse(r.created_at) <= Date.parse(to.value + 'T23:59:59.999')) &&
      (!days.value ||
        (() => {
          const start = new Date();
          start.setHours(0, 0, 0, 0);
          start.setDate(start.getDate() - (days.value - 1));
          return Date.parse(r.created_at) >= start.getTime();
        })()),
  ),
);
const rows = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20));
function done(r: EvaluationRun) {
  const ids = link(r.id)?.runIds ?? [r.id],
    values = ids.map((id) => progress.value[id]);
  return values.every(Boolean)
    ? {
        done: values.reduce((s, p) => s + p.completed_cases, 0),
        total: values.reduce((s, p) => s + p.total_cases, 0),
      }
    : null;
}
function strategy(r: EvaluationRun) {
  const specs = (r.manifest as any).evaluator_specs ?? [];
  return [
    ...new Set(
      specs
        .filter((s: any) => r.manifest.primary_evaluator_ids.includes(s.id))
        .map((s: any) =>
          s.kind === 'rule' ? '规则评估' : s.kind === 'llm_judge' ? 'LLM 评估' : '复合评估',
        ),
    ),
  ].join(' + ');
}
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
    await request(`/evaluation-tasks/${id}`, 'DELETE');
    ElMessage.success('任务已删除');
    await load();
  } catch (e) {
    ElMessage.error('删除失败：' + String(e));
  }
}

function exportTasks(ids?: string[]) {
  downloadCsv(
    [
      ['任务名称', '被测Agent', '测评集', '状态', '评估方式', '得分', '创建时间'],
      ...filtered.value
        .filter((r) => !ids || ids.includes(r.id))
        .map((r) => [
          title(r),
          r.manifest.target.display_name,
          r.manifest.dataset.dataset_name,
          statusLabel(state(r)),
          strategy(r),
          score(reports.value[r.id]?.metrics.find((m) => m.level === 'overall')?.score ?? null),
          r.created_at,
        ]),
    ],
    '测评任务.csv',
  );
}
async function details() {
  for (let start = 0; start < rows.value.length; start += 4) {
    if (disposed) return;
    await Promise.all(
      rows.value
        .slice(start, start + 4)
        .flatMap((r) => link(r.id)?.runIds ?? [r.id])
        .map(async (id) => {
          try {
            const p = await api.status(id);
            if (disposed) return;
            progress.value[id] = p;
            if (p.status === 'completed' && !reports.value[id])
              reports.value[id] = await api.report(id);
          } catch (e) {
            if (!disposed) error.value = String(e);
          }
        }),
    );
  }
}
async function load() {
  busy.value = true;
  try {
    const [r, l] = await Promise.all([api.runs(), refreshTaskLinks()]);
    if (disposed) return;
    runs.value = r;
    links.value = l;
    error.value = '';
    await details();
  } catch (e) {
    if (!disposed) error.value = String(e);
  } finally {
    busy.value = false;
    if (!disposed) timer = setTimeout(load, 5000);
  }
}
watch([status, taskTab, query, from, to, kind, days], () => {
  page.value = 1;
  checked.value = [];
});
watch(rows, () => void details());
watch(filtered, (x) => (page.value = Math.min(page.value, Math.max(1, Math.ceil(x.length / 20)))));
onMounted(load);
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
});
</script>
<template>
  <div class="page-head">
    <div style="display: flex; align-items: flex-end; gap: 16px">
      <h1 class="page-title">测评任务</h1>
      <div class="tabs">
        <button
          v-for="d in [1, 7, 30]"
          :key="d"
          :class="['tab', { active: days === d }]"
          :aria-pressed="days === d"
          @click="days = d"
        >
          {{ d === 1 ? '今日' : '近' + d + '天' }}
        </button>
      </div>
    </div>
  </div>
  <section class="card tasks-list">
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
          @click="
            taskTab = t[0];
            status = '';
          "
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
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
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
              <button class="link" :title="title(r)" @click="emit('navigate', 'tasks/' + r.id)">
                {{ title(r) }}</button
              ><small>{{ new Date(r.created_at).toLocaleString() }}</small>
            </td>
            <td>
              <span>{{
                link(r.id)?.kind === 'ab'
                  ? 'A/B试验'
                  : link(r.id)?.kind === 'stability'
                    ? '稳定性测试'
                    : '单任务'
              }}</span>
            </td>
            <td>
              <span class="primary-text" :title="r.manifest.target.display_name">{{
                r.manifest.target.display_name
              }}</span
              ><small>{{ r.manifest.target.ref.external_version_id }}</small>
            </td>
            <td>
              <span class="primary-text" :title="r.manifest.dataset.dataset_name">{{
                r.manifest.dataset.dataset_name
              }}</span
              ><small>v{{ r.manifest.dataset.version }}</small>
            </td>
            <td>
              <span>{{ strategy(r) }}</span>
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
                  :class="{ failed: state(r) === 'failed' }" /></template
              ><small>{{ statusLabel(state(r)) }}</small>
            </td>
            <td class="task-score">
              <template v-if="link(r.id)?.kind === 'ab'"
                ><p v-for="(id, i) in link(r.id)!.runIds" :key="id">
                  {{ i === 0 ? 'A' : 'B' }}
                  {{
                    score(reports[id]?.metrics.find((m) => m.level === 'overall')?.score ?? null)
                  }}
                </p></template
              ><template v-else>{{
                score(reports[r.id]?.metrics.find((m) => m.level === 'overall')?.score ?? null)
              }}</template
              ><small
                v-if="reports[r.id]?.release_gate.reason_code === 'evaluator_error'"
                class="danger"
                >评估器异常</small
              >
            </td>
            <td class="row-actions">
              <button class="link" @click="exportTasks([r.id])">导出</button
              ><button
                v-if="
                  (link(r.id)?.kind ?? 'single') === 'single' &&
                  ['pending', 'running', 'scheduled'].includes(r.status)
                "
                class="link"
                @click="emit('action', r.id, 'cancel')"
              >
                取消
              </button>
              <button class="link danger" @click="deleteTask(r.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!rows.length" class="empty">{{ busy ? '正在加载…' : '暂无符合条件的任务' }}</p>
    <footer>
      <span>共 {{ filtered.length }} 个任务</span
      ><button class="secondary" :disabled="page === 1" @click="page--">上一页</button
      ><span>{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / 20)) }}</span
      ><button class="secondary" :disabled="page * 20 >= filtered.length" @click="page++">
        下一页
      </button>
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
  min-width: 0;
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
