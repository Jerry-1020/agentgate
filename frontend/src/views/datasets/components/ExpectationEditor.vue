<script setup lang="ts">
import { computed, ref, toRaw, watch } from 'vue';
import type { Condition, Expectation, JsonObject, JsonValue } from '../types/index';

const props = defineProps<{ modelValue: Expectation[]; disabled?: boolean }>();
const emit = defineEmits<{
  'update:modelValue': [value: Expectation[]];
  draftChange: [dirty: boolean];
}>();
const kindLabels = { state: '最终状态', tool_argument: '工具参数', output: '最终输出' };
const rows = ref<Expectation[]>([]);
type JsonField = 'expected' | 'allowed' | 'json_schema';
type JsonDraft = { field: JsonField; text: string; error: string };
const drafts = ref(new Map<string, JsonDraft>());
const error = ref('');
const invalidDraft = computed(() => [...drafts.value.values()].some((draft) => draft.error));
watch(invalidDraft, (dirty) => emit('draftChange', dirty));
let lastEmitted = '';
let lastEmittedValue: Expectation[] | null = null;
let syncing = false;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

watch(
  () => props.modelValue,
  (value) => {
    if (toRaw(value) === lastEmittedValue && JSON.stringify(value) === lastEmitted) return;
    syncing = true;
    const previous = new Map(rows.value.map((row) => [row.id, row]));
    for (const [id] of drafts.value) {
      const current = value.find((row) => row.id === id);
      if (
        !current ||
        JSON.stringify(current.condition) !== JSON.stringify(previous.get(id)?.condition)
      )
        drafts.value.delete(id);
    }
    rows.value = clone(value);
    error.value = '';
    queueMicrotask(() => {
      syncing = false;
    });
  },
  { immediate: true, deep: true },
);
watch(
  rows,
  (value) => {
    if (syncing) return;
    const normalized = value.map((row) => ({
      ...row,
      name: row.name?.trim() || null,
      path: row.kind === 'output' ? row.path?.trim() || null : row.path.trim(),
      ...(row.kind === 'tool_argument' ? { tool: row.tool.trim() } : {}),
    })) as Expectation[];
    lastEmitted = JSON.stringify(normalized);
    lastEmittedValue = clone(normalized);
    emit('update:modelValue', lastEmittedValue);
  },
  { deep: true },
);

