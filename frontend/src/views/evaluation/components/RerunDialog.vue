<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { request, type Report } from '../../../api/evaluations';
import RunConfiguration from './RunConfiguration.vue';
const props = defineProps<{ id: string; taskId?: string }>(),
  emit = defineEmits<{ close: []; created: [id: string] }>();
const report = ref<{ manifest: Report['run']['manifest'] } | null>(null),
  busy = ref(false),
  error = ref('');
const taskId = ref(props.taskId ?? '');
onMounted(async () => {
  try {
    if (!taskId.value) {
      const tasks = await request<{ id: string; kind: string; run_ids: string[] }[]>('/evaluation-tasks');
      const task = tasks.find(t => t.kind === 'single' && t.run_ids[0] === props.id);
      if (!task) throw Error('当前运行没有可重跑的单任务关联。');
      taskId.value = task.id;
    }
    report.value = {
      manifest: await request<Report['run']['manifest']>(
        '/runs/' + encodeURIComponent(props.id) + '/manifest',
      ),
    };
  } catch (e) {
    error.value = String(e);
  }
});
async function submit() {
  if (busy.value || !report.value || !taskId.value) return;
  busy.value = true;
  error.value = '';
  try {
    const r = await request<{ id: string; run_ids: string[] }>(
      '/evaluation-tasks/' + encodeURIComponent(taskId.value) + '/rerun',
      'POST',
      { source_run_id: props.id },
    );
    emit('created', r.id);
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
    title="重新运行当前任务"
    width="min(860px,94vw)"
    :close-on-click-modal="false"
    :before-close="
      () => {
        if (!busy) emit('close');
      }
    "
    ><p>将该任务按照原始配置重新运行一次，该任务原始运行结果保留。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <RunConfiguration v-if="report" :manifest="report.manifest" />
    <p v-else>正在读取任务配置…</p>
    <template #footer
      ><button class="secondary" :disabled="busy" @click="emit('close')">取消</button
      ><button class="primary" :disabled="busy || !report" @click="submit">
        开始测评
      </button></template
    ></el-dialog
  >
</template>
