<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { request, type EvaluationRun } from '../../../api/evaluations';
import { useAuthStore } from '../../../stores/modules/auth';
import EvaluationTaskForm, { type RerunConfiguration } from './EvaluationTaskForm.vue';
const props = defineProps<{ id: string; taskId?: string }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();
interface SourceTask {
  id: string;
  name?: string | null;
  kind: 'single' | 'ab' | 'stability';
  run_ids: string[];
  previous_run_ids?: string[];
  static_report_ids: string[];
}
const configuration = ref<RerunConfiguration | null>(null);
const error = ref('');
let sequence = 0;
const auth = useAuthStore();
watch(
  () => [auth.loginMode, auth.token, auth.teamId, auth.userId],
  () => {
    sequence++;
    emit('close');
  },
);
onBeforeUnmount(() => sequence++);
async function load() {
  const ticket = ++sequence;
  error.value = '';
  try {
    const task = props.taskId
      ? await request<SourceTask>('/evaluation-tasks/' + encodeURIComponent(props.taskId))
      : (await request<SourceTask[]>('/evaluation-tasks')).find(
          (item) => item.run_ids.includes(props.id) || item.previous_run_ids?.includes(props.id),
        );
    if (ticket !== sequence) return;
    if (task?.kind === 'stability') throw Error('请从单任务或 A/B 试验发起重跑。');
    const ids = task?.kind === 'ab' ? task.run_ids : [props.id];
    if (task?.kind === 'ab' && ids.length !== 2) throw Error('原 A/B 试验的两侧运行记录不完整。');
    const manifests = await Promise.all(
      ids.map((id) =>
        request<EvaluationRun['manifest']>('/runs/' + encodeURIComponent(id) + '/manifest'),
      ),
    );
    if (ticket !== sequence) return;
    const staticReports = await Promise.all(
      (task?.static_report_ids ?? []).map(async (id) => {
        const detail = await request<{
          report: {
            target_ref: { external_version_id: string };
            target_descriptor_sha256: string;
          };
        }>('/skill-analysis/reports/' + encodeURIComponent(id));
        return {
          reportId: id,
          version: detail.report.target_ref.external_version_id,
          descriptorHash: detail.report.target_descriptor_sha256,
        };
      }),
    );
    if (ticket !== sequence) return;
    const name = task?.name || manifests[0].target.display_name || '测评任务';
    configuration.value = {
      name: Array.from(name).slice(0, 125).join('') + '_重跑',
      kind: task?.kind === 'ab' ? 'ab' : 'single',
      baseline: manifests[0],
      candidate: manifests[1],
      staticReports,
    };
  } catch {
    if (ticket === sequence)
      error.value = '无法读取原任务的完整配置，请检查访问权限和运行记录后重试。';
  }
}
onMounted(() => void load());
</script>
<template>
  <EvaluationTaskForm
    v-if="configuration"
    :rerun="configuration"
    @close="emit('close')"
    @created="emit('created', $event.id)"
  />
  <el-dialog
    v-else
    :model-value="true"
    title="读取重跑任务配置"
    width="min(800px,96vw)"
    :close-on-click-modal="false"
    @close="emit('close')"
  >
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else role="status">正在读取原任务配置…</p>
    <template #footer>
      <button class="secondary" @click="emit('close')">取消</button>
      <button v-if="error" class="primary" @click="load">重试</button>
    </template>
  </el-dialog>
</template>