function condition(kind: Condition['kind']): Condition {
  switch (kind) {
    case 'equals':
      return { kind, expected: '' };
    case 'within_tolerance':
      return { kind, expected: 0, epsilon: 0.000001 };
    case 'within_range':
      return { kind, minimum: null, maximum: null };
    case 'matches_pattern':
      return { kind, pattern: '' };
    case 'one_of':
      return { kind, allowed: [] };
    case 'matches_json_schema':
      return { kind, json_schema: {} };
    case 'must_be_missing':
      return { kind };
  }
}
function add(kind: Expectation['kind']) {
  const base = { id: crypto.randomUUID(), name: null, condition: condition('equals') };
  if (kind === 'tool_argument')
    rows.value.push({ ...base, kind, path: '', tool: '', occurrence: 'last' });
  else if (kind === 'state') rows.value.push({ ...base, kind, path: '' });
  else rows.value.push({ ...base, kind, path: null });
}
function remove(index: number) {
  drafts.value.delete(rows.value[index].id);
  rows.value.splice(index, 1);
  error.value = '';
}
function changeKind(index: number, kind: Expectation['kind']) {
  const current = rows.value[index];
  const base = { id: current.id, name: current.name, condition: current.condition };
  if (kind === 'tool_argument')
    rows.value[index] = {
      ...base,
      kind,
      path: current.path ?? '',
      tool: current.kind === 'tool_argument' ? current.tool : '',
      occurrence: current.kind === 'tool_argument' ? current.occurrence : 'last',
    };
  else if (kind === 'state') rows.value[index] = { ...base, kind, path: current.path ?? '' };
  else rows.value[index] = { ...base, kind, path: current.path || null };
}
function changeCondition(row: Expectation, kind: Condition['kind']) {
  drafts.value.delete(row.id);
  row.condition = condition(kind);
  error.value = '';
}
function jsonText(row: Expectation, field: JsonField) {
  const draft = drafts.value.get(row.id);
  if (draft?.field === field) return draft.text;
  const value =
    field === 'expected' && row.condition.kind === 'equals'
      ? row.condition.expected
      : field === 'allowed' && row.condition.kind === 'one_of'
        ? row.condition.allowed
        : row.condition.kind === 'matches_json_schema'
          ? row.condition.json_schema
          : null;
  return JSON.stringify(value);
}
function setJson(row: Expectation, field: JsonField, text: string) {
  try {
    let value: JsonValue;
    try {
      value = JSON.parse(text);
    } catch {
      // Plain text remains convenient, but incomplete JSON must not silently become a string.
      if (field !== 'expected' || ['[', '{', '"'].includes(text.trimStart()[0]))
        throw Error('请输入有效 JSON');
      value = text;
    }
    requireFiniteNumbers(value);
    if (field === 'allowed' && (!Array.isArray(value) || !value.length))
      throw Error('允许值必须是非空 JSON 数组');
    if (field === 'json_schema' && (!value || typeof value !== 'object' || Array.isArray(value)))
      throw Error('JSON Schema 必须是 JSON 对象');
    if (field === 'expected' && row.condition.kind === 'equals') row.condition.expected = value;
    else if (field === 'allowed' && row.condition.kind === 'one_of')
      row.condition.allowed = value as JsonValue[];
    else if (field === 'json_schema' && row.condition.kind === 'matches_json_schema')
      row.condition.json_schema = value as JsonObject;
    drafts.value.set(row.id, { field, text, error: '' });
    error.value = '';
  } catch (e) {
    drafts.value.set(row.id, { field, text, error: e instanceof Error ? e.message : String(e) });
  }
}
function requireFiniteNumbers(value: JsonValue) {
  if (typeof value === 'number' && !Number.isFinite(value)) throw Error('JSON 数字必须是有限值');
  if (value && typeof value === 'object') Object.values(value).forEach(requireFiniteNumbers);
}
function canonical(value: JsonValue): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ':' + canonical(value[key]))
        .join(',') +
      '}'
    );
  return JSON.stringify(value);
}
function validate() {
  error.value = '';
  try {
    rows.value.forEach((row, index) => {
      const prefix = `第 ${index + 1} 项${kindLabels[row.kind]}：`;
      const fail = (message: string) => {
        throw Error(prefix + message);
      };
      const draft = drafts.value.get(row.id);
      if (draft?.error) fail(draft.error);
      if (row.kind !== 'output' && !row.path.trim()) fail('请输入字段路径');
      if (row.kind === 'tool_argument' && !row.tool.trim()) fail('请输入工具名');
      const c = row.condition;
      if (
        c.kind === 'within_tolerance' &&
        (typeof c.expected !== 'number' ||
          !Number.isFinite(c.expected) ||
          typeof c.epsilon !== 'number' ||
          !Number.isFinite(c.epsilon) ||
          c.epsilon <= 0)
      )
        fail('期望值须为有限数值，容差须大于 0');
      if (c.kind === 'within_range') {
        if (c.minimum == null && c.maximum == null) fail('请至少填写一个范围边界');
        for (const bound of [c.minimum, c.maximum])
          if (bound != null && (typeof bound !== 'number' || !Number.isFinite(bound)))
            fail('范围边界须为有限数值');
        if (c.minimum != null && c.maximum != null && c.minimum > c.maximum)
          fail('最小值不能大于最大值');
      }
      if (c.kind === 'one_of') {
        if (!c.allowed.length) fail('允许值必须是非空 JSON 数组');
        if (new Set(c.allowed.map(canonical)).size !== c.allowed.length) fail('允许值不能重复');
      }
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    throw e;
  }
}
defineExpose({ validate });
</script>

<template>
  <section class="expectation-editor" aria-label="期望结果">
    <div class="subsection-heading">
      <div><b>期望结果</b><small>系统会把每一项期望与真实 Trace、状态或输出比较。</small></div>
      <el-dropdown v-if="!disabled" trigger="click" @command="add">
        <el-button type="primary" plain data-testid="add-expectation">添加期望</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="(label, kind) in kindLabels" :key="kind" :command="kind">{{
              label
            }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <div
      v-for="(row, index) in rows"
      :key="row.id"
      class="expectation-row"
      :data-testid="`expectation-${index}`"
    >
      <div class="expectation-row-head">
        <el-select
          :model-value="row.kind"
          :disabled="disabled"
          aria-label="期望类型"
          @update:model-value="changeKind(index, $event)"
        >
          <el-option v-for="(label, kind) in kindLabels" :key="kind" :label="label" :value="kind" />
        </el-select>
        <el-input v-model="row.name" :disabled="disabled" placeholder="检查名称（可选）" />
        <el-button v-if="!disabled" link type="danger" @click="remove(index)">删除</el-button>
      </div>
      <div class="expectation-fields">
        <label v-if="row.kind === 'tool_argument'"
          >工具名 <span class="required">*</span>
          <el-input
            v-model="row.tool"
            :disabled="disabled"
            :data-testid="`expectation-tool-${index}`"
            placeholder="工具名，例如 approve_loan"
          />
        </label>
        <label
          >{{ row.kind === 'output' ? '输出路径' : '字段路径' }}
          <span v-if="row.kind !== 'output'" class="required">*</span>
          <el-input
            v-model="row.path"
            :disabled="disabled"
            :data-testid="`expectation-path-${index}`"
            :aria-label="row.kind === 'output' ? '输出路径' : '字段路径'"
            :placeholder="
              row.kind === 'output'
                ? '输出路径（留空表示完整输出）'
                : row.kind === 'tool_argument'
                  ? '例如 arguments.amount'
                  : '例如 status'
            "
          />
        </label>
        <label v-if="row.kind === 'tool_argument'"
          >调用范围
          <el-select v-model="row.occurrence" :disabled="disabled" aria-label="调用范围">
            <el-option label="最后一次调用" value="last" /><el-option
              label="第一次调用"
              value="first"
            />
            <el-option label="任意一次通过" value="any" /><el-option
              label="所有调用通过"
              value="all"
            />
          </el-select>
        </label>
        <label
          >判定方式
          <el-select
            :model-value="row.condition.kind"
            :disabled="disabled"
            aria-label="判定方式"
            @update:model-value="changeCondition(row, $event)"
          >
            <el-option label="等于" value="equals" /><el-option
              label="数值容差"
              value="within_tolerance"
            />
            <el-option label="数值范围" value="within_range" /><el-option
              label="正则匹配"
              value="matches_pattern"
            />
            <el-option label="属于集合" value="one_of" /><el-option
              label="字段不存在"
              value="must_be_missing"
            />
            <el-option label="JSON Schema" value="matches_json_schema" />
          </el-select>
        </label>
        <label v-if="row.condition.kind === 'equals'" class="value-field"
          >期望值
          <el-input
            :model-value="jsonText(row, 'expected')"
            :disabled="disabled"
            :data-testid="`expectation-value-${index}`"
            placeholder="期望值，支持 JSON"
            @input="setJson(row, 'expected', $event)"
          />
        </label>
        <template v-else-if="row.condition.kind === 'within_tolerance'">
          <label
            >期望值<el-input-number
              v-model="row.condition.expected"
              :disabled="disabled"
              placeholder="期望值"
          /></label>
          <label
            >容差<el-input-number
              v-model="row.condition.epsilon"
              :disabled="disabled"
              aria-label="容差"
              placeholder="容差"
          /></label>
        </template>
        <template v-else-if="row.condition.kind === 'within_range'">
          <label
            >最小值<el-input-number
              v-model="row.condition.minimum"
              :disabled="disabled"
              placeholder="最小值"
          /></label>
          <label
            >最大值<el-input-number
              v-model="row.condition.maximum"
              :disabled="disabled"
              placeholder="最大值"
          /></label>
        </template>
        <label v-else-if="row.condition.kind === 'matches_pattern'" class="value-field"
          >正则表达式
          <el-input v-model="row.condition.pattern" :disabled="disabled" placeholder="正则表达式" />
        </label>
        <label v-else-if="row.condition.kind === 'one_of'" class="value-field"
          >允许值（JSON 数组）
          <el-input
            :model-value="jsonText(row, 'allowed')"
            :disabled="disabled"
            :data-testid="`expectation-allowed-${index}`"
            placeholder='例如 ["completed", "approved"]'
            @input="setJson(row, 'allowed', $event)"
          />
        </label>
        <label v-else-if="row.condition.kind === 'matches_json_schema'" class="value-field"
          >JSON Schema
          <el-input
            :model-value="jsonText(row, 'json_schema')"
            type="textarea"
            :rows="3"
            :disabled="disabled"
            :data-testid="`expectation-schema-${index}`"
            placeholder="JSON Schema 对象"
            @input="setJson(row, 'json_schema', $event)"
          />
        </label>
      </div>
      <p v-if="drafts.get(row.id)?.error" class="expectation-error" role="alert">
        {{ drafts.get(row.id)?.error }}
      </p>
    </div>
    <el-empty v-if="!rows.length" description="暂无字段、状态或输出期望" :image-size="58" />
    <p v-if="error" class="expectation-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.expectation-editor {
  border: 1px solid #dfe8e6;
  border-radius: 10px;
  padding: 18px;
  background: #f8faf9;
}
.subsection-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.subsection-heading b {
  font-size: 14px;
}
.subsection-heading small {
  display: block;
  margin-top: 6px;
  color: #74829a;
  font-size: 12px;
}
.subsection-heading :deep(.el-button) {
  flex-shrink: 0;
}
.expectation-row {
  padding: 16px;
  margin-top: 12px;
  border: 1px solid #e1e7f1;
  border-radius: 8px;
  background: #fff;
}
.expectation-row-head {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}
.expectation-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}
.expectation-fields label {
  display: block;
  min-width: 0;
  font-size: 12px;
  color: #5a6879;
}
.expectation-fields label :deep(.el-input),
.expectation-fields label :deep(.el-select),
.expectation-fields label :deep(.el-input-number),
.expectation-fields label :deep(.el-textarea) {
  width: 100%;
  margin-top: 6px;
}
.expectation-fields label :deep(.el-input-number .el-input) {
  margin-top: 0;
}
.value-field {
  grid-column: 1 / -1;
}
.required,
.expectation-error {
  color: #d14343;
}
.expectation-error {
  font-size: 12px;
  margin-bottom: 0;
}
@media (max-width: 760px) {
  .subsection-heading {
    align-items: flex-start;
  }
  .expectation-row-head {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .expectation-row-head > :first-child {
    grid-column: 1 / -1;
  }
  .expectation-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
