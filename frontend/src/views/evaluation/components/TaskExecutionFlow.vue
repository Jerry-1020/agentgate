<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { request } from '../../../api/evaluations';
import {
  executionReferences,
  executionTiming,
  groupExecutionFlow,
  type FlowNode,
  type RunEvent,
} from '../utils/task-execution-flow';

const props = defineProps<{ runIds: string[]; statuses: Record<string, string> }>();
const selected = ref(props.runIds[0] ?? '');
const events = ref<RunEvent[]>([]),
  error = ref(''),
  loading = ref(false);
const autoRefresh = ref(true),
  now = ref(Date.now());
const detailPages = ref<Record<string, number>>({});
const expanded = ref<Record<string, boolean>>({});
const snapshotAgents = ref<Record<string, string>>({});
const terminal = computed(() =>
  ['completed', 'failed', 'cancelled'].includes(props.statuses[selected.value]),
);
const nodes = computed(() => groupExecutionFlow(events.value, props.statuses[selected.value]));
const references = computed(() =>
  executionReferences(events.value, snapshotAgents.value[selected.value]),
);
const total = computed(() => executionTiming(events.value, props.statuses[selected.value]));
const totalDuration = computed(() =>
  total.value.unknownEnd
    ? '结束时间未知'
    : total.value.running && total.value.startedAt
      ? elapsed(total.value.startedAt)
      : milliseconds(total.value.durationMs),
);
const taskError = computed(() =>
  nodes.value.some((node) => node.issues.length) ? null : references.value.taskErrors[0],
);
let timer: ReturnType<typeof setTimeout> | undefined;
let clock: ReturnType<typeof setInterval> | undefined;
let disposed = false,
  ticket = 0,
  terminalRefreshes = 0;

