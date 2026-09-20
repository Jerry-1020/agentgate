<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { EvaluatorSummary } from '../../../api/evaluations';
import EvaluatorImport from './EvaluatorImport.vue';
import RuleEvaluatorCreate from './RuleEvaluatorCreate.vue';
import { dimensionNames, chineseEvaluatorText, ruleExamples } from '../utils/evaluator-display';
import { evaluatorScenarios, evaluatorTechnicalChecks } from '../utils/evaluator-guidance';
const creatingRule = ref(false);
import EvaluatorModelSelect from './EvaluatorModelSelect.vue';
import { modelRefError, modelRefLabel } from '../utils/evaluator-model';
import {
  evaluatorCatalog,
  evaluatorDetails,
  loadReviewAssets,
  assetsLoading,
  assetsError,
  copy,
  exportUx,
} from '../../../stores/review-assets';
import {
  evaluatorDesigns,
  evaluatorDesignHistory,
  weightError,
  type EvaluatorDesign,
} from '../utils/evaluator-design';
import '../../../styles/review-assets.scss';
const props = defineProps<{ initialId?: string }>(),
  emit = defineEmits<{ dirtyChange: [value: boolean]; launch: [id: string] }>();
const category = ref<'rule' | 'llm_judge'>('llm_judge'),
  query = ref(''),
  importing = ref(false),
  rule = ref<EvaluatorSummary | null>(null);
const design = ref<EvaluatorDesign | null>(null),
  editing = ref(false),
  selected = ref(0),
  originId = ref(''),
  error = ref(''),
  full = ref(false),
  historyOpen = ref(false);
