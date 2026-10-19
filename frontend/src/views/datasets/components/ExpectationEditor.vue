<script setup lang="ts">
import { ref, watch } from 'vue';
import type { Expectation } from '../types/index';
import { expectationFieldsFromText, expectationFieldsText } from '../utils/sample-expectations';

type ExpectationKind = Expectation['kind'];
const props = withDefaults(
  defineProps<{
    modelValue: Expectation[];
    disabled?: boolean;
    kinds?: ExpectationKind[];
    compactOutput?: boolean;
    simplified?: boolean;
  }>(),
  { kinds: () => ['state', 'tool_argument', 'output'] },
);
const kindLabels: Record<ExpectationKind, string> = {
  state: '最终状态',
  tool_argument: '工具参数',
  output: '最终输出',
};
const emit = defineEmits<{
  'update:modelValue': [value: Expectation[]];
  draftChange: [dirty: boolean];
}>();
const rows = ref<any[]>([]);
type ToolRule = Extract<Expectation, { kind: 'tool_argument' }>;
type StateRule = Extract<Expectation, { kind: 'state' }>;
type ToolDraft = { id: string; tool: string; text: string; original: ToolRule[] };
const stateText = ref('');
const originalStates = ref<StateRule[]>([]);
const toolDrafts = ref<ToolDraft[]>([]);
const simpleError = ref('');
let lastSimpleModel = '';
// Keep incomplete JSON as typed text; only the parsed value belongs in the saved model.
const jsonDrafts = ref(new Map<string, { text: string; serialized: string | undefined }>());
let syncing = false;
const cloneJson = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

watch(
  () => props.modelValue,
  (value) => {
    syncing = true;
    rows.value = cloneJson(value ?? []);
    if (props.simplified && JSON.stringify(value ?? []) !== lastSimpleModel) {
      originalStates.value = cloneJson(
        value.filter((row): row is StateRule => row.kind === 'state'),
      );
      stateText.value = expectationFieldsText(originalStates.value);
      const groups = new Map<string, ToolDraft>();
      for (const row of value) {
        if (row.kind !== 'tool_argument') continue;
        const key = JSON.stringify([row.tool, row.occurrence]);
        if (!groups.has(key))
          groups.set(key, { id: row.id, tool: row.tool, text: '', original: [] });
        groups.get(key)!.original.push(cloneJson(row));
      }
      toolDrafts.value = [...groups.values()].map((group) => ({
        ...group,
        text: expectationFieldsText(group.original, 'arguments.'),
      }));
      if (!toolDrafts.value.length)
        toolDrafts.value.push({ id: crypto.randomUUID(), tool: '', text: '', original: [] });
      simpleError.value = '';
      lastSimpleModel = JSON.stringify(value ?? []);
      emit('draftChange', false);
    }
    const currentRows = new Map(rows.value.map((row) => [row.id, row]));
    for (const [id, draft] of jsonDrafts.value) {
      const row = currentRows.get(id);
      if (
        row?.condition?.kind !== 'equals' ||
        serializedExpected(row.condition.expected) !== draft.serialized
      ) {
        jsonDrafts.value.delete(id);
      }
    }
    queueMicrotask(() => {
      syncing = false;
    });
  },
  { immediate: true, deep: true },
);
watch(
  rows,
  (value) => {
    if (!syncing) emit('update:modelValue', cloneJson(value));
  },
  { deep: true },
);

const uuid = () => crypto.randomUUID();

function simpleValues(): { values: Expectation[]; tools: ToolRule[][] } {
  let values: Expectation[];
  try {
    values = expectationFieldsFromText(stateText.value, originalStates.value, uuid).map((row) => ({
      ...row,
      kind: 'state',
    }));
  } catch (error) {
    throw Error('最终状态：' + (error instanceof Error ? error.message : String(error)));
  }
  const tools: ToolRule[][] = [];
  for (const draft of toolDrafts.value) {
    if (!draft.tool.trim() && !draft.text.trim()) {
      tools.push([]);
      continue;
    }
    if (!draft.tool.trim()) throw Error('工具参数：请输入工具名');
    if (!draft.text.trim()) throw Error('工具参数：请输入工具参数值');
    try {
      const rules = expectationFieldsFromText(draft.text, draft.original, uuid, 'arguments.').map(
        (row) => ({
          ...row,
          kind: 'tool_argument' as const,
          tool: draft.tool.trim(),
          occurrence:
            draft.original.find((original) => original.id === row.id)?.occurrence ??
            draft.original[0]?.occurrence ??
            'last',
        }),
      );
      tools.push(rules);
      values.push(...rules);
    } catch (error) {
      throw Error('工具参数：' + (error instanceof Error ? error.message : String(error)));
    }
  }
  return { values: [...props.modelValue.filter((row) => row.kind === 'output'), ...values], tools };
}

