<script setup lang="ts">
import { shallowRef, computed, ref, watch } from 'vue';
import AnalysisAnnotation from './AnalysisAnnotation.vue';
import CaseReport from './CaseReport.vue';
import { api, pretty, request, type Report } from '../../../api/evaluations';
import type { EvaluationResult, Trace } from '../../../api/client';
import { readTaskLinks } from '../utils/task-links';
const props = defineProps<{ report: Report }>();
const annotations = ref<Record<string, string>>({});
watch(
  () => props.report.run.id,
  () => {
    annotations.value = {};
  },
);
const reportCase = ref('');
const trace = shallowRef<Trace | null>(null),
  traceLoading = ref(false),
  traceError = ref('');
const sample = computed(() =>
  props.report.run.manifest.dataset.cases.find((c) => c.id === reportCase.value),
);
let traceTicket = 0;
watch(
  () => props.report.run.id,
  () => {
    reportCase.value = '';
  },
);
watch(reportCase, async (id) => {
  const ticket = ++traceTicket;
  trace.value = null;
  traceError.value = '';
  traceLoading.value = !!id;
  if (!id) return;
  try {
    const value = await api.trace(props.report.run.id, id);
    if (ticket === traceTicket) trace.value = value;
  } catch (e) {
    if (ticket === traceTicket) traceError.value = String(e);
  } finally {
    if (ticket === traceTicket) traceLoading.value = false;
  }
});
const evaluatorTitle = (id: string, name: string) =>
  (
    ({
      'final-state': '最终业务状态',
      'forbidden-tool': '调用了禁用工具',
      'policy-compliance': '策略合规',
      'required-tool': '必需工具调用',
      'skill-routing': '技能路由',
      'tool-arguments': '工具参数',
      'final-output': '最终输出',
    }) as Record<string, string>
  )[id] ?? name;
const groups = computed(() => {
  const map = new Map<
    string,
    { key: string; name: string; version: string; metric: string; items: EvaluationResult[] }
  >();
  for (const result of props.report.results.filter((r) => r.outcome === 'fail')) {
    const key = result.evaluator_id + ':' + result.evaluator_version;
    const group = map.get(key) ?? {
      key,
      name: result.evaluator_name,
      version: result.evaluator_version ?? '',
      metric: result.metric,
      items: [],
    };
    group.items.push(result);
    map.set(key, group);
  }
  return [...map.values()].sort((a, b) => b.items.length - a.items.length);
});
const failed = computed(() => props.report.results.filter((r) => r.outcome === 'fail'));

const errors = computed(() => props.report.results.filter((r) => r.outcome === 'error').length);
const reviews = computed(() => props.report.results.filter((r) => r.outcome === 'review').length);
const caseName = (id: string) =>
  props.report.run.manifest.dataset.cases.find((c) => c.id === id)?.name ?? id;