function time(value: string | null) {
  return value
    ? new Date(value).toLocaleString(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3,
        hour12: false,
      })
    : '—';
}
function milliseconds(value: number | null) {
  if (value === null) return '未采集';
  if (value < 1000) return value > 0 && value < 0.01 ? '<0.01 毫秒' : `${value.toFixed(2)} 毫秒`;
  return `${(value / 1000).toFixed(2)} 秒`;
}
function elapsed(start: string) {
  return `已运行 ${Math.max(0, (now.value - Date.parse(start)) / 1000).toFixed(0)} 秒`;
}
function nodeDuration(node: FlowNode) {
  if (node.status === 'pending' || node.status === 'uncollected') return '—';
  if (node.status === 'unknown' || node.status === 'interrupted') return '结束时间未知';
  if (node.status === 'running' && node.startedAt) return elapsed(node.startedAt);
  return milliseconds(node.durationMs);
}
function duration(event: RunEvent) {
  if (event.status === 'interrupted' || (!event.ended_at && terminal.value)) return '结束时间未知';
  return event.ended_at ? milliseconds(event.duration_ms) : elapsed(event.started_at);
}
const labels: Record<string, string> = {
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断／待确认',
  unknown: '状态待确认',
  pending: '未开始',
  uncollected: '未采集',
};
function state(event: RunEvent) {
  return !event.ended_at && terminal.value ? labels.unknown : labels[event.status];
}
function badge(status: string) {
  return status === 'failed' || status === 'interrupted'
    ? 'error'
    : status === 'completed'
      ? 'success'
      : 'info';
}
function detailPage(node: FlowNode) {
  return Math.min(
    detailPages.value[node.id] ?? 0,
    Math.max(0, Math.ceil(node.rows.length / 20) - 1),
  );
}
function visibleRows(node: FlowNode) {
  return node.rows.slice(detailPage(node) * 20, (detailPage(node) + 1) * 20);
}
function changePage(node: FlowNode, offset: number) {
  detailPages.value[node.id] = detailPage(node) + offset;
}
function isExpanded(node: FlowNode) {
  return expanded.value[node.id] ?? node.expanded;
}
function toggleNode(node: FlowNode) {
  expanded.value[node.id] = !isExpanded(node);
}
async function loadSnapshotAgent(id: string) {
  if (snapshotAgents.value[id]) return;
  try {
    const manifest = await request<{ target: { ref: { external_target_id: string } } }>(
      `/runs/${encodeURIComponent(id)}/manifest`,
    );
    if (!disposed) snapshotAgents.value[id] = manifest.target.ref.external_target_id;
  } catch {
    // A snapshot lookup must not hide execution logs; new logs also carry the agent ID.
    return;
  }
}
async function load() {
  clearTimeout(timer);
  if (disposed || document.hidden || !selected.value) return;
  void loadSnapshotAgent(selected.value);
  const current = ++ticket;
  loading.value = true;
  try {
    const collected = new Map<string, RunEvent>();
    let offset = 0,
      hasMore = true;
    // Summaries and shared references include all pages, not only the first 100 records.
    while (hasMore) {
      const rows = await request<RunEvent[]>(
        `/runs/${encodeURIComponent(selected.value)}/events?offset=${offset}&limit=200`,
      );
      if (disposed || current !== ticket) return;
      rows.forEach((row) => collected.set(row.id, row));
      hasMore = rows.length === 200;
      offset += 200;
    }
    events.value = [...collected.values()];
    error.value = '';
  } catch (e) {
    if (!disposed && current === ticket) error.value = `执行流程读取失败：${String(e)}`;
  } finally {
    if (!disposed && current === ticket) {
      loading.value = false;
      if (autoRefresh.value && (!terminal.value || terminalRefreshes++ < 1 || error.value))
        timer = setTimeout(load, 5000);
    }
  }
}
function visibilityChanged() {
  ticket++;
  clearTimeout(timer);
  loading.value = false;
  if (!document.hidden && autoRefresh.value) void load();
}
watch(
  () => props.runIds,
  (ids) => {
    if (!ids.includes(selected.value)) selected.value = ids[0] ?? '';
  },
);
watch(selected, () => {
  events.value = [];
  detailPages.value = {};
  expanded.value = {};
  terminalRefreshes = 0;
  void load();
});
watch(autoRefresh, (enabled) => {
  clearTimeout(timer);
  if (enabled) void load();
});
watch(terminal, () => {
  terminalRefreshes = 0;
  void load();
});
onMounted(() => {
  document.addEventListener('visibilitychange', visibilityChanged);
  clock = setInterval(() => {
    now.value = Date.now();
  }, 1000);
  void load();
});
onUnmounted(() => {
  disposed = true;
  ticket++;
  clearTimeout(timer);
  clearInterval(clock);
  document.removeEventListener('visibilitychange', visibilityChanged);
});
</script>

