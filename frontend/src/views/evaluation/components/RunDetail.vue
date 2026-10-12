<script setup lang="ts">
import { shallowRef, computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import RerunDialog from './RerunDialog.vue';
import RunConfiguration from './RunConfiguration.vue';
import RunLineage from './RunLineage.vue';
import TargetStructure from './TargetStructure.vue';
import TaskStaticAnalysis from './TaskStaticAnalysis.vue';
import ReportEvidenceAnalysis from './ReportEvidenceAnalysis.vue';
import CaseReport from './CaseReport.vue';
import { needsAttention } from '../utils/report-presentation';
const rerunPreview = ref(false);
const detailTab = ref(
  new URLSearchParams(location.hash.split('?')[1] ?? '').get('tab') === 'analysis' ||
    location.hash.startsWith('#optimizer/')
    ? 'analysis'
    : 'results',
);
const noEvidence = computed(
  () => report.value?.release_gate.reason_code === 'no_applicable_results',
);
import {
  api,
  request,
  statusLabel,
  score,
  metricLabel,
  type Report,
  type Trace,
  type RunProgress,
  type RunSamples,
} from '../../../api/evaluations';
const props = withDefaults(defineProps<{ id: string; returnPage?: string }>(), {
    returnPage: 'tasks',
  }),
  emit = defineEmits<{ navigate: [path: string] }>();
const progress = ref<RunProgress | null>(null),
  report = shallowRef<Report | null>(null),
  trace = shallowRef<Trace | null>(null),
  error = ref(''),
  traceError = ref(''),
  busy = ref(false),
  caseId = ref(''),
  filter = ref(''),
  traceLoading = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  traceRequest = 0;
const evidence = shallowRef<RunSamples | null>(null);
const groups = computed(() =>
  Array.from(new Set(evidence.value?.results.map((r) => r.case_id) ?? [])),
);
const filteredCases = computed(() =>
  groups.value.filter(
    (id) =>
      !filter.value ||
      evidence.value?.results.some((r) => r.case_id === id && r.outcome === filter.value),
  ),
);
const results = computed(
  () => evidence.value?.results.filter((r) => r.case_id === caseId.value) ?? [],
);
const attentionCount = (id: string) =>
  evidence.value?.results.filter((r) => r.case_id === id && needsAttention(r)).length ?? 0;
const sample = computed(() =>
  evidence.value?.run.manifest.dataset.cases.find((c) => c.id === caseId.value),
);
async function update() {
  try {
    const p = await api.status(props.id);
    const completed = p.status === 'completed' ? await api.report(props.id) : null;
    const s = completed
      ? { run: completed.run, results: completed.results, complete: true }
      : await api.samples(props.id);
    if (disposed) return;
    progress.value = p;
    evidence.value = s;
    if (completed) report.value = completed;
    if (!caseId.value) {
      const wanted = new URLSearchParams(location.hash.split('?')[1] ?? '').get('case');
      caseId.value = wanted && groups.value.includes(wanted) ? wanted : (groups.value[0] ?? '');
    }
    error.value = '';
  } catch (e) {
    error.value = String(e);
  } finally {
    if (
      !disposed &&
      (!!error.value ||
        !['completed', 'failed', 'cancelled'].includes(progress.value?.status ?? ''))
    )
      timer = setTimeout(update, 2000);
  }
}
watch(filteredCases, (ids) => {
  if (!ids.includes(caseId.value)) {
    const wanted = new URLSearchParams(location.hash.split('?')[1] ?? '').get('case');
    caseId.value = wanted && ids.includes(wanted) ? wanted : (ids[0] ?? '');
  }
});
const badCaseIds = computed(() => [
  ...new Set(
    report.value?.results
      .filter(
        (r) =>
          report.value!.run.manifest.primary_evaluator_ids.includes(r.evaluator_id) &&
          ['fail', 'error', 'review'].includes(r.outcome),
      )
      .map((r) => r.case_id) ?? [],
  ),
]);
async function writeback() {
  if (!report.value || !sample.value || busy.value) return;
  const source = sample.value;
  try {
    await ElMessageBox.confirm(
      '将本次运行中的用例快照写回原测评集草稿？如草稿已有同 ID 用例，将覆盖该用例。已发布版本及历史结果不变。',
      '回写失败用例',
      { type: 'warning', confirmButtonText: '确认回写', cancelButtonText: '取消' },
    );
    busy.value = true;
    const result = await request<{ source_dataset_id: string }>(
      `/runs/${props.id}/cases/${encodeURIComponent(source.id)}/writeback`,
      'POST',
      { case: source },
    );
    emit('navigate', 'datasets/' + result.source_dataset_id + '?version=draft');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = String(e);
  } finally {
    busy.value = false;
  }
}
watch(caseId, async (id) => {
  const ticket = ++traceRequest;
  trace.value = null;
  traceError.value = '';
  traceLoading.value = !!id;
  if (!id) return;
  try {
    const t = await api.trace(props.id, id);
    if (ticket === traceRequest) trace.value = t;
  } catch (e) {
    if (ticket === traceRequest) traceError.value = String(e);
  } finally {
    if (ticket === traceRequest) traceLoading.value = false;
  }
});
async function runAction(action: 'cancel' | 'rerun') {
  if (busy.value) return;
  try {
    if (action === 'cancel')
      await ElMessageBox.confirm(
        action === 'cancel'
          ? '取消当前测评任务？已产生的运行记录将保留。'
          : '使用原版本快照创建一个新的测评任务？',
        action === 'cancel' ? '取消测评' : '重新测评',
        { confirmButtonText: '确认', cancelButtonText: '返回' },
      );
    busy.value = true;
    const r = await request<RunProgress>(`/runs/${props.id}/${action}`, 'POST');
    if (action === 'rerun') {
      rerunPreview.value = false;
      emit('navigate', 'tasks/' + r.run_id);
    } else {
      clearTimeout(timer);
      await update();
    }
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = String(e);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  await update();
  await nextTick();
  if (new URLSearchParams(location.hash.split('?')[1] ?? '').get('action') === 'regression')
    document.getElementById('regression-action')?.scrollIntoView({ block: 'center' });
});
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
  traceRequest++;
});
</script>
<template>
  <div class="page-head">
    <div>
      <button class="link" @click="emit('navigate', returnPage)">← {{ '返回任务列表' }}</button>
      <h1 class="page-title">{{ '测评任务详情' }}</h1>
      <p class="page-sub">{{ id }}</p>
    </div>
    <div class="actions">
      <button
        v-if="progress && ['scheduled', 'pending', 'running'].includes(progress.status)"
        class="secondary"
        :disabled="busy"
        @click="runAction('cancel')"
      >
        取消任务</button
      ><button v-else-if="progress" class="primary" :disabled="busy" @click="rerunPreview = true">
        使用原配置重跑
      </button>
    </div>
  </div>
  <div v-if="error" class="notice error" role="alert">{{ error }}</div>
  <section v-if="progress" class="task-overview" aria-label="任务结果总览">
    <div class="overview-heading">
      <div>
        <span class="overview-eyebrow">本次测评</span>
        <h2>任务结果总览</h2>
      </div>
      <span
        class="badge"
        :class="report ? (report.release_gate.outcome === 'pass' ? 'success' : 'warn') : 'info'"
        >{{
          report
            ? noEvidence
              ? '无有效评判依据'
              : statusLabel(report.release_gate.outcome)
            : statusLabel(progress.status)
        }}</span
      >
    </div>
    <div v-if="report" class="overview-scores">
      <article
        v-for="m in report.metrics.filter((m) => m.level === 'overall' || m.level === 'kind')"
        :key="m.key"
        class="score-tile"
        :class="{ primary: m.level === 'overall' }"
      >
        <span>{{ metricLabel(m.key) }}</span>
        <div class="score-number">{{ score(m.score) }}<small>/ 100</small></div>
        <p>
          通过 {{ m.passed }} · 未通过 {{ m.failed }} · 待复核 {{ m.reviewed }} · 异常
          {{ m.errors }} · 不适用 {{ m.not_applicable }}
        </p>
      </article>
    </div>
    <p v-if="report" class="score-caption">按评估结果统计，非唯一样本数；无分数时显示“—”。</p>
    <div class="overview-facts">
      <div>
        <span>执行状态</span><b>{{ statusLabel(progress.status) }}</b
        ><small>{{ progress.completed_cases }} / {{ progress.total_cases }} 样本</small>
      </div>
      <div>
        <span>智能体版本</span><b>{{ progress.target_name }}</b
        ><small>{{ progress.target_version }}</small>
      </div>
      <div>
        <span>测评集版本</span><b>{{ progress.dataset_name }}</b
        ><small>v{{ progress.dataset_version }}</small>
      </div>
      <div>
        <span>运行耗时</span
        ><b>{{
          progress.duration_seconds == null ? '—' : progress.duration_seconds.toFixed(1) + ' 秒'
        }}</b
        ><small v-if="progress.queue_position != null"
          >队列位置：{{ progress.queue_position }}</small
        >
      </div>
    </div>
    <details v-if="evidence" class="overview-config">
      <summary>本次任务配置与版本来源</summary>
      <RunConfiguration :manifest="evidence.run.manifest" /><RunLineage :run-id="id" />
    </details>
  </section>
  <details v-if="progress" class="card">
    <summary>测评对象来源与智能体图谱</summary>
    <TargetStructure :run-id="id" :trace="trace" />
  </details>
  <div v-if="progress?.error" class="notice error">
    <b>执行异常</b>
    <pre>{{ progress.error }}</pre>
  </div>
  <div v-if="progress && !report && progress.status !== 'failed'" class="notice">
    {{
      progress.status === 'scheduled'
        ? '任务已预约，等待到期调度。'
        : progress.status === 'cancelled'
          ? '任务已取消，未生成完整测评报告。'
          : '任务正在处理，页面每 2 秒查询进度。已完成样本逐条显示，下方每 2 秒更新；最终结论在整批结束后生成。'
    }}
  </div>
  <RerunDialog
    v-if="rerunPreview"
    :id="id"
    @close="rerunPreview = false"
    @created="
      (next) => {
        rerunPreview = false;
        emit('navigate', 'tasks/' + next);
      }
    "
  />
  <div v-if="report" class="tabs" aria-label="任务详情内容">
    <button :class="['tab', { active: detailTab === 'results' }]" @click="detailTab = 'results'">
      测评结果</button
    ><button :class="['tab', { active: detailTab === 'analysis' }]" @click="detailTab = 'analysis'">
      调优分析</button
    ><button :class="['tab', { active: detailTab === 'static' }]" @click="detailTab = 'static'">
      Skill 静态分析
    </button>
  </div>
  <TaskStaticAnalysis v-if="detailTab === 'static'" :run-ids="[id]" />
  <ReportEvidenceAnalysis v-if="report && detailTab === 'analysis'" :report="report" />
  <template v-if="evidence && detailTab === 'results'">
    <div v-if="noEvidence" class="notice warn" role="status">
      <b>没有适用的评估检查，发布门禁未通过</b>
      <p>这不代表智能体业务失败。请补充用例期望，或选择能评判这些样本的评估器。</p>
      <a
        class="link"
        :href="
          '#datasets/' +
          evidence.run.manifest.dataset.dataset_id +
          '?version=' +
          evidence.run.manifest.dataset.version
        "
        >查看本次测评集版本并创建修改草稿 →</a
      >
    </div>
    <div class="report-layout case-report-layout">
      <aside class="card case-navigation">
        <h3>样本（{{ groups.length }}）</h3>
        <select class="input" v-model="filter" aria-label="样本结果筛选">
          <option value="">全部样本</option>
          <option
            v-for="s in ['fail', 'error', 'review', 'pass', 'not_applicable']"
            :key="s"
            :value="s"
          >
            含{{ statusLabel(s) }}评估项
          </option>
        </select>
        <button
          v-for="id in filteredCases"
          :key="id"
          :class="['evaluator-choice', { selected: caseId === id }]"
          :aria-pressed="caseId === id"
          @click="caseId = id"
        >
          <b>{{ evidence.run.manifest.dataset.cases.find((c) => c.id === id)?.name ?? id }}</b>
          <span>{{ id }}</span
          ><span v-if="attentionCount(id)" class="case-attention"
            >需处理 {{ attentionCount(id) }} 项</span
          >
        </button>
        <p v-if="!filteredCases.length" class="empty">无匹配样本</p>
      </aside>
      <div v-if="sample">
        <div v-if="results.some((r) => r.outcome === 'fail')" class="toolbar">
          <button class="secondary" :disabled="busy" @click="writeback">回写失败用例到草稿</button>
        </div>
        <CaseReport
          v-if="sample"
          :key="caseId"
          :sample="sample"
          :results="results"
          :primary-ids="evidence.run.manifest.primary_evaluator_ids"
          :trace="trace"
          :trace-error="traceError"
          :trace-loading="traceLoading"
          :complete="!!report"
          hide-analyze
        />
      </div>
      <section v-else class="card empty">暂无可展示的样本结果</section>
    </div>
  </template>
