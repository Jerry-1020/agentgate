<script setup lang="ts">
import { useRoute, useRouter, onBeforeRouteUpdate } from 'vue-router';
import EvaluationLayout from '../../layout/EvaluationLayout.vue';
import TaskStaticAnalysis from './components/TaskStaticAnalysis.vue';
import TaskTuning from './components/TaskTuning.vue';
import EvaluationTaskForm from './components/EvaluationTaskForm.vue';
import { readTaskLinks, refreshTaskLinks, type TaskLink } from './utils/task-links';
import { shallowRef, computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  api,
  request,
  statusLabel,
  kindLabel,
  type EvaluationRun,
  type Overview,
  type DatasetSummary,
  type EvaluatorSummary,
  type Report,
} from '../../api/evaluations';
import OverviewMetrics from './components/OverviewMetrics.vue';
import DatasetMerge from './components/DatasetMerge.vue';
import RerunDialog from './components/RerunDialog.vue';
import DatasetWorkspace from '../datasets/index.vue';
import AnnotationAssets from './components/AnnotationAssets.vue';
import ScoringTemplates from './components/ScoringTemplates.vue';
import JudgeSystem from './components/JudgeSystem.vue';
import ModelSettings from './components/ModelSettings.vue';
import RunDetail from './components/TaskResults.vue';
import TaskList from './components/TaskList.vue';
import Comparisons from './components/Comparisons.vue';
import Analysis from './components/UpstreamAnalysis.vue';
import Stability from './components/Stability.vue';
import {
  evaluatorScenarios,
  recommendEvaluators,
  recommendationReason,
} from './utils/evaluator-guidance';
const datasetDirty = ref(false),
  evaluatorDirty = ref(false),
  settingsDirty = ref(false);
const rerunId = ref('');
const currentRoute = useRoute(),
  router = useRouter();
const route = computed(() => currentRoute.fullPath.slice(1) || 'overview');
const page = computed(() => {
  const base = route.value.split('/')[0];
  return ['results', 'experiments', 'optimizer'].includes(base)
    ? 'tasks'
    : ['judges', 'scoring-templates'].includes(base)
      ? 'evaluators'
      : base === 'annotation-templates'
        ? 'annotations'
        : base;
});
const taskDetailTab = ref('results');
watch(
  route,
  (value) =>
    (taskDetailTab.value =
      value.startsWith('optimizer/') ||
      new URLSearchParams(value.split('?')[1] ?? '').get('tab') === 'analysis'
        ? 'analysis'
        : 'results'),
  { immediate: true },
);
function pairRows(id: string) {
  return (linkFor(id)?.runIds ?? [id]).map((runId, index) => {
    const run = runs.value.find((r) => r.id === runId);
    return {
      id: runId,
      side: index === 0 ? 'A' : 'B',
      name: run?.manifest.target.display_name ?? '运行记录待加载',
      version: run?.manifest.target.ref.external_version_id ?? '—',
    };
  });
}
const taskType = ref(''),
  datasetFilter = ref(''),
  evaluatorFilter = ref(''),
  timeOrder = ref('newest');
const taskLinks = ref(readTaskLinks()),
  detailDialog = ref('');
