<script setup lang="ts">
import { useRouter } from 'vue-router';
const router = useRouter();
import { shallowRef, computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
  api,
  request,
  statusLabel,
  score,
  type RunSamples,
  type RunProgress,
  type Report,
  type Trace,
} from '../../../api/evaluations';
import { ElMessageBox } from 'element-plus';
import {
  scoreColumns,
  columnScore,
  sampleSummary,
  downloadCsv,
  displayValue,
  traceSeconds,
} from '../utils/task-report';
import ResultEvaluationCard from './ResultEvaluationCard.vue';
import RerunDialog from './RerunDialog.vue';
import { sameJson } from '../utils/report-presentation';
import { taskTitle } from '../utils/dashboard-data';
const props = defineProps<{ id: string; returnPage?: string }>(),
  emit = defineEmits<{ navigate: [path: string] }>();
const writing = ref(false);
async function writeback() {
  if (!sample.value || writing.value) return;
  try {
    await ElMessageBox.confirm(
      '将本次样本快照写回原评测集草稿？同 ID 草稿样本将被替换，已发布版本和历史结果不变。',
      '回写失败样本',
      { confirmButtonText: '确认回写', cancelButtonText: '取消' },
    );
    writing.value = true;
    const r = await request<{ source_dataset_id: string }>(
      `/runs/${props.id}/cases/${encodeURIComponent(sample.value.id)}/writeback`,
      'POST',
      { case: sample.value },
    );
    emit('navigate', 'datasets/' + r.source_dataset_id + '?version=draft');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = String(e);
  } finally {
    writing.value = false;
  }
}
const progress = ref<RunProgress | null>(null),
  data = shallowRef<RunSamples | null>(null),
  report = shallowRef<Report | null>(null),
  error = ref(''),
  tab = ref('results'),
  rerun = ref(false);
const sampleId = ref(location.hash.match(/\/samples\/([^?]+)/)?.[1] ?? ''),
  turnIndex = ref(0),
  continuous = ref(false),
  status = ref(''),
  range = ref(''),
  scenario = ref('');
const traces = ref<Record<string, Trace>>({}),
  traceErrors = ref<Record<string, string>>({});
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  traceTicket = 0;
const manifest = computed<any>(() => data.value?.run.manifest);
const cases = computed(
  () =>
    manifest.value?.dataset.cases.filter(
      (c: any) =>
        !manifest.value.selected_case_ids || manifest.value.selected_case_ids.includes(c.id),
    ) ?? [],
);
const specs = computed<any[]>(
  () =>
    manifest.value?.evaluator_specs.filter((s: any) =>
      manifest.value.primary_evaluator_ids.includes(s.id),
    ) ?? [],
);
const columns = computed(() => (manifest.value ? scoreColumns(manifest.value) : []));
const caseResults = (id: string) => data.value?.results.filter((r) => r.case_id === id) ?? [];
const summary = (id: string) => {
  const result = sampleSummary(caseResults(id), manifest.value?.primary_evaluator_ids ?? []);
  return result.outcome === 'pending' && progress.value?.status === 'failed'
    ? { ...result, outcome: 'error' }
    : result;
};
const scenarios = computed<string[]>(() => [
  ...new Set<string>(cases.value.flatMap((c: any) => c.tags ?? [])),
]);
const filtered = computed(() =>
  cases.value.filter((c: any) => {
    const s = summary(c.id);
    return (
      (!status.value || s.outcome === status.value) &&
      (!scenario.value || c.tags.includes(scenario.value)) &&
      (!range.value ||
        (s.score !== null && (range.value === 'high' ? s.score >= 0.8 : s.score < 0.8)))
    );
  }),
);
const sample = computed(() => cases.value.find((c: any) => c.id === sampleId.value)),
  trace = computed(() => traces.value[sampleId.value]),
  results = computed(() => caseResults(sampleId.value));
