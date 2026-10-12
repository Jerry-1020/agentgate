<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { Filter, Close } from '@element-plus/icons-vue';
import { request, type EvaluationRun } from '../../../api/evaluations';
import type { Report, Trace, EvaluationResult } from '../../../api/client';
import { copy, useReviewStore, type AnnotationTask } from '../../../stores/modules/review';
import { matchesAnnotationTarget } from '../utils/annotation-feedback';
import { taskTitle } from '../utils/dashboard-data';
import AnnotationV2Editor from './AnnotationV2Editor.vue';
import { annotationV2Status } from '../utils/annotation-v2-editor';
import {
  annotationCaseScore,
  annotationFilterError,
  emptyAnnotationFilters,
  matchesAnnotationFilters,
} from '../utils/annotation-v2-list';

const props = defineProps<{ task: AnnotationTask }>();
const emit = defineEmits<{ back: [] }>();
const review = useReviewStore();
const task = computed(
  () => review.annotationTasks.find((t) => t.id === props.task.id) ?? props.task,
);
type Entry = {
  key: string;
  run: EvaluationRun;
  caseId: string;
  name: string;
  taskId: string;
  taskName: string;
  score: number | null;
  badCase: boolean;
  trace?: Trace;
  results?: EvaluationResult[];
  error?: string;
};
const entries = ref<Entry[]>([]);
const loading = ref(false),
  error = ref('');