function syncTaskLinks() {
  taskLinks.value = readTaskLinks();
}
const currentLink = computed(() => taskLinks.value.find((t) => t.runIds.includes(runId.value)));
const pairLink = computed(() =>
  currentLink.value?.kind === 'ab' && !route.value.includes('/samples/') ? currentLink.value : null,
);
function linkFor(id: string) {
  return taskLinks.value.find((t) => t.runIds.includes(id));
}
function groupStatus(run: EvaluationRun, records = runs.value) {
  const link = linkFor(run.id);
  if (!link || link.runIds.length === 1) return run.status;
  const states = link.runIds.map((id) => records.find((r) => r.id === id)?.status);
  if (states.includes('failed')) return 'failed';
  if (states.includes('cancelled')) return 'cancelled';
  if (states.every((s) => s === 'completed')) return 'completed';
  return states.includes('running') || states.includes('completed') ? 'running' : 'pending';
}
const datasetOptions = computed(() => [
  ...new Map(
    runs.value.map((r) => [r.manifest.dataset.dataset_id, r.manifest.dataset.dataset_name]),
  ).entries(),
]);
const evaluatorOptions = computed(() => [
  ...new Set(runs.value.flatMap((r) => r.manifest.primary_evaluator_ids)),
]);
const runId = computed(() => route.value.split('/')[1]?.split('?')[0] || '');
function go(value: string) {
  const id = value.split('/')[1];
  void router.push(
    '/' +
      (value.startsWith('tasks/') && linkFor(id)?.kind === 'stability' ? 'stability/' + id : value),
  );
}
onBeforeRouteUpdate((to, from) => {
  if (
    (datasetDirty.value || evaluatorDirty.value || settingsDirty.value) &&
    to.fullPath !== from.fullPath &&
    !window.confirm('当前页面有未保存的修改，确定离开并放弃修改？')
  )
    return false;
  datasetDirty.value = false;
  evaluatorDirty.value = false;
  settingsDirty.value = false;
});
const runs = shallowRef<EvaluationRun[]>([]),
  overview = ref<Overview | null>(null);
const error = ref(''),
  online = ref<boolean | null>(null),
  loading = ref(false);
const query = ref(''),
  status = ref(''),
  listLoading = ref(false);
const reportSummaries = ref<Record<string, Report>>({}),
  reportErrors = ref<Record<string, boolean>>({});
const visibleRuns = shallowRef<EvaluationRun[]>([]),
  totalRuns = ref(0),
  pageNumber = ref(1),
  pageSize = ref(20);
