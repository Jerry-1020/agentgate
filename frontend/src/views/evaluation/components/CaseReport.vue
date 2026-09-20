<script setup lang="ts">
import { computed, ref } from 'vue';
import type { EvaluationCase } from '../../datasets/types/index';
import type { EvaluationResult, Trace } from '../../../api/client';
import { pretty } from '../../../api/evaluations';
import ResultEvaluationCard from './ResultEvaluationCard.vue';
import { needsAttention, sameJson } from '../utils/report-presentation';

const props = defineProps<{
  sample: EvaluationCase;
  results: EvaluationResult[];
  primaryIds: string[];
  hideAnalyze?: boolean;
  trace: Trace | null;
  traceError: string;
  traceLoading: boolean;
  complete: boolean;
}>();
defineEmits<{ analyze: [] }>();
const tab = ref('evidence');
const attention = computed(() => props.results.filter(needsAttention));
const passed = computed(() => props.results.filter((result) => result.outcome === 'pass'));
const inapplicable = computed(() =>
  props.results.filter((result) => result.outcome === 'not_applicable'),
);
const traceTurn = (id: string) => props.trace?.turn_outcomes?.[id];
const inputStatus = (id: string, input: unknown) => {
  if (props.traceLoading) return 'loading';
  if (props.traceError) return 'error';
  const actual = traceTurn(id)?.input;
  return actual === undefined ? 'missing' : sameJson(input, actual) ? 'same' : 'different';
};
</script>

<template>
  <section class="card case-report-detail" data-testid="case-report">
    <header class="case-report-heading">
      <div>
        <h2 class="section-title">{{ sample.name }}</h2>
        <span class="muted case-id">{{ sample.id }}</span>
      </div>
      <button v-if="complete && !hideAnalyze" class="secondary" @click="$emit('analyze')">
        查看调优分析
      </button>
    </header>
    <section class="case-evaluations" aria-label="当前样本评估明细">
      <h3>评估明细</h3>
      <p class="evaluation-counts" data-testid="evaluation-counts">
        <strong v-if="attention.length" class="attention-count"
          >需处理 {{ attention.length }} 项</strong
        >
        <span v-else>{{ complete ? '无待处理评估项' : '暂未返回待处理评估项' }}</span>
        <span>通过 {{ passed.length }} 项</span><span>不适用 {{ inapplicable.length }} 项</span>
      </p>
      <p v-if="!complete" class="muted">尚未生成完整报告，以下为已返回结果。</p>
      <p v-else-if="!results.length" class="muted">未返回评估明细，请核对任务的评估器配置。</p>
      <p v-else-if="inapplicable.length === results.length" class="muted">
        本样本没有适用检查，不能据此判断通过。
      </p>
      <ResultEvaluationCard
        v-for="result in attention"
        :key="result.evaluator_id"
        :result="result"
        :primary="primaryIds.includes(result.evaluator_id)"
        :turns="sample.turns"
      />
      <details v-if="passed.length" class="result-group" data-testid="passed-results">
        <summary>已通过的评估项（{{ passed.length }}）</summary>
        <ResultEvaluationCard
          v-for="result in passed"
          :key="result.evaluator_id"
          :result="result"
          :primary="primaryIds.includes(result.evaluator_id)"
          :turns="sample.turns"
        />
      </details>
      <details v-if="inapplicable.length" class="result-group" data-testid="inapplicable-results">
        <summary>不适用的评估项（{{ inapplicable.length }}）</summary>
        <p class="muted">未参与本样本评分，不等于通过或失败。</p>
        <ResultEvaluationCard
          v-for="result in inapplicable"
          :key="result.evaluator_id"
          :result="result"
          :primary="primaryIds.includes(result.evaluator_id)"
          :turns="sample.turns"
        />
      </details>
    </section>
    <div class="tabs" role="tablist" aria-label="执行证据">
      <button
        id="case-io-tab"
        role="tab"
        :aria-selected="tab === 'evidence'"
        aria-controls="case-io"
        :class="['tab', { active: tab === 'evidence' }]"
        @click="tab = 'evidence'"
      >
        输入与输出
      </button>
      <button
        id="case-trace-tab"
        role="tab"
        :aria-selected="tab === 'trace'"
        aria-controls="case-trace"
        :class="['tab', { active: tab === 'trace' }]"
        @click="tab = 'trace'"
      >
        执行 Trace
      </button>
    </div>
    <div v-if="traceError" class="notice error" role="alert">
      执行证据读取失败：{{ traceError }}
    </div>
    <section v-if="tab === 'evidence'" id="case-io" role="tabpanel" aria-labelledby="case-io-tab">
      <article v-for="(turn, index) in sample.turns" :key="turn.id" class="turn-evidence">
        <h3>第 {{ index + 1 }} 轮</h3>
        <div class="io-grid">
          <section>
            <header class="io-header">
              <h4>{{ inputStatus(turn.id, turn.input) === 'same' ? '输入' : '用例输入' }}</h4>
              <p
                v-if="inputStatus(turn.id, turn.input) === 'same'"
                class="muted input-note"
                data-testid="input-match"
              >
                与实际执行输入一致
              </p>
              <p
                v-else-if="inputStatus(turn.id, turn.input) === 'loading'"
                class="muted input-note"
              >
                正在读取执行输入…
              </p>
              <p
                v-else-if="inputStatus(turn.id, turn.input) === 'missing'"
                class="muted input-note"
              >
                未记录实际输入，无法比对。
              </p>
            </header>
            <div class="io-body">
              <pre data-testid="sample-input">{{ pretty(turn.input) }}</pre>
              <template v-if="inputStatus(turn.id, turn.input) === 'different'">
                <h4>实际执行输入</h4>
                <p class="input-note attention-count">与用例输入不同</p>
                <pre data-testid="actual-input">{{ pretty(traceTurn(turn.id)?.input) }}</pre>
              </template>
            </div>
          </section>
          <section>
            <header class="io-header">
              <h4>智能体实际输出</h4>
              <p v-if="traceLoading" class="muted input-note">正在读取输出…</p>
              <p v-else-if="traceError" class="muted input-note">输出读取失败</p>
              <p v-else class="muted input-note">来自本轮执行 Trace</p>
            </header>
            <div class="io-body">
              <pre v-if="!traceLoading && !traceError" data-testid="actual-output">{{
                pretty(traceTurn(turn.id)?.output) ?? '未记录输出'
              }}</pre>
            </div>
          </section>
        </div>
        <details class="secondary-evidence">
          <summary>执行状态与用例期望</summary>
          <h4>实际执行状态</h4>
          <pre>{{
            traceLoading
              ? '正在读取…'
              : traceError
                ? '执行状态读取失败'
                : (pretty(traceTurn(turn.id)?.state) ?? '未记录状态')
          }}</pre>
          <h4>用例期望条件</h4>
          <pre>{{ pretty(turn.expectations) }}</pre>
        </details>
      </article>
    </section>
    <section v-else id="case-trace" role="tabpanel" aria-labelledby="case-trace-tab">
      <pre>{{
        trace ? pretty(trace) : traceLoading ? '正在读取 Trace…' : '未取得 Trace 记录'
      }}</pre>
    </section>
  </section>
