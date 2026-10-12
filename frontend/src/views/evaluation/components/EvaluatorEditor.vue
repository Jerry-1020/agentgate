<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { evaluatorScenarios } from '../utils/evaluator-guidance';
import { request, type Definition, type EvaluatorSummary } from '../../../api/evaluations';
const props = defineProps<{
  modelValue: Definition;
  items: EvaluatorSummary[];
  disabled?: boolean;
}>();
const emit = defineEmits<{ 'update:modelValue': [value: Definition] }>();
const value = ref<Definition>(JSON.parse(JSON.stringify(props.modelValue)));
const versions = ref<Record<string, string[]>>({});
const error = ref('');
watch(
  () => props.modelValue,
  (v) => {
    value.value = JSON.parse(JSON.stringify(v));
  },
  { deep: true },
);
const total = computed(() =>
  value.value.children.reduce((sum, c) => sum + (c.weight ?? 0) * 100, 0),
);
const choices = computed(() =>
  props.items.filter(
    (e) =>
      e.kind !== 'hybrid' &&
      ((e.enabled && e.latest_version) ||
        value.value.children.some((c) => c.evaluator_id === e.id)),
  ),
);
function update() {
  emit('update:modelValue', JSON.parse(JSON.stringify(value.value)));
}
function setConfig(key: string, v: unknown) {
  value.value.config[key] = v;
  update();
}
type ConnectedModel = { provider_id: string; model_id: string; credential_ref: string };
const models = ref<ConnectedModel[]>([]),
  modelError = ref('');
const modelKey = (m: any) => JSON.stringify([m?.provider_id, m?.model_id, m?.credential_ref]);
const selectedModel = computed(() =>
  models.value.findIndex((m) => modelKey(m) === modelKey(value.value.config.model)),
);
async function loadModels() {
  models.value = [];
  modelError.value =
    '当前主仓未提供模型目录接口。请从已发布 LLM 配置复制或导入管理员提供的配置；此处不伪造可用模型。';
}
function chooseModel(index: number) {
  if (models.value[index]) {
    value.value.config.model = { ...models.value[index] };
    update();
  }
}
onMounted(loadModels);
async function addChild(e: EvaluatorSummary, checked: boolean) {
  if (checked) {
    value.value.children.push({
      evaluator_id: e.id,
      evaluator_version: e.latest_version!,
      weight: 0.5,
    });
    try {
      versions.value[e.id] = (
        await request<Definition[]>('/evaluators/' + encodeURIComponent(e.id) + '/versions')
      ).map((v) => String(v.version));
    } catch (e) {
      error.value = String(e);
    }
  } else value.value.children = value.value.children.filter((c) => c.evaluator_id !== e.id);
  update();
}
function changeCombination(v: string) {
  value.value.combination = v;
  value.value.children.forEach(
    (c) => (c.weight = v === 'weighted_score' ? 1 / value.value.children.length : null),
  );
  update();
}
const rubricRows = computed(() =>
  Object.entries((value.value.config.rubric as Record<string, string>) ?? {}),
);
const unified = computed(
  () => rubricRows.value.length === 1 && rubricRows.value[0]?.[0] === 'scoring_guide',
);
const guide = computed(() =>
  String(((value.value.config.rubric as Record<string, string>) ?? {}).scoring_guide ?? ''),
);
function convertGuide() {
  if (!window.confirm('将当前各项评分标准合为一段评分说明？原执行指令保留，保存草稿后才生效。'))
    return;
  setConfig('rubric', {
    scoring_guide: rubricRows.value.map(([key, text]) => key + '：' + text).join('\n\n'),
  });
}
const missingChildren = computed(() =>
  value.value.children.filter((c) => !props.items.some((e) => e.id === c.evaluator_id)),
);
const criterion = ref(''),
  criterionText = ref('');
