<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api, request, type Report } from '../../../api/evaluations';
import RunConfiguration from './RunConfiguration.vue';
const props = defineProps<{ id: string }>(),
  emit = defineEmits<{ close: []; created: [id: string] }>();
const report = ref<{ manifest: Report['run']['manifest'] } | null>(null),
  busy = ref(false),
  error = ref('');
onMounted(async () => {
  try {
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
  if (busy.value || !report.value) return;
  busy.value = true;
  error.value = '';
  try {
    const r = await request<{ run_id: string }>(
      '/runs/' + encodeURIComponent(props.id) + '/rerun',
      'POST',
    );
    emit('created', r.run_id);
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
    title="确认原配置重跑"
    width="min(860px,94vw)"
    :close-on-click-modal="false"
    :before-close="
      () => {
        if (!busy) emit('close');
      }
    "
    ><p>复用以下版本快照创建新任务，不采用最新版本。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <RunConfiguration v-if="report" :manifest="report.manifest" />
    <p v-else>正在读取任务配置…</p>
    <template #footer
      ><button class="secondary" :disabled="busy" @click="emit('close')">取消</button
      ><button class="primary" :disabled="busy || !report" @click="submit">
        确认创建新任务
      </button></template
    ></el-dialog
  >
</template>
