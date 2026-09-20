<script setup lang="ts">
import { shallowRef, computed, ref, watch, onMounted, onUnmounted } from 'vue';
import NewComparison from './NewComparison.vue';
import RunChoice from './RunChoice.vue';
import ComparisonRunSummary from './ComparisonRunSummary.vue';
import ConfigurationDiff from './ConfigurationDiff.vue';
import {
  api,
  request,
  score,
  statusLabel,
  metricLabel,
  type Report,
  type EvaluationRun,
  type Comparison,
} from '../../../api/evaluations';
import {
  frozenEvaluators,
  reportComparisonIssues,
  comparisonErrorMessage,
} from '../utils/comparison-compatibility';

const props = defineProps<{ initialPair?: { a: string; b: string }; embedded?: boolean }>();
const mode = ref('history'),
  submitted = ref<{ a: string; b: string } | null>(null);
const pairStatus = ref<Record<string, string>>({}),
  pairError = ref('');
let pairTimer: ReturnType<typeof setTimeout> | undefined,
  pairTicket = 0;
const pairReady = computed(
  () =>
    !!submitted.value &&
    [submitted.value.a, submitted.value.b].every((id) => pairStatus.value[id] === 'completed'),
);
async function checkPair(ticket: number) {
  if (!submitted.value) return;
  try {
    const results = await Promise.all(
      [submitted.value.a, submitted.value.b].map((id) => api.status(id)),
    );
    if (ticket !== pairTicket) return;
    pairStatus.value = Object.fromEntries(results.map((r) => [r.run_id, r.status]));
    pairError.value = '';
  } catch {
    if (ticket === pairTicket) pairError.value = '暂未取得执行进度，正在重试；也可打开任务查看。';
  }
  if (
    ticket === pairTicket &&
    !Object.values(pairStatus.value).some((s) => ['failed', 'cancelled'].includes(s)) &&
    !pairReady.value
  )
    pairTimer = setTimeout(() => void checkPair(ticket), 2500);
}
function created(a: string, b: string) {
  clearTimeout(pairTimer);
  submitted.value = { a, b };
  pairStatus.value = {};
  pairError.value = '';
  void checkPair(++pairTicket);
}
function showCreatedPair() {
  if (!submitted.value || !pairReady.value) return;
  baseline.value = submitted.value.a;
  candidate.value = submitted.value.b;
  mode.value = 'history';
}
const baseline = ref(''),
  candidate = ref(''),
  snapshots = ref<Record<string, Report>>({});
const history = shallowRef<EvaluationRun[]>([]),
  historyLoading = ref(false),
  historyError = ref('');
let historyTicket = 0;
const records = computed(() =>
  [
    ...new Map(
      [...history.value, ...Object.values(snapshots.value).map((report) => report.run)]
        .filter((run) => run.status === 'completed')
        .map((run) => [run.id, run]),
    ).values(),
  ].sort((a, b) =>
    String(b.completed_at ?? b.created_at).localeCompare(String(a.completed_at ?? a.created_at)),
  ),
);
async function loadHistory() {
  const ticket = ++historyTicket;
  historyLoading.value = true;
  historyError.value = '';
  try {
    const collected = await request<EvaluationRun[]>('/runs?status=completed&limit=200');
    if (ticket !== historyTicket) return;
    history.value = collected;
  } catch {
    if (ticket === historyTicket) historyError.value = '已完成任务列表读取失败，请重试。';
  } finally {
    if (ticket === historyTicket) historyLoading.value = false;
  }
}
onMounted(() => {
  void loadHistory();
  if (props.initialPair) {
    created(props.initialPair.a, props.initialPair.b);
  }
});
watch(pairReady, (ready) => {
  if (ready && props.initialPair) showCreatedPair();
});
watch(mode, (value) => {
  if (value === 'history') void loadHistory();
});

const snapshotLoading = ref(false),
  snapshotError = ref(''),
  busy = ref(false),
  error = ref('');
const result = ref<Comparison | null>(null),
  showDiff = ref(false);
let snapshotTicket = 0,
  comparisonTicket = 0;
const a = computed(() => snapshots.value[baseline.value]),
  b = computed(() => snapshots.value[candidate.value]);
