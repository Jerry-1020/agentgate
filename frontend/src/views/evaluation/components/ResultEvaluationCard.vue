<script setup lang="ts">
import { computed } from 'vue';
import type { EvaluationResult } from '../../../api/client';
import { metricLabel, pretty, score, statusLabel } from '../../../api/evaluations';
import {
  equalsCondition,
  llmCheckDetails,
  llmScoringBasis,
  needsAttention,
} from '../utils/report-presentation';
import type { EvaluatorSnapshot, WeightedChildResult } from '../utils/task-report';

const props = defineProps<{
  result: EvaluationResult;
  primary: boolean;
  turns: { id: string }[];
  childResults?: WeightedChildResult[];
  evaluatorSpecs?: EvaluatorSnapshot[];
  subEvaluator?: boolean;
  weight?: number | null;
}>();
const checks = computed(() =>
  [...props.result.checks].sort((a, b) => Number(needsAttention(b)) - Number(needsAttention(a))),
);
const isLlm = computed(() => ['llm_judge', 'llm_group'].includes(props.result.evaluator_kind));
const scoringBasis = computed(() => llmScoringBasis(props.result, props.evaluatorSpecs));
const llmChecks = computed(() =>
  checks.value.map((check) => ({ check, ...llmCheckDetails(check) })),
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
        <h4>
          {{
            subEvaluator || result.evaluator_kind === 'llm_group'
              ? result.evaluator_name
              : metricLabel(result.metric)
          }}
        </h4>
        <p class="muted evaluator-reference">
          {{ result.evaluator_name }} ·
          {{ result.evaluator_version ? 'v' + result.evaluator_version : '版本未记录'
          }}<span v-if="subEvaluator">
            · 子评估器<span v-if="weight != null">
              · 权重 {{ Number((weight * 100).toFixed(2)) }}%</span
            ></span
          ><span v-else-if="!primary"> · 辅助评估项</span>
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
        <small
          v-if="!isLlm && result.score != null && result.outcome !== 'not_applicable'"
          class="muted"
          >{{ result.evaluator_kind === 'llm_group' ? '综合得分' : '本评估器' }}
          {{ score(result.score) }} / 100</small
        >
      </div>
    </header>
    <div v-if="isLlm" :key="result.id ?? result.case_id" class="llm-assessment">
      <details class="llm-basis" aria-label="评分依据">
        <summary class="llm-summary">
          <span class="llm-summary-title" role="heading" aria-level="5">
            <span class="disclosure-triangle" aria-hidden="true"></span>
            评分依据
          </span>
          <span class="muted basis-source">来源：本次任务保存的评估器配置</span>
          <span class="passing-score">
            <b>通过分数：</b>
            <template v-if="scoringBasis.passThreshold !== null">
              {{ score(scoringBasis.passThreshold) }} / 100
              <span v-if="scoringBasis.usesDefaultThreshold" class="muted">（默认）</span>
            </template>
            <span v-else class="muted">本次任务未记录</span>
          </span>
        </summary>
        <p v-if="scoringBasis.minConfidence" class="muted">
          置信度低于 {{ score(scoringBasis.minConfidence) }}% 时需要人工复核。
        </p>
        <p v-if="scoringBasis.instruction" class="criterion-text">{{ scoringBasis.instruction }}</p>
        <p v-if="scoringBasis.combination">{{ scoringBasis.combination }}</p>
        <dl v-if="scoringBasis.criteria.length" class="scoring-criteria">
          <template v-for="(criterion, index) in scoringBasis.criteria" :key="index">
            <dt>
              {{ criterion.name }}
              <span v-if="criterion.weight !== null" class="muted">
                · 权重 {{ criterion.weight }}%</span
              >
            </dt>
            <dd class="criterion-text">{{ criterion.description }}</dd>
          </template>
        </dl>
        <p v-else-if="!scoringBasis.instruction && !scoringBasis.combination" class="muted">
          本次任务未保存评分标准，无法展示。
        </p>
      </details>
      <details class="llm-conclusion" aria-label="评估结论">
        <summary class="llm-summary">
          <span class="llm-summary-title" role="heading" aria-level="5">
            <span class="disclosure-triangle" aria-hidden="true"></span>
            评估结论
          </span>
          <span class="conclusion-summary">
            <span
              ><b>得分：</b
              >{{ result.score === null ? '未评分' : score(result.score) + ' / 100' }}</span
            >
            <span
              ><b>结果：</b
              ><span :class="['check-outcome', result.outcome]">{{
                statusLabel(result.outcome)
              }}</span></span
            >
          </span>
        </summary>
        <p class="criterion-text"><b>原因：</b>{{ result.reason || '未返回评估原因' }}</p>
        <div
          v-for="item in llmChecks"
          :key="item.check.id"
          class="llm-check"
          :data-check="item.check.id"
        >
          <h6 v-if="llmChecks.length > 1">
            {{ item.check.name }} · {{ turnLabel(item.check.turn_id) }} ·
            {{ statusLabel(item.check.outcome) }}
          </h6>
          <p v-if="item.check.reason && item.check.reason !== result.reason" class="criterion-text">
            {{ item.check.reason }}
          </p>
          <p v-if="item.check.actual_missing" class="missing-evidence">评估证据缺失</p>
          <p v-if="item.confidence !== null" class="muted">
            评估置信度：{{ score(item.confidence) }}%
          </p>
          <template v-if="item.violations.length">
            <h6>具体问题</h6>
            <ul class="evaluation-issues">
              <li v-for="(violation, index) in item.violations" :key="index">
                <b v-if="violation.criterion">{{ violation.criterion }}：</b>{{ violation.detail }}
              </li>
            </ul>
          </template>
          <dl v-if="item.dimensions.length" class="scoring-criteria">
            <template v-for="(dimension, index) in item.dimensions" :key="index">
              <dt>
                {{ dimension.name }} ·
                {{ dimension.score === null ? '未评分' : score(dimension.score) + ' / 100'
                }}<span v-if="dimension.review" class="check-outcome review"> · 待复核</span>
              </dt>
              <dd class="criterion-text">{{ dimension.reason || '未返回评估原因' }}</dd>
            </template>
          </dl>
        </div>
      </details>
    </div>
    <p v-if="!isLlm && (!checks.length || result.outcome === 'error')" class="result-reason">
      {{ result.reason || '未返回检查明细' }}
    </p>
    <section v-if="childResults?.length" class="child-results" aria-label="子评估器结果">
      <h5>子评估器结果</h5>
      <ResultEvaluationCard
        v-for="child in childResults"
        :key="child.result.evaluator_id"
        :result="child.result"
        :primary="false"
        :sub-evaluator="true"
        :weight="child.weight"
        :turns="turns"
        :evaluator-specs="evaluatorSpecs"
      />
    </section>
    <p v-if="!isLlm && subEvaluator && checks.length" class="result-reason">
      {{ checks.map((c) => c.reason).join('；') }}
    </p>
    <div v-if="checks.length && !isLlm" class="check-table-wrap">
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
.llm-assessment {
  display: grid;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.llm-basis,
.llm-conclusion {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.llm-basis {
  background: #f8fafb;
}
.llm-summary {
  display: block;
  list-style: none;
  color: inherit;
  cursor: pointer;
}
.llm-summary::-webkit-details-marker {
  display: none;
}
.llm-summary:focus-visible {
  outline: 2px solid #007f69;
  outline-offset: 4px;
}
.llm-summary-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.disclosure-triangle {
  display: inline-block;
  width: 0;
  height: 0;
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 6px solid #007f69;
}
details[open] > .llm-summary .disclosure-triangle {
  transform: rotate(90deg);
}
.llm-assessment h6 {
  margin: 10px 0 4px;
  font-size: 13px;
}
.llm-assessment p {
  margin: 6px 0;
}
.basis-source {
  font-size: 12px;
}
.basis-source,
.passing-score {
  display: block;
  margin: 6px 0;
}
.scoring-criteria {
  margin: 10px 0 0;
}
.scoring-criteria dt {
  font-weight: 600;
}
.scoring-criteria dd {
  margin: 2px 0 10px;
}
.scoring-criteria dd:last-child {
  margin-bottom: 0;
}
.criterion-text,
.evaluation-issues {
  white-space: pre-wrap;
}
.conclusion-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 24px;
}
.evaluation-issues {
  margin: 0;
  padding-left: 20px;
}
.evaluation-issues li + li {
  margin-top: 6px;
}
.child-results {
  margin: 12px 0;
  padding-left: 16px;
  border-left: 3px solid var(--el-color-primary-light-7);
}
.child-results h5 {
  margin: 0 0 8px;
  font-size: 14px;
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
