<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import TaskEvaluatorPicker from './TaskEvaluatorPicker.vue';
import AgentTargetPicker, { type AgentTargetSelection } from './AgentTargetPicker.vue';
import { agentDirectory, localAgentDirectory } from '../../../api/agent-platform';
import { useAuthStore } from '../../../stores/modules/auth';
import { ApiError, httpRequest } from '../../../utils/request';
import { assertLocallyEnabled } from '../utils/evaluator-preferences';
import TargetStructure from './TargetStructure.vue';
import {
  api,
  request,
  type DatasetSummary,
  type EvaluatorSummary,
  type BankTarget,
} from '../../../api/evaluations';
import { recommendEvaluators } from '../utils/evaluator-guidance';
import { refreshTaskLinks, saveTaskLink, type TaskLink } from '../utils/task-links';
const props = defineProps<{
  source?: {
    id: string;
    version: number;
    caseIds?: string[];
    caseName?: string;
    targetVersion?: string;
    evaluatorId?: string;
  };
}>();
const emit = defineEmits<{ close: []; created: [link: TaskLink] }>();
const taskKind = ref<'single' | 'ab'>('single'),
  candidateVersion = ref(''),
  includeStatic = ref(false);
const platformPicker = ref<InstanceType<typeof AgentTargetPicker> | null>(null);
const platformSelection = ref<AgentTargetSelection | null>(null);
const auth = useAuthStore();
const platformDirectory = computed(() =>
  auth.loginMode === 'external' ? localAgentDirectory : agentDirectory,
);
const platformToken = computed(() => (auth.loginMode === 'bank' ? auth.token : 'local'));
const platformTeamId = computed(() => (auth.loginMode === 'bank' ? auth.teamId : ''));
function receivePlatformSelection(selection: AgentTargetSelection | null) {
  platformSelection.value = selection;
}
const gradingMode = ref<'overall' | 'per_turn'>('overall');
const staticDialog = ref(false),
  staticLoading = ref(false),
  staticError = ref('');
const staticConnection = ref<{ model: string; base_url: string; configured: boolean } | null>(null);
const staticReport = ref<any>(null),
  staticReports = ref<{ version: string; reportId: string }[]>([]);
let staticSequence = 0;
function cancelAnalysis() {
  staticSequence++;
  staticDialog.value = false;
  includeStatic.value = false;
  staticReport.value = null;
  staticReports.value = [];
  staticLoading.value = false;
}
async function confirmStatic() {
  if (taskKind.value !== 'ab' || submitting.value) return;
  const ticket = ++staticSequence;
  staticLoading.value = true;
  staticError.value = '';
  includeStatic.value = false;
  staticReport.value = null;
  staticReports.value = [];
  try {
    const reports = [];
    for (const version of taskKind.value === 'ab'
      ? [selectedVersion.value, candidateVersion.value]
      : [selectedVersion.value]) {
      const report = bankTarget.value
        ? await request<any>(
            '/skill-analysis/reports',
            'POST',
            { target_descriptor_sha256: bankTarget.value.descriptor.content_sha256 },
            240000,
          )
        : await request<any>('/evaluations/skill-analysis', 'POST', { version }, 240000);
      if (ticket !== staticSequence) return;
      if (report.status === 'failed') {
        staticReport.value = report;
        throw Error('静态分析未完成，请检查模型权限或连接。报告 ID：' + report.id);
      }
      reports.push({ version, reportId: report.id });
      if (!staticReport.value) staticReport.value = report;
    }
    staticReports.value = reports;
    includeStatic.value = true;
    staticDialog.value = false;
  } catch (e) {
    if (ticket === staticSequence) staticError.value = String(e);
  } finally {
    if (ticket === staticSequence) staticLoading.value = false;
  }
}
async function openStatic() {
  if (taskKind.value !== 'ab' || submitting.value) return;
  const ticket = ++staticSequence;
  staticDialog.value = true;
  staticError.value = '';
  staticLoading.value = true;
  try {
    const data = await request<{
      connections: { role: string; model: string; base_url: string; configured: boolean }[];
    }>('/model-runtime');
    if (ticket !== staticSequence) return;
    staticConnection.value = data.connections.find((c) => c.role === 'Skill 静态分析') ?? null;
  } catch {
    if (ticket === staticSequence) staticError.value = '读取静态分析模型配置失败，请重试。';
  } finally {
    if (ticket === staticSequence) staticLoading.value = false;
  }
}
const create = ref(true),
  submitting = ref(false),
  formLoading = ref(false),
  datasetLoading = ref(false);
let formSequence = 0;
watch(create, (open) => {
  if (!open) {
    formSequence++;
  }
});
const datasets = ref<DatasetSummary[]>([]),
  evaluators = ref<EvaluatorSummary[]>([]),
  versions = ref<{ id: string; label: string }[]>([]);
const selectedDataset = ref(''),
  selectedVersion = ref(''),
  selectedEvaluators = ref<string[]>([]);
const repetitions = ref(1),
  launchMode = ref('now'),
  scheduledAt = ref('');
const bankTargets = ref<BankTarget[]>([]),
  selectedAgent = ref('demo'),
  targetError = ref('');