const active = computed(() => design.value?.dimensions[selected.value]);
const entries = computed(() =>
  evaluatorCatalog.value.filter(
    (e) =>
      e.kind === category.value &&
      e.latest_version &&
      e.name.toLowerCase().includes(query.value.toLowerCase()),
  ),
);
const drafts = computed(() =>
  category.value === 'llm_judge'
    ? evaluatorDesigns.value.filter((e) => e.name.toLowerCase().includes(query.value.toLowerCase()))
    : [],
);
const models = computed(() =>
  Array.from(
    new Map(
      Object.values(evaluatorDetails.value)
        .filter((d) => d.latest?.kind === 'llm_judge')
        .map((d) => d.latest!.config.model as { provider_id: string; model_id: string })
        .filter(Boolean)
        .map((m) => [JSON.stringify(m), m]),
    ).entries(),
  ),
);
const total = computed(
  () => design.value?.dimensions.reduce((sum, d) => sum + (d.weight ?? 0), 0) ?? 0,
);
watch([editing, importing], ([a, b]) => emit('dirtyChange', a || b));
function blank() {
  return {
    id: crypto.randomUUID(),
    name: '',
    description: '',
    version: 1,
    dimensions: [
      ['relevance', '相关性', 25],
      ['correctness', '正确性', 25],
      ['conciseness', '简洁性', 25],
      ['safety', '安全性', 5],
      ['tools', '工具', 20],
    ].map(([id, name, weight]) => ({
      id: String(id),
      name: String(name),
      description: '',
      prompt: '',
      weight: Number(weight),
    })),
    modelKey: '',
    scope: 'final_output',
    threshold: 80,
  } as EvaluatorDesign;
}
function create() {
  design.value = blank();
  originId.value = '';
  editing.value = true;
  selected.value = 0;
  error.value = '';
}
function open(e: EvaluatorSummary) {
  if (e.kind === 'rule') {
    rule.value = e;
    return;
  }
  const d = evaluatorDetails.value[e.id]?.latest;
  if (!d) return;
  design.value = {
    id: e.id,
    name: e.name,
    description: e.description,
    version: Number(d.version),
    modelKey: JSON.stringify(d.config.model),
    scope: String(d.config.input_selection),
    threshold: Number(d.config.pass_threshold) * 100,
    dimensions: Object.entries((d.config.rubric as Record<string, string>) ?? {}).map(
      ([id, text]) => ({
        id,
        name: id,
        description: String(text),
        prompt: String(d.config.instruction ?? '') + '\n\n' + text,
        weight: null,
      }),
    ),
  };
  originId.value = e.id;
  editing.value = false;
  selected.value = 0;
  error.value = '';
}
function openLocal(d: EvaluatorDesign) {
  design.value = copy(d);
  originId.value = '';
  editing.value = false;
  selected.value = 0;
  error.value = '';
}
function edit() {
  if (!design.value) return;
  if (originId.value) {
    design.value = {
      ...copy(design.value),
      id: crypto.randomUUID(),
      name: design.value.name + '（副本）',
      version: 1,
    };
    const count = design.value.dimensions.length;
    design.value.dimensions.forEach(
      (d, i) =>
        (d.weight =
          i === count - 1 ? 100 - Math.floor(100 / count) * (count - 1) : Math.floor(100 / count)),
    );
    originId.value = '';
  }
  editing.value = true;
}
function close() {
  if (editing.value && !window.confirm('放弃未保存的评估器设计？')) return;
  design.value = null;
  editing.value = false;
}
function save() {
  const d = design.value;
  if (!d) return;
  error.value = !d.name.trim()
    ? '请输入评估器名称。'
    : modelRefError(d.modelKey) || weightError(d.dimensions);
  if (!error.value && d.dimensions.some((x) => !x.name.trim() || !x.id.trim() || !x.prompt.trim()))
    error.value = '请填写各维度名称、标识和评分提示词。';
  if (!error.value && new Set(d.dimensions.map((x) => x.id.trim())).size !== d.dimensions.length)
    error.value = '维度标识不能重复。';
  if (!error.value && (!Number.isFinite(d.threshold) || d.threshold < 0 || d.threshold > 100))
    error.value = '通过分数须为 0—100。';
  if (error.value) return;
  const index = evaluatorDesigns.value.findIndex((x) => x.id === d.id);
  if (index >= 0) {
    (evaluatorDesignHistory.value[d.id] ??= []).unshift(copy(evaluatorDesigns.value[index]));
    d.version = evaluatorDesigns.value[index].version + 1;
    evaluatorDesigns.value[index] = copy(d);
  } else evaluatorDesigns.value.unshift(copy(d));
  editing.value = false;
}
async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(active.value?.prompt ?? '');
    error.value = '已复制当前维度提示词。';
  } catch {
    error.value = '无法访问剪贴板，请手动选择提示词复制。';
  }
}
onMounted(async () => {
  await loadReviewAssets();
  if (props.initialId) {
    const e = evaluatorCatalog.value.find((e) => e.id === decodeURIComponent(props.initialId!));
    if (e && e.kind !== 'hybrid') {
      category.value = e.kind;
      open(e);
    }
  }
});
const templateLabels1: Record<string, string> = {
  final_output: '最终回答',
  output_and_tools: '回答与工具',
  full_trajectory: '完整轨迹',
};
</script>
<template>
  <section class="review-assets">
    <div class="asset-heading">
      <div><h1>评估器</h1></div>
      <div class="actions">
        <button class="asset-secondary" @click="loadReviewAssets" :disabled="assetsLoading">
          刷新</button
        ><template v-if="category === 'rule'"
          ><button class="asset-secondary" @click="importing = true">导入评估器</button
          ><button class="asset-primary" @click="creatingRule = true">
            ＋ 新建规则评估器
          </button></template
        ><button v-else class="asset-primary" @click="create">＋ 新建 LLM 评估器</button>
      </div>
    </div>
    <div class="asset-tabs">
      <button :class="{ active: category === 'rule' }" @click="category = 'rule'">规则评估</button
      ><button :class="{ active: category === 'llm_judge' }" @click="category = 'llm_judge'">
        LLM 评估
      </button>
    </div>
    <p v-if="category === 'llm_judge'" class="asset-note">新建设计暂存本页 · 未发布</p>
    <p v-if="assetsError" role="alert" class="asset-error">{{ assetsError }}</p>
    <div class="asset-filters">
      <input v-model="query" aria-label="搜索评估器" placeholder="搜索评估器名称" />
    </div>
    <p v-if="assetsLoading">正在读取…</p>
    <div v-else class="asset-grid">
      <article v-for="d in drafts" :key="d.id" class="asset-card">
        <span class="asset-chip preview">UX 草稿 · v{{ d.version }}</span>
        <h2>{{ d.name }}</h2>
        <p>{{ d.dimensions.length }} 项维度 · {{ d.description }}</p>
        <p class="asset-small">评审模型：{{ modelRefLabel(d.modelKey) }}</p>
        <button class="asset-link" @click="openLocal(d)">查看设计</button>
      </article>
      <article v-for="e in entries" :key="e.id" class="asset-card">
        <span class="asset-chip"
          >{{ e.source === 'builtin' ? '预置' : '自建' }} · v{{ e.latest_version }}</span
        >
        <h2>{{ e.name }}</h2>
        <p>{{ e.description || e.metric }}</p>
        <p v-if="e.kind === 'llm_judge'" class="asset-small">
          评审模型：{{
            modelRefLabel(JSON.stringify(evaluatorDetails[e.id]?.latest?.config.model ?? {}))
          }}
        </p>
        <div class="asset-card-actions">
          <button class="asset-link" @click="open(e)">查看详情</button
          ><span class="asset-small">{{ e.enabled ? '已启用' : '已停用' }}</span>
        </div>
      </article>
    </div>
  </section>
  <el-dialog
    :model-value="!!design"
    :before-close="close"
    :close-on-click-modal="false"
    title="LLM 评估器设计"
    width="min(1280px,96vw)"
    class="asset-dialog"
  >
    <template v-if="design"
      ><header class="design-header">
        <div>
          <h2 v-if="!editing">
            {{ design.name }} <span class="asset-chip">v{{ design.version }}</span>
          </h2>
          <input
            v-else
            v-model="design.name"
            aria-label="评估器名称"
            placeholder="评估器名称"
          /><input
            v-if="editing"
            v-model="design.description"
            aria-label="评估器描述"
            placeholder="描述"
          />
          <p v-else>{{ design.description }}</p>
        </div>
        <div class="actions">
          <button v-if="!originId && !editing" class="asset-secondary" @click="historyOpen = true">
            版本历史</button
          ><button v-if="!editing" class="asset-primary" @click="edit">
            {{ originId ? '复制并编辑' : '编辑' }}
          </button>
        </div>
      </header>
      <p class="asset-small">
        {{ originId ? '原定义未配置维度权重' : '本页临时设计 · 刷新后清除' }}
      </p>
      <EvaluatorModelSelect
        :key="design.id"
        v-model="design.modelKey"
        :editable="editing"
        :models="models"
      />
      <section class="execution-config">
        <div v-if="editing" class="asset-form-grid">
          <label
            >评审输入范围<select v-model="design.scope" aria-label="评审输入范围">
              <option value="final_output">最终回答</option>
              <option value="output_and_tools">回答与工具</option>
              <option value="full_trajectory">完整轨迹</option>
            </select></label
          ><label
            >通过分数（0—100）<input
              type="number"
              v-model.number="design.threshold"
              min="0"
              max="100"
              aria-label="评估器通过分数"
          /></label>
        </div>
        <p v-else class="asset-small">
          评审范围：{{ templateLabels1[design.scope] ?? design.scope }} · 通过分数
          {{ design.threshold }}
        </p>
      </section>
      <div class="dimension-design">
        <aside>
          <h3>评估维度（{{ design.dimensions.length }}）</h3>
          <button
            v-for="(d, i) in design.dimensions"
            :key="i"
            class="dimension-item"
            :class="{ active: selected === i }"
            @click="selected = i"
          >
            <strong>{{ dimensionNames[d.name] ?? d.name ?? '未命名维度' }}</strong
            ><span>{{ d.weight == null ? '未定义' : d.weight + '%' }}</span></button
          ><button
            v-if="editing"
            class="asset-link"
            @click="
              design.dimensions.push({
                id: 'dimension_' + (design.dimensions.length + 1),
                name: '新维度',
                description: '',
                prompt: '',
                weight: 0,
              });
              selected = design.dimensions.length - 1;
            "
          >
            ＋ 添加维度
          </button>
          <p v-if="editing" :class="{ 'asset-error': Math.abs(total - 100) > 0.001 }">
            权重合计 {{ total }}% / 100%
          </p>
        </aside>
        <section v-if="active" class="dimension-content">
          <header>
            <h3>{{ dimensionNames[active.name] ?? active.name ?? '评估维度' }}</h3>
            <div class="actions">
              <button
                v-if="editing"
                class="asset-link"
                @click="
                  design.dimensions.splice(selected, 1);
                  selected = Math.max(0, selected - 1);
                "
              >
                移除维度
              </button>
            </div>
          </header>
          <div v-if="editing" class="asset-form-grid">
            <label>维度名称<input v-model="active.name" aria-label="维度名称" /></label
            ><label>标识<input v-model="active.id" aria-label="维度标识" /></label
            ><label
              >权重（%）<input
                v-model.number="active.weight"
                type="number"
                min="0.01"
                max="100"
                step=".01"
                aria-label="维度权重" /></label
            ><label>说明<input v-model="active.description" aria-label="维度说明" /></label>
          </div>
          <p v-else>{{ chineseEvaluatorText(active.description) }}</p>
          <textarea
            v-if="editing"
            v-model="active.prompt"
            aria-label="维度评分提示词"
            rows="14"
            placeholder="填写评分标准、指导说明和扣分条件；这是本维度的提示词。"
          />
          <pre v-else>{{ chineseEvaluatorText(active.prompt) }}</pre>
        </section>
      </div>
      <p v-if="error" role="status" class="asset-error">{{ error }}</p></template
    >
    <template #footer
      ><button class="asset-secondary" @click="close">关闭</button
      ><button v-if="editing" class="asset-primary" @click="save">保存 UX 设计</button
      ><button
        v-else-if="design && !originId"
        class="asset-secondary"
        @click="exportUx(design, 'evaluator-design-ux.json')"
      >
        导出 UX 设计</button
      ><button
        v-if="originId && !editing"
        class="asset-primary"
        :disabled="!evaluatorCatalog.find((e) => e.id === originId)?.enabled"
        @click="
          emit('launch', originId);
          design = null;
        "
      >
        打开评测配置
      </button></template
    ></el-dialog
  >
  <el-dialog v-model="full" title="维度提示词" fullscreen class="asset-dialog">
    <textarea
      v-if="active && editing"
      v-model="active.prompt"
      aria-label="全屏评分提示词"
      rows="25"
    />
    <pre v-else>{{ active?.prompt }}</pre>
  </el-dialog>
  <el-dialog v-model="historyOpen" title="UX 版本历史" class="asset-dialog"
    ><p>本页草稿历史，不是后端发布版本；刷新后清除。</p>
    <p v-for="v in evaluatorDesignHistory[design?.id ?? ''] ?? []" :key="v.version">
      v{{ v.version }} · {{ v.name }} · {{ v.dimensions.length }} 个维度
    </p>
    <p v-if="!(evaluatorDesignHistory[design?.id ?? ''] ?? []).length">暂无历史修订。</p></el-dialog
  >
  <el-dialog :model-value="!!rule" @close="rule = null" title="规则评估器详情" class="asset-dialog"
    ><template v-if="rule"
      ><h2>{{ rule.name }}</h2>
      <div class="asset-chips">
        <span class="asset-chip">{{ rule.source === 'builtin' ? '预置' : '自建' }}</span
        ><span class="asset-chip">代码</span><span class="asset-chip">仅看结果</span>
      </div>
      <p>{{ evaluatorScenarios[rule.implementation_id] || rule.description || rule.metric }}</p>
      <section class="rule-explanation">
        <h3>检查方式</h3>
        <p v-for="text in evaluatorTechnicalChecks(rule, [])" :key="text">{{ text }}</p>
      </section>
      <section v-if="ruleExamples[rule.implementation_id]" class="rule-example">
        <h3>使用案例</h3>
        <p>{{ ruleExamples[rule.implementation_id].expectation }}</p>
        <p class="example-pass">{{ ruleExamples[rule.implementation_id].passed }}</p>
        <p class="example-fail">{{ ruleExamples[rule.implementation_id].failed }}</p>
      </section>
      <details v-if="Object.keys(evaluatorDetails[rule.id]?.latest?.config ?? {}).length">
        <summary>规则配置</summary>
        <pre>{{ JSON.stringify(evaluatorDetails[rule.id]?.latest?.config, null, 2) }}</pre>
      </details>
      <p class="asset-small">
        执行实现：{{ rule.implementation_id }} @ {{ rule.implementation_version }}
      </p></template
    ><template #footer
      ><button class="asset-secondary" @click="rule = null">关闭</button></template
    ></el-dialog
  >
  <EvaluatorImport
    v-if="importing"
    @close="importing = false"
    @imported="
      importing = false;
      loadReviewAssets();
    "
  />
  <RuleEvaluatorCreate
    v-if="creatingRule"
    @close="creatingRule = false"
    @created="
      creatingRule = false;
      loadReviewAssets();
    "
  />
