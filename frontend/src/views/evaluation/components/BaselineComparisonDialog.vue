<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { api, score, statusLabel, type Report } from '../../../api/evaluations';
import { getTaskSummaries, type TaskListSummary } from '../../../api/evaluation-summaries';
import { createHistoricalComparison } from '../../../api/historical-comparisons';
import { useAuthStore } from '../../../stores/modules/auth';
import { useTaskTimings } from '../composables/use-task-timings';
import { taskTiming, formatTaskTime } from '../utils/task-timing';
import ConfigurationDiff from './ConfigurationDiff.vue';

const props = defineProps<{ taskId: string; candidate: Report }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();
const auth = useAuthStore();
const identity = () => [auth.loginMode, auth.token, auth.teamId, auth.userId];
const rows = shallowRef<TaskListSummary[]>([]),
  selected = shallowRef<TaskListSummary>();
const baseline = shallowRef<Report>(),
  page = ref(1),
  total = ref(0),
  keyword = ref('');
const loading = ref(false),
  checking = ref(false),
  saving = ref(false),
  error = ref('');
const checked = ref(false),
  confirmed = ref(false);
const { entries, retry } = useTaskTimings(rows, identity);
let controller = new AbortController(),
  generation = 0,
  comparisonId = '';

function unavailable(row: TaskListSummary) {
  if (row.task_id === props.taskId || row.runs.some((r) => r.run_id === props.candidate.run.id))
    return '当前任务不能与自身对比';
  if (!row.task_id || row.kind !== 'single' || row.runs.length !== 1)
    return '该记录没有独立的单任务关联';
  if (row.status !== 'completed') return '任务完成后才可比较结果';
  return '';
}
function startTime(row: TaskListSummary) {
  const time = taskTiming(row, entries.value).start;
  const formatted = formatTaskTime(time.value);
  return formatted ? `${formatted.date} ${formatted.time}` : time.label;
}
function select(row: TaskListSummary) {
  if (unavailable(row) || saving.value) return;
  selected.value = row;
  baseline.value = undefined;
  checked.value = confirmed.value = false;
  comparisonId = crypto.randomUUID();
  error.value = '';
}
async function load() {
  controller.abort();
  controller = new AbortController();
  const ticket = ++generation;
  rows.value = [];
  loading.value = true;
  error.value = '';
  try {
    const result = await getTaskSummaries(
      {
        page: page.value,
        page_size: 10,
        kind: 'single',
        keyword: keyword.value.trim() || undefined,
      },
      controller.signal,
    );
    if (ticket !== generation) return;
    rows.value = result.items;
    total.value = result.total;
  } catch {
    if (ticket === generation) error.value = '历史单任务读取失败，请重试。';
  } finally {
    if (ticket === generation) loading.value = false;
  }
}
function turnPage(next: number) {
  page.value = next;
  void load();
}
async function check() {
  if (!selected.value || checking.value) return;
  const ticket = ++generation,
    runId = selected.value.runs[0].run_id;
  checking.value = true;
  error.value = '';
  try {
    const result = await api.report(runId);
    if (ticket !== generation) return;
    if (result.run.status !== 'completed') throw Error('所选运行记录尚未完成，请刷新后选择。');
    baseline.value = result;
    checked.value = true;
    confirmed.value = false;
  } catch (e) {
    if (ticket === generation)
      error.value = e instanceof Error ? e.message : '执行条件读取失败，请重试。';
  } finally {
    if (ticket === generation) checking.value = false;
  }
}
async function save() {
  if (!confirmed.value || !baseline.value || !selected.value?.task_id || saving.value) return;
  const ticket = ++generation;
  saving.value = true;
  error.value = '';
  try {
    const task = await createHistoricalComparison({
      comparison_id: comparisonId,
      baseline_task_id: selected.value.task_id,
      baseline_run_id: baseline.value.run.id,
      candidate_task_id: props.taskId,
      candidate_run_id: props.candidate.run.id,
    });
    if (ticket !== generation) return;
    window.dispatchEvent(new Event('task-links-updated'));
    emit('created', task.id);
  } catch (e) {
    if (ticket === generation) error.value = e instanceof Error ? e.message : '保存失败，请重试。';
  } finally {
    if (ticket === generation) saving.value = false;
  }
}
function close() {
  if (!saving.value) emit('close');
}
watch(identity, () => {
  generation++;
  controller.abort();
  emit('close');
});
onBeforeUnmount(() => {
  generation++;
  controller.abort();
});
onMounted(load);
</script>
<template>
  <el-dialog
    :model-value="true"
    :title="checked ? '与历史任务执行条件比较' : '与基线对比 · 选择历史单任务'"
    width="min(1120px,96vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @close="close"
  >
    <div class="baseline-comparison" data-testid="baseline-comparison">
      <p class="muted">A任务：历史基线；B任务：当前任务。对比已有结果，不重新运行任务。</p>
      <p v-if="error" class="notice error" role="alert">
        {{ error }} <button v-if="!checked && !selected" class="link" @click="load">重试</button>
      </p>
      <template v-if="!checked">
        <form class="picker-toolbar" @submit.prevent="turnPage(1)">
          <input
            v-model="keyword"
            aria-label="搜索历史单任务"
            placeholder="搜索任务名称或编号"
            maxlength="256"
            :disabled="checking"
          />
          <button class="secondary" :disabled="loading || checking">搜索</button>
          <button
            type="button"
            class="link"
            :disabled="loading || checking"
            @click="
              load();
              retry();
            "
          >
            刷新
          </button>
          <span class="muted">全部时间 · 共 {{ total }} 条单任务</span>
        </form>
        <table class="history-table" aria-label="历史单任务">
          <colgroup>
            <col style="width: 31%" />
            <col style="width: 20%" />
            <col style="width: 20%" />
            <col style="width: 21%" />
            <col style="width: 8%" />
          </colgroup>
          <thead>
            <tr>
              <th>任务名称</th>
              <th>被测Agent</th>
              <th>测评集</th>
              <th>启动时间</th>
              <th>得分</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.id"
              :class="{ selected: selected?.id === row.id, disabled: unavailable(row) }"
              :title="unavailable(row)"
              @click="!checking && select(row)"
            >
              <td>
                <label class="task-choice"
                  ><input
                    type="radio"
                    name="history-baseline"
                    :aria-label="'选择基线：' + row.name"
                    :checked="selected?.id === row.id"
                    :disabled="!!unavailable(row) || checking"
                    @change="select(row)"
                  /><span :title="row.name">{{ row.name }}</span></label
                >
              </td>
              <td :title="row.runs[0]?.target_name ?? ''">
                {{ row.runs[0]?.target_name ?? '未记录' }}
              </td>
              <td :title="row.runs[0]?.dataset_name ?? ''">
                {{ row.runs[0]?.dataset_name ?? '未记录' }}
              </td>
              <td class="start-time" :title="startTime(row)">{{ startTime(row) }}</td>
              <td :title="statusLabel(row.status)">
                {{ score(row.runs[0]?.overall_score ?? null) }}
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="5" class="empty">
                {{ loading ? '正在读取历史单任务…' : '暂无符合条件的单任务' }}
              </td>
            </tr>
          </tbody>
        </table>
        <div class="picker-toolbar pagination">
          <span class="muted">{{
            selected
              ? '已选 A任务：' + selected.name
              : '请选择一条已完成的历史单任务；灰色记录暂不可选。'
          }}</span>
          <button
            class="secondary"
            :disabled="page <= 1 || loading || checking"
            @click="turnPage(page - 1)"
          >
            上一页
          </button>
          <span>{{ page }} / {{ Math.max(1, Math.ceil(total / 10)) }}</span>
          <button
            class="secondary"
            :disabled="page * 10 >= total || loading || checking"
            @click="turnPage(page + 1)"
          >
            下一页
          </button>
        </div>
      </template>
      <template v-else-if="baseline">
        <p>
          <b>A任务：</b>{{ selected?.name }} <span class="muted">→</span> <b>B任务：</b>当前任务
        </p>
        <ConfigurationDiff :baseline="baseline.run.manifest" :candidate="candidate.run.manifest" />
        <p class="notice warn">
          两侧都有得分时，分数差按 B任务得分减去A任务得分计算；执行条件差异将保留在结果中。
        </p>
        <label class="confirmation"
          ><input
            v-model="confirmed"
            type="checkbox"
            :disabled="saving"
          />我已查看并确认上述差异，同意使用这两份历史结果进行对比。</label
        >
      </template>
    </div>
    <template #footer>
      <button class="secondary" :disabled="saving" @click="close">取消</button>
      <button
        v-if="checked"
        class="secondary"
        :disabled="saving"
        @click="
          checked = false;
          confirmed = false;
          error = '';
        "
      >
        重新选择
      </button>
      <button
        v-if="!checked"
        class="primary"
        :disabled="!selected || loading || checking"
        @click="check"
      >
        {{ checking ? '正在检查…' : '与历史任务执行条件比较' }}
      </button>
      <button v-else class="primary" :disabled="!confirmed || saving" @click="save">
        {{ saving ? '正在保存对比任务…' : '执行任务结果对比' }}
      </button>
    </template>
  </el-dialog>