const gitBranchUrl = ref('');
const bankTarget = computed(() =>
  taskKind.value === 'ab'
    ? bankTargets.value.find((t) => t.snapshot.invocation_config.mode === selectedAgent.value)
    : undefined,
);
const usesGitBranch = computed(
  () => taskKind.value === 'ab' && selectedAgent.value === 'cloudshrimp',
);
const branchOptions = computed(() =>
  bankTargets.value.filter(
    (t) => t.snapshot.invocation_config.mode === selectedAgent.value && t.git_branch_url,
  ),
);
const normalizedBranch = (value: string) => value.trim().replace(/\/+$/, '');
const branchMismatch = computed(
  () =>
    usesGitBranch.value &&
    !!bankTarget.value &&
    normalizedBranch(gitBranchUrl.value) !==
      normalizedBranch(bankTarget.value.git_branch_url ?? ''),
);
const targetDescriptor = computed(() =>
  branchMismatch.value ? undefined : bankTarget.value?.descriptor,
);
watch(
  bankTarget,
  (target) => {
    gitBranchUrl.value = usesGitBranch.value ? (target?.git_branch_url ?? '') : '';
  },
  { flush: 'sync', immediate: true },
);
watch([gitBranchUrl, selectedVersion, candidateVersion, taskKind], cancelAnalysis);
const versionOptions = computed(() =>
  bankTarget.value
    ? [
        {
          id: bankTarget.value.descriptor.ref.external_version_id,
          label: bankTarget.value.descriptor.display_name,
        },
      ]
    : versions.value,
);
watch(selectedAgent, (agent) => {
  if (taskKind.value !== 'ab') return;
  selectedVersion.value =
    agent === 'demo'
      ? (versions.value[0]?.id ?? '')
      : (bankTarget.value?.descriptor.ref.external_version_id ?? '');
  if (agent === 'demo') timeout.value = 300;
  if (agent !== 'demo') {
    concurrency.value = 1;
    timeout.value = 180;
    retries.value = 0;
    includeStatic.value = false;
  }
  if (!runSource.value?.id) {
    const d = datasets.value.find((d) =>
      agent === 'demo'
        ? d.name === '高风险贷款策略评估'
        : d.name === `独立贷款智能体 · ${agent} · test-policy-v1`,
    );
    if (d) selectedDataset.value = d.id;
  }
});
const scope = ref('all'),
  selectedCaseIds = ref<string[]>([]);
const availableCases = computed(
  () => datasetVersions.value.find((v) => v.version === selectedDatasetVersion.value)?.cases ?? [],
);
const executionCases = computed(() =>
  scope.value === 'selected'
    ? availableCases.value.filter((c) => selectedCaseIds.value.includes(c.id))
    : availableCases.value,
);
watch(repetitions, (v) => {
  if (v > 1) {
    launchMode.value = 'now';
    scheduledAt.value = '';
  }
});
const datasetVersions = ref<{ version: number; cases: any[] }[]>([]),
  selectedDatasetVersion = ref<number | null>(null);
const concurrency = ref(2),
  timeout = ref(300),
  retries = ref(0),
  formError = ref('');
const runSource = ref<{
  id: string;
  version: number;
  caseIds?: string[];
  caseName?: string;
  evaluatorId?: string;
} | null>(null);
async function openCreate(source?: {
  id: string;
  version: number;
  caseIds?: string[];
  caseName?: string;
  targetVersion?: string;
  evaluatorId?: string;
}) {
  const ticket = ++formSequence;
  formLoading.value = true;
  runSource.value = source ?? null;
  selectedAgent.value = 'demo';
  targetError.value = '';
  includeStatic.value = false;
  scope.value = source?.caseIds ? 'selected' : 'all';
  selectedCaseIds.value = source?.caseIds ?? [];
  repetitions.value = 1;
  concurrency.value = 2;
  timeout.value = 300;
  retries.value = 0;
  launchMode.value = 'now';
  scheduledAt.value = '';
  formError.value = '';
  selectedDataset.value = '';
  create.value = true;
  try {
    const [d, e] = await Promise.all([api.datasets(), api.evaluators()]);
    if (ticket !== formSequence) return;
    datasets.value = d.filter((x) => x.version !== null && !x.archived);
    evaluators.value = e.filter((x) => x.enabled && x.latest_version && x.kind !== 'hybrid');
    selectedDataset.value = source?.id || datasets.value[0]?.id || '';
    selectedEvaluators.value = source?.evaluatorId ? [source.evaluatorId] : [];
  } catch (e) {
    if (ticket === formSequence) formError.value = String(e);
  } finally {
    if (ticket === formSequence) formLoading.value = false;
  }
}
const legacyLoading = ref(false);
let legacyLoaded = false;
let legacySequence = 0;
async function loadLegacyTargets() {
  if (legacyLoaded || legacyLoading.value) return;
  const ticket = ++legacySequence;
  legacyLoading.value = true;
  targetError.value = '';
  try {
    const [v, b] = await Promise.all([
      api.versions(),
      request<BankTarget[]>('/bank-targets').catch(() => {
        if (ticket === legacySequence)
          targetError.value = '真实智能体目录暂不可用，仍可选择内置 Demo 进行 A/B 实验。';
        return [];
      }),
    ]);
    if (ticket !== legacySequence || taskKind.value !== 'ab') return;
    versions.value = v;
    bankTargets.value = b;
    selectedVersion.value =
      props.source?.targetVersion && v.some((x) => x.id === props.source?.targetVersion)
        ? props.source.targetVersion
        : (v[0]?.id ?? '');
    candidateVersion.value = v.find((x) => x.id !== selectedVersion.value)?.id ?? '';
    if (b.length && !props.source?.targetVersion)
      selectedAgent.value =
        b.find((t) =>
          datasets.value
            .find((d) => d.id === props.source?.id)
            ?.name.includes(' · ' + t.snapshot.invocation_config.mode + ' · '),
        )?.snapshot.invocation_config.mode ?? 'base';
    legacyLoaded = true;
  } catch {
    if (ticket === legacySequence)
      targetError.value = '被测智能体目录不可用，请切换回单任务后重试 A/B 实验。';
  } finally {
    if (ticket === legacySequence) legacyLoading.value = false;
  }
}
const recommended = ref<string[]>([]),
  recommendationError = ref('');