const issues = computed(() => (a.value && b.value ? reportComparisonIssues(a.value, b.value) : []));
const canCompare = computed(
  () =>
    !!a.value &&
    !!b.value &&
    baseline.value !== candidate.value &&
    !snapshotLoading.value &&
    !snapshotError.value &&
    !issues.value.length,
);
function selectBaseline(id: string) {
  baseline.value = id;
  if (!id || id === candidate.value) candidate.value = '';
}
async function loadSnapshots() {
  const ticket = ++snapshotTicket;
  comparisonTicket++;
  busy.value = false;
  result.value = null;
  error.value = '';
  snapshotError.value = '';
  showDiff.value = false;
  snapshotLoading.value = mode.value === 'history' && !!(baseline.value || candidate.value);
  if (mode.value !== 'history') return;
  const ids = [...new Set([baseline.value, candidate.value].filter(Boolean))];
  try {
    await Promise.all(
      ids.map(async (id) => {
        if (snapshots.value[id]) return;
        const report = await api.report(id);
        if (ticket === snapshotTicket) snapshots.value[id] = report;
      }),
    );
  } catch {
    if (ticket === snapshotTicket) snapshotError.value = '未能读取完整报告，请重试。';
  } finally {
    if (ticket === snapshotTicket) snapshotLoading.value = false;
  }
  // Selecting records is the only user action: this GET never submits or reruns a task.
  if (ticket === snapshotTicket && canCompare.value) void compare();
}
watch([baseline, candidate, mode], loadSnapshots);
async function compare() {
  if (mode.value !== 'history' || busy.value || !canCompare.value) return;
  const ticket = ++comparisonTicket,
    aid = baseline.value,
    bid = candidate.value;
  busy.value = true;
  error.value = '';
  result.value = null;
  try {
    const data = await request<Comparison>(
      '/run-comparisons?' + new URLSearchParams({ baseline_run_id: aid, candidate_run_id: bid }),
    );
    if (ticket === comparisonTicket && aid === baseline.value && bid === candidate.value)
      result.value = data;
  } catch (e) {
    if (ticket === comparisonTicket) error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (ticket === comparisonTicket) busy.value = false;
  }
}
const changes = computed(() => ({
  improvement: result.value?.case_deltas.filter((d) => d.change === 'improvement').length ?? 0,
  regression: result.value?.case_deltas.filter((d) => d.change === 'regression').length ?? 0,
  unchanged: result.value?.case_deltas.filter((d) => d.change === 'unchanged').length ?? 0,
  changed: result.value?.case_deltas.filter((d) => d.change === 'changed').length ?? 0,
}));
const caseName = (id: string) =>
  a.value?.run.manifest.dataset.cases.find((c) => c.id === id)?.name ??
  b.value?.run.manifest.dataset.cases.find((c) => c.id === id)?.name ??
  id;
const evaluatorName = (id: string) =>
  (a.value && frozenEvaluators(a.value.run).find((e) => e.id === id)?.label) || id;
const delta = (value: number | null) =>
  value == null ? '—' : (value > 0 ? '+' : '') + score(value);
