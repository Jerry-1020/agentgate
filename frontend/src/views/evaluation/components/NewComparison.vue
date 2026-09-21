<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import {
  api,
  request,
  type DatasetSummary,
  type EvaluatorSummary,
  type Definition,
} from '../../../api/evaluations';
import { recommendEvaluators } from '../utils/evaluator-guidance';
const emit = defineEmits<{ created: [a: string, b: string] }>();
const versions = ref<{ id: string; label: string }[]>([]),
  datasets = ref<DatasetSummary[]>([]),
  evaluators = ref<EvaluatorSummary[]>([]);
const a = ref(''),
  b = ref(''),
  datasetId = ref(''),
  version = ref<number | null>(null),
  published = ref<any[]>([]),
  selected = ref<string[]>([]),
  busy = ref(false),
  error = ref('');
let sequence = 0;
const evaluatorVersions = ref<Record<string, Definition[]>>({});
const chosenVersions = ref<Record<string, string>>({});
const versionsLoading = ref(false),
  datasetLoading = ref(false),
  catalogLoading = ref(true);
onMounted(async () => {
  try {
    const [v, d, e] = await Promise.all([api.versions(), api.datasets(), api.evaluators()]);
    // 自动化导入测试留下的时间戳规则不作为正式实验选项；历史报告仍保留原始引用。
    versions.value = v;
    datasets.value = d.filter((x) => !x.archived);
    evaluators.value = e.filter(
      (x) => x.enabled && x.latest_version && !/^联调导入规则\s*\d+$/.test(x.name),
    );
    a.value = v[0]?.id ?? '';
    b.value = v[1]?.id ?? '';
    datasetId.value = datasets.value.find((x) => x.version !== null)?.id ?? '';
    versionsLoading.value = true;
    try {
      await Promise.all(
        evaluators.value.map(async (item) => {
          const history = await request<Definition[]>(
            `/evaluators/${encodeURIComponent(item.id)}/versions`,
          );
          evaluatorVersions.value[item.id] = history;
          chosenVersions.value[item.id] = item.latest_version!;
        }),
      );
    } finally {
      versionsLoading.value = false;
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    catalogLoading.value = false;
  }
});
watch(datasetId, async (id) => {
  const ticket = ++sequence;
  published.value = [];
  version.value = null;
  selected.value = [];
  datasetLoading.value = true;
  error.value = '';
  try {
    const d = await request<{ versions: any[] }>(`/datasets/${encodeURIComponent(id)}`);
    if (ticket !== sequence) return;
    published.value = d.versions
      .filter((v) => v.status === 'published')
      .sort((a, b) => b.version - a.version);
    version.value = published.value[0]?.version ?? null;
  } catch (e) {
    if (ticket === sequence) error.value = String(e);
  } finally {
    if (ticket === sequence) datasetLoading.value = false;
  }
});
watch(
  version,
  () =>
    (selected.value = recommendEvaluators(
      evaluators.value,
      published.value.find((v) => v.version === version.value)?.cases ?? [],
    )),
);
async function submit() {
  if (busy.value) return;
  if (
    !a.value ||
    !b.value ||
    a.value === b.value ||
    version.value === null ||
    !selected.value.length
  ) {
    error.value = '请选择不同的智能体版本、同一评测集版本及评估器。';
    return;
  }
  busy.value = true;
  error.value = '';
  try {
    const chosen = evaluators.value.filter((e) => selected.value.includes(e.id));
    if (
      versionsLoading.value ||
      chosen.some(
        (e) =>
          !evaluatorVersions.value[e.id]?.some((v) => v.version === chosenVersions.value[e.id]),
      )
    )
      throw Error('评估器版本尚未加载或不可用，请重新选择。');
    const definitions = chosen.map((e) => ({
      ...e,
      ...evaluatorVersions.value[e.id]!.find((v) => v.version === chosenVersions.value[e.id])!,
    }));
    if (
      definitions.every((e) => e.kind === 'rule') &&
      !recommendEvaluators(
        definitions,
        published.value.find((v) => v.version === version.value)?.cases ?? [],
      ).length
    )
      throw Error('没有匹配的样本期望，请先补充评测集。');
    const r = await request<{ baseline: { run_id: string }; candidate: { run_id: string } }>(
      '/run-comparisons',
      'POST',
      {
        baseline_version: a.value,
        candidate_version: b.value,
        dataset_id: datasetId.value,
        dataset_version: version.value,
        evaluators: chosen.map((e) => ({ id: e.id, version: chosenVersions.value[e.id] })),
      },
    );
    emit('created', r.baseline.run_id, r.candidate.run_id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="card new-comparison">
    <h2 class="section-title">创建实验并运行</h2>
    <p class="muted">两侧共用评测集和评估器的固定版本，仅比较智能体版本变化。</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div class="form-grid">
      <label class="field"
        >实验 A · 基线版本<select
          class="input"
          v-model="a"
          aria-label="实验 A · 基线版本"
          :disabled="busy || catalogLoading"
        >
          <option v-for="v in versions" :key="v.id" :value="v.id">
            {{ v.label }} · {{ v.id }}
          </option>
        </select></label
      >
      <label class="field"
        >实验 B · 候选版本<select
          class="input"
          v-model="b"
          aria-label="实验 B · 候选版本"
          :disabled="busy || catalogLoading"
        >
          <option v-for="v in versions" :key="v.id" :value="v.id">
            {{ v.label }} · {{ v.id }}
          </option>
        </select></label
      >
      <label class="field"
        >共同评测集<select
          class="input"
          v-model="datasetId"
          aria-label="共同评测集"
          :disabled="busy || catalogLoading"
        >
          <option value="" disabled>请选择评测集名称</option>
          <option v-for="d in datasets" :key="d.id" :value="d.id" :disabled="d.version === null">
            {{ d.name }}{{ d.version === null ? '（草稿，发布后可用）' : '' }}
          </option>
        </select></label
      >
      <label class="field"
        >发布版本<select
          class="input"
          v-model="version"
          aria-label="发布版本"
          :disabled="datasetLoading || busy || catalogLoading"
        >
          <option v-if="!published.length" :value="null">
            {{ datasetLoading ? '正在加载版本…' : '暂无发布版本' }}
          </option>
          <option v-for="(v, index) in published" :key="v.version" :value="v.version">
            v{{ v.version }} · {{ v.cases.length }} 条{{ index === 0 ? ' · 最新发布' : '' }}
          </option>
        </select></label
      >
      <div class="field full">
        <b>共同评估器 · 已选 {{ selected.length }} 个</b>
        <div class="check-list">
          <div v-for="e in evaluators" :key="e.id">
            <label
              ><input
                :disabled="version === null || versionsLoading || busy"
                type="checkbox"
                v-model="selected"
                :value="e.id"
              />{{ e.name }}</label
            ><select
              v-if="selected.includes(e.id)"
              class="input"
              :aria-label="e.name + '的评估版本'"
              v-model="chosenVersions[e.id]"
              :disabled="versionsLoading || busy"
            >
              <option v-for="v in evaluatorVersions[e.id]" :key="v.version!" :value="v.version">
                v{{ v.version }}{{ v.version === e.latest_version ? ' · 最新发布' : ' · 历史发布' }}
              </option>
            </select>
          </div>
        </div>
      </div>
    </div>
    <div class="form-footer">
      <button
        class="primary"
        :disabled="busy || datasetLoading || versionsLoading || catalogLoading"
        @click="submit"
      >
        {{ busy ? '正在创建…' : '创建并运行两侧任务' }}
      </button>
    </div>
  </section>
</template>
<style scoped>
.new-comparison .form-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.new-comparison .field {
  min-width: 0;
}
.new-comparison .input {
  max-width: 100%;
  min-width: 0;
}
@media (max-width: 768px) {
  .new-comparison .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