</template>

<style scoped>
.case-report-detail {
  min-width: 0;
}
.case-report-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: start;
  margin-bottom: 24px;
}
.case-report-heading h2 {
  margin: 0 0 8px;
}
.case-id {
  font-size: 12px;
  overflow-wrap: anywhere;
}
.case-report-heading button {
  flex-shrink: 0;
}
.case-evaluations > h3 {
  margin: 0 0 12px;
}
.evaluation-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #6b7280;
  margin: 0 0 16px;
}
.attention-count {
  color: #b42318;
}
.result-group {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px;
  font-size: 13px;
}
.result-group > summary,
.secondary-evidence > summary {
  color: #596473;
}
.case-report-detail > .tabs {
  margin-top: 24px;
}
.turn-evidence {
  padding: 12px 0;
  border-bottom: 1px solid #edf0f3;
}
.turn-evidence > h3 {
  margin: 0 0 12px;
}
.io-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.io-grid > section {
  min-width: 0;
  display: grid;
  grid-template-rows: subgrid;
  grid-row: span 2;
  align-content: start;
}
.io-header {
  min-width: 0;
}
.io-grid h4 {
  margin: 0 0 8px;
}
.input-note {
  font-size: 12px;
  margin: 8px 0;
}
.io-grid pre {
  margin: 8px 0;
  max-height: 280px;
}
.secondary-evidence {
  font-size: 12px;
}
@media (max-width: 1000px) {
  .io-grid {
    grid-template-columns: 1fr;
  }
  .io-grid > section {
    display: block;
    grid-row: auto;
  }
  .case-report-heading {
    flex-wrap: wrap;
  }
}
</style>