const isMultiTurn = computed(() => (sample.value?.turns.length ?? 0) > 1);
const shownTurns = computed(() =>
  !isMultiTurn.value || continuous.value
    ? (sample.value?.turns ?? [])
    : (sample.value?.turns.slice(turnIndex.value, turnIndex.value + 1) ?? []),
);
const stats = computed(() => {
  const summaries = cases.value.map((c: any) => summary(c.id));
  return {
    pass: summaries.filter((s: any) => s.outcome === 'pass').length,
    failed: summaries.filter((s: any) => ['error', 'fail'].includes(s.outcome)).length,
    pending: summaries.filter((s: any) => ['pending', 'review'].includes(s.outcome)).length,
  };
});
const durations = computed(() =>
  Object.values(traces.value)
    .map(traceSeconds)
    .filter((n): n is number => n !== null),
);
const avgTime = computed(() =>
  durations.value.length === cases.value.length && durations.value.length
    ? durations.value.reduce((a, b) => a + b, 0) / durations.value.length
    : null,
);
const overall = computed(
  () => report.value?.metrics.find((m) => m.level === 'overall')?.score ?? null,
);
const currentPosition = computed(() => cases.value.findIndex((c: any) => c.id === sampleId.value));
const formatTime = (n: number | null) =>
  n === null ? '—' : n < 0.01 ? '< 0.01s' : n.toFixed(2) + 's';