function validate() {
  if (!props.simplified) return;
  try {
    simpleValues();
    simpleError.value = '';
  } catch (error) {
    simpleError.value = error instanceof Error ? error.message : String(error);
    throw error;
  }
}

function updateSimple() {
  try {
    const { values, tools } = simpleValues();
    originalStates.value = rememberRules(
      originalStates.value,
      values.filter((row): row is StateRule => row.kind === 'state'),
    );
    toolDrafts.value.forEach((draft, index) => {
      draft.original = rememberRules(draft.original, tools[index]);
    });
    simpleError.value = '';
    lastSimpleModel = JSON.stringify(values);
    emit('update:modelValue', values);
    emit('draftChange', false);
  } catch (error) {
    simpleError.value = error instanceof Error ? error.message : String(error);
    emit('draftChange', true);
  }
}

function rememberRules<T extends { id: string }>(original: T[], current: T[]): T[] {
  const known = new Map(original.map((row) => [row.id, row]));
  for (const row of current) known.set(row.id, cloneJson(row));
  return [...known.values()];
}

function removeTool(index: number) {
  if (props.disabled) return;
  toolDrafts.value.splice(index, 1);
  if (!toolDrafts.value.length)
    toolDrafts.value.push({ id: uuid(), tool: '', text: '', original: [] });
  updateSimple();
}

defineExpose({ validate });
const condition = (kind = 'equals'): any => {
  if (kind === 'equals') return { kind, expected: '' };
  if (kind === 'within_tolerance') return { kind, expected: 0, epsilon: 0.000001 };
  if (kind === 'within_range') return { kind, minimum: null, maximum: null };
  if (kind === 'matches_pattern') return { kind, pattern: '' };
  if (kind === 'one_of') return { kind, allowed: [] };
  return { kind: 'must_be_missing' };
};

function add(kind: 'state' | 'tool_argument' | 'output' = 'state') {
  const base: any = { id: uuid(), kind, name: null, path: '', condition: condition() };
  if (kind === 'tool_argument') Object.assign(base, { tool: '', occurrence: 'last' });
  if (kind === 'output') base.path = null;
  rows.value.push(base);
}

function removeOutput(index: number) {
  if (props.disabled || rows.value.length <= 1) return;
  rows.value.splice(index, 1);
}

function changeKind(index: number, kind: string) {
  const current = rows.value[index];
  const next: any = {
    id: current.id,
    kind,
    name: current.name,
    path: kind === 'output' ? null : (current.path ?? ''),
    condition: current.condition,
  };
  if (kind === 'tool_argument')
    Object.assign(next, {
      tool: current.tool ?? '',
      occurrence: current.occurrence ?? 'last',
    });
  rows.value[index] = next;
}

function changeCondition(row: any, kind: string) {
  jsonDrafts.value.delete(row.id);
  row.condition = condition(kind);
}

function serializedExpected(value: unknown) {
  return JSON.stringify(value === undefined ? '' : value);
}

function asJson(row: any) {
  const serialized = serializedExpected(row.condition.expected);
  const draft = jsonDrafts.value.get(row.id);
  return draft && draft.serialized === serialized ? draft.text : serialized;
}

function setJson(row: any, field: string, value: string) {
  try {
    row.condition[field] = JSON.parse(value);
  } catch {
    row.condition[field] = value;
  }
  jsonDrafts.value.set(row.id, {
    text: value,
    serialized: serializedExpected(row.condition.expected),
  });
}

function allowedText(row: any) {
  return (row.condition.allowed ?? [])
    .map((item: unknown) => (typeof item === 'string' ? item : JSON.stringify(item)))
    .join(', ');
}

function setAllowed(row: any, value: string) {
  row.condition.allowed = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      try {
        return JSON.parse(item);
      } catch {
        return item;
      }
    });
}
</script>