</template>
<style scoped>
.rule-explanation,
.rule-example {
  margin: 20px 0;
  padding: 18px;
  background: #f6faf8;
  border: 1px solid #e0ebe5;
  border-radius: 10px;
  line-height: 1.8;
}
.rule-example h3,
.rule-explanation h3 {
  margin-bottom: 10px;
}
.example-pass {
  color: #008b76;
}
.example-fail {
  color: #a76438;
}
.execution-config {
  padding: 14px 0;
}
.design-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
}
.design-header > div:first-child {
  flex: 1;
  min-width: 0;
}
.dimension-design {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  border-top: 1px solid #e4eaf4;
  margin-top: 22px;
}
.dimension-design aside {
  padding: 20px 18px 20px 0;
  border-right: 1px solid #e4eaf4;
}
.dimension-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 20px 14px;
  margin-bottom: 12px;
  border: 1px solid #e2e8f5;
  border-radius: 10px;
  background: #f7f9fd;
  color: #34415a;
}
.dimension-item.active {
  border-color: #2868ff;
  box-shadow: 0 0 0 3px #2868ff15;
}
.dimension-content {
  padding: 20px;
  min-width: 0;
}
.dimension-content header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.dimension-content pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
  background: #f7f9fb;
  padding: 24px;
  border-radius: 10px;
  min-height: 300px;
}
.design-header .actions {
  align-items: flex-start;
  flex-wrap: wrap;
}
@media (max-width: 720px) {
  .dimension-design {
    grid-template-columns: 1fr;
  }
  .dimension-design aside {
    border: 0;
    padding: 16px 0;
  }
  .dimension-content {
    padding: 12px 0;
  }
  .design-header {
    flex-wrap: wrap;
  }
}
</style>
