<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { request, pretty } from '../../../api/evaluations';
import ExecutionScope from './ExecutionScope.vue';
const props = defineProps<{ baseline: object; candidate: object }>();
type Skill = {
  external_skill_id: string;
  external_version_id: string;
  name: string;
  [key: string]: unknown;
};
type Descriptor = {
  content_sha256: string;
  skills: Skill[];
  prompt?: string;
  description?: string;
};
const descriptors = ref<Descriptor[]>([]),
  error = ref('');
// Current upstream exposes manifest snapshots, not the descriptor catalog.
onMounted(() => {
  error.value = '';
});
const a = computed(() => props.baseline as Record<string, any>),
  b = computed(() => props.candidate as Record<string, any>);
const da = computed(() =>
  descriptors.value.find((d) => d.content_sha256 === a.value.target.descriptor_sha256),
);
const db = computed(() =>
  descriptors.value.find((d) => d.content_sha256 === b.value.target.descriptor_sha256),
);
const fields = [
  'description',
  'prompt',
  'prompt_sha256',
  'tools',
  'input_schema',
  'output_schema',
  'metadata',
];
const fieldNames: Record<string, string> = {
  description: '职责描述',
  prompt: '提示词',
  prompt_sha256: '提示词 Hash',
  tools: '工具定义',
  input_schema: '输入结构',
  output_schema: '输出结构',
  metadata: '元信息',
};
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
const skills = computed(() =>
  [
    ...new Set(
      [...(da.value?.skills ?? []), ...(db.value?.skills ?? [])].map((s) => s.external_skill_id),
    ),
  ].map((id) => {
    const old = da.value?.skills.find((s) => s.external_skill_id === id),
      next = db.value?.skills.find((s) => s.external_skill_id === id);
    const changed = fields.filter((f) => !same(old?.[f], next?.[f]));
    return {
      id,
      old,
      next,
      changed,
      state: !old
        ? '新增'
        : !next
          ? '移除'
          : old.external_version_id !== next.external_version_id || changed.length
            ? '已变更'
            : '未变更',
    };
  }),
);
const conditions = computed(() =>
  [
    ['评测集内容', a.value.dataset, b.value.dataset],
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
    <h3>Skill 变更</h3>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!da || !db">未取得对应任务的 Skill 定义快照，无法核对变更。</p>
    <template v-else>
      <p v-if="!skills.length">两个快照均未记录 Skill。</p>
      <article v-for="s in skills" :key="s.id" class="mini-card section-gap">
        <b>{{ s.next?.name ?? s.old?.name }} · {{ s.state }}</b>
        <p>
          {{ s.old?.external_version_id ?? '未包含' }} →
          {{ s.next?.external_version_id ?? '未包含' }}
        </p>
        <details v-if="s.changed.length">
          <summary>查看具体修改（{{ s.changed.map((f) => fieldNames[f]).join('、') }}）</summary>
          <div v-for="field in s.changed" :key="field">
            <h4>{{ fieldNames[field] }}</h4>
            <div class="grid two-columns">
              <div>
                <b>基线</b>
                <pre>{{ pretty(s.old?.[field]) ?? '未记录' }}</pre>
              </div>
              <div>
                <b>候选</b>
                <pre>{{ pretty(s.next?.[field]) ?? '未记录' }}</pre>
              </div>
            </div>
          </div>
        </details>
      </article>
      <p class="muted">以上来自任务绑定的定义快照；未记录的源码修改不作推断。</p>
    </template>
    <h3>评测条件</h3>
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
