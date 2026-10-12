<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import VerificationCases from './VerificationCases.vue';
import {
  analysisTitle,
  relatedClusters,
  clusterName,
  guidance,
} from '../utils/optimization-evidence';
const skillLabels: Record<string, [string, string]> = {
  loan_approval: ['贷款审批', '评估申请并选择审批动作'],
  repayment_plan: ['还款计划', '计算贷款还款安排'],
  complaint: ['投诉处理', '登记与申请相关的投诉'],
  credit_inquiry: ['征信查询', '查询申请的风险分类'],
};
function titleFor(key: string, row: any) {
  return analysisTitle(key, row, data.value);
}
const reviewChoices = ref<Record<string, string>>({});
const activeCluster = ref(''),
  verificationFinding = ref<any>(null);
const sourceReport = ref<any>(null);
const analysisMode = ref('server');
const capability = ref<{ configured: boolean; reason?: string | null } | null>(null),
  capabilityError = ref('');
async function checkCapability() {
  capabilityError.value = '';
  try {
    capability.value = await request('/skill-analysis/capability');
  } catch {
    capability.value = null;
    capabilityError.value = '无法读取分析服务状态，请重试。';
  }
}
onMounted(checkCapability);
watch(analysisMode, () => {
  sequence++;
  data.value = null;
  reviews.value = [];
  reviewChoices.value = {};
  selectedSkill.value = '';
  verificationFinding.value = null;
  error.value = '';
  historyId.value = '';
});
async function focusItem(id: string) {
  const key = (data.value?.hypotheses ?? []).some((r: any) => r.id === id)
    ? 'hypotheses'
    : 'suggestions';
  const row = (data.value?.[key] ?? []).find((r: any) => r.id === id);
  if (row && !relatedClusters(key, row, data.value).some((c: any) => c.id === activeCluster.value))
    activeCluster.value = relatedClusters(key, row, data.value)[0]?.id ?? '';
  await nextTick();
  document
    .getElementById('analysis-item-' + id)
    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
async function showContext(id: string) {
  activeCluster.value = id;
  await nextTick();
  document
    .getElementById('analysis-context')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
import { ElMessageBox, ElMessage } from 'element-plus';
import { api, request, pretty, type EvaluationRun } from '../../../api/evaluations';
const props = defineProps<{ mode: string; runs: EvaluationRun[]; initialId?: string }>();
const emit = defineEmits<{
  runVersion: [source: { id: string; version: number; caseIds: string[]; targetVersion: string }];
}>();
type Descriptor = {
  prompt?: string;
  content_sha256: string;
  ref: { external_version_id: string };
  skills: {
    external_skill_id: string;
    external_version_id: string;
    name: string;
    description?: string;
  }[];
};
type Review = {
  item_id?: string;
  finding_id?: string;
  decision: string;
  reviewer_id: string;
  comment?: string;
  created_at?: string;
  reviewed_at?: string;
};
const selected = ref(props.initialId ?? ''),
  versions = ref<{ id: string; label: string }[]>([]),
  descriptors = ref<Descriptor[]>([]);
const busy = ref(false),
  error = ref(''),
  data = ref<Record<string, any> | null>(null),
  reviews = ref<Review[]>([]),
  history = ref<Record<string, any>[]>([]);
const selectedSkill = ref(''),
  reviewer = ref(''),
  historyId = ref('');
const displayError = computed(() =>
  error.value.includes('Skill analysis is unavailable')
    ? '服务端尚未启用 Skill 静态分析（HTTP 503）。请检查服务端模型配置并启用分析服务；本次没有生成分析报告。'
    : error.value,
);
const executionFeedback = ref<HTMLElement | null>(null);
let sequence = 0;
const options = computed(() =>
  props.mode === 'analysis'
    ? versions.value.map((v) => ({
        ...v,
        label:
          (v.id === 'loan-agent-v1-risky'
            ? '旧方案（可能直接批准高风险申请）'
            : v.id === 'loan-agent-v2-fixed'
              ? '修复方案（高风险转人工复核）'
              : v.label) +
          ' · ' +
          v.id,
      }))
    : props.runs
        .filter((r) => r.status === 'completed')
        .map((r) => ({
          id: r.id,
          label: `${r.manifest.target.display_name} · ${r.manifest.target.ref.external_version_id} · ${r.manifest.dataset.dataset_name} v${r.manifest.dataset.version} · ${new Date(r.created_at).toLocaleString()} · ${r.id.slice(0, 8)}`,
        })),
);
const descriptor = computed(() =>
  descriptors.value.find((d) => d.ref.external_version_id === selected.value),
);
watch(selected, async () => {
  sequence++;
  data.value = null;
  reviews.value = [];
  reviewChoices.value = {};
  activeCluster.value = '';
  verificationFinding.value = null;
  sourceReport.value = null;
  error.value = '';
  history.value = [];
  historyId.value = '';
  selectedSkill.value = '';
  if (props.mode === 'analysis' && descriptor.value) await loadHistory();
});
onMounted(async () => {
  try {
    const [v, d] = await Promise.all([
      api.versions(),
      request<Descriptor[]>('/target-descriptors'),
    ]);
    versions.value = v;
    descriptors.value = d;
    if (props.initialId && props.mode === 'optimizer') await execute();
  } catch (e) {
    error.value = String(e);
  }
});
async function loadHistory() {
  const hash = descriptor.value?.content_sha256;
  if (!hash) return;
  try {
    const response = await request<Record<string, any>[]>(
      '/skill-analysis/reports?target_descriptor_sha256=' + hash,
    );
    if (descriptor.value?.content_sha256 === hash) history.value = response;
  } catch (e) {
    error.value = String(e);
  }
}
async function openHistory() {
  if (!historyId.value) return;
  const ticket = ++sequence;
  busy.value = true;
  try {
    const result = await request<{ report: Record<string, any>; reviews: Review[] }>(
      '/skill-analysis/reports/' + historyId.value,
    );
    if (ticket === sequence) {
      data.value = result.report;
      reviews.value = result.reviews;
      error.value = '';
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
async function execute() {
  if (busy.value || !selected.value) return;
  if (props.mode === 'analysis' && analysisMode.value === 'server' && !capability.value?.configured)
    return;
  busy.value = true;
  error.value = '';
  data.value = null;
  reviews.value = [];
  activeCluster.value = '';
  reviewChoices.value = {};
  const id = selected.value,
    ticket = ++sequence;
  try {
    if (props.mode === 'analysis') {
      if (analysisMode.value === 'mock') {
        const risky =
          descriptor.value?.prompt?.includes(
            'May approve high-risk applications without human review.',
          ) && descriptor.value.skills.some((s) => s.external_skill_id === 'loan_approval');
        data.value = {
          id: 'mock-static-' + selected.value,
          mock: true,
          findings: risky
            ? [
                {
                  id: 'mock-approval',
                  title: '演示 · 高风险审批缺少人工复核约束',
                  skill_ids: ['loan_approval'],
                  reason:
                    '示例中智能体提示词允许高风险申请未经人工复核直接审批；需核对贷款审批的业务约束。',
                  evidence: [{ field: '智能体提示词', text: descriptor.value!.prompt }],
                  suggestions: [
                    '将高风险申请明确转交人工复核，禁止直接执行 approve_loan；在审批技能中同步这一限制。',
                  ],
                  verification:
                    '使用高风险申请样本重新测评，检查是否调用 request_human_review，且没有调用 approve_loan。',
                },
              ]
            : [],
          errors: [],
          sample_note: risky
            ? '基于当前定义构造的交互样例，非模型分析结论。'
            : '该版本没有预置问题样例，不代表已通过静态分析。',
        };

        return;
      }
      const response = await request<Record<string, any>>('/evaluations/skill-analysis', 'POST', {
        version: id,
      });
      if (ticket === sequence) {
        data.value = response;
        historyId.value = response.id;
        await loadHistory();
      }
    } else {
      const [response, reviewData] = await Promise.all([
        request<Record<string, any>>(`/runs/${id}/optimization`),
        request<Review[]>(`/runs/${id}/optimization/reviews`),
      ]);
      if (ticket === sequence) {
        data.value = response;
        reviews.value = reviewData;
        const report = await api.report(id);
        if (ticket === sequence) sourceReport.value = report;
      }
    }
  } catch (e) {
    if (ticket === sequence) {
      error.value = String(e);
      ElMessage.error(displayError.value);
      await nextTick();
      executionFeedback.value?.scrollIntoView({ block: 'nearest' });
      executionFeedback.value?.focus();
    }
  } finally {
    busy.value = false;
  }
}
const labels: Record<string, string> = {
  confirmed: '已确认',
  dismissed: '已排除',
  accepted_risk: '已接受风险',
  deferred: '暂缓处理',
};
function latest(id: string) {
  return reviews.value.find((r) => (r.item_id ?? r.finding_id) === id);
}
async function review(id: string, decision: string) {
  if (!reviewer.value.trim()) {
    ElMessage.warning('请先填写复核人');
    return;
  }
  if (!decision || busy.value) return;
  if (data.value?.mock) {
    reviews.value = [
      {
        finding_id: id,
        decision,
        reviewer_id: reviewer.value.trim(),
        comment: '演示复核，仅本页展示，不写入服务端',
      },
      ...reviews.value,
    ];
    return;
  }
  const source = selected.value,
    reportId = data.value?.id;
  try {
    const { value } = await ElMessageBox.prompt(
      '记录判断依据；此操作不修改模型建议、原始报告或智能体。',
      '复核说明',
      {
        inputType: 'textarea',
        inputValidator: (v) => !!v?.trim() || '请填写说明',
        confirmButtonText: '保存状态',
        cancelButtonText: '取消',
      },
    );
    busy.value = true;
    const path =
      props.mode === 'analysis'
        ? `/skill-analysis/reports/${reportId}/findings/${id}/review`
        : `/runs/${source}/optimization/items/${id}/reviews`;
    const saved = await request<Review>(path, props.mode === 'analysis' ? 'PUT' : 'POST', {
      decision,
      reviewer_id: reviewer.value.trim(),
      comment: value,
    });
    if (selected.value === source) reviews.value = [saved, ...reviews.value];
    ElMessage.success('复核状态已保存');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = String(e);
  } finally {
    busy.value = false;
  }
}
const sections = computed(() => {
  if (props.mode === 'analysis')
    return ['findings', 'errors']
      .map(
        (key) =>
          [
            key,
            (data.value?.[key] ?? []).filter(
              (r: any) =>
                key !== 'findings' ||
                !selectedSkill.value ||
                (r.skill_ids ?? []).includes(selectedSkill.value),
            ),
          ] as [string, Record<string, any>[]],
      )
      .filter(([key, rows]) => key === 'findings' || rows.length);
  return ['clusters', 'hypotheses', 'suggestions']
    .map(
      (key) =>
        [
          key,
          (data.value?.[key] ?? []).filter(
            (r: any) =>
              key === 'clusters' ||
              (activeCluster.value &&
                relatedClusters(key, r, data.value).some((c: any) => c.id === activeCluster.value)),
          ),
        ] as [string, Record<string, any>[]],
    )
    .filter(([, rows]) => rows.length);
});
const orphaned = computed(() =>
  ['hypotheses', 'suggestions'].flatMap((key) =>
    (data.value?.[key] ?? []).filter((r: any) => !relatedClusters(key, r, data.value).length),
  ),
);
const templateLabels1: Record<string, string> = {
  findings: '发现项',
  errors: '分析异常',
  clusters: '失败聚类',
  suggestions: '改进建议',
  hypotheses: '根因假设',
  failure_clusters: '失败聚类',
  risk_matrix: '静态风险关系',
};
const templateLabels2: Record<string, string> = {
  critical: '紧急',
  high: '高',
  medium: '中',
  low: '低',
};
</script>
<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">{{ mode === 'analysis' ? 'Skill 静态分析' : '调优中心' }}</h1>
      <p class="page-sub">
        {{
          mode === 'analysis'
            ? '按精确版本查看 Skill 关系、历史分析与复核结果'
            : '从失败证据定位原因，记录建议复核状态，再进入回归验证'
        }}
      </p>
    </div>
    <button
      v-if="mode === 'analysis'"
      class="secondary"
      :disabled="busy"
      @click="analysisMode = analysisMode === 'server' ? 'mock' : 'server'"
    >
      {{ analysisMode === 'server' ? '查看演示样例' : '返回正式分析' }}</button
    ><a v-if="mode === 'optimizer' && selected" :href="'#results/' + selected" class="link"
      >查看原始报告 →</a
    >
  </div>
  <section class="card">
    <div v-if="mode === 'analysis' && analysisMode === 'server'" role="status">
      <p>
        {{
          capabilityError ||
          (capability?.configured
            ? '分析器已配置；运行时仍需连接模型服务。'
            : (capability?.reason ?? '正在读取服务状态…'))
        }}
      </p>
      <button class="link" @click="checkCapability">刷新服务状态</button>
    </div>
    <p v-if="mode === 'analysis' && analysisMode === 'mock'" class="muted" role="status">
      <span class="badge warn">演示模式</span> 预设样例，不调用模型，不保存报告或复核记录。
    </p>
    <h3 v-if="mode === 'analysis'">第一步：选择要检查的智能体版本</h3>
    <div class="toolbar">
      <label class="field"
        >{{ mode === 'analysis' ? '检查对象' : '已完成测评任务'
        }}<select
          class="input"
          v-model="selected"
          :disabled="busy"
          :aria-label="mode === 'analysis' ? '检查对象' : '已完成测评任务'"
        >
          <option value="">请选择</option>
          <option v-for="o in options" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select></label
      ><button
        class="primary"
        :disabled="
          !selected ||
          busy ||
          (mode === 'analysis' && analysisMode === 'server' && !capability?.configured)
        "
        @click="execute"
      >
        {{
          busy
            ? '正在处理…'
            : mode === 'analysis'
              ? analysisMode === 'mock'
                ? '展示样例'
                : '运行分析'
              : '查看分析结果'
        }}
      </button>
    </div>
    <div ref="executionFeedback" tabindex="-1" aria-live="polite">
      <p v-if="busy" role="status" class="notice">
        请求已发出，正在等待服务端返回；请勿重复点击。超过 30 秒将提示超时。
      </p>
      <div v-if="error" class="notice error" role="alert">
        <b>未能完成分析</b>
        <p>{{ displayError }}</p>
        <p v-if="error.includes('Skill analysis is unavailable')">
          需配置服务端 Judge 模型并重启对应服务。若只体验交互，请点击右上角“查看演示样例”。
        </p>
        <details>
          <summary>服务端原始信息</summary>
          {{ error }}
        </details>
      </div>
      <p v-else-if="data && !busy" role="status" class="muted">
        {{ data.mock ? '样例已展示（非真实分析结果）' : '分析数据已返回' }}
      </p>
    </div>
    <template v-if="mode === 'analysis' && descriptor"
      ><h3>第二步：确认要检查的技能职责</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>Skill / 版本</th>
            <th>职责描述</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(s, rowIndex1) in descriptor.skills" :key="rowIndex1">
            <td>
              {{ skillLabels[s.external_skill_id]?.[0] ?? s.name
              }}<small class="muted"> · {{ s.external_version_id }}</small>
            </td>
            <td>{{ skillLabels[s.external_skill_id]?.[1] ?? s.description ?? '未提供描述' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!history.length && analysisMode === 'server'" class="muted">
        暂无历史报告
      </p></template
    >
    <div v-if="mode === 'analysis' && descriptor && (data || history.length)" class="form-grid">
      <label v-if="analysisMode === 'server'" class="field"
        >历史分析<select class="input" v-model="historyId" :disabled="busy" @change="openHistory">
          <option value="">选择历史报告</option>
          <option v-for="r in history" :key="r.id" :value="r.id">
            {{ new Date(r.created_at).toLocaleString() }} · {{ r.status }} ·
            {{ r.findings.length }} 项
          </option>
        </select></label
      >
    </div>
  </section>
  <section v-if="data" class="card section-gap">
    <div v-if="mode === 'optimizer' && data.failed_result_count === 0" class="notice warn">
      <b>{{
        sourceReport?.release_gate.reason_code === 'no_applicable_results'
          ? '没有适用的评估检查'
          : '没有可聚类的失败结果'
      }}</b>
      <p>
        {{
          sourceReport?.release_gate.reason_code === 'no_applicable_results'
            ? '请补充样本期望并选择匹配评估器；当前不能据此判断智能体质量。'
            : '调优聚类只分析业务失败项；执行异常、待复核和不适用项请查看原报告。'
        }}
      </p>
      <a class="link" :href="'#datasets/' + data.dataset_id + '?version=' + data.dataset_version"
        >查看测评集版本 →</a
      >
    </div>
    <div v-if="mode === 'optimizer' && sourceReport" class="toolbar">
      <a class="link" :href="'#results/' + selected + '?action=regression'"
        >选择问题样本并创建回归草稿 →</a
      >
    </div>
    <div class="toolbar">
      <h2 class="section-title">
        {{ mode === 'analysis' ? '第三步：查看问题与修改建议' : '分析结果' }}
      </h2>
      <label class="field"
        >复核人<input
          class="input"
          v-model="reviewer"
          placeholder="填写姓名或工号（当前为人工声明）"
      /></label>
    </div>
    <p v-if="data.sample_note" class="muted">{{ data.sample_note }}</p>
    <label v-if="mode === 'analysis' && descriptor" class="field"
      >筛选报告中涉及的 Skill<select
        class="input"
        v-model="selectedSkill"
        aria-label="筛选问题 Skill"
      >
        <option value="">全部 Skill</option>
        <option
          v-for="s in descriptor.skills"
          :key="s.external_skill_id"
          :value="s.external_skill_id"
        >
          {{ skillLabels[s.external_skill_id]?.[0] ?? s.name }} · {{ s.external_version_id }}
        </option>
      </select></label
    >
    <div v-for="[key, rows] in sections" :key="key" class="section-gap">
      <div
        v-if="
          key === 'hypotheses' ||
          (key === 'suggestions' && !sections.some(([k]) => k === 'hypotheses'))
        "
        id="analysis-context"
        class="toolbar"
      >
        <b
          >当前问题：{{
            clusterName(data?.clusters?.find((c: any) => c.id === activeCluster) ?? {})
          }}</b
        ><button class="link" @click="activeCluster = ''">收起关联分析</button>
      </div>
      <h3>{{ templateLabels1[key] ?? key }}</h3>
      <p v-if="!rows.length" class="muted">
        {{ key === 'findings' ? '当前筛选下没有发现项；不代表该 Skill 已通过检查。' : '无记录' }}
      </p>
      <article
        v-for="(row, index) in rows"
        :key="row.id ?? index"
        :id="'analysis-item-' + row.id"
        class="mini-card section-gap"
      >
        <div class="toolbar">
          <b>{{ titleFor(key, row) }}</b
          ><label
            v-if="['findings', 'hypotheses', 'suggestions'].includes(key) && row.id"
            class="field"
            >复核状态<select
              class="input"
              :disabled="busy"
              :value="reviewChoices[row.id] ?? latest(row.id)?.decision ?? ''"
              @change="reviewChoices[row.id] = ($event.target as HTMLSelectElement).value"
            >
              <option value="">未复核</option>
              <option v-for="(text, key) in labels" :key="key" :value="key">
                {{ text }}
              </option></select
            ><button
              class="secondary"
              :disabled="busy || !reviewChoices[row.id]"
              @click="review(row.id, reviewChoices[row.id])"
            >
              保存复核
            </button></label
          >
        </div>
        <button v-if="key === 'clusters'" class="secondary" @click="showContext(row.id)">
          查看关联原因与建议
        </button>
        <template v-if="key === 'suggestions'"
          ><p>
            <b>优先级：</b>{{ templateLabels2[row.priority] ?? row.priority }} ·
            <b>具体修改对象：</b>{{ row.target_id ?? '后端未定位，需根据证据确认' }}
          </p>
          <section v-for="c in relatedClusters(key, row, data)" :key="c.id">
            <h4>{{ clusterName(c) }}</h4>
            <h4>怎么改</h4>
            <p>{{ guidance(c, row.target)[0] }}</p>
            <h4>如何验证</h4>
            <p>{{ guidance(c, row.target)[1] }}</p>
          </section>
          <p v-if="!relatedClusters(key, row, data).length">
            未关联到失败检查，请查看原始建议，不推断具体修改。
          </p></template
        >
        <p v-else-if="key === 'hypotheses'">
          关联 {{ row.cluster_ids?.length ?? 0 }} 个失败聚类、{{ row.result_ids?.length ?? 0 }}
          条失败结果。规则计算的证据强度
          {{ Math.round((row.confidence ?? 0) * 100) }}%，不代表根因成立的概率。
        </p>
        <p v-else-if="key !== 'clusters'">
          {{ row.reason ?? row.explanation ?? row.description ?? '' }}
        </p>
        <div
          v-if="['clusters', 'hypotheses', 'suggestions'].includes(key)"
          class="failure-evidence"
        >
          <div v-for="c in relatedClusters(key, row, data)" :key="c.id">
            <p v-if="key !== 'clusters' && relatedClusters(key, row, data).length > 1">
              <b>{{ clusterName(c) }}</b>
            </p>
            <p v-for="m in c.members" :key="m.result_id">{{ m.case_id }}：{{ m.reason }}</p>
          </div>
        </div>
        <template v-if="key === 'findings'">
          <p>
            <b>涉及 Skill：</b
            >{{
              (row.skill_ids ?? []).map((id: string) => skillLabels[id]?.[0] ?? id).join('、') ||
              '智能体整体'
            }}
          </p>
          <h4>问题证据</h4>
          <pre>{{ pretty(row.evidence ?? []) }}</pre>
          <h4>修改建议</h4>
          <ul v-if="row.suggestions?.length">
            <li v-for="(s, rowIndex2) in row.suggestions" :key="rowIndex2">{{ s }}</li>
          </ul>
          <p v-else>{{ row.recommendation ?? '服务端未提供修改建议' }}</p>
          <button
            class="secondary"
            :disabled="busy || !!data.mock"
            @click="verificationFinding = row"
          >
            选择验证用例</button
          ><small v-if="data.mock" class="muted">样例发现项不用于真实测评。</small>
          <h4>验证方式</h4>
          <p>
            {{ row.verification ?? '修改对应版本定义后重新分析，并对涉及 Skill 的样本发起测评。' }}
          </p>
        </template>
        <p v-if="row.case_count != null">
          涉及 {{ row.case_count }} 条样本、{{ row.failure_count }} 条失败结果
        </p>
        <div v-if="row.cluster_ids?.length">
          <button
            v-for="(id, clusterIndex) in row.cluster_ids"
            :key="id"
            class="link"
            @click="focusItem(id)"
          >
            查看关联聚类{{ row.cluster_ids.length > 1 ? ' ' + (Number(clusterIndex) + 1) : '' }} →
          </button>
        </div>
        <div v-if="row.hypothesis_ids?.length">
          <b>对应根因假设：</b
          ><button
            v-for="(id, rowIndex3) in row.hypothesis_ids"
            :key="rowIndex3"
            class="link"
            @click="focusItem(id)"
          >
            {{ titleFor('hypotheses', data?.hypotheses?.find((x: any) => x.id === id) ?? {}) }}
          </button>
        </div>
        <div v-if="row.members?.length">
          <b>样本与执行证据：</b
          ><a
            v-for="(member, rowIndex4) in row.members"
            :key="rowIndex4"
            class="link"
            :href="'#results/' + member.run_id + '?case=' + encodeURIComponent(member.case_id)"
            >{{ member.case_id }} → 查看报告</a
          >
        </div>
        <p v-if="latest(row.id)" class="muted">
          {{ labels[latest(row.id)!.decision] }} · {{ latest(row.id)!.reviewer_id }}：{{
            latest(row.id)!.comment
          }}
        </p>
        <details>
          <summary>
            {{ data.mock ? '查看样例原始数据' : '查看后端原始证据与建议（保留原文）' }}
          </summary>
          <pre>{{ pretty(row) }}</pre>
        </details>
        <details v-if="reviews.filter((r) => (r.item_id ?? r.finding_id) === row.id).length > 1">
          <summary>复核历史</summary>
          <pre>{{ pretty(reviews.filter((r) => (r.item_id ?? r.finding_id) === row.id)) }}</pre>
        </details>
      </article>
    </div>
    <details v-if="mode === 'optimizer' && orphaned.length">
      <summary>未关联问题的分析记录 · {{ orphaned.length }} 条</summary>
      <pre>{{ pretty(orphaned) }}</pre>
    </details>
    <details>
      <summary>{{ data.mock ? '完整样例数据' : '完整后端响应' }}</summary>
      <pre>{{ pretty(data) }}</pre>
    </details>
  </section>
  <VerificationCases
    v-if="verificationFinding"
    :skill-ids="verificationFinding.skill_ids ?? []"
    :title="verificationFinding.title ?? verificationFinding.reason"
    :target-version="selected"
    @close="verificationFinding = null"
    @run="
      (source) => {
        verificationFinding = null;
        emit('runVersion', source);
      }
    "
  />
</template>