const filters = ref(emptyAnnotationFilters());
const page = ref(1);
const detailKey = ref('');
let generation = 0;
const rows = computed(() =>
  entries.value.map((entry) => {
    const exempt = task.value.skippedConversations?.includes(entry.key) ?? false;
    return {
      ...entry,
      status: exempt
        ? '免标注'
        : entry.error
          ? '读取失败'
          : entry.trace
            ? annotationV2Status(
                task.value,
                entry.key,
                [
                  ...new Set([
                    ...(entry.run.manifest.dataset.cases
                      .find((c) => c.id === entry.caseId)
                      ?.turns.map((t) => t.id) ?? []),
                    ...Object.keys(entry.trace.turn_outcomes),
                  ]),
                ],
                entry.run.manifest.evaluator_specs?.map((e) => e.id),
              )
            : '读取中',
      evaluatedAt: entry.run.completed_at ?? entry.run.started_at,
    };
  }),
);
const filtered = computed(() =>
  rows.value.filter((row) => matchesAnnotationFilters(row, filters.value)),
);
const visible = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20));
const maxPage = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)));
const selected = computed(() => rows.value.find((row) => row.key === detailKey.value));
const taskOptions = computed(() => [
  ...new Map(rows.value.map((row) => [row.taskId, row.taskName])).entries(),
]);
const statuses = computed(() => [...new Set(rows.value.map((row) => row.status))]);
const filterColumns = [
  { key: 'taskId', label: '测评任务' },
  { key: 'name', label: '会话名称' },
  { key: 'score', label: '综合分' },
  { key: 'status', label: '标注状态' },
  { key: 'date', label: '测评时间' },
] as const;
type FilterColumn = (typeof filterColumns)[number]['key'];
function filterActive(key: FilterColumn) {
  if (key === 'score')
    return filters.value.badOnly || filters.value.scoreMin !== '' || filters.value.scoreMax !== '';
  if (key === 'date') return !!(filters.value.from || filters.value.to);
  return !!filters.value[key];
}
function clearColumn(key: FilterColumn) {
  if (key === 'score') {
    filters.value.scoreMin = '';
    filters.value.scoreMax = '';
    filters.value.badOnly = false;
  } else if (key === 'date') {
    filters.value.from = '';
    filters.value.to = '';
  } else filters.value[key] = '';
}
const filterError = computed(() => annotationFilterError(filters.value));
watch(
  filters,
  () => {
    page.value = 1;
  },
  { deep: true },
);
watch(maxPage, (value) => {
  page.value = Math.min(page.value, value);
});
function resetFilters() {
  filters.value = emptyAnnotationFilters();
}
function toggleExempt(entry: Entry) {
  error.value = '';
  const updated = copy(task.value);
  const keys = new Set(updated.skippedConversations ?? []);
  keys.has(entry.key) ? keys.delete(entry.key) : keys.add(entry.key);
  updated.skippedConversations = [...keys];
  try {
    review.saveAnnotationTask(updated);
  } catch (cause) {
    error.value = String(cause);
  }
}
async function load() {
  const ticket = ++generation;
  loading.value = true;
  error.value = '';
  entries.value = [];
  detailKey.value = '';
  try {
    const [runs, tasks] = await Promise.all([
      request<EvaluationRun[]>('/runs?status=completed&limit=200'),
      request<{ id: string; name?: string | null; kind: string; run_ids: string[] }[]>(
        '/evaluation-tasks',
      ),
    ]);
    if (ticket !== generation) return;
    const matched = runs.filter((run) => {
      if (task.value.target) return matchesAnnotationTarget(run, task.value.target);
      const ref = run.manifest.target.ref,
        app = task.value.app;
      return (
        run.status === 'completed' &&
        ref.source_id === app.source_id &&
        ref.target_type === app.target_type &&
        ref.external_target_id === app.external_target_id &&
        (!app.external_version_id || ref.external_version_id === app.external_version_id)
      );
    });
    entries.value = matched.flatMap((run) => {
      const linked = tasks.find((t) => t.run_ids.includes(run.id));
      const lead = linked ? runs.find((r) => r.id === linked.run_ids[0]) : run;
      const taskName =
        linked?.name ||
        (lead ? taskTitle(lead, linked?.kind) : `测评任务 · ${linked!.id.slice(0, 8)}`);
      return run.manifest.dataset.cases
        .filter(
          (c) => !run.manifest.selected_case_ids || run.manifest.selected_case_ids.includes(c.id),
        )
        .map((c) => ({
          key: run.id + '/' + c.id,
          run,
          caseId: c.id,
          name: c.name,
          taskId: linked?.id ?? run.id,
          taskName,
          score: null,
          badCase: false,
        }));
    });
    let cursor = 0;
    await Promise.all(
      Array.from({ length: Math.min(4, matched.length) }, async () => {
        while (ticket === generation) {
          const run = matched[cursor++];
          if (!run) break;
          const cases = entries.value.filter((entry) => entry.run.id === run.id);
          let report: Report | undefined;
          try {
            report = await request<Report>(`/runs/${encodeURIComponent(run.id)}`);
          } catch {
            if (ticket === generation)
              error.value = '部分测评结果读取失败；缺失的综合分显示为 —，请刷新重试。';
          }
          for (const entry of cases) {
            if (ticket !== generation) return;
            if (report)
              Object.assign(entry, annotationCaseScore(report, entry.caseId), {
                results: report.results.filter((r) => r.case_id === entry.caseId),
              });
            try {
              const trace = await request<Trace>(
                `/runs/${encodeURIComponent(run.id)}/traces/${encodeURIComponent(entry.caseId)}`,
              );
              if (ticket === generation) entry.trace = trace;
            } catch {
              if (ticket === generation) entry.error = '会话轨迹读取失败';
            }
          }
        }
      }),
    );
  } catch {
    if (ticket === generation) error.value = '读取测评任务或会话列表失败，请刷新重试。';
  } finally {
    if (ticket === generation) loading.value = false;
  }
}
watch(
  () => props.task.id,
  () => {
    resetFilters();
    void load();
  },
  { immediate: true },
);
onUnmounted(() => {
  generation++;
});
</script>