function openSample(id: string) {
  sampleId.value = id;
  turnIndex.value = 0;
  void router.replace(`/tasks/${props.id}/samples/${id}`);
}
function back() {
  sampleId.value = '';
  void router.replace(`/tasks/${props.id}`);
}
function move(n: number) {
  const c = cases.value[currentPosition.value + n];
  if (c) openSample(c.id);
}
function toolsFor(id: string) {
  const spans = trace.value?.spans ?? [],
    ids = new Set(
      spans.filter((s) => s.attributes['agentgate.turn.id'] === id).map((s) => s.span_id),
    );
  let changed = true;
  while (changed) {
    changed = false;
    for (const s of spans as any[])
      if (ids.has(s.parent_span_id) && !ids.has(s.span_id)) {
        ids.add(s.span_id);
        changed = true;
      }
  }
  return spans.filter((s) => s.operation_type === 'tool' && ids.has(s.span_id));
}
async function loadTraces() {
  const ticket = ++traceTicket;
  const pending = cases.value.filter(
    (c: any) => data.value?.results.some((r) => r.case_id === c.id) && !traces.value[c.id],
  );
  for (let i = 0; i < pending.length; i += 4) {
    if (disposed || ticket !== traceTicket) return;
    await Promise.all(
      pending.slice(i, i + 4).map(async (c: any) => {
        try {
          const t = await api.trace(props.id, c.id);
          if (!disposed) traces.value[c.id] = t;
        } catch (e) {
          if (!disposed) traceErrors.value[c.id] = String(e);
        }
      }),
    );
  }
}
async function load() {
  try {
    const p = await api.status(props.id),
      r = p.status === 'completed' ? await api.report(props.id) : null,
      s = r ? { run: r.run, results: r.results, complete: true } : await api.samples(props.id);
    if (disposed) return;
    progress.value = p;
    report.value = r;
    data.value = s;
    error.value = '';
    void loadTraces();
  } catch (e) {
    error.value = String(e);
  } finally {
    if (
      !disposed &&
      (error.value || !['completed', 'failed', 'cancelled'].includes(progress.value?.status ?? ''))
    )
      timer = setTimeout(load, 3000);
  }
}
function exportRows() {
  downloadCsv(
    [
      ['用户输入', '场景', '状态', '综合分', ...columns.value.map((c) => c.name), '耗时（秒）'],
      ...filtered.value.map((c: any) => [
        displayValue(c.turns[0]?.input),
        c.tags.join('、'),
        statusLabel(summary(c.id).outcome),
        score(summary(c.id).score),
        ...columns.value.map((col) => score(columnScore(caseResults(c.id), col))),
        traceSeconds(traces.value[c.id]),
      ]),
    ],
    `评测结果-${props.id}.csv`,
  );
}
onMounted(load);
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
  traceTicket++;
});
watch(sampleId, () => {
  turnIndex.value = 0;
  continuous.value = false;
});
</script>
<template>
  <div class="task-results">
    <div class="breadcrumbs">
      <button class="link" @click="emit('navigate', 'tasks')">评测任务</button><span>/</span
      ><button class="link" @click="back">任务详情</button
      ><template v-if="sampleId"><span>/</span><span>样本详情</span></template>
    </div>
    <p v-if="error" class="notice error" role="alert">
      {{ error }} <button class="link" @click="load">重试</button>
    </p>
    <template v-if="data && progress">
      <template v-if="!sampleId">
        <header class="task-hero">
          <div class="hero-icon">{{ progress.status === 'completed' ? '✓' : '◷' }}</div>
          <div>
            <h1>{{ taskTitle(data.run) }}</h1>
            <p>
              {{ manifest.target.ref.external_version_id }} <span>·</span>
              {{ new Date(progress.created_at).toLocaleString() }}
            </p>
          </div>
          <span
            class="badge"
            :class="
              progress.status === 'failed'
                ? 'error'
                : progress.status === 'completed'
                  ? 'success'
                  : 'info'
            "
            >{{ statusLabel(progress.status) }}</span
          >
        </header>
        <nav class="tabs">
          <button
            v-for="t in [
              ['results', '样本结果'],
              ['config', '任务配置'],
            ]"
            :key="t[0]"
            class="tab"
            :class="{ active: tab === t[0] }"
            @click="tab = t[0]"
          >
            {{ t[1] }}
          </button>
        </nav>
        <p v-if="progress.error" class="notice error">{{ progress.error }}</p>
        <template v-if="tab === 'results'">
          <section class="task-kpis">
            <article>
              <span>完成进度</span><b>{{ Math.round(progress.progress * 100) }}%</b
              ><progress :value="progress.completed_cases" :max="progress.total_cases || 1" />
            </article>
            <article>
              <span>已处理 / 总样本</span
              ><b
                >{{ progress.completed_cases }} <small>/ {{ progress.total_cases }}</small></b
              >
            </article>
            <article>
              <span>当前得分</span><b class="violet">{{ score(overall) }}</b>
            </article>
            <article>
              <span>平均耗时</span><b>{{ formatTime(avgTime) }}</b>
            </article>
            <article>
              <span>样本通过率</span
              ><b class="green"
                >{{ cases.length ? Math.round((stats.pass / cases.length) * 100) : 0 }}%</b
              >
            </article>
            <article>
              <span>失败 / 待评审</span
              ><b class="danger"
                >{{ stats.failed }} <small>/ {{ stats.pending }}</small></b
              >
            </article>
          </section>
          <p v-if="report && report.release_gate.outcome !== 'pass'" class="notice warn">
            任务判定：{{ statusLabel(report.release_gate.outcome) }} ·
            {{
              report.release_gate.reason_code === 'evaluator_error'
                ? '评估器执行异常'
                : report.release_gate.reason_code === 'no_applicable_results'
                  ? '无适用检查'
                  : report.release_gate.reason_code
            }}
          </p>
          <div class="toolbar result-filters">
            <select class="input" v-model="status" aria-label="样本状态">
              <option value="">全部状态</option>
              <option
                v-for="s in ['pass', 'fail', 'error', 'review', 'pending', 'not_applicable']"
                :key="s"
                :value="s"
              >
                {{ statusLabel(s) }}
              </option></select
            ><select class="input" v-model="range" aria-label="分数区间">
              <option value="">全部分数</option>
              <option value="high">80—100 分</option>
              <option value="low">低于 80 分</option></select
            ><select class="input" v-model="scenario" aria-label="样本场景">
              <option value="">全部场景</option>
              <option v-for="(s, rowIndex1) in scenarios" :key="rowIndex1">{{ s }}</option></select
            ><button class="secondary export" @click="exportRows">导出 CSV</button>
          </div>
          <div class="table-wrap">
            <table class="data-table sample-table">
              <thead>
                <tr>
                  <th>用户输入</th>
                  <th>场景</th>
                  <th>状态</th>
                  <th>综合分</th>
                  <th v-for="c in columns" :key="c.key">{{ c.name }}</th>
                  <th>耗时</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in filtered" :key="c.id">
                  <td>
                    <b>{{ c.name }}</b>
                    <p class="query-preview">{{ displayValue(c.turns[0]?.input) }}</p>
                  </td>
                  <td>{{ c.tags.join('、') || '—' }}</td>
                  <td>{{ statusLabel(summary(c.id).outcome) }}</td>
                  <td class="green">{{ score(summary(c.id).score) }}</td>
                  <td v-for="col in columns" :key="col.key" class="violet">
                    {{ score(columnScore(caseResults(c.id), col)) }}
                  </td>
                  <td>{{ formatTime(traceSeconds(traces[c.id])) }}</td>
                  <td><button class="link" @click="openSample(c.id)">样本详情</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!filtered.length" class="empty">暂无匹配样本</p>
          <p v-if="columns.some((c) => c.criterion)" class="muted">
            LLM 未返回独立维度分数，显示为“—”。
          </p>
        </template>
        <section v-else-if="tab === 'config'" class="config-cards">
          <article class="card">
            <h2>被测智能体</h2>
            <div class="config-block">
              <b>{{ manifest.target.display_name }}</b>
              <p>
                {{ manifest.target.ref.external_target_id }} ·
                {{ manifest.target.ref.external_version_id }}
              </p>
            </div>
            <h3>评测数据集</h3>
            <div class="config-block">
              <a class="link" :href="'#datasets/' + manifest.dataset.dataset_id">{{
                manifest.dataset.dataset_name
              }}</a>
              <p>{{ cases.length }} 条样本 · v{{ manifest.dataset.version }}</p>
            </div>
            <h3>执行设置</h3>
            <p>
              并发 {{ manifest.max_parallel_cases }} · 超时 {{ manifest.timeout_seconds }} 秒 · 重试
              {{ manifest.max_retries }} 次
            </p>
            <button class="secondary" @click="rerun = true">使用原配置重跑</button>
          </article>
          <article class="card">
            <h2>评估器配置</h2>
            <div v-for="s in specs" :key="s.id" class="config-block">
              <b
                >{{ s.name }}
                <span class="badge info">{{ s.kind === 'rule' ? '规则评估' : 'LLM 评估' }}</span></b
              >
              <p>v{{ s.version }} · {{ s.dimension }} · {{ s.metric }}</p>
              <p v-if="s.config?.model">
                {{ s.config.model.provider_id }} · {{ s.config.model.model_id }}
              </p>
              <dl v-if="s.config?.rubric">
                <template v-for="(text, key) in s.config.rubric" :key="key"
                  ><dt>{{ key }}</dt>
                  <dd>{{ text }}</dd></template
                >
              </dl>
            </div>
            <p class="muted">
              {{
                manifest.metric_plan.id === 'p1-equal-mean'
                  ? '按适用评估结果等权汇总'
                  : manifest.metric_plan.id
              }}
            </p>
          </article>
        </section>
      </template>
      <template v-else-if="sample">
        <header class="sample-head">
          <div>
            <h1>样本评测详情</h1>
            <p>{{ sample.name }} · {{ sample.turns.length }} 轮对话</p>
          </div>
          <span class="badge info">{{ statusLabel(summary(sample.id).outcome) }}</span
          ><button class="secondary" :disabled="currentPosition <= 0" @click="move(-1)">
            上一条</button
          ><button
            class="secondary"
            :disabled="currentPosition >= cases.length - 1"
            @click="move(1)"
          >
            下一条
          </button>
        </header>
        <div v-if="results.some((r) => r.outcome === 'fail')" class="toolbar">
          <button class="secondary" :disabled="writing" @click="writeback">
            回写失败样本到草稿
          </button>
        </div>
        <div class="conversation-layout">
          <section class="conversation-panel">
            <header>
              <h2>{{ isMultiTurn ? '多轮对话' : '单轮对话' }}</h2>
              <div v-if="isMultiTurn" class="actions" role="radiogroup" aria-label="对话展示方式">
                <button
                  class="secondary"
                  :class="{ selected: !continuous }"
                  role="radio"
                  :aria-checked="!continuous"
                  @click="continuous = false"
                >
                  单轮聚焦</button
                ><button
                  class="secondary"
                  :class="{ selected: continuous }"
                  role="radio"
                  :aria-checked="continuous"
                  @click="continuous = true"
                >
                  连续对话
                </button>
              </div>
            </header>
            <div class="conversation-body" :class="{ 'single-turn': !isMultiTurn }">
              <aside v-if="isMultiTurn">
                <h4>轮次目录</h4>
                <button
                  v-for="(turn, i) in sample.turns"
                  :key="turn.id"
                  :class="{ active: turnIndex === i }"
                  @click="
                    turnIndex = i;
                    continuous = false;
                  "
                >
                  第 {{ Number(i) + 1 }} 轮 <span>{{ displayValue(turn.input) }}</span>
                </button>
              </aside>
              <main tabindex="0" aria-label="对话内容，可滚动">
                <p v-if="traceErrors[sample.id]" class="notice error">
                  {{ traceErrors[sample.id] }}
                </p>
                <p v-else-if="!trace" class="muted">
                  {{ caseResults(sample.id).length ? '正在读取执行轨迹…' : '尚无执行轨迹' }}
                </p>
                <article v-for="turn in shownTurns" :key="turn.id" class="conversation-turn">
                  <h3 v-if="isMultiTurn">第 {{ sample.turns.indexOf(turn) + 1 }} 轮</h3>
                  <h4>用户输入</h4>
                  <pre class="message user">{{
                    displayValue(trace?.turn_outcomes?.[turn.id]?.input ?? turn.input)
                  }}</pre>
                  <details
                    v-if="
                      trace?.turn_outcomes?.[turn.id] &&
                      !sameJson(turn.input, trace.turn_outcomes[turn.id].input)
                    "
                    class="notice warn"
                  >
                    <summary>实际输入与样本配置不同</summary>
                    <pre>{{ displayValue(turn.input) }}</pre>
                  </details>
                  <h4>期望结果</h4>
                  <div class="message expected">
                    <p v-if="!turn.expectations.length">未设置期望</p>
                    <div v-for="e in turn.expectations" :key="e.id">
                      <b>{{ e.name || e.kind }} {{ e.path || e.tool || e.policy_id || '' }}</b>
                      <pre>{{ displayValue(e.condition ?? e) }}</pre>
                    </div>
                  </div>
                  <h4>实际回答</h4>
                  <pre class="message answer">{{
                    displayValue(trace?.turn_outcomes?.[turn.id]?.output)
                  }}</pre>
                  <details v-if="toolsFor(turn.id).length" class="message">
                    <summary>工具调用（{{ toolsFor(turn.id).length }}）</summary>
                    <div v-for="tool in toolsFor(turn.id)" :key="tool.span_id">
                      <h4>{{ tool.name }}</h4>
                      <pre>{{ displayValue(tool.attributes) }}</pre>
                    </div>
                  </details>
                </article>
              </main>
            </div>
          </section>
          <aside class="evaluation-panel">
            <h2>评测结果</h2>
            <section class="score-box">
              <span>综合得分</span
              ><strong>{{ score(summary(sample.id).score) }}<small>/100</small></strong
              ><span
                class="badge"
                :class="summary(sample.id).outcome === 'pass' ? 'success' : 'warn'"
                >{{ statusLabel(summary(sample.id).outcome) }}</span
              >
            </section>
            <section class="dimension-bars">
              <h3>
                评分维度 <small>{{ columns.length }} 项</small>
              </h3>
              <div v-for="col in columns" :key="col.key">
                <p>
                  <span>{{ col.name }}</span
                  ><b>{{ score(columnScore(results, col)) }}</b>
                </p>
                <progress :value="columnScore(results, col) ?? 0" max="1" />
              </div>
            </section>
            <details open>
              <summary>评估结论与依据</summary>
              <ResultEvaluationCard
                v-for="r in results"
                :key="r.evaluator_id"
                :result="r"
                :primary="manifest.primary_evaluator_ids.includes(r.evaluator_id)"
                :turns="sample.turns"
              />
            </details>
          </aside>
        </div>
        <footer class="sample-footer">
          <span>耗时 {{ formatTime(traceSeconds(trace)) }}</span
          ><span>轮次 {{ sample.turns.length }}</span
          ><span>Trace {{ trace?.trace_id ?? '—' }}</span>
        </footer>
      </template>
      <p v-else class="empty">
        样本不存在 <button class="link" @click="back">返回任务详情</button>
      </p>
    </template>
    <p v-else-if="!error" class="empty">正在加载任务…</p>
    <RerunDialog
      v-if="rerun"
      :id="id"
      @close="rerun = false"
      @created="(next) => emit('navigate', 'tasks/' + next)"
    />
  </div>
