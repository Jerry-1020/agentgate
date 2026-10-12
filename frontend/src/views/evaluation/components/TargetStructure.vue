<script setup lang="ts">
import { computed, ref, watch, getCurrentInstance } from 'vue';
import { request, type TargetDescriptor } from '../../../api/evaluations';
type Node = {
  id: string;
  kind: string;
  label: string;
  description: string;
  node_type?: string;
  trace_name?: string;
};
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
      if (current === ticket) error.value = '未能读取本次任务的测评对象快照。';
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
  workflow: '流程节点',
  tool: 'Tool',
};
const columns = computed(() =>
  ['agent', 'subagent', 'skill', 'workflow', 'tool'].filter((k) =>
    graph.value?.nodes.some((n) => n.kind === k),
  ),
);
const arrowId = `structure-arrow-${getCurrentInstance()?.uid ?? 0}`;
const nodeTypeName: Record<string, string> = {
  llm: 'LLM',
  rule: '规则',
  tool: '工具',
  terminal: '起止',
};
const workflow = computed(
  () => !!graph.value?.nodes.length && graph.value.nodes.every((n) => n.kind === 'workflow'),
);
// Layer only acyclic execution graphs; other topologies retain their declared kind layout.
const workflowLayers = computed(() => {
  if (!workflow.value || !graph.value) return null;
  const nodes = graph.value.nodes;
  const incoming = new Map(nodes.map((n) => [n.id, 0]));
  const levels = new Map(nodes.map((n) => [n.id, 0]));
  for (const e of graph.value.edges) {
    if (!incoming.has(e.source) || !incoming.has(e.target)) return null;
    incoming.set(e.target, incoming.get(e.target)! + 1);
  }
  const queue = nodes.filter((n) => incoming.get(n.id) === 0).map((n) => n.id);
  let visited = 0;
  while (queue.length) {
    const id = queue.shift()!;
    visited++;
    for (const e of graph.value.edges.filter((e) => e.source === id)) {
      levels.set(e.target, Math.max(levels.get(e.target)!, levels.get(id)! + 1));
      incoming.set(e.target, incoming.get(e.target)! - 1);
      if (incoming.get(e.target) === 0) queue.push(e.target);
    }
  }
  if (visited !== nodes.length) return null;
  return Array.from({ length: Math.max(...levels.values()) + 1 }, (_, level) =>
    nodes.filter((n) => levels.get(n.id) === level),
  );
});
const width = computed(() =>
  workflowLayers.value
    ? Math.max(760, Math.max(...workflowLayers.value.map((row) => row.length)) * 300 + 140)
    : Math.max(480, columns.value.length * 240),
);
const height = computed(() =>
  workflowLayers.value
    ? workflowLayers.value.length * 118 + 30
    : Math.max(
        170,
        ...columns.value.map(
          (k) => (graph.value?.nodes.filter((n) => n.kind === k).length ?? 0) * 86 + 50,
        ),
      ),
);
const positioned = computed(() =>
  workflowLayers.value
    ? workflowLayers.value.flatMap((row, level) =>
        row.map((node, lane) => ({
          ...node,
          x: 140 + lane * 300,
          y: 20 + level * 118,
        })),
      )
    : columns.value.flatMap((kind, col) => {
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
      const a = positioned.value.find((n) => n.id === edge.source);
      const b = positioned.value.find((n) => n.id === edge.target);
      if (!a || !b) return [];
      if (workflowLayers.value) {
        const x = a.x + 102.5,
          y = a.y + 64,
          endX = b.x + 102.5;
        const bypass = b.y - a.y > 119;
        const side = a.x > 140 ? width.value - 35 : 55;
        return [
          {
            ...edge,
            labelX: bypass ? side : endX,
            labelY: y + 24,
            d: bypass
              ? `M ${x} ${y} V ${y + 18} H ${side} V ${b.y - 18} H ${endX} V ${b.y - 4}`
              : `M ${x} ${y} C ${x} ${y + 28}, ${endX} ${b.y - 28}, ${endX} ${b.y - 4}`,
          },
        ];
      }
      const x = a.x + 205,
        y = a.y + 32;
      return [
        {
          ...edge,
          labelX: 0,
          labelY: 0,
          d: `M ${x} ${y} C ${(x + b.x) / 2} ${y}, ${(x + b.x) / 2} ${b.y + 32}, ${b.x - 4} ${b.y + 32}`,
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
  <section class="target-structure" aria-label="测评对象来源与图谱">
    <p v-if="loading" role="status">正在读取测评对象快照…</p>
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
            v-for="kind in columns"
            :key="kind"
            :class="{ absent: !graph.nodes.some((n) => n.kind === kind) }"
            >{{ kindName[kind] }}
            <b>{{ graph.nodes.filter((n) => n.kind === kind).length }}</b></span
          >
        </div>
        <p v-if="workflow" class="workflow-explainer">
          工作流 · 按箭头执行，按条件选择分支。节点标明 LLM、规则或工具；起止节点不执行业务动作。
        </p>
        <p v-if="workflow && !workflowLayers" class="source-note">
          此图含循环或无法分层的连线，按节点关系展示。
        </p>
        <p class="source-note">
          {{ runId ? '来自本次任务固定快照' : '来自被测服务声明的执行结构' }}。{{
            trace
              ? '绿色节点表示所选样本 Trace 中实际执行的节点。'
              : '展示全部可用分支，不代表每轮都会执行。'
          }}
          点击节点查看职责与依赖。
        </p>
        <div class="graph-scroll" :class="{ 'workflow-graph': workflow }">
          <svg
            :viewBox="`0 0 ${width} ${height}`"
            :style="{
              width: workflowLayers ? '100%' : width + 'px',
              minWidth: workflowLayers ? '520px' : width + 'px',
              margin: '0 auto',
            }"
            role="group"
            aria-label="智能体结构图"
          >
            <defs>
              <marker
                :id="arrowId"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#7e9e91" />
              </marker>
            </defs>
            <path
              v-for="(p, i) in paths"
              :key="i"
              :d="p.d"
              :marker-end="`url(#${arrowId})`"
              fill="none"
              :class="['edge', { focused: p.source === selected || p.target === selected }]"
            />
            <template v-if="workflowLayers">
              <text
                v-for="(p, i) in paths.filter((p) => p.relation !== '下一步')"
                :key="'label-' + i"
                :x="p.labelX"
                :y="p.labelY"
                class="edge-label"
                text-anchor="middle"
              >
                {{ p.relation }}
              </text>
            </template>
            <g
              v-for="n in positioned"
              :key="n.id"
              :transform="`translate(${n.x},${n.y})`"
              :class="[
                'graph-node',
                'node-' + (n.node_type ?? n.kind),
                { chosen: selected === n.id, executed: executed.has(n.id) },
              ]"
              role="button"
              tabindex="0"
              :aria-label="kindName[n.kind] + ' ' + n.label"
              :aria-pressed="selected === n.id"
              @click="selected = n.id"
              @keydown.enter="selected = n.id"
              @keydown.space.prevent="selected = n.id"
            >
              <title>{{ n.description }}</title>
              <rect width="205" height="64" :rx="n.node_type === 'terminal' ? 32 : 10" />
              <text x="12" y="22" class="node-kind">
                {{ nodeTypeName[n.node_type ?? ''] ?? kindName[n.kind] }}
              </text>
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
.workflow-explainer {
  color: #436358;
  font-size: 13px;
  line-height: 1.7;
}
.workflow-graph {
  max-height: 690px;
}
.edge-label {
  font-size: 11px;
  fill: #556c62;
  paint-order: stroke;
  stroke: #f5f9f7;
  stroke-width: 5px;
  stroke-linejoin: round;
}
.graph-node.node-llm rect {
  fill: #eff4ff;
  stroke: #9badde;
}
.graph-node.node-rule rect {
  fill: #fff7e8;
  stroke: #d9b977;
}
.graph-node.node-tool rect {
  fill: #edf8f5;
  stroke: #91c6b7;
}
.graph-node.node-terminal rect {
  fill: #e9eeec;
  stroke: #9aaaa2;
}
.graph-node.node-skill rect {
  fill: #f4eeff;
  stroke: #b6a0d3;
}

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
