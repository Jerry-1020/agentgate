<script setup lang="ts">
import { computed, ref } from 'vue';
import { pretty } from '../../../api/evaluations';
import ExecutionScope from './ExecutionScope.vue';
const props = defineProps<{ baseline: object; candidate: object }>();
type Descriptor = {
  content_sha256: string;
  prompt?: string;
  description?: string;
};
// Current upstream exposes manifest snapshots, not the descriptor catalog.
const descriptors = ref<Descriptor[]>([]);
const a = computed(() => props.baseline as Record<string, any>),
  b = computed(() => props.candidate as Record<string, any>);
const da = computed(() =>
  descriptors.value.find((d) => d.content_sha256 === a.value.target.descriptor_sha256),
);
const db = computed(() =>
  descriptors.value.find((d) => d.content_sha256 === b.value.target.descriptor_sha256),
);
const same = (x: unknown, y: unknown) => stable(x) === stable(y);
function stable(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => JSON.stringify(k) + ':' + stable(v))
        .join(',') +
      '}'
    );
  return JSON.stringify(value) ?? '未记录';
}
const conditions = computed(() =>
  [
    ['测评集内容', a.value.dataset, b.value.dataset],
    ['评估器及版本定义', a.value.evaluator_specs, b.value.evaluator_specs],
    ['主评估器', a.value.primary_evaluator_ids, b.value.primary_evaluator_ids],
    ['指标口径', a.value.metric_plan, b.value.metric_plan],
    ['通过条件', a.value.gate_spec, b.value.gate_spec],
    [
      '执行参数',
      {
        timeout: a.value.timeout_seconds,
        retries: a.value.max_retries,
        parallel: a.value.max_parallel_cases,
      },
      {
        timeout: b.value.timeout_seconds,
        retries: b.value.max_retries,
        parallel: b.value.max_parallel_cases,
      },
    ],
  ].map(([name, old, next]) => ({ name, old, next, equal: same(old, next) })),
);
</script>
<template>
  <section class="card section-gap" data-testid="configuration-diff">
    <h2 class="section-title">方案差异</h2>
    <p>
      智能体版本：{{ a.target.ref.external_version_id }} → {{ b.target.ref.external_version_id }}
    </p>
    <details v-if="da && db">
      <summary>智能体提示词 · {{ same(da.prompt, db.prompt) ? '一致' : '已变更' }}</summary>
      <div class="grid two-columns">
        <pre>基线：{{ da.prompt ?? '未记录' }}</pre>
        <pre>候选：{{ db.prompt ?? '未记录' }}</pre>
      </div>
    </details>
    <h3>测评条件</h3>
    <ExecutionScope :baseline="a" :candidate="b" />
    <div v-for="c in conditions" :key="String(c.name)">
      <details>
        <summary>{{ c.name }} · {{ c.equal ? '一致' : '不同' }}</summary>
        <div class="grid two-columns">
          <pre>基线：{{ pretty(c.old) ?? '未记录' }}</pre>
          <pre>候选：{{ pretty(c.next) ?? '未记录' }}</pre>
        </div>
      </details>
    </div>
  </section>
</template>
