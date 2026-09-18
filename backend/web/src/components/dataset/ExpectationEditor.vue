<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Expectation } from '../../types/dataset'

const props = defineProps<{ modelValue: Expectation[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Expectation[]] }>()
const rows = ref<any[]>([])
let syncing = false
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

watch(
  () => props.modelValue,
  value => {
    syncing = true
    rows.value = cloneJson(value ?? [])
    queueMicrotask(() => { syncing = false })
  },
  { immediate: true, deep: true },
)
watch(rows, value => {
  if (!syncing) emit('update:modelValue', cloneJson(value))
}, { deep: true })

const uuid = () => crypto.randomUUID()
const condition = (kind = 'equals'): any => {
  if (kind === 'equals') return { kind, expected: '' }
  if (kind === 'within_tolerance') return { kind, expected: 0, epsilon: 0.000001 }
  if (kind === 'within_range') return { kind, minimum: null, maximum: null }
  if (kind === 'matches_pattern') return { kind, pattern: '' }
  if (kind === 'one_of') return { kind, allowed: [] }
  return { kind: 'must_be_missing' }
}

function add(kind: 'state'|'tool_argument'|'output' = 'state') {
  const base: any = { id: uuid(), kind, name: null, path: '', condition: condition() }
  if (kind === 'tool_argument') Object.assign(base, { tool: '', occurrence: 'last' })
  if (kind === 'output') base.path = null
  rows.value.push(base)
}

function changeKind(index: number, kind: string) {
  const current = rows.value[index]
  const next: any = {
    id: current.id,
    kind,
    name: current.name,
    path: kind === 'output' ? null : current.path ?? '',
    condition: current.condition,
  }
  if (kind === 'tool_argument') Object.assign(next, {
    tool: current.tool ?? '',
    occurrence: current.occurrence ?? 'last',
  })
  rows.value[index] = next
}

function changeCondition(row: any, kind: string) {
  row.condition = condition(kind)
}

function asJson(value: unknown) {
  return JSON.stringify(value ?? '', null, 0)
}

function setJson(row: any, field: string, value: string) {
  try { row.condition[field] = JSON.parse(value) }
  catch { row.condition[field] = value }
}

function allowedText(row: any) {
  return (row.condition.allowed ?? []).map((item: unknown) =>
    typeof item === 'string' ? item : JSON.stringify(item)
  ).join(', ')
}

function setAllowed(row: any, value: string) {
  row.condition.allowed = value.split(',').map(item => item.trim()).filter(Boolean).map(item => {
    try { return JSON.parse(item) } catch { return item }
  })
}
</script>

<template>
  <div class="expectation-editor">
    <div class="subsection-heading">
      <div><b>期望结果</b><small>系统会把每一项期望与真实 Trace、状态或输出比较。</small></div>
      <el-dropdown v-if="!disabled" trigger="click" @command="add">
        <el-button size="small" data-testid="add-expectation">添加期望</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="state">最终状态</el-dropdown-item>
            <el-dropdown-item command="tool_argument">工具参数</el-dropdown-item>
            <el-dropdown-item command="output">最终输出</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div v-for="(row, index) in rows" :key="row.id" class="expectation-row" :data-testid="`expectation-${index}`">
      <div class="expectation-row-head">
        <el-select :model-value="row.kind" :disabled="disabled" size="small" @update:model-value="changeKind(index, $event)">
          <el-option label="最终状态" value="state" />
          <el-option label="工具参数" value="tool_argument" />
          <el-option label="最终输出" value="output" />
        </el-select>
        <el-input v-model="row.name" :disabled="disabled" size="small" placeholder="检查名称（可选）" />
        <el-button v-if="!disabled" link type="danger" @click="rows.splice(index, 1)">删除</el-button>
      </div>
      <div class="expectation-fields">
        <el-input v-if="row.kind === 'tool_argument'" v-model="row.tool" :disabled="disabled" :data-testid="`expectation-tool-${index}`" placeholder="工具名，例如 approve_loan" />
        <el-input v-model="row.path" :disabled="disabled" :data-testid="`expectation-path-${index}`" :placeholder="row.kind === 'output' ? '输出路径（留空表示完整输出）' : '字段路径，例如 status'" />
        <el-select v-if="row.kind === 'tool_argument'" v-model="row.occurrence" :disabled="disabled">
          <el-option label="最后一次调用" value="last" />
          <el-option label="第一次调用" value="first" />
          <el-option label="任意一次通过" value="any" />
          <el-option label="所有调用通过" value="all" />
        </el-select>
        <el-select :model-value="row.condition.kind" :disabled="disabled" @update:model-value="changeCondition(row, $event)">
          <el-option label="等于" value="equals" />
          <el-option label="数值容差" value="within_tolerance" />
          <el-option label="数值范围" value="within_range" />
          <el-option label="正则匹配" value="matches_pattern" />
          <el-option label="属于集合" value="one_of" />
          <el-option label="字段不存在" value="must_be_missing" />
        </el-select>
        <el-input
          v-if="row.condition.kind === 'equals'"
          :model-value="asJson(row.condition.expected)"
          :disabled="disabled"
          :data-testid="`expectation-value-${index}`"
          placeholder="期望值，支持 JSON"
          @input="setJson(row, 'expected', $event)"
        />
        <template v-else-if="row.condition.kind === 'within_tolerance'">
          <el-input-number v-model="row.condition.expected" :disabled="disabled" placeholder="期望值" />
          <el-input-number v-model="row.condition.epsilon" :disabled="disabled" :min="0.000000001" placeholder="容差" />
        </template>
        <template v-else-if="row.condition.kind === 'within_range'">
          <el-input-number v-model="row.condition.minimum" :disabled="disabled" placeholder="最小值" />
          <el-input-number v-model="row.condition.maximum" :disabled="disabled" placeholder="最大值" />
        </template>
        <el-input v-else-if="row.condition.kind === 'matches_pattern'" v-model="row.condition.pattern" :disabled="disabled" placeholder="正则表达式" />
        <el-input v-else-if="row.condition.kind === 'one_of'" :model-value="allowedText(row)" :disabled="disabled" placeholder="允许值，逗号分隔" @input="setAllowed(row, $event)" />
      </div>
    </div>
    <el-empty v-if="!rows.length" description="暂无字段、状态或输出期望" :image-size="58" />
  </div>
</template>
