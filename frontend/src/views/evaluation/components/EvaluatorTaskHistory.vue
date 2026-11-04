<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { api, statusLabel, type EvaluatorRelatedTaskPage } from '../../../api/evaluations';
import { useAuthStore } from '../../../stores/modules/auth';
import { taskPath } from '../utils/summary-query';
import { formatTaskTime } from '../utils/task-timing';

const props = withDefaults(
  defineProps<{
    evaluatorId: string;
    latestVersion?: string | null;
    currentVersion?: string | null;
    enabled?: boolean;
    divider?: boolean;
  }>(),
  { enabled: true },
);

const auth = useAuthStore();
const activeTab = ref('definition');
const initialized = ref(false);
const version = ref('');
const versions = ref<string[]>([]);
const page = ref<EvaluatorRelatedTaskPage | null>(null);
const cursors = ref<(string | null)[]>([null]);
const loading = ref(false);
const versionsLoading = ref(false);
const error = ref(false);
const versionsError = ref(false);
let versionsRequest: AbortController | undefined;
let pageRequest: AbortController | undefined;

const taskKinds = { single: '单任务', ab: 'A/B试验', stability: '稳定性测试' };

function creationTime(value: string) {
  const parts = formatTaskTime(value);
  return parts ? `${parts.date} ${parts.time}` : '—';
}

function abortRequests() {
  versionsRequest?.abort();
  pageRequest?.abort();
}

async function loadVersions() {
  versionsRequest?.abort();
  const request = (versionsRequest = new AbortController());
  versionsLoading.value = true;
  versionsError.value = false;
  try {
    const published = await api.evaluatorVersions(props.evaluatorId, request.signal);
    if (!request.signal.aborted) {
      versions.value = [
        ...new Set([
          ...published.flatMap((entry) => (entry.version ? [entry.version] : [])),
          version.value,
        ]),
      ];
    }
  } catch {
    if (!request.signal.aborted) versionsError.value = true;
  } finally {
    if (!request.signal.aborted) versionsLoading.value = false;
  }
}

