<script setup lang="ts">
import {
  useRoute,
  useRouter,
  onBeforeRouteUpdate,
  onBeforeRouteLeave,
  type NavigationGuard,
} from 'vue-router';
import EvaluationLayout from '../../layout/EvaluationLayout.vue';
import TaskStaticAnalysis from './components/TaskStaticAnalysis.vue';
import TaskTuning from './components/TaskTuning.vue';
import EvaluationTaskForm from './components/EvaluationTaskForm.vue';
import {
  readTaskLinks,
  refreshTaskLinks,
  includeCurrentTaskRuns,
  type TaskLink,
} from './utils/task-links';
import { shallowRef, computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
  getOverviewSummary,
  getTaskSummaries,
  type TaskAction,
} from '../../api/evaluation-summaries';
import { dayWindow, taskPath } from './utils/summary-query';
import { useSummaryQuery } from './composables/use-summary-query';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/modules/auth';
import { api, request, statusLabel, type EvaluationRun } from '../../api/evaluations';
import OverviewMetrics from './components/OverviewMetrics.vue';
import RerunDialog from './components/RerunDialog.vue';
import DatasetWorkspace from '../datasets/index.vue';
import ScoringTemplates from './components/ScoringTemplates.vue';
import JudgeSystem from './components/JudgeSystem.vue';
import ModelSettings from './components/ModelSettings.vue';
import RunDetail from './components/TaskResults.vue';
import TaskList from './components/TaskList.vue';
import Comparisons from './components/Comparisons.vue';
import Analysis from './components/UpstreamAnalysis.vue';
import Stability from './components/Stability.vue';

const datasetDirty = ref(false),
  evaluatorDirty = ref(false),
  settingsDirty = ref(false);