let recommendationSequence = 0;
watch(
  selectedDataset,
  async (id) => {
    const ticket = ++recommendationSequence;
    recommended.value = [];
    recommendationError.value = '';
    datasetVersions.value = [];
    selectedDatasetVersion.value = null;
    datasetLoading.value = Boolean(id);
    if (!id) return;
    try {
      const d = await request<{
        versions: {
          version: number | null;
          cases: { turns: { expectations: { kind: string; mode?: string }[] }[] }[];
        }[];
      }>(`/datasets/${encodeURIComponent(id)}`);
      if (ticket !== recommendationSequence) return;
      datasetVersions.value = d.versions.filter((v) => v.version !== null) as {
        version: number;
        cases: any[];
      }[];
      selectedDatasetVersion.value =
        runSource.value?.id === id
          ? runSource.value.version
          : (datasets.value.find((d) => d.id === id)?.version ?? null);
    } catch {
      if (ticket === recommendationSequence)
        recommendationError.value = '未能读取样本期望，请按使用场景手动选择。';
    } finally {
      if (ticket === recommendationSequence) datasetLoading.value = false;
    }
  },
  { flush: 'sync' },
);
watch(selectedVersion, () => {
  if (taskKind.value !== 'ab') return;
  if (
    candidateVersion.value === selectedVersion.value ||
    !versionOptions.value.some((v) => v.id === candidateVersion.value)
  )
    candidateVersion.value =
      versionOptions.value.find((v) => v.id !== selectedVersion.value)?.id ?? '';
});
watch(availableCases, (cases) => {
  if (datasetLoading.value) return;
  selectedCaseIds.value = selectedCaseIds.value.filter((id) => cases.some((c) => c.id === id));
});
watch([executionCases, evaluators], () => {
  recommended.value = recommendEvaluators(evaluators.value, executionCases.value);
});
async function submit() {
  if (
    submitting.value ||
    formLoading.value ||
    datasetLoading.value ||
    staticLoading.value ||
    legacyLoading.value
  )
    return;
  const platform =
    taskKind.value === 'single' ? platformPicker.value?.readSubmissionSelection() : null;
  if (taskKind.value === 'single' && !platform) {
    formError.value = '请完整选择被测智能体及版本。';
    return;
  }
  formError.value = '';
  if (gradingMode.value === 'per_turn') {
    formError.value =
      '逐轮评分尚未接入后端任务契约；当前不会以整体评分代替提交。请先选择整体评分。';
    return;
  }
  if (branchMismatch.value) {
    formError.value = '该 Git 分支尚未登记可运行版本，请选择已登记分支，或先部署并登记所填分支。';
    return;
  }
  if (taskKind.value === 'ab' && selectedAgent.value !== 'demo' && !bankTarget.value) {
    formError.value = '被测智能体不可用，请重新加载。';
    return;
  }
  if (bankTarget.value && taskKind.value === 'ab') {
    formError.value =
      '当前真实智能体目录只登记一个版本，且 A/B 接口仅支持内置双版本智能体。请登记两侧真实快照并扩展后端后再运行；不会代用 Demo。';
    return;
  }
  if (
    taskKind.value === 'ab' &&
    (!candidateVersion.value || candidateVersion.value === selectedVersion.value)
  ) {
    formError.value = 'A/B 实验需要选择两个不同版本。';
    return;
  }
  for (const [label, value, min, max] of [
    ['稳定性测试重复次数', repetitions.value, 1, 20],
    ['并发样本数', concurrency.value, 1, 30],
    ['执行超时（秒）', timeout.value, 1, bankTarget.value ? 300 : 3600],
    ['失败重试次数', retries.value, 0, 5],
  ] as [string, number, number, number][]) {
    if (!Number.isInteger(value) || value < min || value > max) {
      formError.value = `${label}必须为 ${min}—${max} 的整数`;
      return;
    }
  }
  if (taskKind.value === 'ab' && repetitions.value > 1) {
    formError.value = 'A/B 实验暂不支持重复执行，请选择单任务进行稳定性测试。';
    return;
  }
  if (
    launchMode.value === 'scheduled' &&
    (repetitions.value !== 1 ||
      !scheduledAt.value ||
      !Number.isFinite(new Date(scheduledAt.value).getTime()) ||
      new Date(scheduledAt.value).getTime() <= Date.now())
  ) {
    formError.value = '预约时间必须晚于当前时间，且只支持单次普通评测。';
    return;
  }
  const dataset = datasets.value.find((d) => d.id === selectedDataset.value);
  if (!dataset || selectedDatasetVersion.value === null) {
    formError.value = '请选择已发布的评测集及版本。';
    return;
  }
  if (taskKind.value === 'ab' && !selectedVersion.value) {
    formError.value = '请选择智能体版本。';
    return;
  }
  if (!selectedEvaluators.value.length) {
    formError.value =
      '尚未选择评估器。请在“评估方式”中勾选至少一个评估器，或点击“采用推荐评估器”。';
    return;
  }
  const snapshot = {
    kind: taskKind.value,
    datasetId: dataset.id,
    datasetVersion: selectedDatasetVersion.value,
    caseIds: scope.value === 'selected' ? [...selectedCaseIds.value] : undefined,
    evaluatorIds: [...selectedEvaluators.value],
    chosen: evaluators.value.filter((e) => selectedEvaluators.value.includes(e.id)),
    concurrency: concurrency.value,
    timeout: timeout.value,
    retries: retries.value,
    repetitions: repetitions.value,
    scheduledFor:
      launchMode.value === 'scheduled' ? new Date(scheduledAt.value).toISOString() : undefined,
    baseline: selectedVersion.value,
    candidate: candidateVersion.value,
    staticReports: taskKind.value === 'ab' && includeStatic.value ? [...staticReports.value] : [],
  };
  submitting.value = true;
  formError.value = '';
  let creating = false;
  let validationError = '';
  const invalid = (message: string): never => {
    validationError = message;
    throw Error(message);
  };
  try {
    const exact = await request<{ cases: any[] }>(
      `/datasets/${encodeURIComponent(snapshot.datasetId)}/versions/${snapshot.datasetVersion}`,
    );
    const caseIds = snapshot.caseIds;
    if (!exact.cases.length || caseIds?.length === 0) invalid('请选择至少一条用例。');
    if (caseIds) {
      exact.cases = exact.cases.filter((c) => caseIds.includes(c.id));
      if (exact.cases.length !== caseIds.length) invalid('所选用例不在当前发布版本中。');
    }
    if (platform) {
      const incompatible = exact.cases.filter(
        (c) =>
          Object.keys(c.initial_state ?? {}).length > 0 ||
          c.turns.some(
            (t: { input?: Record<string, unknown> }) =>
              !t.input ||
              Object.keys(t.input).length !== 1 ||
              typeof t.input.txt !== 'string' ||
              !t.input.txt.trim(),
          ),
      );
      if (incompatible.length)
        invalid(
          `所选评测集有 ${incompatible.length} 条用例包含业务初始状态或非纯文本输入，平台目标仅支持纯文本（txt）用例；请选择如“平台模拟验收”类评测集。`,
        );
    }
    const chosen = snapshot.chosen;
    if (chosen.length !== snapshot.evaluatorIds.length) invalid('所选评估器已不可用，请重新选择。');
    try {
      assertLocallyEnabled(snapshot.evaluatorIds);
    } catch {
      invalid('所选评估器已在本地停用，请重新选择。');
    }
    if (chosen.every((e) => e.kind === 'rule') && !recommendEvaluators(chosen, exact.cases).length)
      invalid('所选评估器与样本期望没有适用检查。请补充期望或调整评估器。');
    const uncovered = exact.cases.filter(
      (c) => chosen.every((e) => e.kind === 'rule') && !recommendEvaluators(chosen, [c]).length,
    );
    if (uncovered.length)
      await ElMessageBox.confirm(
        `${uncovered.length} 条用例没有匹配检查，将标为不适用。是否继续？`,
        '检查覆盖范围',
        { confirmButtonText: '继续评测', cancelButtonText: '返回修改' },
      );
    creating = true;
    if (platform) {
      const target = platform.target;
      const created = await httpRequest<unknown>('/agent-platform/evaluations', {
        method: 'POST',
        headers: { 'X-Agent-Platform-Token': platform.token },
        data: {
          target: {
            ...(target.teamId ? { team_id: target.teamId } : {}),
            agent_id: target.agentId,
            type_group: target.typeGroup,
            agent_version: target.agentVersion,
            ...(target.typeGroup === 'abcclaw' ? { branch_id: target.branchId } : {}),
          },
          dataset_id: snapshot.datasetId,
          dataset_version: snapshot.datasetVersion,
          ...(caseIds ? { case_ids: caseIds } : {}),
          evaluator_ids: snapshot.evaluatorIds,
          max_parallel_cases: snapshot.concurrency,
          timeout_seconds: snapshot.timeout,
          max_retries: snapshot.retries,
          repetitions: snapshot.repetitions,
          ...(snapshot.scheduledFor ? { scheduled_for: snapshot.scheduledFor } : {}),
        },
      });
      const link = platformTaskLink(created, snapshot.repetitions);
      let refreshed = true;
      try {
        await refreshTaskLinks();
      } catch {
        refreshed = false;
      }
      window.dispatchEvent(new Event('task-links-updated'));
      emit('created', link);
      if (refreshed) ElMessage.success('评测任务已提交');
      else
        ElMessage.warning(
          `任务已创建（${link.id}），但列表刷新失败，请刷新任务列表；请勿重复提交。`,
        );
      return;
    }
    const pair = await request<{ baseline: { run_id: string }; candidate: { run_id: string } }>(
      '/run-comparisons',
      'POST',
      {
        baseline_version: snapshot.baseline,
        candidate_version: snapshot.candidate,
        dataset_id: snapshot.datasetId,
        dataset_version: snapshot.datasetVersion,
        evaluators: snapshot.chosen.map((e) => ({ id: e.id, version: e.latest_version! })),
      },
    );
    const link: TaskLink = {
      id: pair.baseline.run_id,
      kind: 'ab',
      runIds: [pair.baseline.run_id, pair.candidate.run_id],
      staticReports: snapshot.staticReports,
    };
    try {
      await saveTaskLink(link);
    } catch {
      throw Error(
        '运行已创建，但任务关联保存失败；请勿重复提交。运行 ID：' + link.runIds.join('、'),
      );
    }
    emit('created', link);
    ElMessage.success(
      link.staticReports.some((x) => x.error)
        ? '运行已提交，静态分析未完成，请查看任务详情'
        : '评测任务已提交',
    );
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      formError.value =
        snapshot.kind === 'ab'
          ? String(e)
          : validationError ||
            (!creating
              ? '读取评测配置失败，请重试。'
              : e instanceof ApiError && e.status >= 400 && e.status < 500
                ? '任务提交被拒绝，请检查访问权限、目标及执行设置后重试。'
                : '暂时无法确认任务是否创建成功，请先检查任务列表，勿重复提交。');
    }
  } finally {
    submitting.value = false;
  }
}