<template>
  <section class="v2-workspace asset-dialog">
    <nav>
      <button class="asset-link" @click="emit('back')">人工标注</button
      ><span> / {{ task.name }}</span>
    </nav>
    <template v-if="!selected">
      <header class="v2-heading">
        <div>
          <h1>{{ task.name }}</h1>
          <p>{{ task.app.name }} · v2.0 <span class="asset-chip">本浏览器保存</span></p>
        </div>
        <button class="asset-secondary" :disabled="loading" @click="load">刷新会话</button>
      </header>
      <div class="v2-kpis">
        <article>
          会话数<strong>{{ rows.length }}</strong>
        </article>
        <article>
          待标注<strong>{{ rows.filter((r) => r.status === '待标注').length }}</strong>
        </article>
        <article>
          免标注<strong>{{ rows.filter((r) => r.status === '免标注').length }}</strong>
        </article>
        <article>
          Bad Case<strong>{{ rows.filter((r) => r.badCase).length }}</strong>
        </article>
      </div>
      <div class="v2-toolbar">
        <button class="asset-link" @click="resetFilters">清空筛选</button
        ><span>筛选 {{ filtered.length }} / {{ rows.length }} 条</span>
      </div>
      <p v-if="loading" role="status">正在读取测评结果与会话…</p>
      <p v-if="error" role="alert" class="asset-error">{{ error }}</p>
      <p v-if="filterError" role="alert" class="asset-error">{{ filterError }}</p>
      <div class="table-wrap">
        <table class="data-table v2-table">
          <thead>
            <tr>
              <th v-for="column in filterColumns" :key="column.key">
                <div class="column-heading">
                  {{ column.label }}
                  <el-popover trigger="click" placement="bottom-start" :width="280">
                    <template #reference>
                      <button
                        class="filter-toggle"
                        :class="{ active: filterActive(column.key) }"
                        :aria-label="column.label + '过滤'"
                        :title="column.label + '过滤'"
                      >
                        <Filter aria-hidden="true" />
                      </button>
                    </template>
                    <div class="column-filter">
                      <div class="filter-heading">
                        <span>{{ column.label }}过滤</span>
                        <button
                          class="filter-clear"
                          :aria-label="'清空' + column.label + '过滤'"
                          title="清空过滤"
                          @click="clearColumn(column.key)"
                        >
                          <Close aria-hidden="true" />
                        </button>
                      </div>
                      <select
                        v-if="column.key === 'taskId'"
                        v-model="filters.taskId"
                        aria-label="筛选测评任务"
                      >
                        <option value="">全部任务</option>
                        <option v-for="[id, name] in taskOptions" :key="id" :value="id">
                          {{ name }}
                        </option>
                      </select>
                      <template v-else-if="column.key === 'name'">
                        <input
                          v-model="filters.name"
                          aria-label="筛选会话名称"
                          placeholder="搜索会话"
                          list="v2-conversation-names"
                        />
                        <datalist id="v2-conversation-names">
                          <option
                            v-for="name in [...new Set(rows.map((r) => r.name))]"
                            :key="name"
                            :value="name"
                          />
                        </datalist>
                      </template>
                      <div v-else-if="column.key === 'score'">
                        <label class="bad-case-filter"
                          ><input v-model="filters.badOnly" type="checkbox" />Bad Case</label
                        >
                        <div class="score-range">
                          <input
                            v-model="filters.scoreMin"
                            type="number"
                            min="0"
                            max="100"
                            step="any"
                            aria-label="最低综合分"
                            placeholder="最低"
                          />
                          <span>—</span>
                          <input
                            v-model="filters.scoreMax"
                            type="number"
                            min="0"
                            max="100"
                            step="any"
                            aria-label="最高综合分"
                            placeholder="最高"
                          />
                        </div>
                      </div>
                      <select
                        v-else-if="column.key === 'status'"
                        v-model="filters.status"
                        aria-label="筛选标注状态"
                      >
                        <option value="">全部状态</option>
                        <option v-for="status in statuses" :key="status">{{ status }}</option>
                      </select>
                      <div v-else class="date-range">
                        <input v-model="filters.from" type="date" aria-label="测评开始日期" />
                        <span>至</span>
                        <input v-model="filters.to" type="date" aria-label="测评结束日期" />
                      </div>
                    </div>
                  </el-popover>
                </div>
              </th>
              <th class="v2-actions-heading">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in visible" :key="entry.key">
              <td>
                {{ entry.taskName }}<small>运行 {{ entry.run.id.slice(0, 8) }}</small>
              </td>
              <td>
                <b>{{ entry.name }}</b
                ><small>{{ entry.run.manifest.target.ref.external_version_id }}</small>
              </td>
              <td>
                {{ entry.score === null ? '—' : entry.score.toFixed(1)
                }}<small v-if="entry.badCase" class="bad-label">Bad Case</small>
              </td>
              <td>
                <span class="asset-chip" :class="{ preview: entry.status === '待标注' }">{{
                  entry.status
                }}</span>
              </td>
              <td>{{ entry.evaluatedAt ? new Date(entry.evaluatedAt).toLocaleString() : '—' }}</td>
              <td class="v2-actions">
                <button class="asset-link" :disabled="!entry.trace" @click="detailKey = entry.key">
                  开始标注</button
                ><button class="asset-link" :disabled="loading" @click="toggleExempt(entry)">
                  {{ entry.status === '免标注' ? '恢复标注' : '免标注' }}
                </button>
              </td>
            </tr>
            <tr v-if="!visible.length && !loading">
              <td colspan="6" class="empty">
                {{ rows.length ? '没有符合筛选条件的会话。' : '暂无关联的已完成测评会话。' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer class="v2-pagination">
        <span>共 {{ filtered.length }} 条会话</span
        ><button class="asset-secondary" :disabled="page <= 1" @click="page--">上一页</button
        ><span>{{ page }} / {{ maxPage }}</span
        ><button class="asset-secondary" :disabled="page >= maxPage" @click="page++">下一页</button>
      </footer>
    </template>
    <AnnotationV2Editor
      v-else-if="selected.trace"
      :key="selected.key"
      :task="task"
      :run="selected.run"
      :case-id="selected.caseId"
      :trace="selected.trace"
      :results="selected.results"
      @back="detailKey = ''"
    />
  </section>
</template>
<style scoped>
.v2-workspace {
  min-width: 0;
}
.v2-heading,
.v2-toolbar,
.v2-pagination {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 20px 0;
  flex-wrap: wrap;
}
.v2-heading {
  justify-content: space-between;
}
h1 {
  margin: 0 0 12px;
  font-size: 24px;
}
.v2-heading p,
.v2-toolbar span {
  color: #7c8c85;
  font-size: 13px;
}
.v2-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin: 20px 0;
}
.v2-kpis article {
  padding: 24px;
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 12px;
  color: #7c8c85;
}
.v2-kpis strong {
  display: block;
  margin-top: 12px;
  font-size: 28px;
  color: #243c32;
}
.v2-toolbar .active {
  color: #008b73;
  border-color: #00aa8c;
  background: #ecfaf5;
}
.v2-table {
  min-width: 900px;
}
.column-heading,
.filter-heading {
  display: flex;
  align-items: center;
  gap: 8px;
}
.column-heading {
  white-space: nowrap;
}
.filter-heading {
  justify-content: space-between;
  margin-bottom: 10px;
  color: #55647a;
}
.filter-toggle,
.filter-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 4px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #87958f;
}
.filter-toggle:hover,
.filter-toggle.active,
.filter-clear:hover {
  color: #008b73;
  background: #e0f3ed;
}
.filter-toggle svg,
.filter-clear svg {
  width: 16px;
  height: 16px;
}
.column-filter input,
.column-filter select {
  width: 100%;
  min-width: 0;
  height: 34px;
  padding: 5px 8px;
  border: 1px solid #dce7e1;
  border-radius: 5px;
  background: white;
  color: #40516a;
  font: inherit;
}
.score-range {
  display: flex;
  align-items: center;
  gap: 6px;
}
.date-range {
  display: grid;
  gap: 6px;
}
.date-range span {
  text-align: center;
  color: #87958f;
}
.v2-table small {
  display: block;
  color: #83908a;
  margin-top: 6px;
}
.v2-table small.bad-label {
  color: #bf4b41;
}
.v2-actions-heading {
  width: 155px;
}
.v2-actions {
  white-space: nowrap;
  text-align: left;
}
.v2-actions button + button {
  margin-left: 14px;
}
.bad-case-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  cursor: pointer;
}
.bad-case-filter input {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: #07ac8e;
}
.v2-pagination {
  justify-content: flex-end;
}
.empty {
  text-align: center;
  padding: 30px;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f5f8f6;
  padding: 16px;
  border-radius: 8px;
}
@media (max-width: 700px) {
  .v2-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
