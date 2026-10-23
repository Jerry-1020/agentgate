<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import { request, score, statusLabel, type RunProgress } from '../../../api/evaluations';
const props = defineProps<{ id?: string }>(),
  emit = defineEmits<{ navigate: [path: string] }>();
type Experiment = { id: string; run_ids: string[]; created_at: string };
type Summary = {
  experiment: Experiment;
  runs: { progress: RunProgress; score: number | null; outcome: string | null }[];
  measured_runs: number;
  mean: number | null;
  sample_variance: number | null;
  sample_stddev: number | null;
  min: number | null;
  max: number | null;
  complete: boolean;
};
const items = ref<Experiment[]>([]),
  data = ref<Summary | null>(null),
  error = ref('');
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  loadTicket = 0;
async function load() {
  clearTimeout(timer);
  if (disposed || document.hidden) return;
  const ticket = ++loadTicket;
  try {
    if (props.id) {
      const summary = await request<Summary>('/stability-experiments/' + encodeURIComponent(props.id));
      if (disposed || ticket !== loadTicket) return;
      data.value = summary;
    } else {
      const experiments = await request<Experiment[]>('/stability-experiments');
      if (disposed || ticket !== loadTicket) return;
      items.value = experiments;
    }
    error.value = '';
  } catch (e) {
    if (!disposed && ticket === loadTicket) error.value = String(e);
  } finally {
    if (!disposed && ticket === loadTicket && !document.hidden && !data.value?.complete)
      timer = setTimeout(load, 5000);
  }
}
function visibilityChanged() {
  loadTicket++;
  clearTimeout(timer);
  if (!document.hidden) void load();
}
onMounted(() => {
  document.addEventListener('visibilitychange', visibilityChanged);
  void load();
});
onUnmounted(() => {
  disposed = true;
  loadTicket++;
  clearTimeout(timer);
  document.removeEventListener('visibilitychange', visibilityChanged);
});
</script>
<template>
  <div class="page-head">
    <div>
      <button class="link" @click="emit('navigate', 'tasks')">← 返回测评任务</button>
      <h1 class="page-title">稳定性测试</h1>
      <p class="page-sub">固定智能体、测评集与评估器快照，重复执行独立任务</p>
    </div>
  </div>
  <p v-if="error" class="notice error">{{ error }}</p>
  <template v-if="data">
    <div class="notice">
      有效评分 {{ data.measured_runs }} /
      {{ data.experiment.run_ids.length }} 次。失败或没有评分的运行不按 0
      分计入。以下为描述性统计，方差不是“显著性分数”，零方差也不代表真实业务绝对稳定。
    </div>
    <div class="grid metric-grid">
      <div class="card">
        <h3>平均分</h3>
        <div class="metric-value">{{ score(data.mean) }}</div>
      </div>
      <div class="card">
        <h3>标准差（分）</h3>
        <div class="metric-value">
          {{ data.sample_stddev === null ? '—' : (data.sample_stddev * 100).toFixed(2) }}
        </div>
      </div>
      <div class="card">
        <h3>样本方差（分²）</h3>
        <div class="metric-value">
          {{ data.sample_variance === null ? '—' : (data.sample_variance * 10000).toFixed(2) }}
        </div>
      </div>
      <div class="card">
        <h3>最低 / 最高分</h3>
        <div class="metric-value">{{ score(data.min) }} / {{ score(data.max) }}</div>
      </div>
    </div>
    <div class="card">
      <table class="data-table">
        <thead>
          <tr>
            <th>轮次</th>
            <th>进度</th>
            <th>状态</th>
            <th>得分</th>
            <th>质量结论</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, index) in data.runs" :key="r.progress.run_id">
            <td>{{ index + 1 }}</td>
            <td>{{ r.progress.completed_cases }} / {{ r.progress.total_cases }}</td>
            <td>{{ statusLabel(r.progress.status) }}</td>
            <td>{{ score(r.score) }}</td>
            <td>{{ r.outcome ? statusLabel(r.outcome) : '—' }}</td>
            <td>
              <button class="link" @click="emit('navigate', 'results/' + r.progress.run_id)">
                查看样本
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
  <div v-else class="card">
    <table class="data-table">
      <thead>
        <tr>
          <th>实验 ID</th>
          <th>重复次数</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in items" :key="e.id">
          <td>{{ e.id }}</td>
          <td>{{ e.run_ids.length }}</td>
          <td>{{ new Date(e.created_at).toLocaleString() }}</td>
          <td><button class="link" @click="emit('navigate', 'stability/' + e.id)">查看</button></td>
        </tr>
      </tbody>
    </table>
    <p v-if="!items.length" class="empty">暂无记录。新建测评任务时设置重复次数即可创建。</p>
  </div>
</template>