</template>
<style scoped>
.baseline-comparison {
  color: #263544;
}
.picker-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin: 16px 0;
}
.picker-toolbar input {
  width: 240px;
  max-width: 45%;
  padding: 8px;
  border: 1px solid #dce4e9;
  border-radius: 4px;
}
.history-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}
.history-table th,
.history-table td {
  padding: 14px 8px;
  text-align: left;
  border-bottom: 1px solid #e7edf0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.history-table th {
  background: #f5f8fa;
}
.history-table tr:not(.disabled) {
  cursor: pointer;
}
.history-table tr.selected {
  background: #edf8f4;
}
.history-table tr.disabled {
  color: #98a3ad;
  background: #fafbfc;
  cursor: not-allowed;
}
.task-choice {
  display: flex;
  align-items: center;
  gap: 9px;
  cursor: inherit;
}
.task-choice span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-choice input {
  flex-shrink: 0;
  accent-color: #159c82;
}
.start-time {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.pagination > span:first-child {
  flex: 1;
  min-width: 180px;
}
.confirmation {
  display: flex;
  gap: 8px;
  align-items: start;
  line-height: 22px;
}
:deep(pre) {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
:deep(.two-columns) {
  min-width: 0;
}
button + button {
  margin-left: 8px;
}
</style>
