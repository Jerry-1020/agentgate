<script setup lang="ts">
import { computed } from 'vue';
import type { EvaluationResult } from '../../../api/client';
import { metricLabel, pretty, score, statusLabel } from '../../../api/evaluations';
import { equalsCondition, needsAttention } from '../utils/report-presentation';

const props = defineProps<{
  result: EvaluationResult;
  primary: boolean;
  turns: { id: string }[];
}>();
const checks = computed(() =>
  [...props.result.checks].sort((a, b) => Number(needsAttention(b)) - Number(needsAttention(a))),
);
const turnLabel = (id: string | null) => {
  const index = props.turns.findIndex((turn) => turn.id === id);
  return id === null ? '用例级检查' : index < 0 ? id : '第 ' + (index + 1) + ' 轮';
};
</script>

<template>
  <article
    class="evaluation-result"
    :data-outcome="result.outcome"
    :data-evaluator="result.evaluator_id"
  >
    <header class="evaluation-heading">
      <div>
        <h4>{{ metricLabel(result.metric) }}</h4>
        <p class="muted evaluator-reference">
          {{ result.evaluator_name }} ·
          {{ result.evaluator_version ? 'v' + result.evaluator_version : '版本未记录'
          }}<span v-if="!primary"> · 辅助评估项</span>
        </p>
      </div>
      <div class="evaluation-score">
        <span
          class="badge"
          :class="
            result.outcome === 'pass'
              ? 'success'
              : result.outcome === 'not_applicable'
                ? 'neutral'
                : 'warn'
          "
          >{{ statusLabel(result.outcome) }}</span
        >
        <small v-if="result.score != null && result.outcome !== 'not_applicable'" class="muted"
          >本评估器 {{ score(result.score) }} / 100</small
        >
      </div>
    </header>
    <p v-if="!checks.length || result.outcome === 'error'" class="result-reason">
      {{ result.reason || '未返回检查明细' }}
    </p>
    <div v-if="checks.length" class="check-table-wrap">
      <table class="check-comparison">
        <thead>
          <tr>
            <th>检查项</th>
            <th>期望</th>
            <th>实际</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="check in checks" :key="check.id" :data-check="check.id">
            <td>
              <b>{{ check.name }}</b
              ><small class="muted">{{ turnLabel(check.turn_id) }}</small>
            </td>
            <td>
              <small v-if="equalsCondition(check.expected)" class="muted">等于</small>
              <pre>{{
                pretty(
                  equalsCondition(check.expected) ? check.expected.expected : check.expected,
                ) ?? '未提供'
              }}</pre>
            </td>
            <td>
              <span v-if="check.actual_missing" class="missing-evidence">证据缺失</span>
              <pre v-else>{{ pretty(check.actual) ?? '未记录' }}</pre>
            </td>
            <td>
              <span :class="['check-outcome', check.outcome]">{{
                statusLabel(check.outcome)
              }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <details class="raw-checks">
      <summary>原始评估记录</summary>
      <pre>{{ pretty(result) }}</pre>
    </details>
  </article>
</template>

<style scoped>
.evaluation-result {
  padding: 16px 0;
  border-top: 1px solid #e5e7eb;
  min-width: 0;
}
.evaluation-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: start;
}
.evaluation-heading h4 {
  font-size: 16px;
  margin: 0;
}
.evaluator-reference {
  font-size: 12px;
  margin: 6px 0 12px;
  overflow-wrap: anywhere;
}
.evaluation-score {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
.evaluation-score small {
  font-size: 12px;
}
.badge.neutral {
  background: #f3f4f6;
  color: #6b7280;
}
.check-table-wrap {
  overflow-x: auto;
}
.check-comparison {
  border-collapse: collapse;
  width: 100%;
  table-layout: fixed;
  font-size: 13px;
}
.check-comparison th {
  background: #f8fafb;
  color: #6b7280;
  font-weight: 500;
  text-align: left;
}
.check-comparison th,
.check-comparison td {
  padding: 10px;
  vertical-align: top;
  border-bottom: 1px solid #edf0f3;
  overflow-wrap: anywhere;
}
.check-comparison th:first-child {
  width: 28%;
}
.check-comparison th:last-child {
  width: 15%;
}
.check-comparison td small {
  display: block;
  margin: 4px 0;
}
.check-comparison pre {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  max-height: 150px;
  font-size: 12px;
}
.check-outcome.fail,
.check-outcome.error,
.missing-evidence {
  color: #b42318;
}
.check-outcome.pass {
  color: #00836b;
}
.check-outcome.review {
  color: #9a6700;
}
.check-outcome.not_applicable {
  color: #6b7280;
}
.raw-checks {
  font-size: 12px;
}
.raw-checks summary {
  color: #6b7280;
}
.result-reason {
  font-size: 13px;
}
@media (max-width: 768px) {
  .evaluation-heading {
    flex-wrap: wrap;
  }
  .evaluation-score {
    align-items: flex-start;
  }
  .check-comparison {
    min-width: 500px;
  }
}
</style>
