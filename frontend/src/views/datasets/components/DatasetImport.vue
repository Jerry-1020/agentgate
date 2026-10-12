<script setup lang="ts">
import { ref } from 'vue';
import { httpRequest, ApiError } from '../../../utils/request';
const emit = defineEmits<{ imported: [id: string] }>();
const format = ref('xlsx'),
  name = ref(''),
  file = ref<File | null>(null),
  busy = ref(false),
  error = ref(''),
  issues = ref<{ sheet: string; row: number | null; column: string | null; message: string }[]>([]);
async function submit() {
  error.value = '';
  issues.value = [];
  if (!file.value || (format.value === 'xlsx' && !name.value.trim())) {
    error.value = '请选择文件并填写测评集名称。';
    return;
  }
  busy.value = true;
  try {
    let data: { dataset: { id: string } };
    if (format.value === 'xlsx') {
      const body = new FormData();
      body.append('file', file.value);
      body.append('name', name.value.trim());
      data = await httpRequest<{ dataset: { id: string } }>('/api/datasets/import/xlsx', {
        method: 'POST',
        data: body,
      });
    } else {
      JSON.parse(await file.value.text());
      data = await httpRequest<{ dataset: { id: string } }>('/api/datasets/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        data: await file.value.text(),
      });
    }
    emit('imported', data.dataset.id);
  } catch (e) {
    if (e instanceof ApiError && e.detail && typeof e.detail === 'object' && 'issues' in e.detail)
      issues.value = (e.detail as { issues: typeof issues.value }).issues;
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="field">
    <label
      >文件格式<select
        class="input"
        v-model="format"
        @change="
          file = null;
          error = '';
          issues = [];
        "
      >
        <option value="xlsx">Excel（.xlsx）</option>
        <option value="json">JSON</option>
      </select></label
    ><label v-if="format === 'xlsx'"
      >测评集名称<input class="input" aria-label="导入测评集名称" v-model="name" /></label
    ><small v-if="format === 'xlsx'"
      >工作表 Cases，每行一轮。case_id、case_name、input_json 必填；输入及期望采用 JSON，category
      可填 positive / negative /
      boundary。导入结果以服务端返回的版本状态为准。行内自有格式需先确认字段映射，可从现有版本导出
      Excel 作为格式参考。</small
    ><input
      :key="format"
      type="file"
      aria-label="导入文件"
      :accept="format === 'xlsx' ? '.xlsx' : '.json'"
      @change="file = ($event.target as HTMLInputElement).files?.[0] ?? null"
    />
    <p v-if="error" role="alert">{{ error }}</p>
    <table v-if="issues.length" class="data-table">
      <thead>
        <tr>
          <th>工作表</th>
          <th>行</th>
          <th>字段</th>
          <th>问题</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(issue, i) in issues" :key="i">
          <td>{{ issue.sheet }}</td>
          <td>{{ issue.row ?? '—' }}</td>
          <td>{{ issue.column ?? '—' }}</td>
          <td>{{ issue.message }}</td>
        </tr>
      </tbody>
    </table>
    <button class="primary" :disabled="busy" @click="submit">
      {{ busy ? '正在导入…' : '确认导入' }}
    </button>
  </div>
</template>
