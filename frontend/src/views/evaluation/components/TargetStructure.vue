<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { request, type TargetDescriptor } from '../../../api/evaluations';
type Node = { id: string; kind: string; label: string; description: string };
type Edge = { source: string; target: string; relation: string };
type Graph = { composition: string; nodes: Node[]; edges: Edge[] };
type Source = {
  repository_url: string;
  branch: string | null;
  commit: string | null;
  commit_url: string | null;
  dirty: boolean | null;
  note: string;
};
const props = defineProps<{
  descriptor?: TargetDescriptor;
  runId?: string;
  hideSource?: boolean;
  trace?: { spans: { attributes: Record<string, unknown> }[] } | null;
}>();
const pinned = ref<TargetDescriptor>(),
  error = ref(''),
  loading = ref(false),
  selected = ref('');
let ticket = 0;
watch(
  () => props.runId,
  async (id) => {
    const current = ++ticket;
    pinned.value = undefined;
    error.value = '';
    loading.value = !!id;
    if (!id) return;
    try {
      const result = await request<TargetDescriptor>(
        '/runs/' + encodeURIComponent(id) + '/target-descriptor',
      );
      if (current === ticket) pinned.value = result;
    } catch {
      if (current === ticket) error.value = '未能读取本次任务的评测对象快照。';
    } finally {
      if (current === ticket) loading.value = false;
    }
  },
  { immediate: true },
);
const target = computed(() => props.descriptor ?? pinned.value);
const source = computed(() => target.value?.metadata.source as Source | undefined);
const graph = computed(() => target.value?.metadata.topology as Graph | undefined);
const kindName: Record<string, string> = {
  agent: '根 Agent',
  subagent: 'Subagent',
  skill: 'Skill',
  workflow: 'Workflow',
  tool: 'Tool',
};
const columns = computed(() =>
  ['agent', 'subagent', 'skill', 'workflow', 'tool'].filter((k) =>
    graph.value?.nodes.some((n) => n.kind === k),
  ),
);
const width = computed(() => Math.max(480, columns.value.length * 240));
const height = computed(() =>
  Math.max(
    170,
    ...columns.value.map(
      (k) => (graph.value?.nodes.filter((n) => n.kind === k).length ?? 0) * 86 + 50,
    ),
  ),
);
const positioned = computed(() =>
  columns.value.flatMap((kind, col) => {
    const rows = graph.value?.nodes.filter((n) => n.kind === kind) ?? [];
    return rows.map((node, row) => ({
      ...node,
      x: col * 240 + 15,
      y: (height.value - rows.length * 86) / 2 + row * 86 + 12,
    }));
  }),
);
const paths = computed(
  () =>
    graph.value?.edges.flatMap((edge) => {
      const a = positioned.value.find((n) => n.id === edge.source),
        b = positioned.value.find((n) => n.id === edge.target);
      if (!a || !b) return [];
      const x = a.x + 205,
        y = a.y + 32;
      return [
        {
          ...edge,
          d: `M ${x} ${y} C ${(x + b.x) / 2} ${y}, ${(x + b.x) / 2} ${b.y + 32}, ${b.x} ${b.y + 32}`,
        },
      ];
    }) ?? [],
);
const active = computed(() => graph.value?.nodes.find((n) => n.id === selected.value));
const executed = computed(
  () =>
    new Set(props.trace?.spans.map((s) => s.attributes['bank.topology_node_id']).filter(Boolean)),
);
const activeEdges = computed(
  () =>
    graph.value?.edges.filter((e) => e.source === selected.value || e.target === selected.value) ??
    [],
);
function safeLink(value?: string | null) {
  try {
    const url = new URL(value ?? '');
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}
watch(
  () => target.value?.content_sha256,
  () => {
    selected.value = '';
  },
);
</script>
<template>
  <section class="target-structure" aria-label="评测对象来源与图谱">
    <p v-if="loading" role="status">正在读取评测对象快照…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="target">
      <div v-if="!hideSource" class="source-grid">
        <div>
          <span>Git 仓库地址</span
          ><a
            v-if="safeLink(source?.repository_url)"
            :href="safeLink(source?.repository_url)"
            target="_blank"
            rel="noopener noreferrer"
            >{{ source?.repository_url }}</a
          ><b v-else>未登记</b>
        </div>
        <div>
          <span>Git 分支</span><b>{{ source?.branch ?? '未记录（或非 Git 安装）' }}</b>
        </div>
        <div>
          <span>提交版本</span
          ><a
            v-if="safeLink(source?.commit_url)"
            :href="safeLink(source?.commit_url)"
            target="_blank"
            rel="noopener noreferrer"
            >{{ source?.commit?.slice(0, 12) }}</a
          ><b v-else>未记录</b><small v-if="source?.dirty" class="dirty">包含本地未提交改动</small>
        </div>
      </div>
      <p v-if="source" class="source-note">
        <template v-if="hideSource"
          >提交 {{ source.commit?.slice(0, 12) ?? '未记录'
          }}<span v-if="source.dirty"> · 包含本地未提交改动</span>。 </template
        >{{ source.note }} 选择已部署分支，不自动拉取或部署代码。
      </p>
      <div class="graph-title">
        <h4>智能体图谱</h4>
        <span>{{ graph?.composition ?? '该历史版本未记录图谱' }}</span>
      </div>
      <template v-if="graph">
        <div class="graph-kinds">
          <span
            v-for="kind in ['agent', 'subagent', 'skill', 'tool']"
            :key="kind"
            :class="{ absent: !graph.nodes.some((n) => n.kind === kind) }"
            >{{ kindName[kind] }}
            <b>{{ graph.nodes.filter((n) => n.kind === kind).length }}</b></span
          >
        </div>
        <p class="source-note">
          {{ runId ? '来自本次任务固定快照' : '来自被测服务声明的执行结构' }}。{{
            trace
              ? '绿色节点表示所选样本 Trace 中实际执行的节点。'
              : '展示全部可用分支，不代表每轮都会执行。'
          }}
          点击节点查看职责与依赖。
        </p>
        <div class="graph-scroll">
          <svg
            :viewBox="`0 0 ${width} ${height}`"
            :style="{ width: width + 'px', minWidth: width + 'px', margin: '0 auto' }"
            role="group"
            aria-label="智能体结构图"
          >
            <path
              v-for="(p, i) in paths"
              :key="i"
              :d="p.d"
              fill="none"
              :class="['edge', { focused: p.source === selected || p.target === selected }]"
            />
            <g
              v-for="n in positioned"
              :key="n.id"
              :transform="`translate(${n.x},${n.y})`"
              :class="['graph-node', { chosen: selected === n.id, executed: executed.has(n.id) }]"
              role="button"
              tabindex="0"
              :aria-label="kindName[n.kind] + ' ' + n.label"
              :aria-pressed="selected === n.id"
              @click="selected = n.id"
              @keydown.enter="selected = n.id"
              @keydown.space.prevent="selected = n.id"
            >
              <title>{{ n.description }}</title>
              <rect width="205" height="64" rx="10" />
              <text x="12" y="22" class="node-kind">{{ kindName[n.kind] }}</text>
              <text x="12" y="46">{{ n.label }}</text>
            </g>
          </svg>
        </div>
        <div v-if="active" class="node-detail" aria-live="polite">
          <b>{{ active.label }}</b>
          <p>{{ active.description }}</p>
          <ul>
            <li v-for="(e, i) in activeEdges" :key="i">
              {{ graph.nodes.find((n) => n.id === e.source)?.label }} → {{ e.relation }} →
              {{ graph.nodes.find((n) => n.id === e.target)?.label }}
            </li>
          </ul>
          <p v-if="trace">
            所选样本：{{ executed.has(active.id) ? '已执行' : '未执行或旧 Trace 未记录节点关联' }}
          </p>
        </div>
      </template>
      <p class="source-note fingerprint">
        对象摘要：{{ target.content_sha256 }}<br />实现摘要：{{
          target.metadata.implementation_sha256 ?? '未记录'
        }}
      </p>
    </template>
  </section>
</template>
<style scoped>
.graph-kinds {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.graph-kinds span {
  padding: 5px 10px;
  border-radius: 6px;
  background: #e8f4ef;
  color: #27705b;
  font-size: 12px;
}
.graph-kinds .absent {
  background: #f0f2f1;
  color: #7c8681;
}
.graph-kinds b {
  margin-left: 6px;
}
.target-structure {
  border: 1px solid #dce7e3;
  border-radius: 12px;
  background: #fbfdfc;
  padding: 18px;
  min-width: 0;
}
.source-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.source-grid > div {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-wrap: anywhere;
}
.source-grid span,
.source-note {
  color: #6b7d78;
  font-size: 12px;
}
.source-grid b,
.source-grid a {
  font-size: 13px;
}
.source-grid a {
  color: #008974;
}
.dirty {
  color: #a05c13;
}
.source-note {
  line-height: 1.6;
  margin: 12px 0;
}
.graph-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.graph-title h4 {
  margin: 12px 0;
}
.graph-title span {
  font-size: 12px;
  color: #008974;
}
.graph-scroll {
  overflow: auto;
  background: #f5f9f7;
  border: 1px solid #e0e9e5;
  border-radius: 10px;
}
svg {
  width: 100%;
  display: block;
}
.edge {
  stroke: #c4d7cf;
  stroke-width: 1.5;
}
.edge.focused {
  stroke: #008974;
  stroke-width: 2;
}
.graph-node {
  cursor: pointer;
  outline: none;
}
.graph-node rect {
  fill: white;
  stroke: #d3dfda;
  stroke-width: 1.5;
}
.graph-node.chosen rect,
.graph-node:focus rect {
  stroke: #008974;
  stroke-width: 2;
}
.graph-node.executed rect {
  fill: #e1f5ed;
  stroke: #43ae8f;
}
.graph-node text {
  font-size: 12px;
  fill: #283e36;
  font-weight: 600;
}
.graph-node .node-kind {
  font-size: 10px;
  fill: #71867d;
  font-weight: 400;
}
.node-detail {
  margin-top: 12px;
  padding: 14px;
  background: white;
  border: 1px solid #dce7e3;
  border-radius: 8px;
  font-size: 13px;
}
.node-detail p {
  margin: 8px 0;
}
.node-detail ul {
  padding-left: 18px;
  line-height: 1.8;
}
.fingerprint {
  overflow-wrap: anywhere;
  font-family: monospace;
  margin-bottom: 0;
}
@media (max-width: 700px) {
  .source-grid {
    grid-template-columns: 1fr;
  }
  .target-structure {
    padding: 12px;
  }
}
</style>