</template>
<style scoped>
.task-overview {
  background: white;
  border: 1px solid #dfe8e5;
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 4px 18px #173b2a05;
}
.overview-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.overview-heading h2 {
  font-size: 21px;
  margin: 6px 0 0;
}
.overview-eyebrow {
  font-size: 12px;
  letter-spacing: 1px;
  color: #718078;
}
.overview-scores {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}
.score-tile {
  padding: 20px;
  border: 1px solid #e4eae8;
  background: #f8faf9;
  border-radius: 12px;
}
.score-tile.primary {
  background: linear-gradient(125deg, #e8f7f1, #f5fbf8);
  border-color: #bbdfd0;
}
.score-tile > span {
  font-size: 14px;
  color: #50675d;
}
.score-number {
  font-size: 38px;
  font-weight: 650;
  letter-spacing: -1px;
  margin: 10px 0;
  color: #183a2d;
}
.score-number small {
  font-size: 14px;
  font-weight: 400;
  color: #83928a;
  margin-left: 8px;
  letter-spacing: 0;
}
.score-tile p {
  font-size: 12px;
  color: #65796f;
  margin: 0;
  line-height: 1.8;
}
.score-caption {
  font-size: 12px;
  color: #7c8882;
  margin: 10px 0 20px;
}
.overview-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 24px;
  padding: 20px 0;
}
.overview-facts > div {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.overview-facts span,
.overview-facts small {
  font-size: 12px;
  color: #758078;
}
.overview-facts b {
  font-size: 15px;
  overflow-wrap: anywhere;
}
.overview-facts small {
  overflow-wrap: anywhere;
}
.overview-config {
  border-top: 1px solid #e8ecea;
  padding-top: 16px;
  font-size: 13px;
}
.overview-config summary {
  color: #008570;
  cursor: pointer;
}
@media (max-width: 800px) {
  .overview-facts {
    grid-template-columns: 1fr 1fr;
  }
  .task-overview {
    padding: 16px;
  }
  .overview-scores {
    grid-template-columns: 1fr;
  }
}

.report-layout.case-report-layout {
  grid-template-columns: 220px minmax(0, 1fr);
}
.case-navigation .case-attention {
  color: #b42318;
  font-weight: 600;
}
@media (max-width: 1280px) {
  .report-layout.case-report-layout {
    grid-template-columns: 180px minmax(0, 1fr);
  }
}
@media (max-width: 768px) {
  .report-layout.case-report-layout {
    grid-template-columns: 1fr;
  }
  .case-navigation {
    max-height: 280px;
  }
}
</style>