let pageRequest = 0;
async function loadPage() {
  const ticket = ++pageRequest;
  listLoading.value = true;
  try {
    const records = await request<EvaluationRun[]>('/runs?limit=200');
    let filtered = records;
    filtered = filtered.filter((r) => {
      const link = linkFor(r.id);
      if (link && link.runIds[0] !== r.id) return false;
      return (
        (link?.runIds ?? [r.id]).some((id) => {
          const item = records.find((x) => x.id === id);
          return JSON.stringify([
            id,
            item?.manifest.target.display_name,
            item?.manifest.target.ref.external_version_id,
            item?.manifest.dataset.dataset_name,
          ])
            .toLowerCase()
            .includes(query.value.toLowerCase());
        }) &&
        (!taskType.value ||
          (link?.kind === 'stability' ? 'single' : (link?.kind ?? 'single')) === taskType.value) &&
        (!status.value || groupStatus(r, records) === status.value) &&
        (!datasetFilter.value || r.manifest.dataset.dataset_id === datasetFilter.value) &&
        (!evaluatorFilter.value || r.manifest.primary_evaluator_ids.includes(evaluatorFilter.value))
      );
    });
    if (timeOrder.value === 'oldest') filtered.reverse();
    const result = {
      items: filtered.slice(
        (pageNumber.value - 1) * pageSize.value,
        pageNumber.value * pageSize.value,
      ),
      total: filtered.length,
    };
    if (ticket === pageRequest) {
      visibleRuns.value = result.items;
      totalRuns.value = result.total;
      if (page.value === 'tasks')
        void loadSummaries(
          records.filter((r) =>
            result.items.some(
              (item) => item.id === r.id || linkFor(item.id)?.runIds.includes(r.id),
            ),
          ),
          ticket,
        );
    }
  } catch (e) {
    if (ticket === pageRequest) error.value = String(e);
  } finally {
    if (ticket === pageRequest) listLoading.value = false;
  }
}
async function loadSummaries(rows: EvaluationRun[], ticket: number) {
  for (let start = 0; start < rows.length; start += 4) {
    if (ticket !== pageRequest) return;
    await Promise.all(
      rows
        .slice(start, start + 4)
        .filter((r) => r.status === 'completed' && !reportSummaries.value[r.id])
        .map(async (r) => {
          try {
            const report = await api.report(r.id);
            if (ticket === pageRequest) {
              reportSummaries.value[r.id] = report;
              reportErrors.value[r.id] = false;
            }
          } catch {
            if (ticket === pageRequest) reportErrors.value[r.id] = true;
          }
        }),
    );
  }
}
function resultSummary(id: string) {
  const report = reportSummaries.value[id];
  return report?.metrics.find((m) => m.level === 'overall');
}
watch([query, status, pageSize, taskType, datasetFilter, evaluatorFilter, timeOrder], () => {
  pageNumber.value = 1;
  void loadPage();
});
watch(pageNumber, () => void loadPage());
const actionRun = ref('');
async function runAction(id: string, action: 'cancel' | 'rerun') {
  if (action === 'rerun') {
    rerunId.value = id;
    return;
  }
  if (actionRun.value) return;
  actionRun.value = id;
  try {
    await ElMessageBox.confirm('取消当前任务？已产生的记录将保留。', '取消任务', {
      confirmButtonText: '确认',
      cancelButtonText: '返回',
    });
    await request(`/runs/${encodeURIComponent(id)}/cancel`, 'POST');
    await refresh();
    ElMessage.success('取消请求已提交');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(String(e));
  } finally {
    actionRun.value = '';
  }
}
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
async function refresh() {
  if (loading.value) return;
  loading.value = true;
  try {
    const [o, r, links] = await Promise.all([api.overview(), api.runs(), refreshTaskLinks()]);
    overview.value = o;
    runs.value = r;
    taskLinks.value = links;
    online.value = true;
    error.value = '';
  } catch (e) {
    online.value = false;
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
async function poll() {
  await refresh();
  if (!disposed) timer = setTimeout(poll, 5000);
}
onMounted(() => {
  window.addEventListener('task-links-updated', syncTaskLinks);
  void poll();
});
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
  window.removeEventListener('task-links-updated', syncTaskLinks);
});
const create = ref(false);
const formSource = ref<{
  id: string;
  version: number;
  caseIds?: string[];
  caseName?: string;
  targetVersion?: string;
  evaluatorId?: string;
}>();
function openCreate(source?: typeof formSource.value) {
  formSource.value = source;
  create.value = true;
}
async function taskCreated(link: TaskLink) {
  create.value = false;
  taskLinks.value = readTaskLinks();
  go((link.kind === 'stability' ? 'stability/' : 'tasks/') + link.id);
  await refresh();
}
</script>
<template>
  <EvaluationLayout :page="page" :online="online">
    <div v-if="error" class="notice error" role="alert">
      服务连接失败：{{ error }}
      <button class="link" @click="refresh">重试</button>。不使用模拟数据替代。
    </div>
    <template v-if="page === 'overview'">
      <div class="page-head">
        <div><h1 class="page-title">评测总览</h1></div>
        <span class="muted">{{ loading ? '正在刷新' : '最近任务每 5 秒刷新' }}</span>
      </div>
      <OverviewMetrics />
      <div class="card">
        <div class="toolbar">
          <h2 class="section-title">最近评测任务</h2>
          <a href="#tasks" class="link">查看全部 →</a>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>智能体 / 版本</th>
              <th>评测集</th>
              <th>执行状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs.slice(0, 6)" :key="r.id">
              <td>
                {{ r.manifest.target.display_name }}
                <div class="muted">{{ r.manifest.target.ref.external_version_id }}</div>
              </td>
              <td>{{ r.manifest.dataset.dataset_name }}</td>
              <td>{{ statusLabel(r.status) }}</td>
              <td><button class="link" @click="go('tasks/' + r.id)">查看</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!runs.length" class="empty">尚无评测任务，请从“评测任务”发起。</p>
      </div>
    </template>
    <ModelSettings v-else-if="page === 'settings'" @dirty-change="settingsDirty = $event" />
    <DatasetWorkspace
      v-else-if="page === 'datasets'"
      :key="page"
      :initial-id="runId"
      @dirty-change="datasetDirty = $event"
      @run-version="openCreate($event)"
    />
    <section v-else-if="page === 'dataset-merge'" class="card">
      多 Skill 合并需求已挂起，当前不提供创建入口。<a href="#datasets">返回评测集</a>
    </section>
    <AnnotationAssets
      v-else-if="page === 'annotations' || page === 'annotation-templates'"
      :key="page"
      :templates="page === 'annotation-templates'"
      :task-id="runId"
      @navigate="go"
      @dirty-change="evaluatorDirty = $event"
    />
    <ScoringTemplates
      v-else-if="page === 'scoring-templates'"
      :key="route"
      :initial-id="runId"
      @dirty-change="evaluatorDirty = $event"
    />
    <JudgeSystem
      v-else-if="page === 'evaluators'"
      :key="route"
      :initial-id="runId"
      @dirty-change="evaluatorDirty = $event"
      @launch="openCreate({ id: '', version: 0, evaluatorId: $event })"
    />
    <template v-else-if="page === 'tasks' || page === 'results'">
      <template v-if="runId">
        <section v-if="pairLink" class="card task-linked-summary">
          <a href="#tasks" class="link">← 返回评测任务</a>
          <h3>A/B 实验</h3>
          <template v-if="pairLink"
            ><p>两侧使用相同评测集与评估器版本。</p>
            <div class="actions">
              <button
                v-for="(id, index) in pairLink.runIds"
                :key="id"
                @click="detailDialog = id"
                class="link"
              >
                实验 {{ index === 0 ? 'A' : 'B' }} ·
                {{ statusLabel(runs.find((r) => r.id === id)?.status ?? 'pending') }}
              </button>
            </div></template
          >
        </section>
        <div v-if="pairLink" class="tabs" aria-label="实验详情内容">
          <button
            :class="['tab', { active: taskDetailTab === 'results' }]"
            @click="taskDetailTab = 'results'"
          >
            实验对比</button
          ><button
            :class="['tab', { active: taskDetailTab === 'analysis' }]"
            @click="taskDetailTab = 'analysis'"
          >
            调优分析</button
          ><button
            :class="['tab', { active: taskDetailTab === 'static' }]"
            @click="taskDetailTab = 'static'"
          >
            Skill 静态分析
          </button>
        </div>
        <TaskStaticAnalysis
          v-if="pairLink && taskDetailTab === 'static'"
          :run-ids="pairLink.runIds" />
        <TaskTuning
          v-if="pairLink && taskDetailTab === 'analysis'"
          :key="pairLink.id"
          :run-ids="pairLink.runIds" />
        <Comparisons
          v-if="pairLink && taskDetailTab === 'results'"
          :key="pairLink.id"
          :initial-pair="{ a: pairLink.runIds[0], b: pairLink.runIds[1] }"
          embedded />
        <RunDetail v-if="!pairLink" :key="route" :id="runId" :return-page="page" @navigate="go"
      /></template>
      <template v-else>
        <TaskList @create="openCreate()" @navigate="go" @action="runAction" />
      </template>
    </template>
    <Stability v-else-if="page === 'stability'" :key="route" :id="runId" @navigate="go" />
    <Comparisons v-else-if="page === 'experiments'" />
    <Analysis
      v-else-if="page === 'optimizer' || page === 'analysis'"
      :key="route"
      :mode="page"
      :initial-id="runId"
      :runs="runs"
    />
    <div v-else class="card empty">页面不存在。<a href="#overview">返回总览</a></div>
    <template #dialogs>
      <RerunDialog
        v-if="rerunId"
        :id="rerunId"
        @close="rerunId = ''"
        @created="
          (id) => {
            rerunId = '';
            go('tasks/' + id);
          }
        "
      />
      <el-dialog
        :model-value="!!detailDialog"
        @close="detailDialog = ''"
        title="实验运行详情"
        width="min(1200px,96vw)"
        destroy-on-close
        ><RunDetail
          v-if="detailDialog"
          :id="detailDialog"
          return-page="tasks"
          @navigate="
            (value) => {
              detailDialog = '';
              go(value);
            }
          "
      /></el-dialog>
      <EvaluationTaskForm
        v-if="create"
        :source="formSource"
        @close="create = false"
        @created="taskCreated"
      />
    </template>
  </EvaluationLayout>