<template>
  <section class="execution-flow" aria-label="任务执行流程">
    <div class="toolbar">
      <h2 class="section-title">执行流程</h2>
      <div class="actions">
        <select
          v-if="runIds.length > 1"
          v-model="selected"
          class="input"
          aria-label="执行流程实验侧"
        >
          <option v-for="(id, i) in runIds" :key="id" :value="id">
            实验 {{ i === 0 ? 'A' : 'B' }}
          </option>
        </select>
        <label><input type="checkbox" v-model="autoRefresh" /> 自动刷新</label>
        <button class="secondary" :disabled="loading" @click="load">
          {{ loading ? '读取中…' : '刷新' }}
        </button>
      </div>
    </div>
    <dl class="total-timing" aria-label="任务总耗时">
      <div>
        <dt>总耗时</dt>
        <dd class="total-duration">{{ totalDuration }}</dd>
      </div>
      <div>
        <dt>开始时间</dt>
        <dd>{{ total.startedAt ? time(total.startedAt) : '未采集' }}</dd>
      </div>
      <div>
        <dt>结束时间</dt>
        <dd>
          {{
            total.unknownEnd
              ? '未知'
              : total.running
                ? '进行中'
                : total.endedAt
                  ? time(total.endedAt)
                  : '未采集'
          }}
        </dd>
      </div>
    </dl>
    <details class="references">
      <summary>关联信息</summary>
      <dl>
        <dt>Run</dt>
        <dd>{{ selected }}</dd>
        <dt>agentId</dt>
        <dd>{{ references.agents.join('、') || '未采集' }}</dd>
        <template v-if="references.pods.length">
          <dt>被测 Pod</dt>
          <dd class="pod-references">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Pod taskId</th>
                  <th>Pod／实例名称</th>
                  <th v-if="references.agents.length > 1">agentId</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="pod in references.pods"
                  :key="JSON.stringify([pod.agentId, pod.taskId, pod.name])"
                >
                  <td>{{ pod.taskId || '未采集' }}</td>
                  <td>{{ pod.name || '未返回／未采集' }}</td>
                  <td v-if="references.agents.length > 1">{{ pod.agentId || '未采集' }}</td>
                </tr>
              </tbody>
            </table>
          </dd>
        </template>
        <template v-if="references.requests.length"
          ><dt>请求 ID</dt>
          <dd>
            <div v-for="id in references.requests" :key="id">{{ id }}</div>
          </dd></template
        >
        <template v-if="references.batches.length"
          ><dt>BJS 批次号</dt>
          <dd>
            <div v-for="batch in references.batches" :key="`${batch.job}:${batch.number}`">
              {{ batch.number
              }}<span v-if="references.batches.length > 1" class="muted"
                >（第 {{ batch.attempt }} 次派发）</span
              >
            </div>
          </dd></template
        >
      </dl>
    </details>
    <p class="muted flow-hint">
      展开节点查看明细。时间按当前时区展示；节点可能重叠，耗时不可相加。
    </p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="taskError" class="notice error" role="alert">
      任务异常：{{ taskError.error_code }} {{ taskError.message }}
    </p>
    <p v-if="!loading && !events.length && !error" class="empty">
      暂无执行流程记录。历史任务未采集的数据不会补造。
    </p>
    <div class="table-wrap" tabindex="0" aria-label="执行流程，可横向滚动">
      <table class="data-table flow-table">
        <thead>
          <tr>
            <th>阶段</th>
            <th>状态</th>
            <th>开始时间</th>
            <th>结束时间</th>
            <th>耗时</th>
            <th>说明／异常</th>
          </tr>
        </thead>
        <tbody v-for="node in nodes" :key="`${selected}:${node.id}`">
          <tr :class="{ 'failed-node': node.status === 'failed' || node.status === 'interrupted' }">
            <td>
              <button
                class="flow-toggle"
                :aria-expanded="isExpanded(node)"
                @click="toggleNode(node)"
              >
                <span aria-hidden="true">{{ isExpanded(node) ? '▾' : '▸' }}</span> {{ node.name }}
              </button>
            </td>
            <td>
              <span class="badge" :class="badge(node.status)">{{ labels[node.status] }}</span>
            </td>
            <td class="nowrap">{{ time(node.startedAt) }}</td>
            <td class="nowrap">
              {{
                node.status === 'interrupted' || node.status === 'unknown'
                  ? '未知'
                  : time(node.endedAt)
              }}
            </td>
            <td class="nowrap">{{ nodeDuration(node) }}</td>
            <td>
              <template v-if="node.issues.length"
                ><span class="error">{{
                  node.issues[0].message ||
                  node.issues[0].error_code ||
                  labels[node.issues[0].status]
                }}</span
                ><small class="muted"
                  >{{ node.issues.length }} 条异常记录，展开查看</small
                ></template
              >
              <span v-else class="muted">{{
                node.rows.length ? `${node.rows.length} 条明细` : '—'
              }}</span>
            </td>
          </tr>
          <tr v-if="isExpanded(node)" class="detail-row">
            <td colspan="6">
              <div class="node-details">
                <p v-if="!node.rows.length" class="muted">
                  {{ node.status === 'pending' ? '等待进入该阶段。' : '该阶段暂无采集记录。' }}
                </p>
                <template v-else>
                  <p v-if="node.issues.length" class="notice error">
                    {{ node.issues[0].name }}：{{
                      node.issues[0].message ||
                      node.issues[0].error_code ||
                      labels[node.issues[0].status]
                    }}
                  </p>
                  <div class="table-wrap" tabindex="0" :aria-label="`${node.name}明细，可横向滚动`">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>执行明细</th>
                          <th>状态</th>
                          <th>开始／结束时间</th>
                          <th>耗时</th>
                          <th>说明／异常</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="event in visibleRows(node)" :key="event.id">
                          <td>
                            {{ event.name }}<small class="muted">第 {{ event.attempt }} 次</small
                            ><small v-if="event.case_id" class="muted"
                              >样本：{{ event.case_id }}</small
                            ><small v-if="event.turn_id" class="muted"
                              >轮次：{{ event.turn_id }}</small
                            ><small v-if="event.evaluator_id" class="muted"
                              >评估器：{{ event.evaluator_id }}</small
                            >
                          </td>
                          <td>
                            <span class="badge" :class="badge(event.status)">{{
                              state(event)
                            }}</span>
                          </td>
                          <td class="nowrap">
                            {{ time(event.started_at)
                            }}<small>{{
                              event.status === 'interrupted' ? '结束时间未知' : time(event.ended_at)
                            }}</small>
                          </td>
                          <td class="nowrap">{{ duration(event) }}</td>
                          <td>
                            <span v-if="event.error_code" class="error"
                              >{{ event.error_code }}： </span
                            >{{ event.message || '—' }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="actions pagination" v-if="node.rows.length > 20">
                    <button
                      class="secondary"
                      :disabled="!detailPage(node)"
                      @click="changePage(node, -1)"
                    >
                      上一页
                    </button>
                    <span
                      >第 {{ detailPage(node) + 1 }} / {{ Math.ceil(node.rows.length / 20) }} 页 ·
                      {{ node.rows.length }} 条</span
                    >
                    <button
                      class="secondary"
                      :disabled="(detailPage(node) + 1) * 20 >= node.rows.length"
                      @click="changePage(node, 1)"
                    >
                      下一页
                    </button>
                  </div>
                </template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.execution-flow {
  min-width: 0;
}
.toolbar {
  flex-wrap: wrap;
  gap: 12px;
}
.references {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 12px 16px;
}
.references summary {
  cursor: pointer;
  color: var(--el-color-primary);
}
.pod-references {
  overflow-x: auto;
  min-width: 0;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 20px;
  margin-bottom: 0;
}
dt {
  color: var(--el-text-color-secondary);
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.flow-hint {
  margin: 12px 0;
}
.total-timing {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 32px;
  margin: 0 0 12px;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
}
.total-timing dt {
  margin-bottom: 6px;
}
.total-duration {
  color: var(--el-color-primary);
  font-size: 18px;
  font-weight: 600;
}
.flow-toggle {
  border: 0;
  background: none;
  padding: 0;
  color: var(--el-color-primary);
  font: inherit;
  cursor: pointer;
  text-align: left;
}
.flow-toggle:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 4px;
}
.node-details {
  padding: 0 8px 8px;
}
.detail-row > td {
  background: var(--el-fill-color-extra-light);
}
.table-wrap {
  overflow-x: auto;
  margin-top: 12px;
}
th,
td {
  vertical-align: top;
}
td:first-child {
  min-width: 170px;
  overflow-wrap: anywhere;
}
td:last-child {
  min-width: 180px;
  max-width: 400px;
  overflow-wrap: anywhere;
}
small {
  display: block;
  margin-top: 4px;
}
.failed-node {
  background: var(--el-color-danger-light-9);
}
.pagination {
  margin-top: 12px;
}
</style>
