<script setup lang="ts">
import { computed, ref } from 'vue';
import type { EvaluationRun } from '../../../api/evaluations';
import { comparisonIssues } from '../utils/comparison-compatibility';

const props = defineProps<{
  modelValue: string;
  rows: EvaluationRun[];
  label: string;
  excluded?: string;
  compatibleWith?: EvaluationRun;
  loading?: boolean;
  disabled?: boolean;
}>();
const emit = defineEmits<{ 'update:modelValue': [id: string] }>();
const query = ref('');
const date = (run: EvaluationRun) => new Date(run.completed_at ?? run.created_at).toLocaleString();
const labelFor = (run: EvaluationRun) =>
  run.manifest.target.ref.external_version_id + ' · ' + run.id.slice(0, 8) + ' · ' + date(run);
const options = computed(() =>
  props.rows
    .filter((run) => run.id !== props.excluded)
    .map((run) => ({
      run,
      label: labelFor(run),
      compatible: !!props.compatibleWith && !comparisonIssues(props.compatibleWith, run).length,
      search: [
        run.id,
        run.manifest.target.display_name,
        run.manifest.target.ref.external_target_id,
        run.manifest.target.ref.external_version_id,
        run.manifest.dataset.dataset_name,
        'v' + run.manifest.dataset.version,
        date(run),
      ]
        .join(' ')
        .toLowerCase(),
    }))
    .filter((item) =>
      query.value
        .toLowerCase()
        .trim()
        .split(/\s+/)
        .every((word) => item.search.includes(word)),
    ),
);
const groups = computed(() =>
  props.compatibleWith
    ? [
        { label: '同口径任务（优先展示）', items: options.value.filter((item) => item.compatible) },
        {
          label: '其他任务（仅并列查看）',
          items: options.value.filter((item) => !item.compatible),
        },
      ]
    : [{ label: '已完成任务 · 按完成时间排序', items: options.value }],
);
</script>
<template>
  <el-select
    class="run-choice"
    :model-value="modelValue || undefined"
    filterable
    clearable
    :filter-method="(value: string) => (query = value)"
    :aria-label="label"
    :placeholder="disabled ? '请先选择实验A的任务' : '搜索并选择已完成任务（名称 / ID / 版本）'"
    :loading="loading"
    :disabled="disabled"
    no-match-text="没有匹配的已完成任务"
    no-data-text="暂无已完成任务"
    loading-text="正在读取任务…"
    @visible-change="query = ''"
    @update:model-value="emit('update:modelValue', $event ?? '')"
  >
    <el-option-group
      v-for="group in groups.filter((group) => group.items.length)"
      :key="group.label"
      :label="group.label"
    >
      <el-option
        v-for="item in group.items"
        :key="item.run.id"
        :value="item.run.id"
        :label="item.label"
        :data-testid="'run-option-' + item.run.id"
        class="history-run-option"
      >
        <div class="run-option-title">
          {{ item.run.manifest.target.display_name }} ·
          {{ item.run.manifest.target.ref.external_version_id }}
        </div>
        <div class="run-option-meta">
          {{ item.run.manifest.dataset.dataset_name }} · v{{ item.run.manifest.dataset.version }} ·
          {{ item.run.id.slice(0, 8) }} · {{ date(item.run) }}
        </div>
      </el-option>
    </el-option-group>
  </el-select>
</template>
<style scoped>
.run-choice {
  width: 100%;
  min-width: 0;
}
.run-choice :deep(.el-select__placeholder) {
  pointer-events: none;
}
.history-run-option {
  height: auto;
  min-height: 64px;
  padding-top: 8px;
  padding-bottom: 8px;
  line-height: 1.5;
  max-width: min(720px, 85vw);
}
.run-option-title,
.run-option-meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-option-title {
  font-size: 13px;
}
.run-option-meta {
  font-size: 12px;
  color: #6b7280;
  margin-top: 4px;
  font-weight: 400;
}
</style>