</template>

<style>
.task-identity {
  min-width: 250px;
}
.ab-identities {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}
.ab-identity {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.ab-side {
  display: inline-grid;
  place-items: center;
  background: #e7f4ee;
  color: #00826a;
  border-radius: 4px;
  width: 21px;
  height: 21px;
  font-size: 11px;
  font-weight: 700;
}
.ab-identity div {
  display: grid;
  gap: 3px;
  font-size: 11px;
  color: #718278;
  overflow-wrap: anywhere;
}
.ab-identity b {
  color: #384e42;
  font-size: 12px;
}
.ab-identity small {
  font-size: 10px;
  color: #8a9791;
}
.task-create-dialog .el-dialog__header {
  padding: 20px 28px;
  border-bottom: 1px solid #e5eaf0;
  margin: 0;
}
.task-create-dialog .el-dialog__body {
  padding: 20px 32px;
  max-height: 76vh;
  overflow: auto;
}
.task-create-dialog .el-dialog__footer {
  border-top: 1px solid #e5eaf0;
  padding: 16px 28px;
}
.task-create-dialog .el-dialog__footer button + button {
  margin-left: 12px;
}
.task-intro {
  color: #64748b;
  margin: 0 0 24px;
  font-size: 14px;
}
.task-create-grid {
  gap: 22px 28px;
}
.task-create-grid .full {
  grid-column: 1 / -1;
}
.form-section-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  padding-top: 24px;
  border-top: 1px solid #e8edf1;
  margin-top: 4px;
}
.form-section-heading:first-child {
  border-top: 0;
  padding-top: 0;
}
.form-section-heading > span {
  background: #e3f5f0;
  color: #00826e;
  border-radius: 8px;
  padding: 10px;
  font-weight: 700;
}
.form-section-heading h3 {
  font-size: 17px;
  margin: 0 0 4px;
}
.form-section-heading p {
  color: #64748b;
  font-size: 13px;
  margin: 0;
}
.task-create-dialog .check-list {
  gap: 12px;
  margin-top: 16px;
}
.task-create-dialog .check-list > label {
  padding: 14px;
  align-items: flex-start;
  background: #fafcfb;
  border: 1px solid #e2e9e6;
  border-radius: 8px;
  font-size: 14px;
}
.task-create-dialog .task-summary {
  padding: 16px;
  background: #f4f8f7;
  border-radius: 8px;
  font-size: 14px;
  margin: 24px 0 0;
}
.task-list-card .task-status-tabs {
  margin: -4px 0 20px;
  overflow-x: auto;
  white-space: nowrap;
}
.task-filterbar {
  justify-content: flex-start;
  gap: 20px;
  margin-bottom: 20px;
}
.task-filterbar .outcome-filter {
  width: 170px;
  flex: none;
}
.task-filterbar .search {
  max-width: 420px;
  flex: 1;
}
.task-list-card table {
  min-width: 1120px;
}
.task-list-card .badge,
.task-list-card .tag {
  white-space: nowrap;
}
.task-list-card td:nth-child(3) {
  min-width: 82px;
}
.task-list-card td:nth-child(4) {
  min-width: 88px;
}
.task-list-card td:nth-child(5) {
  min-width: 110px;
}
.task-list-card th select {
  max-width: 175px;
  background: transparent;
  border: 0;
  color: inherit;
  font: inherit;
  padding: 4px;
  cursor: pointer;
}
.task-linked-summary {
  margin-bottom: 20px;
}
.task-linked-summary .actions {
  display: flex;
  gap: 20px;
  margin-bottom: 16px;
}
.task-linked-summary button {
  margin-left: 16px;
}
.task-list-card th {
  background: #f6f8fa;
  white-space: nowrap;
}
.task-list-card td {
  padding-top: 20px;
  padding-bottom: 20px;
  vertical-align: middle;
}
.task-title {
  font-weight: 600;
  text-align: left;
}
.task-meta {
  display: block;
  font-size: 12px;
  margin-top: 7px;
}
.task-id {
  font-size: 12px;
  max-width: 245px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 5px;
}
.task-row-actions {
  white-space: nowrap;
}
.task-row-actions button + button {
  margin-left: 16px;
}
.task-list-card > .toolbar:last-child {
  justify-content: flex-end;
  gap: 12px;
}
.task-list-card > .toolbar:last-child select {
  width: 130px;
}
@media (max-width: 700px) {
  .task-create-dialog .el-dialog__body {
    padding: 16px;
  }
  .task-create-grid {
    grid-template-columns: 1fr;
  }
  .task-filterbar {
    flex-wrap: wrap;
  }
}
</style>