const rerunId = ref('');
const rerunTaskId = ref('');
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
  return taskLinks.value.find((t) => t.id === id || t.runIds.includes(id));
}
const runId = computed(() => {
  const id = route.value.split('/')[1]?.split('?')[0] || '';
  return /^(tasks|results)\//.test(route.value)
    ? (taskLinks.value.find((t) => t.id === id)?.runIds[0] ?? id)
    : id;
});
function go(value: string) {
  const id = value.split('/')[1];
  void router.push(
    '/' +
      (value.startsWith('tasks/') && linkFor(id)?.kind === 'stability' ? 'stability/' + id : value),
  );
}
const hasUnsavedChanges = computed(
  () => datasetDirty.value || evaluatorDirty.value || settingsDirty.value,
);
function clearDirtyState() {
  datasetDirty.value = false;
  evaluatorDirty.value = false;
  settingsDirty.value = false;
}
const confirmNavigation: NavigationGuard = (to, from) => {
  if (to.fullPath === from.fullPath) return;
  if (hasUnsavedChanges.value && !window.confirm('当前页面有未保存的修改，确定离开并放弃修改？'))
    return false;
  clearDirtyState();
};
onBeforeRouteUpdate(confirmNavigation);
onBeforeRouteLeave(confirmNavigation);
const runs = shallowRef<EvaluationRun[]>([]);
const overviewDays = ref(7);
const auth = useAuthStore();
const authLabel = computed(() => auth.modeLabel);
async function confirmLogout() {
  if (auth.isIntegrated) return;
  try {
    await ElMessageBox.confirm(
      (hasUnsavedChanges.value ? '当前页面有未保存的修改，登出将放弃这些修改。' : '') +
        '将清空登陆用户信息（token、团队选择），页面将返回欢迎页面。',
      '登出确认',
      { confirmButtonText: '确认登出', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  clearDirtyState();
  auth.logout();
  void router.push('/welcome');
}
const error = ref(''),
  online = ref<boolean | null>(null),
  loading = ref(false);
const actionRun = ref('');
const listRefreshToken = ref(0);
async function runAction({ runId: id, taskId, action }: TaskAction) {
  if (action === 'rerun') {
    if (rerunId.value) return;
    rerunId.value = id;
    rerunTaskId.value = taskId ?? '';
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
    listRefreshToken.value++;
    ElMessage.success('取消请求已提交');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(String(e));
  } finally {
    actionRun.value = '';
  }
}
const identity = () => [auth.loginMode, auth.teamId, auth.userId, auth.token, auth.platformReady];
const overviewQuery = useSummaryQuery({
  source: () => [page.value, overviewDays.value],
  identity,
  ready: () => page.value === 'overview' && auth.authenticated,
  load: async (signal) => {
    const [summary, recent] = await Promise.all([
      getOverviewSummary(dayWindow(overviewDays.value), signal),
      getTaskSummaries({ page: 1, page_size: 6 }, signal),
    ]);
    return { summary, recent };
  },
  poll: () => true,
});
const overviewData = overviewQuery.data;
const overviewError = overviewQuery.error;
const latestTasks = computed(() => overviewData.value?.recent.items ?? []);
watch([overviewData, overviewError], () => {
  if (page.value === 'overview')
    online.value = overviewError.value ? false : overviewData.value ? true : null;
});
let contextRequest = 0;
let contextTimer: ReturnType<typeof setTimeout> | undefined;
const detailReady = ref(false);
function needsContext() {
  return (page.value === 'tasks' && !!route.value.split('/')[1]) || page.value === 'analysis';
}
async function refresh() {
  clearTimeout(contextTimer);
  const ticket = ++contextRequest;
  if (page.value === 'overview') {
    await overviewQuery.reload();
    return;
  }
  if (!needsContext()) {
    listRefreshToken.value++;
    return;
  }
  if (document.hidden || !auth.authenticated) return;
  loading.value = true;
  try {
    // Legacy associations remain detail-only; summaries never depend on this cache.
    const [r] = await Promise.all([api.runs(), refreshTaskLinks()]);
    const records = await includeCurrentTaskRuns(r);
    if (ticket !== contextRequest) return;
    runs.value = records;
    taskLinks.value = readTaskLinks();
    online.value = true;
    error.value = '';
    detailReady.value = true;
  } catch (cause) {
    if (ticket === contextRequest) {
      online.value = false;
      error.value = String(cause);
    }
  } finally {
    if (ticket === contextRequest) {
      loading.value = false;
      const ids = currentLink.value?.runIds ?? [runId.value];
      const active = runs.value.some(
        (run) =>
          (page.value === 'analysis' || ids.includes(run.id)) &&
          ['pending', 'scheduled', 'running'].includes(run.status),
      );
      if (!error.value && active && !document.hidden && needsContext())
        contextTimer = setTimeout(() => void refresh(), 5000);
    }
  }
}
watch(
  [
    route,
    ...[
      () => auth.loginMode,
      () => auth.teamId,
      () => auth.userId,
      () => auth.token,
      () => auth.platformReady,
    ],
  ],
  () => {
    contextRequest++;
    clearTimeout(contextTimer);
    loading.value = false;
    detailReady.value = false;
    runs.value = [];
    taskLinks.value = [];
    error.value = '';
    if (needsContext() && auth.authenticated) void refresh();
  },
  { immediate: true },
);
function contextVisibility() {
  clearTimeout(contextTimer);
  if (document.hidden) contextRequest++;
  else if (needsContext()) void refresh();
}
onMounted(() => {
  window.addEventListener('task-links-updated', syncTaskLinks);
  document.addEventListener('visibilitychange', contextVisibility);
});
onUnmounted(() => {
  contextRequest++;
  clearTimeout(contextTimer);
  window.removeEventListener('task-links-updated', syncTaskLinks);
  document.removeEventListener('visibilitychange', contextVisibility);
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
}
async function taskRerunCreated(taskId: string) {
  rerunId.value = '';
  rerunTaskId.value = '';
  detailDialog.value = '';
  if (currentRoute.path === '/tasks/' + taskId) await refresh();
  else go('tasks/' + taskId);
}
</script>
<template>
  <EvaluationLayout
    :page="page"
    :online="online"
    :auth-label="authLabel"
    :hide-auth-controls="auth.isIntegrated"
    @logout="confirmLogout"
  >
    <div v-if="error" class="notice error" role="alert">
      服务连接失败：{{ error }}
      <button class="link" @click="refresh">重试</button>。不使用模拟数据替代。
    </div>
    <template v-if="page === 'overview'">
      <div class="page-head">
        <div style="display: flex; align-items: flex-end; gap: 16px">
          <h1 class="page-title">测评总览</h1>
          <div class="tabs">
            <button
              v-for="d in [1, 7, 30]"
              :key="d"
              :class="['tab', { active: overviewDays === d }]"
              :aria-pressed="overviewDays === d"
              @click="overviewDays = d"
            >
              {{ d === 1 ? '今日' : '近' + d + '天' }}
            </button>
          </div>
        </div>
      </div>
      <OverviewMetrics
        :data="overviewData?.summary ?? null"
        :error="overviewError"
        @retry="overviewQuery.reload"
      />
      <div class="card">
        <div class="toolbar">
          <h2 class="section-title">最近测评任务</h2>
          <a href="#tasks" class="link">查看全部 →</a>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>智能体 / 版本</th>
              <th>测评集</th>
              <th>执行状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in latestTasks" :key="r.id">
              <td class="nowrap">
                {{ r.runs[0].target_name }}
                <span class="muted">· {{ r.runs[0].target_version }}</span>
              </td>
              <td class="nowrap">{{ r.runs[0].dataset_name }}</td>
              <td class="nowrap">{{ statusLabel(r.status) }}</td>
              <td class="nowrap">
                <button class="link" @click="go(taskPath(r))">查看</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="overviewData && !latestTasks.length" class="empty">
          尚无测评任务，请从“测评任务”发起。
        </p>
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
      多 Skill 合并需求已挂起，当前不提供创建入口。<a href="#datasets">返回测评集</a>
    </section>
    <section v-else-if="page === 'annotations' || page === 'annotation-templates'" class="card">
      <h1 class="page-title">标注</h1>
      <p class="empty">待实现</p>
    </section>
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
      <p v-if="runId && !detailReady" class="empty">正在加载任务上下文…</p>
      <template v-else-if="runId">
        <section v-if="pairLink" class="card task-linked-summary">
          <a href="#tasks" class="link">← 返回测评任务</a>
          <h3>A/B试验</h3>
          <template v-if="pairLink"
            ><p>两侧使用相同测评集与评估器版本。</p>
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
        <RunDetail
          v-if="!pairLink"
          :key="route + ':' + runId"
          :id="runId"
          :task-id="currentLink?.id"
          :return-page="page"
          @navigate="go"
          @rerun-created="taskRerunCreated"
      /></template>
      <template v-else>
        <TaskList
          :refresh-token="listRefreshToken"
          @connection="online = $event"
          @create="openCreate()"
          @navigate="go"
          @action="runAction"
        />
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
        :task-id="rerunTaskId || undefined"
        @close="rerunId = ''"
        @created="taskRerunCreated"
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
          :task-id="linkFor(detailDialog)?.id"
          return-page="tasks"
          @rerun-created="taskRerunCreated"
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
.page-head .tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 0;
  margin-bottom: 0;
}
.page-head .tab {
  padding: 3px 12px;
  border: 0;
  background: #f3f4f6;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #394250;
  cursor: pointer;
  line-height: 1.4;
}
.page-head .tab.active {
  background: #07ac8e;
  color: #fff;
}
.nowrap {
  white-space: nowrap;
}
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
  gap: 16px 24px;
}
.task-create-grid .full {
  grid-column: 1 / -1;
}
.form-section-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  padding-top: 16px;
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