onUnmounted(() => {
  pairTicket++;
  historyTicket++;
  snapshotTicket++;
  comparisonTicket++;
  clearTimeout(pairTimer);
});
const templateLabels1: Record<string, string> = {
  overall: '整体',
  kind: '评估类型',
  dimension: '维度',
  metric: '指标',
  evaluator: '评估器',
};
const templateLabels2: Record<string, string> = {
  unchanged: '不变',
  improvement: '改善',
  regression: '退化',
  changed: '变化',
};
</script>
<template>
  <div v-if="!embedded" class="page-head">
    <div>
      <h1 class="page-title">A/B 实验</h1>
      <p class="page-sub">
        {{
          mode === 'history'
            ? '查看最近 200 个已完成任务的结果差异，不会重新运行任务。'
            : '使用相同评测集与评估器运行两个智能体版本'
        }}
      </p>
    </div>
  </div>
  <div v-if="!embedded" class="tabs">
    <button :class="['tab', { active: mode === 'new' }]" @click="mode = 'new'">
      创建实验并运行</button
    ><button :class="['tab', { active: mode === 'history' }]" @click="mode = 'history'">
      比较已有结果
    </button>
  </div>
  <NewComparison v-if="mode === 'new'" @created="created" />
  <section v-if="submitted && (mode === 'new' || embedded) && !pairReady" class="card section-gap">
    <h2>两侧任务已提交</h2>
    <p>
      <a class="link" :href="'#tasks/' + submitted.a"
        >查看实验 A 执行进度 · {{ statusLabel(pairStatus[submitted.a] ?? 'pending') }} →</a
      >
    </p>
    <p>
      <a class="link" :href="'#tasks/' + submitted.b"
        >查看实验 B 执行进度 · {{ statusLabel(pairStatus[submitted.b] ?? 'pending') }} →</a
      >
    </p>
    <p v-if="pairError" role="status">{{ pairError }}</p>
    <button class="secondary" :disabled="!pairReady" @click="showCreatedPair">查看对比结果</button>
    <small class="muted">两侧均完成后可查看；执行异常或取消请先查看对应任务。</small>
  </section>
  <template v-if="mode === 'history' && (!embedded || pairReady)">
    <section v-if="!embedded" class="card comparison-selection">
      <div class="toolbar">
        <div>
          <h2 class="section-title">选择已完成任务</h2>
          <p class="section-note">实验A作为参考，实验B与之对比；选好后自动展示结果。</p>
        </div>
        <button class="link" :disabled="historyLoading" @click="loadHistory">
          {{ historyLoading ? '读取中…' : '刷新任务' }}
        </button>
      </div>
      <div v-if="historyError" class="notice error" role="alert">
        {{ historyError }} <button class="link" @click="loadHistory">重试加载任务</button>
      </div>
      <div class="history-sides">
        <div data-testid="ab-side">
          <h3 class="experiment-label">实验A</h3>
          <RunChoice
            :model-value="baseline"
            :rows="records"
            label="实验A已完成任务"
            :excluded="candidate"
            :loading="historyLoading"
            @update:model-value="selectBaseline"
          />
          <ComparisonRunSummary v-if="a" :key="a.run.id" :report="a" />
        </div>
        <div data-testid="ab-side">
          <h3 class="experiment-label">实验B</h3>
          <RunChoice
            :model-value="candidate"
            :rows="records"
            label="实验B已完成任务"
            :excluded="baseline"
            :compatible-with="a?.run"
            :loading="historyLoading"
            :disabled="!baseline"
            @update:model-value="candidate = $event"
          />
          <ComparisonRunSummary v-if="b" :key="b.run.id" :report="b" />
        </div>
      </div>
      <p v-if="!historyLoading && !historyError && records.length < 2" class="muted section-gap">
        至少需要两条已完成任务。<button class="link" @click="mode = 'new'">创建实验并运行</button>
      </p>
    </section>
    <div v-if="snapshotLoading || busy" class="notice section-gap" role="status">
      {{ snapshotLoading ? '正在读取任务结果…' : '正在加载结果差异…' }}
    </div>
    <div v-else-if="snapshotError" class="notice error section-gap" role="alert">
      {{ snapshotError }} <button class="link" @click="loadSnapshots">重试读取报告</button>
    </div>
    <section
      v-else-if="a && b && issues.length"
      class="notice warn section-gap comparison-preflight"
      data-testid="comparison-preflight"
      role="status"
    >
      <h3>当前两条记录不能直接比较</h3>
      <p>上方仅并列展示原报告结果，不计算分数差，也不据此判断方案改善。</p>
      <ul>
        <li v-for="issue in issues" :key="issue.key">
          <b>{{ issue.title }}</b>
          <p>{{ issue.detail }}</p>
        </li>
      </ul>
      <p>可从实验B列表选择同口径任务，或使用共同配置创建新的实验。</p>
      <button class="secondary" @click="mode = 'new'">创建新实验</button>
    </section>
    <div v-if="error" class="notice error section-gap" role="alert">
      {{ comparisonErrorMessage(error) }}
      <button class="link" @click="compare">重试加载结果</button>
      <details>
        <summary>原始错误</summary>
        <pre>{{ error }}</pre>
      </details>
    </div>
    <template v-if="result">
      <section class="card section-gap" data-testid="comparison-results">
        <h2 class="section-title">结果对比</h2>
        <p class="section-note">
          以下变化均为实验B相对实验A；展示历史报告差异，不代表统计显著性或因果结论。
        </p>
        <div class="comparison-overview">
          <div>
            <span>综合得分变化</span
            ><strong
              :class="
                result.overall_score_delta != null && result.overall_score_delta < 0 ? 'down' : 'up'
              "
              >{{ delta(result.overall_score_delta)
              }}<small v-if="result.overall_score_delta != null"> 分</small></strong
            >
          </div>
          <div>
            <span>改善</span><strong class="up">{{ changes.improvement }}<small> 项</small></strong>
          </div>
          <div>
            <span>退化</span
            ><strong class="down">{{ changes.regression }}<small> 项</small></strong>
          </div>
          <div>
            <span>不变 / 其他变化</span
            ><strong>{{ changes.unchanged }} / {{ changes.changed }}<small> 项</small></strong>
          </div>
        </div>
        <h3 class="section-title">指标对比</h3>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>实验A</th>
                <th>实验B</th>
                <th>分数差（B − A）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in result.metric_deltas" :key="m.level + m.key">
                <td>
                  {{ metricLabel(m.key) }}
                  <div class="muted">{{ templateLabels1[m.level] ?? m.level }}</div>
                </td>
                <td>{{ score(m.baseline.score) }}</td>
                <td>{{ score(m.candidate.score) }}</td>
                <td :class="m.score_delta != null && m.score_delta < 0 ? 'down' : 'up'">
                  {{ delta(m.score_delta) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="card section-gap">
        <h2 class="section-title">逐项结果变化</h2>
        <p class="section-note">每项对应一个用例与一个评估器，不是去重后的用例数。</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>用例</th>
                <th>评估器</th>
                <th>实验A</th>
                <th>实验B</th>
                <th>变化</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in result.case_deltas" :key="d.case_id + d.evaluator_id">
                <td>
                  {{ caseName(d.case_id) }}<small class="case-id">{{ d.case_id }}</small>
                </td>
                <td>{{ evaluatorName(d.evaluator_id) }}</td>
                <td>{{ statusLabel(d.baseline_outcome) }}</td>
                <td>{{ statusLabel(d.candidate_outcome) }}</td>
                <td>{{ templateLabels2[d.change] ?? d.change }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <details
      v-if="a && b && !snapshotLoading"
      :key="baseline + candidate"
      class="card section-gap comparison-details"
      @toggle="showDiff = ($event.target as HTMLDetailsElement).open"
    >
      <summary>查看方案与评测条件差异（只读）</summary>
      <ConfigurationDiff v-if="showDiff" :baseline="a.run.manifest" :candidate="b.run.manifest" />
    </details>
  </template>
</template>
<style scoped>
.experiment-label {
  font-size: 14px;
  font-weight: 650;
  color: #263544;
  margin: 0 0 10px;
  padding-left: 9px;
  border-left: 3px solid #07ac8e;
  line-height: 20px;
}
.history-sides {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.history-sides > div {
  min-width: 0;
}
.comparison-selection .toolbar {
  margin-bottom: 14px;
}
.comparison-selection .section-note {
  margin: 6px 0 0;
}
.comparison-selection .toolbar > .link {
  white-space: nowrap;
}
.comparison-preflight {
  border: 1px solid #f3dcaf;
  background: #fffaf0;
  border-radius: 6px;
  padding: 16px;
}
.comparison-preflight h3 {
  margin-top: 0;
}
.comparison-preflight ul {
  padding-left: 20px;
}
.comparison-preflight p {
  font-size: 13px;
  overflow-wrap: anywhere;
}
.comparison-preflight li p {
  margin: 6px 0 12px;
}
.comparison-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 24px;
}
.comparison-overview > div {
  border: 1px solid #e8eceb;
  background: #f9fbfb;
  border-radius: 6px;
  padding: 14px;
}
.comparison-overview span {
  display: block;
  color: #6b7280;
  font-size: 13px;
}
.comparison-overview strong {
  display: block;
  font-size: 24px;
  margin-top: 8px;
}
.comparison-overview small {
  font-size: 12px;
  font-weight: 400;
}
.data-table td.up {
  color: #007f69;
}
.data-table td.down {
  color: #dc2626;
}
.case-id {
  display: block;
  color: #6b7280;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.comparison-details > summary {
  font-size: 14px;
  font-weight: 600;
  color: #007f69;
}
.comparison-details :deep(> .card) {
  border: 0;
  padding: 0;
}
.comparison-details :deep(.mini-card b) {
  font-size: 16px;
}
@media (max-width: 1000px) {
  .comparison-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 800px) {
  .history-sides {
    grid-template-columns: 1fr;
  }
  .comparison-selection .toolbar {
    align-items: flex-start;
  }
}
</style>