</template>
<style scoped>
.breadcrumbs {
  display: flex;
  gap: 12px;
  align-items: center;
  color: #82918b;
  margin-bottom: 20px;
}
.task-hero,
.sample-head {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 28px;
}
.task-hero {
  border: 1px solid #e0e8e4;
  padding: 28px;
  border-radius: 14px;
  background: white;
}
.hero-icon {
  padding: 15px 23px;
  background: #ddf5eb;
  color: #00a88b;
  font-size: 32px;
  border-radius: 14px;
}
.task-hero h1,
.sample-head h1 {
  font-size: 23px;
  margin: 0 0 12px;
}
.task-hero p,
.sample-head p {
  color: #7b8985;
  margin: 0;
  font-size: 13px;
}
.task-hero > .badge {
  margin-left: auto;
}
.sample-head > div {
  flex: 1;
}
.task-kpis {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  padding: 26px 10px;
  border: 1px solid #dfe8e5;
  border-radius: 14px;
  background: linear-gradient(120deg, #fff, #f6faf8);
  margin: 24px 0;
}
.task-kpis article {
  padding: 0 18px;
  border-right: 1px solid #e9eeeb;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.task-kpis article:last-child {
  border: 0;
}
.task-kpis span {
  font-size: 13px;
  color: #718478;
}
.task-kpis b {
  font-size: 28px;
}
.task-kpis small {
  font-size: 16px;
  font-weight: 400;
  color: #8b9b92;
}
progress {
  height: 7px;
  border: 0;
  border-radius: 6px;
  overflow: hidden;
  width: 100%;
  accent-color: #00ad8b;
}
progress::-webkit-progress-bar {
  background: #edf1ef;
}
progress::-webkit-progress-value {
  background: #0ab292;
  border-radius: 6px;
}
.green {
  color: #00a486;
}
.violet {
  color: #7b4cdc;
}
.danger {
  color: #d74646;
}
.result-filters select {
  width: 160px;
}
.export {
  margin-left: auto;
}
.sample-table {
  min-width: 1000px;
}
.sample-table th {
  min-width: 110px;
}
.sample-table th:first-child {
  min-width: 240px;
}
.sample-table th:last-child,
.sample-table td:last-child {
  position: sticky;
  right: 0;
  background: white;
  min-width: 100px;
  box-shadow: -6px 0 10px #253a2e05;
}
.query-preview {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #8b9992;
  margin-bottom: 0;
}
.config-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  margin-top: 24px;
}
.config-block {
  background: #f7f9f8;
  border-radius: 10px;
  padding: 20px;
  margin: 18px 0;
  overflow-wrap: anywhere;
}
.config-cards h2 {
  font-size: 19px;
}
.config-block p,
.config-cards p {
  font-size: 13px;
  color: #6d7e75;
}
.config-block dt {
  font-weight: 600;
  margin-top: 12px;
}
.config-block dd {
  margin: 6px 0;
  color: #718478;
  font-size: 13px;
}
.full {
  grid-column: 1/-1;
}
.conversation-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(310px, 1fr);
  gap: 20px;
}
.conversation-panel,
.evaluation-panel {
  border: 1px solid #dfe8e5;
  background: white;
  border-radius: 14px;
  overflow: hidden;
}
.conversation-panel > header {
  padding: 18px 20px;
  border-bottom: 1px solid #e8edea;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.conversation-panel h2,
.evaluation-panel h2 {
  font-size: 18px;
  margin: 0;
}
.conversation-body {
  display: grid;
  grid-template-columns: 170px minmax(0, 1fr);
  height: 65vh;
  min-height: 360px;
  min-width: 0;
  overflow: hidden;
}
.conversation-body > aside {
  padding: 16px;
  background: #f8faf9;
  border-right: 1px solid #e8edea;
  overflow: auto;
}
.conversation-body.single-turn {
  grid-template-columns: minmax(0, 1fr);
}
.conversation-body > aside button {
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  padding: 14px;
  width: 100%;
  margin-bottom: 10px;
  color: #496659;
}
.conversation-body > aside button.active {
  background: #e3f5ee;
  color: #008670;
}
.conversation-body > aside span {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
  font-size: 11px;
  margin-top: 10px;
}
.conversation-body > main {
  padding: 22px;
  overflow: auto;
  min-height: 0;
  min-width: 0;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.message {
  padding: 18px;
  background: #f5f7f6;
  border: 1px solid #e6ebe8;
  border-radius: 10px;
}
.expected {
  border-style: dashed;
  background: #fcfdfc;
}
.answer {
  background: #eff9f4;
}
.conversation-turn h4 {
  color: #687f73;
  font-size: 13px;
}
.conversation-turn pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
  line-height: 1.8;
}
.evaluation-panel {
  padding: 22px;
  max-height: calc(75vh + 80px);
  overflow: auto;
}
.score-box {
  margin: 20px 0;
  padding: 22px;
  border: 1px solid #d9eae1;
  border-radius: 12px;
  background: #f4faf7;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 15px;
}
.score-box > span:first-child {
  width: 100%;
  font-size: 13px;
  color: #738a7c;
}
.score-box strong {
  font-size: 38px;
  color: #00a489;
}
.score-box strong small {
  font-size: 12px;
  color: #879d90;
  font-weight: 400;
  margin-left: 8px;
}
.dimension-bars {
  border: 1px solid #e0e8e4;
  padding: 18px;
  border-radius: 12px;
  margin-bottom: 22px;
}
.dimension-bars h3 {
  font-size: 15px;
}
.dimension-bars h3 small {
  float: right;
  font-weight: 400;
  color: #8a9a91;
}
.dimension-bars p {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  margin: 18px 0 8px;
}
.dimension-bars b {
  color: #00a489;
}
.sample-footer {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  background: white;
  border: 1px solid #e0e8e4;
  border-radius: 10px;
  margin-top: 22px;
  padding: 16px;
  font-size: 12px;
  color: #718478;
}
.secondary.selected {
  background: #e4f7ee;
  color: #00836c;
}
summary {
  cursor: pointer;
}
@media (max-width: 1100px) {
  .task-kpis {
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
  }
  .conversation-layout {
    grid-template-columns: 1fr;
  }
  .evaluation-panel {
    max-height: none;
  }
}
@media (max-width: 700px) {
  .config-cards {
    grid-template-columns: 1fr;
  }
  .task-hero {
    padding: 16px;
    gap: 12px;
    flex-wrap: wrap;
  }
  .task-hero h1 {
    font-size: 18px;
  }
  .hero-icon {
    display: none;
  }
  .conversation-body {
    grid-template-columns: 110px 1fr;
  }
  .conversation-body > aside {
    padding: 6px;
  }
  .conversation-body > main {
    padding: 12px;
  }
  .sample-head {
    flex-wrap: wrap;
  }
  .task-kpis {
    grid-template-columns: repeat(2, 1fr);
  }
  .result-filters {
    flex-wrap: wrap;
  }
}
</style>