const reason = (text: string) =>
  [
    ...new Set(
      text
        .split(/[；;]/)
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ].join('；');
const groupKey = ref(''),
  caseKey = ref('');
const activeGroup = computed(
  () => groups.value.find((g) => g.key === groupKey.value) ?? groups.value[0],
);
const caseIds = computed(() => [...new Set(activeGroup.value?.items.map((r) => r.case_id) ?? [])]);
const selectedCase = computed({
  get: () => (caseIds.value.includes(caseKey.value) ? caseKey.value : (caseIds.value[0] ?? '')),
  set: (v: string) => (caseKey.value = v),
});
const caseResults = computed(
  () => activeGroup.value?.items.filter((r) => r.case_id === selectedCase.value) ?? [],
);
interface Optimization {
  run_id: string;
  clusters: { id: string; members: { result_id: string }[] }[];
  hypotheses: {
    id: string;
    title: string;
    explanation: string;
    result_ids: string[];
    cluster_ids: string[];
  }[];
  suggestions: {
    id: string;
    title: string;
    recommendation: string;
    rationale: string;
    hypothesis_ids: string[];
  }[];
}
const optimization = ref<Optimization | null>(null),
  analysisLoading = ref(false),
  analysisError = ref('');
let analysisTicket = 0;
const staticReportId = computed(
  () =>
    readTaskLinks()
      .find((t) => t.runIds.includes(props.report.run.id))
      ?.staticReports.find(
        (r) => r.descriptorHash === props.report.run.manifest.target.descriptor_sha256,
      )?.reportId,
);
watch([() => props.report.run.id, staticReportId], () => {
  ++analysisTicket;
  optimization.value = null;
  analysisLoading.value = false;
  analysisError.value = '';
});
const hypotheses = computed(
  () =>
    optimization.value?.hypotheses.filter(
      (h) =>
        h.result_ids.some((id) => caseResults.value.some((r) => r.id === id)) ||
        optimization.value?.clusters.some(
          (c) =>
            h.cluster_ids.includes(c.id) &&
            c.members.some((m) => caseResults.value.some((r) => r.id === m.result_id)),
        ),
    ) ?? [],
);
const modelSuggestions = computed(
  () =>
    optimization.value?.suggestions.filter((s) =>
      s.hypothesis_ids.some((id) => hypotheses.value.some((h) => h.id === id)),
    ) ?? [],
);
async function analyze() {
  if (analysisLoading.value || optimization.value) return;
  const ticket = ++analysisTicket,
    runId = props.report.run.id;
  analysisLoading.value = true;
  analysisError.value = '';
  try {
    const query = staticReportId.value
      ? '?skill_analysis_report_id=' + encodeURIComponent(staticReportId.value)
      : '';
    const value = await request<Optimization>(
      '/runs/' + encodeURIComponent(runId) + '/optimization' + query,
      'GET',
      undefined,
      240000,
    );
    if (value.run_id !== runId) throw Error('分析报告与当前运行不一致');
    if (ticket === analysisTicket) optimization.value = value;
  } catch (e) {
    if (ticket === analysisTicket) analysisError.value = String(e);
  } finally {
    if (ticket === analysisTicket) analysisLoading.value = false;
  }
}
watch(
  () => props.report.run.id,
  () => {
    groupKey.value = '';
    caseKey.value = '';
  },
);
</script>
<template>
  <section class="card section-gap rule-analysis" aria-label="基于真实报告的规则分析">
    <h2>分析结果</h2>
    <p v-if="!failed.length">
      {{ errors || reviews ? '暂无未通过结果，请先处理异常或待复核项。' : '本次没有未通过结果。' }}
    </p>
    <div v-if="activeGroup" class="tuning-workbench">
      <nav class="tuning-evaluators" aria-label="调优评估器">
        <h3>评估器</h3>
        <button
          v-for="group in groups"
          :key="group.key"
          class="evaluator-option"
          :class="{ selected: activeGroup.key === group.key }"
          :aria-pressed="activeGroup.key === group.key"
          @click="groupKey = group.key"
        >
          <b>{{ evaluatorTitle(group.items[0].evaluator_id, group.name) }}</b
          ><small
            >v{{ group.version }} ·
            {{ new Set(group.items.map((r) => r.case_id)).size }} 条问题用例</small
          >
        </button>
      </nav>
      <section class="tuning-cases" aria-label="测试用例与样本报告">
        <h3>测试用例与样本报告</h3>
        <label class="case-picker"
          >测试用例<select v-model="selectedCase" aria-label="选择分析用例">
            <option v-for="id in caseIds" :key="id" :value="id">{{ caseName(id) }}</option>
          </select></label
        >
        <div class="case-heading">
          <h4>{{ caseName(selectedCase) }}</h4>
          <button class="link" @click="reportCase = selectedCase">查看完整样本测评报告 ↗</button>
        </div>
        <p class="muted">当前展示所选评估器的未通过检查项。</p>
        <article v-for="(result, index) in caseResults" :key="index" class="case-result">
          <p>{{ reason(result.reason) }}</p>
          <div
            v-for="check in result.checks.filter((c) => c.outcome === 'fail')"
            :key="check.id"
            class="check-result"
          >
            <b>{{ check.name }}</b
            ><small>{{ check.reason }}</small>
            <div class="expected-actual">
              <div>
                <h5>期望</h5>
                <pre>{{ pretty(check.expected) ?? '未提供' }}</pre>
              </div>
              <div>
                <h5>实际</h5>
                <pre>{{
                  check.actual_missing ? '未记录实际值' : (pretty(check.actual) ?? '未提供')
                }}</pre>
              </div>
            </div>
          </div>
          <p v-if="!result.checks.some((c) => c.outcome === 'fail')" class="muted">
            报告未提供检查项明细，可查看完整样本报告。
          </p>
        </article>
        <details class="recommendation">
          <summary>原因与改进建议</summary>
          <button v-if="!optimization" :disabled="analysisLoading" @click="analyze">
            {{ analysisLoading ? '模型分析中…' : '运行模型调优分析' }}
          </button>
          <p v-if="analysisError" role="alert">{{ analysisError }}</p>
          <template v-if="optimization">
            <p class="muted">
              以下为后端模型基于本次运行中同类失败的代表证据生成的原因分析，建议需人工复核，不会自动修改智能体或用例。
            </p>
            <article v-for="item in hypotheses" :key="item.id">
              <b>{{ item.title }}</b>
              <p>{{ item.explanation }}</p>
            </article>
            <article v-for="item in modelSuggestions" :key="item.id">
              <b>{{ item.title }}</b>
              <p>{{ item.recommendation }}</p>
              <p>{{ item.rationale }}</p>
            </article>
            <p v-if="!hypotheses.length">
              模型未返回关联当前检查项的原因，不能据此推断具体修复方案。
            </p>
          </template>
        </details>
      </section>
      <aside class="tuning-notes" aria-label="用例人工备注">
        <p class="note-context">{{ caseName(selectedCase) }}</p>
        <AnalysisAnnotation
          :key="report.run.id + ':' + selectedCase"
          :run-id="report.run.id"
          :case-id="selectedCase"
          :case-name="caseName(selectedCase)"
          :dataset-name="report.run.manifest.dataset.dataset_name"
          :model-value="annotations[selectedCase] ?? ''"
          @update:model-value="annotations[selectedCase] = $event"
        />
      </aside>
    </div>
  </section>
  <el-dialog
    :model-value="!!reportCase"
    @close="reportCase = ''"
    title="样本测评报告"
    width="min(1200px,94vw)"
    top="4vh"
    destroy-on-close
  >
    <div class="report-dialog-body">
      <CaseReport
        v-if="sample"
        :key="reportCase"
        :sample="sample"
        :results="report.results.filter((r) => r.case_id === reportCase)"
        :primary-ids="report.run.manifest.primary_evaluator_ids"
        :trace="trace"
        :trace-error="traceError"
        :trace-loading="traceLoading"
        complete
        hide-analyze
      />
    </div>
  </el-dialog>
</template>
<style scoped>
.tuning-workbench {
  display: grid;
  grid-template-columns: minmax(160px, 0.7fr) minmax(0, 2fr) minmax(220px, 1fr);
  border: 1px solid #e1e9e6;
  border-radius: 10px;
  overflow: hidden;
}
.tuning-evaluators,
.tuning-cases,
.tuning-notes {
  min-width: 0;
  padding: 20px;
}
.tuning-evaluators {
  background: #f7faf9;
}
.tuning-cases {
  border-inline: 1px solid #e1e9e6;
}
.tuning-workbench h3 {
  font-size: 16px;
  margin: 0 0 20px;
}
.evaluator-option {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  padding: 14px 10px;
  margin-bottom: 8px;
  cursor: pointer;
  overflow-wrap: anywhere;
}
.evaluator-option.selected {
  background: #e3f4ef;
  border-color: #9cd6c5;
  color: #007d68;
}
small {
  display: block;
  color: #718096;
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.6;
}
.case-picker {
  display: grid;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}
.case-picker select {
  width: 100%;
  padding: 10px;
  border: 1px solid #d3dbd8;
  border-radius: 6px;
  background: white;
  color: #172333;
}
.case-heading {
  margin-top: 20px;
}
.case-heading h4 {
  margin: 0 0 10px;
}
.case-heading button {
  text-align: left;
  font-size: 13px;
}
.case-result {
  font-size: 13px;
  line-height: 1.7;
}
.check-result {
  padding: 14px 0;
  border-bottom: 1px solid #e7eeeb;
}
.expected-actual {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.expected-actual > div {
  min-width: 0;
}
h5 {
  margin: 10px 0 6px;
  color: #64748b;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f7f9fa;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  margin: 0;
  max-height: 240px;
  overflow: auto;
}
.recommendation {
  margin-top: 20px;
  padding: 12px;
  background: #f3f8f6;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.8;
}
summary {
  cursor: pointer;
  color: #00846f;
}
.note-context {
  font-size: 13px;
  color: #64748b;
  margin-top: 0;
}
.tuning-notes :deep(.annotation-panel) {
  border: 0;
  padding: 0;
}
.report-dialog-body {
  max-height: 78vh;
  overflow: auto;
}
@media (max-width: 950px) {
  .tuning-workbench {
    grid-template-columns: 1fr;
  }
  .tuning-cases {
    border-inline: 0;
    border-block: 1px solid #e1e9e6;
  }
  .tuning-evaluators {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .tuning-evaluators h3 {
    width: 100%;
  }
  .evaluator-option {
    width: auto;
    margin: 0;
  }
}
</style>
