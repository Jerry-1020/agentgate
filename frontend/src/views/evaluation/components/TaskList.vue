<script setup lang="ts">
import { shallowRef, computed, onMounted, onUnmounted, ref, watch } from 'vue';
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
  query = ref(''),
  from = ref(''),
  to = ref(''),
  kind = ref(''),
  page = ref(1),
  checked = ref<string[]>([]);
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false;
const link = (id: string) => links.value.find((t) => t.runIds.includes(id));
const title = (r: EvaluationRun) => taskTitle(r, link(r.id)?.kind);
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
      (!kind.value || (link(r.id)?.kind ?? 'single') === kind.value) &&
      `${title(r)} ${r.id}`.toLowerCase().includes(query.value.toLowerCase()) &&
      (!from.value || Date.parse(r.created_at) >= Date.parse(from.value + 'T00:00:00')) &&
      (!to.value || Date.parse(r.created_at) <= Date.parse(to.value + 'T23:59:59.999')),
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
function exportTasks(ids?: string[]) {
  downloadCsv(
    [
      ['任务名称', '应用', '数据集', '状态', '评估方式', '得分', '创建时间'],
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
    '评测任务.csv',
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
watch([status, query, from, to, kind], () => {
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
  <div class="page-head"><h1 class="page-title">评测任务</h1></div>
  <section class="card tasks-list">
    <nav class="tabs">
      <button
        v-for="s in [
          ['', '全部'],
          ['pending', '等待中'],
          ['running', '运行中'],
          ['completed', '已完成'],
          ['failed', '失败'],
          ['cancelled', '已取消'],
        ]"
        :key="s[0]"
        class="tab"
        :class="{ active: status === s[0] }"
        @click="status = s[0]"
      >
        {{ s[1] }}
      </button>
    </nav>
    <div class="toolbar filters">
      <input
        class="input"
        v-model="query"
        aria-label="搜索任务名称"
        placeholder="搜索任务名称或 ID"
      />
      <div class="date-range">
        <input type="date" v-model="from" aria-label="创建开始日期" /><span>—</span
        ><input type="date" v-model="to" :min="from" aria-label="创建结束日期" />
      </div>
      <select class="input" v-model="kind" aria-label="任务类型">
        <option value="">全部任务类型</option>
        <option value="single">单任务</option>
        <option value="ab">A/B 实验</option>
        <option value="stability">稳定性测试</option></select
      ><button class="secondary" :disabled="!checked.length" @click="exportTasks(checked)">
        批量导出{{ checked.length ? '（' + checked.length + '）' : '' }}</button
      ><button class="primary" @click="emit('create')">新建评测任务</button>
    </div>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div class="table-wrap">
      <table class="data-table">
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
            <th>应用</th>
            <th>数据集</th>
            <th>评估方式</th>
            <th>评分模式</th>
            <th>进度</th>
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
              <button class="link" @click="emit('navigate', 'tasks/' + r.id)">{{ title(r) }}</button
              ><small>{{ new Date(r.created_at).toLocaleString() }}</small>
            </td>
            <td>
              {{ r.manifest.target.display_name
              }}<small>{{ r.manifest.target.ref.external_version_id }}</small>
            </td>
            <td>
              {{ r.manifest.dataset.dataset_name }}<small>v{{ r.manifest.dataset.version }}</small>
            </td>
            <td>
              <span class="badge info">{{ strategy(r) }}</span>
            </td>
            <td><span class="badge info">整体评分</span></td>
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
.tasks-list {
  padding: 24px;
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
  gap: 10px;
}
.date-range input {
  border: 0;
  background: none;
  color: #687d71;
  min-width: 125px;
  font: inherit;
  font-size: 13px;
}
.data-table {
  min-width: 1250px;
}
.data-table th {
  white-space: nowrap;
}
.name-cell {
  min-width: 200px;
  max-width: 300px;
}
.name-cell .link {
  text-align: left;
  font-weight: 500;
  line-height: 1.7;
}
.data-table small {
  display: block;
  font-size: 11px;
  color: #81928a;
  margin-top: 8px;
}
.data-table td {
  padding-top: 20px;
  padding-bottom: 20px;
}
.row-actions {
  position: sticky;
  right: 0;
  background: white;
  min-width: 130px;
  box-shadow: -5px 0 8px #23402f06;
}
.row-actions button {
  margin: 5px;
  font-size: 12px;
}
.progress-cell {
  min-width: 120px;
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
  font-size: 19px;
  font-weight: 650;
  color: #00a584;
}
.task-score p {
  font-size: 14px;
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