function platformTaskLink(value: unknown, repetitions: number): TaskLink {
  const task = value as { id?: unknown; kind?: unknown; run_ids?: unknown } | null;
  const kind = repetitions > 1 ? 'stability' : 'single';
  const validId = (id: unknown): id is string => typeof id === 'string' && id.trim().length > 0;
  if (
    !task ||
    !validId(task.id) ||
    task.kind !== kind ||
    !Array.isArray(task.run_ids) ||
    task.run_ids.length !== repetitions ||
    !task.run_ids.every(validId) ||
    new Set(task.run_ids).size !== task.run_ids.length
  )
    throw Error('Invalid task response');
  return { id: task.id, kind, runIds: [...task.run_ids], staticReports: [] };
}

watch(taskKind, (kind) => {
  platformSelection.value = null;
  formError.value = '';
  cancelAnalysis();
  if (kind !== 'ab') {
    legacySequence++;
    legacyLoading.value = false;
    targetError.value = '';
  }
  if (kind === 'ab') {
    void loadLegacyTargets();
    if (!candidateVersion.value)
      candidateVersion.value =
        versionOptions.value.find((v) => v.id !== selectedVersion.value)?.id ?? '';
    repetitions.value = 1;
    scope.value = 'all';
    launchMode.value = 'now';
    concurrency.value = 1;
    timeout.value = 300;
    retries.value = 0;
  }
});
onBeforeUnmount(() => {
  formSequence++;
  recommendationSequence++;
  legacySequence++;
  cancelAnalysis();
  platformSelection.value = null;
});
onMounted(() => void openCreate(props.source));
</script>
<template>
  <el-dialog
    :model-value="true"
    @close="emit('close')"
    :show-close="!submitting"
    :close-on-press-escape="!submitting"
    title="新建评测任务"
    width="min(1080px, 96vw)"
    class="task-create-dialog"
    top="3vh"
    :close-on-click-modal="false"
  >
    <p v-if="formLoading || datasetLoading" role="status">正在加载任务配置…</p>
    <p v-if="targetError" role="alert">{{ targetError }}</p>

    <div class="form-section-heading full">
      <span>01</span>
      <div><h3>任务类型</h3></div>
    </div>
    <div class="task-kind-choice" aria-label="任务类型">
      <button
        type="button"
        :class="{ selected: taskKind === 'single' }"
        :disabled="submitting || formLoading"
        @click="taskKind = 'single'"
      >
        <b>单任务</b></button
      ><button
        type="button"
        :class="{ selected: taskKind === 'ab' }"
        :disabled="submitting || formLoading"
        @click="taskKind = 'ab'"
      >
        <b>A/B 实验</b>
      </button>
    </div>
    <fieldset
      :disabled="submitting || formLoading || legacyLoading"
      class="form-grid task-create-grid"
    >
      <div class="form-section-heading full">
        <span>02</span>
        <div><h3>评测对象</h3></div>
      </div>
      <AgentTargetPicker
        v-if="taskKind === 'single'"
        ref="platformPicker"
        class="full"
        :directory="platformDirectory"
        :token="platformToken"
        :team-id="platformTeamId"
        :disabled="submitting || formLoading"
        @selection-change="receivePlatformSelection"
      />
      <p v-if="taskKind === 'single'" class="muted full">
        平台目录暂未提供图谱与静态分析所需信息，当前无法展示智能体图谱或进行静态分析。
      </p>
      <p v-if="legacyLoading" class="full" role="status">正在加载 A/B 智能体目录…</p>
      <div
        v-if="taskKind === 'ab'"
        class="target-choice full"
        :class="{ 'is-ab': taskKind === 'ab', 'has-git-branch': usesGitBranch }"
      >
        <label class="field"
          >智能体 ID<select class="input" aria-label="智能体" v-model="selectedAgent">
            <option
              v-for="t in bankTargets"
              :key="t.snapshot.invocation_config.mode"
              :value="t.snapshot.invocation_config.mode"
            >
              {{ t.descriptor.ref.external_target_id }} · {{ t.descriptor.display_name }}
            </option>
            <option value="demo">贷款审批演示智能体（内置 Demo）</option>
          </select></label
        >
        <label v-if="usesGitBranch" class="field git-branch-field"
          >Git 仓库分支地址<input
            class="input"
            type="text"
            list="registered-target-branches"
            v-model="gitBranchUrl"
            aria-label="Git 仓库分支地址"
            :disabled="!bankTarget?.git_branch_url"
            placeholder="填写或选择 Git 仓库分支地址"
            autocomplete="off"
            spellcheck="false"
          /><datalist id="registered-target-branches">
            <option v-for="t in branchOptions" :key="t.git_branch_url!" :value="t.git_branch_url!">
              本地测试服务分支
            </option>
          </datalist></label
        >
        <label class="field"
          >{{ taskKind === 'ab' ? '实验 A · 基线版本' : '智能体版本'
          }}<select
            aria-label="智能体版本"
            class="input"
            v-model="selectedVersion"
            :disabled="branchMismatch"
          >
            <option v-if="branchMismatch" :value="selectedVersion">该分支暂无可运行版本</option>
            <template v-else
              ><option v-for="v in versionOptions" :key="v.id" :value="v.id">
                {{
                  v.id === 'loan-agent-v1-risky'
                    ? '旧方案 v1（风险版本）'
                    : v.id === 'loan-agent-v2-fixed'
                      ? '修正方案 v2'
                      : v.label
                }}
                · {{ v.id }}
              </option></template
            >
          </select></label
        >
        <label v-if="taskKind === 'ab'" class="field"
          >实验 B · 候选版本<select
            class="input"
            v-model="candidateVersion"
            aria-label="实验 B · 候选版本"
          >
            <option value="">请选择不同的候选版本</option>
            <option
              v-for="v in versionOptions"
              :key="v.id"
              :value="v.id"
              :disabled="v.id === selectedVersion"
            >
              {{
                v.id === 'loan-agent-v1-risky'
                  ? '旧方案 v1（风险版本）'
                  : v.id === 'loan-agent-v2-fixed'
                    ? '修正方案 v2'
                    : v.label
              }}
              · {{ v.id }}
            </option>
          </select></label
        >
        <p v-if="taskKind === 'ab'" class="target-note">
          {{ bankTarget ? '该智能体暂不支持双版本 A/B' : '内置 Demo 双版本 A/B' }}
        </p>
      </div>
      <p v-if="branchMismatch" class="notice error full" role="alert">
        该地址未匹配到当前智能体的已登记分支，版本与图谱不可用。请先部署并登记，或从下拉建议恢复当前分支。
      </p>
      <details v-if="targetDescriptor" class="full task-graph">
        <summary>智能体图谱</summary>
        <TargetStructure :descriptor="targetDescriptor" hide-source />
      </details>
      <div class="form-section-heading full">
        <span>03</span>
        <div><h3>评测数据</h3></div>
      </div>
      <div class="dataset-selection full">
        <label class="field"
          >评测集<select class="input" v-model="selectedDataset" aria-label="任务评测集">
            <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select></label
        >
        <label class="field"
          >评测集版本<select
            class="input"
            v-model="selectedDatasetVersion"
            aria-label="任务评测集版本"
          >
            <option v-for="v in datasetVersions" :key="v.version" :value="v.version">
              v{{ v.version }} · {{ v.cases.length }} 条样本
            </option>
          </select></label
        >
        <label class="field"
          >运行范围<select
            :disabled="taskKind === 'ab'"
            class="input"
            aria-label="运行范围"
            v-model="scope"
          >
            <option value="all">全部用例（{{ availableCases.length }} 条）</option>
            <option value="selected">指定用例</option></select
          ><el-select
            v-if="scope === 'selected'"
            v-model="selectedCaseIds"
            :disabled="submitting || formLoading || datasetLoading"
            multiple
            filterable
            placeholder="选择要运行的用例"
            aria-label="指定用例"
            ><el-option
              v-for="c in availableCases"
              :key="c.id"
              :label="c.name"
              :value="c.id" /></el-select
          ><small v-if="taskKind === 'ab'"
            >当前 A/B 接口运行发布版本的全部用例；指定用例需后端扩展。</small
          ><small v-if="scope === 'selected' && !selectedCaseIds.length"
            >请从当前发布版本重新选择用例。</small
          ></label
        >
      </div>
      <div class="form-section-heading full">
        <span>04</span>
        <div><h3>评估方式</h3></div>
      </div>
      <TaskEvaluatorPicker
        class="full"
        :evaluators="evaluators"
        :cases="executionCases"
        v-model="selectedEvaluators"
        :static-report="staticReport"
        :static-enabled="includeStatic"
        :static-available="taskKind === 'ab' && (!bankTarget || !!targetDescriptor?.skills.length)"
        @static="openStatic"
        @cancel-analysis="cancelAnalysis"
      />
      <div class="full grading-mode">
        <h4>多轮对话评分模式</h4>
        <div class="task-kind-choice" role="radiogroup" aria-label="评分模式">
          <button
            type="button"
            role="radio"
            :aria-checked="gradingMode === 'overall'"
            :class="{ selected: gradingMode === 'overall' }"
            @click="
              gradingMode = 'overall';
              formError = '';
            "
          >
            <b>整体评分</b><small>按完整会话汇总评估结果</small></button
          ><button
            type="button"
            role="radio"
            :aria-checked="gradingMode === 'per_turn'"
            :class="{ selected: gradingMode === 'per_turn' }"
            @click="gradingMode = 'per_turn'"
          >
            <b>逐轮评分</b><small>逐轮评判后汇总 · 待后端接入</small>
          </button>
        </div>
        <p v-if="gradingMode === 'per_turn'" class="notice warn">
          当前后端不支持任务级逐轮 LLM 评分，暂不能启动此模式。
        </p>
      </div>
      <div class="form-section-heading full">
        <span>05</span>
        <div><h3>执行设置</h3></div>
      </div>
      <div class="execution-settings full" aria-label="执行参数">
        <label class="field"
          >执行时间<select
            aria-label="执行时间"
            class="input"
            v-model="launchMode"
            :disabled="taskKind === 'ab'"
          >
            <option value="now">立即执行</option>
            <option value="scheduled">预约执行</option></select
          ><small v-if="repetitions > 1">稳定性测试暂不支持预约。</small></label
        >
        <label v-if="launchMode === 'scheduled'" class="field"
          >预约时间<input
            aria-label="预约时间"
            class="input"
            type="datetime-local"
            v-model="scheduledAt"
          /><small
            >本机时区
            {{ Intl.DateTimeFormat().resolvedOptions().timeZone }}；到期由调度服务进入队列。</small
          ></label
        >
        <label class="field"
          >并发样本数<input
            class="input"
            v-model.number="concurrency"
            :disabled="taskKind === 'ab'"
            title="最多 30 个样本并发"
            aria-label="并发样本数"
            type="number"
            min="1"
            max="30"
            step="1"
        /></label>
        <label class="field"
          >执行超时（秒）<input
            class="input"
            :disabled="taskKind === 'ab'"
            v-model.number="timeout"
            :title="bankTarget ? '1–300 秒，最大 300 秒' : '1–3600 秒，最大 3600 秒'"
            aria-label="执行超时（秒）"
            type="number"
            min="1"
            :max="bankTarget ? 300 : 3600"
            step="1"
        /></label>
        <label class="field"
          >稳定性测试<input
            class="input"
            type="number"
            v-model.number="repetitions"
            min="1"
            max="20"
            step="1"
            title="1–20 次，最大 20 次；各轮独立执行"
            aria-label="稳定性测试"
        /></label>
        <label class="field"
          >失败重试次数<input
            class="input"
            v-model.number="retries"
            :disabled="taskKind === 'ab'"
            title="最多 5 次；仅重试可安全重试的执行错误"
            aria-label="失败重试次数"
            type="number"
            min="0"
            max="5"
            step="1"
        /></label>
      </div>

      <p v-if="taskKind === 'ab'" class="muted full">A/B 两侧沿用固定执行参数：并发 1，失败重试 0。</p>
    </fieldset>
    <p class="task-summary">
      本次：{{
        taskKind === 'ab' ? 'A/B 实验 · 两个版本' : repetitions > 1 ? '稳定性测试' : '单任务'
      }}
      ·
      {{
        (taskKind === 'single'
          ? platformSelection?.agentName
          : versionOptions.find((v) => v.id === selectedVersion)?.label) ?? '待选目标'
      }}
      · v{{ selectedDatasetVersion ?? '—' }} · {{ executionCases.length }} 条用例 ×
      {{ repetitions }} 次 · {{ selectedEvaluators.length }} 个评估器
    </p>
    <template #footer>
      <div class="submission-feedback">
        <div v-if="formError" class="notice error" role="alert">{{ formError }}</div>
        <p v-if="submitting" role="status">
          {{
            includeStatic
              ? '任务提交与静态分析处理中，请勿重复提交；模型分析可能需要数分钟。'
              : '正在提交任务…'
          }}
        </p>
        <p v-else-if="formLoading || datasetLoading" role="status">正在加载任务配置…</p>
        <p v-else-if="branchMismatch" role="status">
          Git 分支未匹配，暂不能开始评测，请修正分支地址。
        </p>
      </div>
      <div class="submission-actions">
        <span class="selection-count">已选 {{ selectedEvaluators.length }} 个评估器</span>
        <button
          v-if="!selectedEvaluators.length && recommended.length"
          type="button"
          class="secondary"
          :disabled="submitting || formLoading || datasetLoading"
          @click="
            selectedEvaluators = [...recommended];
            formError = '';
          "
        >
          采用推荐评估器
        </button>
        <button class="secondary" :disabled="submitting" @click="emit('close')">取消</button
        ><button
          class="primary"
          :disabled="
            submitting ||
            legacyLoading ||
            (taskKind === 'single' && !platformSelection) ||
            formLoading ||
            datasetLoading ||
            staticLoading ||
            branchMismatch ||
            (taskKind === 'ab' && !!bankTarget)
          "
          @click="submit"
        >
          {{ submitting ? '正在处理…' : taskKind === 'ab' ? '创建 A/B 实验' : '开始评测' }}
        </button>
      </div>
    </template>
  </el-dialog>
  <el-dialog
    v-model="staticDialog"
    :close-on-click-modal="!staticLoading"
    :show-close="!staticLoading"
    :close-on-press-escape="!staticLoading"
    title="Skill 静态分析 · 模型配置"
    width="min(740px,94vw)"
    append-to-body
  >
    <p v-if="staticLoading">{{ staticConnection ? '正在分析 Skill…' : '正在读取模型配置…' }}</p>
    <p v-if="staticError" role="alert">{{ staticError }}</p>
    <template v-if="staticConnection"
      ><label class="field"
        >Base URL<input class="input" :value="staticConnection.base_url" readonly /></label
      ><label class="field"
        >模型<input class="input" :value="staticConnection.model" readonly /></label
      ><label class="field"
        >API Key<input class="input" value="服务端安全管理，不返回浏览器" readonly
      /></label>
      <p v-if="!staticConnection.configured" role="alert">模型尚未配置</p></template
    >
    <template #footer
      ><button
        class="primary"
        :disabled="staticLoading || !staticConnection?.configured"
        @click="confirmStatic"
      >
        {{ staticLoading ? '处理中…' : '确认' }}
      </button></template
    >
  </el-dialog>
