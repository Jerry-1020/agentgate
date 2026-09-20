<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue';
import { request } from '../../../api/evaluations';
const props = defineProps<{ version: string }>();
type Node = {
  id: string;
  kind: string;
  label: string;
  external_id: string;
  version: string | null;
};
type Graph = {
  root_node_id: string;
  nodes: Node[];
  edges: { source_id: string; target_id: string; relation: string }[];
};
const expanded = ref(false),
  data = ref<Graph | null>(null),
  error = ref(''),
  loading = ref(false);
let ticket = 0;
const root = computed(() => data.value?.nodes.find((n) => n.id === data.value?.root_node_id));
const skills = computed(
  () =>
    data.value?.nodes.filter(
      (n) =>
        n.kind === 'skill' &&
        data.value?.edges.some(
          (e) =>
            e.source_id === root.value?.id &&
            e.target_id === n.id &&
            e.relation === 'includes_skill',
        ),
    ) ?? [],
);
async function load() {
  const current = ++ticket;
  data.value = null;
  error.value = '';
  if (!expanded.value || !props.version) return;
  loading.value = true;
  try {
    const result = await request<Graph>(
      '/targets/agentgate-demo/agent/loan-agent/versions/' +
        encodeURIComponent(props.version) +
        '/lineage',
    );
    if (current === ticket) data.value = result;
  } catch (e) {
    if (current === ticket) error.value = String(e);
  } finally {
    if (current === ticket) loading.value = false;
  }
}
watch([expanded, () => props.version], load);
onUnmounted(() => ticket++);
</script>
<template>
  <details class="field full" @toggle="expanded = ($event.target as HTMLDetailsElement).open">
    <summary>查看所选智能体的 Skill 与提示词</summary>
    <p v-if="loading">正在加载 Agent 图谱…</p>
    <p v-if="error" role="alert">{{ error }} <button class="link" @click="load">重试</button></p>
    <div v-if="root" class="agent-graph" aria-label="Agent 与 Skill 关联图">
      <div class="node">
        <b>{{ root.label }}</b
        ><small>Agent · {{ root.version }}</small>
      </div>
      <div v-if="skills.length" class="connector">↓ 包含 Skill</div>
      <div class="skills">
        <div v-for="skill in skills" :key="skill.id" class="node">
          <b>{{ skill.label }}</b
          ><small>{{ skill.external_id }} · {{ skill.version ?? '版本未提供' }}</small>
        </div>
      </div>
      <p v-if="!skills.length">暂无可查询的 Skill 关系数据。</p>
    </div>
    <small>此图展示后端记录的包含关系，不表示实际执行顺序。当前接口未返回提示词正文。</small>
  </details>
</template>
<style scoped>
.agent-graph {
  padding: 24px;
  background: #f5faf9;
  margin: 16px 0;
  text-align: center;
}
.node {
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid #a7d8cd;
  border-radius: 8px;
  background: white;
  overflow-wrap: anywhere;
  max-width: 100%;
}
.connector {
  padding: 14px;
  color: #00856f;
}
.skills {
  display: flex;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}
small {
  color: #64748b;
}
</style>