function addCriterion() {
  if (!criterion.value.trim() || !criterionText.value.trim()) return;
  setConfig('rubric', {
    ...(value.value.config.rubric as object),
    [criterion.value.trim()]: criterionText.value.trim(),
  });
  criterion.value = '';
  criterionText.value = '';
}
</script>
<template>
  <fieldset class="evaluator-fields" :disabled="disabled">
    <template v-if="value.kind === 'rule'">
      <section class="rule-design" aria-label="规则评估器设计">
        <h3>规则设计</h3>
        <div class="form-grid">
          <div class="field full">
            <span>判定逻辑</span
            ><strong>{{
              evaluatorScenarios[value.implementation_id] ?? '使用已注册的规则实现'
            }}</strong
            ><small
              >实现：{{ value.implementation_id }} · v{{ value.implementation_version }}</small
            >
          </div>
          <label class="field"
            >失败影响<select
              class="input"
              aria-label="失败影响"
              v-model="value.severity"
              @change="update"
            >
              <option value="standard">普通检查</option>
              <option value="blocking">阻断检查</option>
            </select></label
          >
          <div class="field">
            <span>评估指标</span><strong>{{ value.metric }}</strong>
          </div>
        </div>
        <p class="muted">
          具体期望值、必需／禁用工具及字段条件在测评用例中设置；此处复用后端已注册规则，不支持编写任意代码或新增自定义条件。
        </p>
      </section>
    </template>
    <template v-else-if="value.kind === 'llm_judge'">
      <div class="form-grid">
        <label class="field full"
          >评估模型<select
            class="input"
            aria-label="评估模型"
            :value="selectedModel"
            @change="chooseModel(Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="-1" disabled>
              {{
                value.config.model && (value.config.model as any).model_id
                  ? '原配置模型当前未接入'
                  : '请选择已接入模型'
              }}
            </option>
            <option v-for="(m, i) in models" :key="modelKey(m)" :value="i">
              {{ m.model_id }} · {{ m.provider_id }}
            </option></select
          ><small v-if="!models.length && !modelError"
            >暂无已接入模型，请在配置中查看接入状态。</small
          ><small v-if="modelError" role="alert">{{ modelError }}</small
          ><span class="actions"
            ><button type="button" class="link" @click="loadModels">刷新模型列表</button
            ><a class="link" href="#settings" target="_blank" rel="noopener">查看配置 →</a></span
          ></label
        >
        <label class="field"
          >评估输入范围<select
            class="input"
            :value="value.config.input_selection"
            @change="setConfig('input_selection', ($event.target as HTMLSelectElement).value)"
          >
            <option value="final_output">最终回答</option>
            <option value="output_and_tools">回答及工具记录</option>
            <option value="full_trajectory">完整执行轨迹</option>
          </select></label
        >
        <label class="field"
          >通过分数（0—100）<input
            class="input"
            type="number"
            min="0"
            max="100"
            :value="Number(value.config.pass_threshold ?? 0.8) * 100"
            @input="
              setConfig('pass_threshold', Number(($event.target as HTMLInputElement).value) / 100)
            "
        /></label>
        <label v-if="unified" class="field full"
          >评分说明<textarea
            class="input"
            rows="7"
            aria-label="评分说明"
            :value="guide"
            @input="
              setConfig('rubric', { scoring_guide: ($event.target as HTMLTextAreaElement).value })
            "
          /><small>写明通过条件、扣分情形和判断依据。</small></label
        >
        <details class="field full">
          <summary>输入来源与执行协议</summary>
          <p>
            实际输入来自任务 Trace
            的用户输入和智能体回答，按范围附加工具或轨迹。本版本不支持任意字段映射，也未将样本期望输出传给
            LLM；期望输出的精确比较请使用规则评估器。
          </p>
          <label class="field"
            >执行指令<textarea
              class="input"
              rows="3"
              :value="String(value.config.instruction ?? '')"
              @input="setConfig('instruction', ($event.target as HTMLTextAreaElement).value)"
            />
          </label>
          <p>
            返回分数、判定、原因、置信度及违规项；异常和不适用不计为零分。服务端会拼接评分标准与结构化输出协议。
          </p>
          <pre>{{
            JSON.stringify(
              {
                instruction: value.config.instruction,
                rubric: value.config.rubric,
                input_selection: value.config.input_selection,
              },
              null,
              2,
            )
          }}</pre>
        </details>
      </div>
      <template v-if="!unified"
        ><h3>原有评分标准</h3>
        <p class="muted">保留历史配置。可以继续逐项编辑，或确认转换为统一评分说明。</p>
        <button v-if="!disabled" type="button" class="secondary" @click="convertGuide">
          转换为统一评分说明
        </button>
        <div v-for="[key, text] in rubricRows" :key="key" class="field">
          <label>{{ key }}</label
          ><textarea
            class="input"
            rows="2"
            :value="text"
            @input="
              setConfig('rubric', {
                ...(value.config.rubric as object),
                [key]: ($event.target as HTMLTextAreaElement).value,
              })
            "
          /><button
            class="link"
            @click="setConfig('rubric', Object.fromEntries(rubricRows.filter(([k]) => k !== key)))"
          >
            移除此标准
          </button>
        </div>
        <div v-if="!disabled" class="form-grid">
          <label class="field">标准名称<input v-model="criterion" class="input" /></label
          ><label class="field">判定要求<input v-model="criterionText" class="input" /></label
          ><button class="secondary" @click="addCriterion">添加评分标准</button>
        </div></template
      >
    </template>
    <template v-else-if="value.kind === 'hybrid'">
      <label class="field"
        >组合方式<select
          class="input"
          :value="value.combination"
          @change="changeCombination(($event.target as HTMLSelectElement).value)"
        >
          <option value="weighted_score">加权评分</option>
          <option value="all">全部通过</option>
          <option value="any">至少一项通过（阻断项仍须通过）</option>
        </select></label
      >
      <p
        v-if="value.combination === 'weighted_score'"
        :class="['notice', { error: Math.abs(total - 100) > 0.00001 }]"
      >
        总权重：{{ total.toFixed(2) }}% / 100%。
      </p>
      <div v-for="e in choices" :key="e.id" class="mini-card section-gap">
        <label
          ><input
            type="checkbox"
            :checked="value.children.some((c) => c.evaluator_id === e.id)"
            @change="addChild(e, ($event.target as HTMLInputElement).checked)"
          />
          {{ e.name }} · {{ e.kind === 'rule' ? '规则' : 'LLM'
          }}{{ !e.enabled ? ' · 已停用（保留原引用）' : '' }}</label
        >
        <div
          v-for="(c, rowIndex1) in value.children.filter((c) => c.evaluator_id === e.id)"
          :key="rowIndex1"
          class="form-grid"
        >
          <label class="field"
            >版本<select class="input" v-model="c.evaluator_version" @change="update">
              <option
                v-for="v in [
                  ...new Set([c.evaluator_version, ...(versions[e.id] ?? []), e.latest_version!]),
                ]"
                :key="v"
                :value="v"
              >
                v{{ v }}
              </option>
            </select></label
          ><label v-if="value.combination === 'weighted_score'" class="field"
            >权重（%）<input
              class="input"
              type="number"
              min="0.01"
              max="100"
              step="0.01"
              :value="(c.weight ?? 0) * 100"
              @input="
                c.weight = Number(($event.target as HTMLInputElement).value) / 100;
                update();
              "
          /></label>
        </div>
      </div>
      <label v-if="value.combination === 'weighted_score'" class="field"
        >综合通过分数（0—100）<input
          class="input"
          type="number"
          min="0"
          max="100"
          :value="Number(value.config.pass_threshold ?? 0.8) * 100"
          @input="
            setConfig('pass_threshold', Number(($event.target as HTMLInputElement).value) / 100)
          "
      /></label>
      <p v-for="(c, rowIndex2) in missingChildren" :key="rowIndex2" class="notice error">
        引用的子评估器 {{ c.evaluator_id }} · v{{ c.evaluator_version }}
        当前不可读取；原引用保留，请核对后再保存。
      </p>
      <p v-if="!choices.some((e) => e.kind === 'llm_judge')" class="notice">
        请先创建并发布 LLM 评估器，然后完成复合配置。
      </p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </fieldset>
</template>
<style scoped>
.evaluator-fields {
  border: 0;
  margin: 0;
  padding: 0;
  min-width: 0;
}
.field {
  margin-bottom: 12px;
}
input[type='checkbox'] {
  accent-color: #07ac8e;
}
</style>