<template>
  <div v-if="simplified" class="simple-expectations">
    <section class="rule-card">
      <header><b>最终状态</b></header>
      <textarea
        v-model="stateText"
        :disabled="disabled"
        rows="1"
        wrap="off"
        aria-label="最终状态值"
        placeholder='请输入期望的最终状态，例如 {"status": "completed"}'
        @input="updateSimple"
      />
    </section>
    <section class="rule-card">
      <header>
        <b>工具参数</b>
      </header>
      <div v-for="(draft, index) in toolDrafts" :key="draft.id" class="tool-draft">
        <label>
          工具名
          <input
            v-model="draft.tool"
            :disabled="disabled"
            :aria-label="`工具名 ${index + 1}`"
            placeholder="请输入工具名"
            @input="updateSimple"
          />
        </label>
        <label>
          工具参数值
          <textarea
            v-model="draft.text"
            :disabled="disabled"
            rows="1"
            wrap="off"
            :aria-label="`工具参数值 ${index + 1}`"
            placeholder='请输入期望的工具参数，例如 {"limit": 10}'
            @input="updateSimple"
          />
        </label>
        <el-button
          v-if="!disabled && (toolDrafts.length > 1 || draft.tool || draft.text)"
          link
          type="danger"
          @click="removeTool(index)"
          >删除工具</el-button
        >
      </div>
    </section>
    <p v-if="simpleError" class="simple-error" role="alert">{{ simpleError }}</p>
  </div>
  <div v-else class="expectation-editor">
    <h4 v-if="compactOutput" class="output-heading">期望评估方式</h4>
    <div v-if="!compactOutput" class="subsection-heading">
      <div><b>期望结果</b><small>系统会把每一项期望与真实 Trace、状态或输出比较。</small></div>
      <el-button
        v-if="!disabled && kinds.length === 1"
        size="small"
        data-testid="add-expectation"
        @click="add(kinds[0])"
        >添加期望</el-button
      >
      <el-dropdown v-else-if="!disabled" trigger="click" @command="add">
        <el-button size="small" data-testid="add-expectation">添加期望</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="kind in kinds" :key="kind" :command="kind">{{
              kindLabels[kind]
            }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div
      v-for="(row, index) in rows"
      :key="row.id"
      class="expectation-row"
      :class="{ 'compact-row': compactOutput }"
      :data-testid="`expectation-${index}`"
    >
      <div v-if="!compactOutput" class="expectation-row-head">
        <el-select
          :model-value="row.kind"
          :disabled="disabled"
          size="small"
          @update:model-value="changeKind(index, $event)"
        >
          <el-option v-for="kind in kinds" :key="kind" :label="kindLabels[kind]" :value="kind" />
        </el-select>
        <el-input
          v-model="row.name"
          :disabled="disabled"
          size="small"
          placeholder="检查名称（可选）"
        />
        <el-button v-if="!disabled" link type="danger" @click="rows.splice(index, 1)"
          >删除</el-button
        >
      </div>
      <el-button
        v-if="compactOutput && !disabled"
        class="remove-output"
        link
        type="danger"
        :disabled="rows.length <= 1"
        @click="removeOutput(index)"
        >删除</el-button
      >
      <div class="expectation-fields" :class="{ 'compact-output': compactOutput }">
        <el-input
          v-if="row.kind === 'tool_argument'"
          v-model="row.tool"
          :disabled="disabled"
          :data-testid="`expectation-tool-${index}`"
          placeholder="工具名，例如 approve_loan"
        />
        <label v-if="compactOutput" class="compact-label"
          >输出路径
          <el-input
            v-model="row.path"
            :disabled="disabled"
            :data-testid="`expectation-path-${index}`"
            :aria-label="row.kind === 'output' ? '输出路径' : '字段路径'"
            :placeholder="
              row.kind === 'output' ? '输出路径（留空表示完整输出）' : '字段路径，例如 status'
            "
          />
        </label>
        <el-input
          v-else
          v-model="row.path"
          :disabled="disabled"
          :data-testid="`expectation-path-${index}`"
          :aria-label="row.kind === 'output' ? '输出路径' : '字段路径'"
          :placeholder="
            row.kind === 'output' ? '输出路径（留空表示完整输出）' : '字段路径，例如 status'
          "
        />
        <el-select
          v-if="row.kind === 'tool_argument'"
          v-model="row.occurrence"
          :disabled="disabled"
        >
          <el-option label="最后一次调用" value="last" />
          <el-option label="第一次调用" value="first" />
          <el-option label="任意一次通过" value="any" />
          <el-option label="所有调用通过" value="all" />
        </el-select>
        <div class="condition-select">
          <label v-if="compactOutput">评估方式</label>
          <el-select
            :model-value="row.condition.kind"
            :disabled="disabled"
            :aria-label="compactOutput ? '评估方式' : '判定方式'"
            @update:model-value="changeCondition(row, $event)"
          >
            <el-option label="等于" value="equals" />
            <el-option label="数值容差" value="within_tolerance" />
            <el-option label="数值范围" value="within_range" />
            <el-option label="正则匹配" value="matches_pattern" />
            <el-option label="属于集合" value="one_of" />
            <el-option label="字段不存在" value="must_be_missing" />
          </el-select>
        </div>
        <el-input
          v-if="!compactOutput && row.condition.kind === 'equals'"
          :model-value="asJson(row)"
          :disabled="disabled"
          :data-testid="`expectation-value-${index}`"
          placeholder="期望值，支持 JSON"
          @input="setJson(row, 'expected', $event)"
        />
        <template v-else-if="row.condition.kind === 'within_tolerance'">
          <el-input-number
            v-if="!compactOutput"
            v-model="row.condition.expected"
            :disabled="disabled"
            placeholder="期望值"
          />
          <el-input-number
            v-model="row.condition.epsilon"
            aria-label="容差"
            :disabled="disabled"
            :min="0.000000001"
            placeholder="容差"
          />
        </template>
        <template v-else-if="row.condition.kind === 'within_range'">
          <el-input-number
            v-model="row.condition.minimum"
            :disabled="disabled"
            placeholder="最小值"
          />
          <el-input-number
            v-model="row.condition.maximum"
            :disabled="disabled"
            placeholder="最大值"
          />
        </template>
        <el-input
          v-else-if="!compactOutput && row.condition.kind === 'matches_pattern'"
          v-model="row.condition.pattern"
          :disabled="disabled"
          placeholder="正则表达式"
        />
        <el-input
          v-else-if="!compactOutput && row.condition.kind === 'one_of'"
          :model-value="allowedText(row)"
          :disabled="disabled"
          placeholder="允许值，逗号分隔"
          @input="setAllowed(row, $event)"
        />
      </div>
    </div>
    <el-button v-if="compactOutput && !disabled" class="add-output" @click="add('output')"
      >增加评估方式</el-button
    >
    <el-empty
      v-if="!compactOutput && !rows.length"
      description="暂无字段、状态或输出期望"
      :image-size="58"
    />
  </div>
</template>

<style scoped>
.rule-card {
  background: #fff;
  border: 1px solid #e1e7f1;
  border-top: 3px solid #b294ff;
  border-radius: 10px;
  margin-bottom: 16px;
  padding: 16px;
}
.rule-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 16px;
}
.rule-card label {
  display: block;
  font-size: 12px;
  color: #74829a;
  margin: 8px 0;
}
.rule-card input,
.rule-card textarea {
  box-sizing: border-box;
  height: 40px;
  width: 100%;
  border: 1px solid #dbe2ee;
  border-radius: 7px;
  background: #fff;
  padding: 10px;
  margin-top: 7px;
  color: #34435a;
  font: inherit;
  font-size: 12px;
}
.rule-card textarea {
  resize: none;
  line-height: 18px;
}
.rule-card input:disabled,
.rule-card textarea:disabled {
  background: #f8fafc;
}
.rule-card > textarea {
  margin-top: 0;
}
.tool-draft + .tool-draft {
  border-top: 1px solid #e1e7f1;
  margin-top: 16px;
  padding-top: 8px;
}
.simple-error {
  color: #c33;
  font-size: 12px;
}
.output-heading {
  margin: 0 0 12px;
  font-size: 14px;
}
.expectation-row.compact-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.compact-row .expectation-fields {
  flex: 1;
  min-width: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.remove-output {
  order: 1;
  flex-shrink: 0;
  margin-top: 24px;
}
.compact-row .compact-label,
.compact-row .condition-select > label {
  display: block;
  margin: 0;
  line-height: 18px;
  font-size: 12px;
  color: #74829a;
}
.compact-row .compact-label :deep(.el-input),
.compact-row .condition-select :deep(.el-select) {
  margin-top: 7px;
  width: 100%;
}
.compact-row .condition-select :deep(.el-select__wrapper) {
  min-height: 40px;
}
.add-output {
  margin-top: 12px;
}
</style>