</template>
<style scoped>
.dataset-selection {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.dataset-selection .field {
  min-width: 0;
}
.dataset-selection .input {
  width: 100%;
  min-width: 0;
}
@media (max-width: 650px) {
  .dataset-selection {
    grid-template-columns: 1fr;
  }
}
.submission-feedback {
  text-align: left;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.submission-feedback .notice {
  margin: 0 0 10px;
}
.submission-feedback p {
  margin: 0 0 10px;
  color: #725b2a;
}
.submission-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.selection-count {
  font-size: 12px;
  color: #64748b;
  margin-right: auto;
}
.target-choice.has-git-branch:not(.is-ab) {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr) minmax(0, 1fr);
}
.git-branch-field small {
  color: #75837e;
  font-size: 12px;
}
.structure-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  background: #f3f9f6;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  color: #536c62;
}
@media (max-width: 700px) {
  .target-choice.has-git-branch:not(.is-ab) {
    grid-template-columns: 1fr;
  }
}
.execution-settings {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}
.execution-settings .field {
  min-width: 0;
  margin: 0;
  font-size: 13px;
  gap: 8px;
}
.execution-settings .input {
  width: 100%;
  min-width: 0;
  padding: 10px 12px;
  font-size: 14px;
}
.execution-settings small {
  font-size: 11px;
}
@media (max-width: 1000px) {
  .execution-settings {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 650px) {
  .execution-settings {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 420px) {
  .execution-settings {
    grid-template-columns: 1fr;
  }
}
.execution-limit {
  color: #986616;
}
.static-model-settings {
  padding: 20px;
  border: 1px solid #d5e8df;
  border-radius: 10px;
  background: #fbfdfc;
}
.static-model-settings > .field {
  max-width: 440px;
}
.static-model-settings .muted,
.platform-model-note {
  font-size: 13px;
  line-height: 1.7;
}
.platform-model-note {
  color: #43715e;
  margin-bottom: 0;
}
.model-config-fields {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
  gap: 20px;
  min-width: 0;
}
.model-config-fields .field {
  min-width: 0;
}
@media (max-width: 800px) {
  .model-config-fields {
    grid-template-columns: 1fr;
  }
}
.mock-notice {
  margin: 0;
  padding: 12px;
  background: #fff9eb;
  border: 1px solid #eadbb9;
  border-radius: 6px;
  color: #896e35;
  font-size: 12px;
  line-height: 1.6;
}
.task-kind-choice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}
.task-kind-choice button {
  text-align: left;
  padding: 16px 20px;
  border: 1px solid #dce4e1;
  background: white;
  border-radius: 8px;
  cursor: pointer;
}
.task-kind-choice button.selected {
  border-color: #00a88b;
  background: #edf9f5;
  color: #007f6b;
}
.task-kind-choice small {
  display: block;
  margin-top: 6px;
  color: #64748b;
}
.target-choice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.target-choice.is-ab {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.target-choice .field {
  min-width: 0;
}
.target-choice .input {
  width: 100%;
  min-width: 0;
}
.target-note {
  grid-column: 1/-1;
  margin: 0;
  color: #64748b;
  font-size: 12px;
  padding: 10px 12px;
  background: #f6f8f9;
  border-radius: 6px;
}
.static-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #f3f9f6;
  padding: 16px;
  border-radius: 8px;
}
.static-option small {
  display: block;
  color: #64748b;
  margin-top: 6px;
}
fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  min-width: 0;
}
@media (max-width: 700px) {
  .target-choice,
  .target-choice.is-ab {
    grid-template-columns: 1fr;
  }
}
</style>
