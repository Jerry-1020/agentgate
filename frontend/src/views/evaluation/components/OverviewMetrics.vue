<script setup lang="ts">
import { score } from '../../../api/evaluations';
import type { OverviewSummary } from '../../../api/evaluation-summaries';
defineProps<{ data: OverviewSummary | null; error: string }>();
const emit = defineEmits<{ retry: [] }>();
</script>
<template>
  <section aria-label="总览统计">
    <p v-if="error" role="alert">
      {{ error }} <button class="link" @click="emit('retry')">重试</button>
    </p>
    <div class="overview-metrics">
      <article class="card">
        <div class="metric-label">测评任务总数</div>
        <div class="metric-value">{{ data?.task_count ?? '—' }}</div>
        <small>所选区间内创建的任务</small>
      </article>
      <article class="card">
        <div class="metric-label">平均综合分</div>
        <div class="metric-value">{{ score(data?.average_score) }}<small> / 100</small></div>
        <small>{{ data?.scored_run_count ?? '—' }} 次已完成且有有效评分的执行</small>
      </article>
      <article class="card">
        <div class="metric-label">测评完成样本数</div>
        <div class="metric-value">{{ data?.completed_sample_count ?? '—' }}</div>
        <small>已完成任务的执行用例数，重跑单独计数</small>
      </article>
      <article class="card">
        <div class="metric-label">测评集样本</div>
        <div class="metric-value">{{ data?.dataset_sample_count ?? '—' }}</div>
        <small>当前 {{ data?.dataset_count ?? '—' }} 个未归档集的最新发布样本，不随时间筛选</small>
      </article>
    </div>
  </section>
</template>
<style scoped>
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
small {
  color: #64748b;
  font-size: 12px;
}
.metric-value {
  margin: 12px 0;
}
@media (max-width: 1300px) {
  .overview-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .overview-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
