<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { datasetApi } from '../../../api/datasets';
import type { DatasetVersion } from '../types/index';
import { sampleExportBlob } from '../utils/sample-export';
const props = defineProps<{
  datasetId: string;
  initialVersionId?: string;
  initialIds?: string[];
}>();
const emit = defineEmits<{ close: [] }>();
const versions = ref<DatasetVersion[]>([]),
  versionId = ref(''),
  ids = ref<string[]>([]);
const scope = ref<'all' | 'selected'>('all'),
  format = ref<'json' | 'xlsx'>('xlsx');
const loading = ref(true),
  busy = ref(false),
  error = ref(''),
  name = ref('');
const version = computed(() => versions.value.find((v) => v.id === versionId.value));
watch(versionId, () => {
  ids.value = [];
  scope.value = 'all';
});
async function load() {
  try {
    const detail = await datasetApi.detail(props.datasetId);
    name.value = detail.dataset.name;
    versions.value = detail.versions;
    versionId.value =
      detail.versions.find((v) => v.id === props.initialVersionId)?.id ??
      detail.versions[0]?.id ??
      '';
    await Promise.resolve();
    if (props.initialIds?.length) {
      ids.value = props.initialIds.filter((id) => version.value?.cases.some((c) => c.id === id));
      scope.value = 'selected';
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}
void load();
async function download() {
  if (!version.value || busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    const blob = await sampleExportBlob(
      version.value,
      scope.value === 'all' ? undefined : ids.value,
      format.value,
    );
    const url = URL.createObjectURL(blob),
      link = document.createElement('a');
    link.href = url;
    link.download =
      name.value.replace(/[\\/:*?"<>|]/g, '_') +
      '-' +
      (version.value.version ? 'v' + version.value.version : '草稿') +
      '-样本.' +
      format.value;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <el-dialog
    :model-value="true"
    title="导出评测集样本"
    width="min(760px,94vw)"
    :close-on-click-modal="false"
    :before-close="() => !busy && emit('close')"
  >
    <div v-loading="loading" class="export-form">
      <h3>{{ name }}</h3>
      <label
        >选择版本<select v-model="versionId" class="input" aria-label="导出版本" :disabled="busy">
          <option v-for="v in versions" :key="v.id" :value="v.id">
            {{ v.status === 'draft' ? '当前草稿' : '已发布 v' + v.version }} ·
            {{ v.cases.length }} 条样本
          </option>
        </select></label
      >
      <div class="export-options">
        <label><input v-model="scope" type="radio" value="all" :disabled="busy" />全部样本</label
        ><label
          ><input v-model="scope" type="radio" value="selected" :disabled="busy" />选择样本</label
        ><select v-model="format" class="input" aria-label="导出格式" :disabled="busy">
          <option value="xlsx">Excel (.xlsx)</option>
          <option value="json">JSON</option>
        </select>
      </div>
      <div v-if="scope === 'selected'" class="export-samples">
        <button class="link" :disabled="busy" @click="ids = version?.cases.map((c) => c.id) ?? []">
          全选
        </button>
        <button class="link" :disabled="busy" @click="ids = []">清空</button
        ><label v-for="c in version?.cases" :key="c.id"
          ><input type="checkbox" v-model="ids" :value="c.id" :disabled="busy" />{{ c.name }}
          <small>{{ c.turns.length }} 轮</small></label
        >
      </div>
      <p>导出 {{ scope === 'all' ? (version?.cases.length ?? 0) : ids.length }} 条样本</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </div>
    <template #footer
      ><el-button :disabled="busy" @click="emit('close')">关闭</el-button
      ><el-button
        type="primary"
        :loading="busy"
        :disabled="loading || !version?.cases.length || (scope === 'selected' && !ids.length)"
        @click="download"
        >导出</el-button
      ></template
    >
  </el-dialog>
</template>
<style scoped>
.export-form > label {
  display: grid;
  gap: 8px;
}
.export-options {
  display: flex;
  gap: 24px;
  align-items: center;
  margin: 24px 0;
}
.export-options select {
  margin-left: auto;
  width: 170px;
}
.export-samples {
  max-height: 320px;
  overflow: auto;
  border: 1px solid #e1e8e6;
  border-radius: 8px;
  padding: 16px;
}
.export-samples label {
  display: flex;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #edf1f0;
}
.export-samples small {
  margin-left: auto;
  color: #81958e;
}
</style>