async function loadPage() {
  pageRequest?.abort();
  const request = (pageRequest = new AbortController());
  loading.value = true;
  error.value = false;
  page.value = null;
  try {
    const result = await api.evaluatorRelatedTasks(
      props.evaluatorId,
      version.value,
      cursors.value[cursors.value.length - 1],
      request.signal,
    );
    if (!request.signal.aborted) page.value = result;
  } catch {
    if (!request.signal.aborted) error.value = true;
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}

function selectVersion() {
  cursors.value = [null];
  void loadPage();
}

function initializeHistory() {
  initialized.value = true;
  version.value = props.currentVersion || props.latestVersion || '';
  versions.value = version.value ? [version.value] : [];
  cursors.value = [null];
  page.value = null;
  loading.value = false;
  versionsLoading.value = false;
  error.value = false;
  versionsError.value = false;
  if (version.value) {
    void loadVersions();
    void loadPage();
  }
}

function previousPage() {
  cursors.value.pop();
  void loadPage();
}

function nextPage() {
  const cursor = page.value?.next_cursor;
  if (!cursor) return;
  cursors.value.push(cursor);
  void loadPage();
}

watch(activeTab, (tab) => {
  if (tab === 'history' && auth.authenticated && !initialized.value) initializeHistory();
});
watch(
  () => [
    props.enabled,
    props.evaluatorId,
    props.latestVersion,
    props.currentVersion,
    auth.loginMode,
    auth.platformReady,
    auth.token,
    auth.teamId,
    auth.userId,
  ],
  () => {
    abortRequests();
    initialized.value = false;
    activeTab.value = 'definition';
    page.value = null;
  },
  { flush: 'sync' },
);
onBeforeUnmount(abortRequests);
</script>

<template>
  <el-tabs
    v-if="enabled && auth.authenticated"
    v-model="activeTab"
    class="evaluator-detail-tabs"
    :class="{ 'with-divider': divider, 'showing-history': activeTab === 'history' }"
  >
    <el-tab-pane label="评估器详情" name="definition">
      <slot />
    </el-tab-pane>
    <el-tab-pane label="关联测评历史" name="history" class="history-pane" lazy>
      <div v-if="initialized" class="history-content">
        <p v-if="!version" role="status">评估器尚未发布，暂无关联测评任务。</p>
        <template v-else>
          <div class="history-toolbar">
            <label>
              发布版本
              <select v-model="version" :disabled="versionsLoading" @change="selectVersion">
                <option v-for="published in versions" :key="published" :value="published">
                  V{{ published }}
                </option>
              </select>
            </label>
            <p v-if="versionsError" role="alert" class="asset-error">
              无法读取其他发布版本。
              <button type="button" class="asset-link" @click="loadVersions">重试读取版本</button>
            </p>
          </div>
          <p v-if="loading" role="status">正在读取关联测评任务…</p>
          <p v-else-if="error" role="alert" class="asset-error">
            无法读取关联测评任务。
            <button type="button" class="asset-link" @click="loadPage">重试读取任务</button>
          </p>
          <p v-else-if="!page?.items.length" role="status">当前版本暂无关联测评任务</p>
          <div v-else class="history-scroll" role="region" aria-label="关联测评任务" tabindex="0">
            <table class="history-table" aria-label="关联测评任务">
              <thead>
                <tr>
                  <th scope="col">任务名称</th>
                  <th scope="col">所用版本</th>
                  <th scope="col">状态</th>
                  <th scope="col">创建时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="task in page.items"
                  :key="task.task_id === null ? 'run:' + task.run_id : 'task:' + task.task_id"
                >
                  <th scope="row">
                    {{ task.name }}
                    <small>{{ taskKinds[task.kind] }}</small>
                  </th>
                  <td>
                    <span class="asset-chip">V{{ task.evaluator_version }}</span>
                  </td>
                  <td>
                    <span class="asset-chip" :class="{ preview: task.status === 'failed' }">
                      {{ statusLabel(task.status) }}
                    </span>
                  </td>
                  <td>
                    <time :datetime="task.created_at">{{ creationTime(task.created_at) }}</time>
                  </td>
                  <td>
                    <RouterLink
                      class="asset-link"
                      :to="'/' + taskPath(task)"
                      :aria-label="'查看任务 ' + task.name"
                      >查看任务</RouterLink
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="history-pagination">
            <span aria-live="polite">第 {{ cursors.length }} 页</span>
            <button
              type="button"
              class="asset-secondary"
              :disabled="loading || cursors.length === 1"
              @click="previousPage"
            >
              上一页
            </button>
            <button
              type="button"
              class="asset-secondary"
              :disabled="loading || !page?.next_cursor"
              @click="nextPage"
            >
              下一页
            </button>
          </div>
        </template>
      </div>
    </el-tab-pane>
  </el-tabs>
  <slot v-else />
</template>

<style scoped>
.evaluator-detail-tabs {
  min-width: 0;
}
.evaluator-detail-tabs > :deep(.el-tabs__header .el-tabs__nav-wrap) {
  margin-bottom: 0;
}
.evaluator-detail-tabs.with-divider > :deep(.el-tabs__header .el-tabs__nav-wrap) {
  padding-bottom: 8px;
}
.evaluator-detail-tabs:not(.with-divider) > :deep(.el-tabs__header .el-tabs__nav-wrap::after),
.evaluator-detail-tabs > :deep(.el-tabs__header .el-tabs__active-bar) {
  display: none;
}
.evaluator-detail-tabs > :deep(.el-tabs__header .el-tabs__nav) {
  display: flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-light);
}
.evaluator-detail-tabs > :deep(.el-tabs__header .el-tabs__item) {
  height: 34px;
  padding: 0 clamp(10px, 2vw, 16px);
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--el-text-color-regular);
}
.evaluator-detail-tabs > :deep(.el-tabs__header .el-tabs__item.is-active) {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  font-weight: 600;
}
.history-content {
  padding-block: 4px 8px;
}
.history-toolbar,
.history-pagination {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
}
.history-toolbar label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.history-toolbar select {
  width: auto;
  min-width: 88px;
}
.history-scroll {
  max-height: 50vh;
  overflow: auto;
  border: 1px solid #e9edf5;
  border-radius: 8px;
}
.history-table {
  width: 100%;
  min-width: 570px;
  border-collapse: collapse;
  text-align: left;
}
.history-table th,
.history-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #e9edf5;
}
.history-table thead th {
  position: sticky;
  top: 0;
  background: #f7f9fb;
}
.history-table tbody th {
  width: 100%;
  overflow-wrap: anywhere;
}
.history-table small {
  display: block;
  font-weight: normal;
  color: #586a65;
}
.history-table td,
.history-table thead th {
  white-space: nowrap;
}
.history-pagination {
  margin-top: 14px;
}
.history-pagination span {
  margin-inline-end: auto;
}
</style>
