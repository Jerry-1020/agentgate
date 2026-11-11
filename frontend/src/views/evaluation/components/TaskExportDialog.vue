<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { useAuthStore } from '../../../stores/modules/auth';
import {
  loadTaskExport,
  checkExportCancelled,
  type TaskExportRequest,
  type TaskExportData,
  type TaskExportKind,
} from '../utils/task-export-data';
import {
  taskExportExcel,
  taskExportFilename,
  taskExportTable,
  taskExportOptions,
} from '../utils/task-export';
const props = defineProps<{
  request: Omit<TaskExportRequest, 'kind'>;
}>();
const emit = defineEmits<{ close: [] }>();
const auth = useAuthStore();
const kind = computed<TaskExportKind>(() =>
  props.request.runIds.length === 2 ? 'ab_items' : 'full',
);
const selected = computed(() => taskExportOptions.find((o) => o.value === kind.value)!);
const busy = ref(false),
  progress = ref(''),
  error = ref('');
const prepared = shallowRef<TaskExportData | null>(null);
const table = computed(() => (prepared.value ? taskExportTable(prepared.value) : null));
const previewRows = computed(() => table.value?.rows.slice(0, 5) ?? []);
let controller: AbortController | undefined;
function close() {
  controller?.abort();
  emit('close');
}
function cancel() {
  controller?.abort();
}
watch(
  () => [
    auth.loginMode,
    auth.token,
    auth.teamId,
    auth.userId,
    auth.platformReady,
    props.request.runIds.join('|'),
    props.request.taskId,
  ],
  close,
);
onMounted(() => prepare(false));
onBeforeUnmount(() => controller?.abort());
async function prepare(download: boolean) {
  if (busy.value) return;
  const active = new AbortController();
  controller = active;
  busy.value = true;
  error.value = '';
  try {
    const data =
      prepared.value ??
      (await loadTaskExport(
        {
          ...props.request,
          kind: kind.value,
        },
        active.signal,
        (v) => {
          if (!active.signal.aborted) progress.value = v;
        },
      ));
    checkExportCancelled(active.signal);
    prepared.value = data;
    const result = taskExportTable(data);
    if (!result.rows.length) {
      error.value =
        kind.value.startsWith('ab_') && !data.runs.every((r) => r.report)
          ? '两侧尚未都形成最终报告，请进入实验 A 或实验 B 导出已有结果。'
          : '当前任务没有可导出的结果。';
      return;
    }
    if (download) {
      progress.value = '正在生成 Excel…';
      const file = await taskExportExcel(data);
      checkExportCancelled(active.signal);
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url;
      link.download = taskExportFilename(data);
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (e) {
    error.value = active.signal.aborted
      ? '已取消导出。'
      : e instanceof Error
        ? e.message
        : '导出失败，请重试。';
    active.abort();
  } finally {
    busy.value = false;
    progress.value = '';
  }
}
const cellText = (value: unknown, column = '') =>
  value == null || (typeof value === 'string' && !value.trim())
    ? '-'
    : typeof value === 'number' && /得分|分数/.test(column)
      ? value.toFixed(1)
      : String(value);
</script>
<template>
  <el-dialog
    :model-value="true"
    title="导出 Excel"
    width="960px"
    :close-on-click-modal="false"
    @close="close"
  >
    <p v-if="busy" role="status">{{ progress }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <section v-if="table && table.rows.length" class="export-preview">
      <h3>
        {{ selected.label }}预览
        <small>共 {{ table.rows.length }} 行 · {{ table.columns.length }} 列，仅预览前 5 行</small>
      </h3>
      <p v-if="prepared?.runs.some((r) => r.warnings.length)" class="notice warn">
        部分证据未取得，缺失说明已写入对应行；关闭弹窗后重新导出可重试。
      </p>
      <div class="preview-scroll" tabindex="0" aria-label="Excel 内容预览，可横向滚动查看列">
        <table aria-label="Excel 内容预览">
          <thead>
            <tr>
              <th v-for="column in table.columns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in previewRows" :key="index">
              <td v-for="column in table.columns" :key="column">
                <span class="preview-cell" :title="cellText(row[column], column)">{{
                  cellText(row[column], column)
                }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <template #footer>
      <button v-if="busy" class="secondary" @click="cancel">取消导出</button
      ><button v-else class="secondary" @click="close">关闭</button>
      <button class="primary" :disabled="busy" @click="prepare(true)">
        {{ busy ? '正在读取…' : '开始导出' }}
      </button>
    </template>
  </el-dialog>
</template>
<style scoped>
.export-preview h3 {
  font-size: 15px;
  margin: 16px 0 10px;
}
.export-preview h3 small {
  color: #64748b;
  font-weight: normal;
  margin-left: 8px;
}
.preview-scroll {
  max-height: 340px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
table {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  font-size: 12px;
}
th,
td {
  border-bottom: 1px solid #e2e8f0;
  padding: 10px;
  text-align: left;
  vertical-align: top;
  min-width: 70px;
  max-width: 250px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
th {
  position: sticky;
  top: 0;
  background: #f6f8fa;
  white-space: nowrap;
}
td {
  height: 32px;
  padding: 6px 10px;
}
.preview-cell {
  display: block;
  max-width: 250px;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
button + button {
  margin-left: 8px;
}
</style>
