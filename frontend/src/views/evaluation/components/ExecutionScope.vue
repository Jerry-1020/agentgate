<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ baseline: Record<string, any>; candidate: Record<string, any> }>();
type Scope = { label: string; names: string[]; ids: string[] | null; error: string };
const scopes = computed<Scope[]>(() =>
  [props.baseline, props.candidate].map((m) => {
    const selected: string[] | null = m.selected_case_ids ?? null;
    try {
      const version = m.dataset as { cases: { id: string; name: string }[] };
      if (!Array.isArray(version?.cases)) throw Error('任务快照缺少样本');
      const ids = selected ?? version.cases.map((c) => c.id);
      return {
        label: `${selected === null ? '全部用例' : '指定用例'} · ${ids.length} 条`,
        ids,
        names: ids.map(
          (id) => version.cases.find((c) => c.id === id)?.name ?? `未找到名称（${id}）`,
        ),
        error: '',
      };
    } catch {
      return {
        label: selected === null ? '全部用例 · 数量未能读取' : `指定用例 · ${selected.length} 条`,
        ids: selected,
        names: selected?.map((id) => `用例 ID：${id}`) ?? [],
        error: '任务快照中未记录完整用例信息。',
      };
    }
  }),
);
const comparison = computed(() => {
  if (scopes.value.length !== 2) return '读取中';
  if (scopes.value.some((s) => s.error)) return '待核对';
  if (
    JSON.stringify([...scopes.value[0].ids!].sort()) !==
    JSON.stringify([...scopes.value[1].ids!].sort())
  )
    return '不同';
  return '一致';
});
</script>
<template>
  <details open data-testid="execution-scope">
    <summary>执行用例 · {{ comparison }}</summary>
    <div class="grid two-columns">
      <div v-for="(scope, index) in scopes" :key="index" class="mini-card">
        <b>{{ index === 0 ? 'A任务' : 'B任务' }}：{{ scope.label }}</b>
        <ul>
          <li v-for="(name, i) in scope.names" :key="i">{{ name }}</li>
        </ul>
        <small v-if="scope.error">{{ scope.error }}</small>
      </div>
    </div>
    <p v-if="comparison === '不同'" class="muted">
      两侧执行用例不同，不能直接将结果差异归因于方案修改。
    </p>
    <small v-else-if="comparison === '一致'"
      >仅表示用例 ID 集合一致，测评集版本和内容是否一致仍需核对。</small
    >
  </details>
</template>
