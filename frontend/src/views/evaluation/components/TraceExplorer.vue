<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { EditorState, StateEffect, StateField } from '@codemirror/state';
import { Decoration, EditorView, type DecorationSet } from '@codemirror/view';
import { basicSetup } from 'codemirror';
import { json } from '@codemirror/lang-json';
import { foldedRanges, unfoldEffect } from '@codemirror/language';
import type { Trace } from '../../../api/evaluations';
import { buildTracePresentation } from '../utils/trace-presentation';

const props = defineProps<{ trace: Trace }>();
const simulated = computed(() =>
  props.trace.spans.some((span) => span.attributes['platform.simulated'] === true),
);
const presentation = computed(() => buildTracePresentation(props.trace));
const selectedId = ref<string | null>(null);
const editorContainer = ref<HTMLDivElement>();
const graphContainer = ref<HTMLDivElement>();
let editor: EditorView | undefined;

const rowHeight = 88;
const indent = 18;
const graphWidth = computed(() =>
  Math.max(360, ...presentation.value.nodes.map((node) => node.depth * indent + 360)),
);
const selectedNode = computed(() =>
  presentation.value.nodes.find((node) => node.id === selectedId.value),
);
const connections = computed(() =>
  presentation.value.nodes.flatMap((node, index) => {
    if (node.parentIndex === null) return [];
    const parent = presentation.value.nodes[node.parentIndex];
    if (!parent) return [];
    const x = parent.depth * indent + 12;
    const y = node.parentIndex * rowHeight + rowHeight / 2;
    return [
      {
        id: node.id,
        path: `M ${x} ${y} V ${index * rowHeight + rowHeight / 2} H ${node.depth * indent + 12}`,
      },
    ];
  }),
);
const highlight = StateEffect.define<{ from: number; to: number }>();
const highlightedSpan = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    if (transaction.docChanged) value = Decoration.none;
    for (const effect of transaction.effects) {
      if (effect.is(highlight))
        value = Decoration.set([
          Decoration.mark({ class: 'trace-json-highlight' }).range(
            effect.value.from,
            effect.value.to,
          ),
        ]);
    }
    return value;
  },
  provide: (field) => EditorView.decorations.from(field),
});

function createEditorState() {
  return EditorState.create({
    doc: presentation.value.json,
    extensions: [
      basicSetup,
      json(),
      EditorState.readOnly.of(true),
      EditorView.editable.of(false),
      EditorView.lineWrapping,
      highlightedSpan,
      EditorView.contentAttributes.of({
        'aria-label': '完整 Trace JSON',
        'aria-readonly': 'true',
        tabindex: '0',
      }),
      EditorView.theme({
        '&': { height: '100%', fontSize: '13px' },
        '.cm-scroller': { overflow: 'auto' },
        '.cm-gutters': { backgroundColor: '#f7f9f8', color: '#64766e' },
        '.trace-json-highlight': { backgroundColor: '#fff0b3' },
        '&.cm-focused': { outline: '2px solid #00a88b', outlineOffset: '-2px' },
      }),
    ],
  });
}

function selectNode(id: string) {
  const range = presentation.value.spanRanges.get(id);
  if (!editor || !range) return;
  selectedId.value = id;
  const effects: StateEffect<unknown>[] = [];
  // Unfold both ancestors and nested ranges so the complete object is visible.
  foldedRanges(editor.state).between(0, editor.state.doc.length, (from, to) => {
    if (from < range.to && to > range.from) effects.push(unfoldEffect.of({ from, to }));
  });
  effects.push(
    highlight.of(range),
    EditorView.scrollIntoView(range.from, { y: 'start', yMargin: 24 }),
  );
  editor.dispatch({ selection: { anchor: range.from }, effects });
}

function durationLabel(duration: number | null) {
  if (duration === null) return '未记录耗时';
  return duration < 1000 ? `${duration.toFixed(1)} ms` : `${(duration / 1000).toFixed(2)} s`;
}
function statusLabel(status: string) {
  return status === 'ok' ? '成功' : status === 'error' ? '错误' : '未设置状态';
}
onMounted(() => {
  editor = new EditorView({ parent: editorContainer.value, state: createEditorState() });
});
watch(
  () => props.trace,
  () => {
    selectedId.value = null;
    editor?.setState(createEditorState());
    if (editor) editor.scrollDOM.scrollTop = 0;
    graphContainer.value?.scrollTo({ top: 0, left: 0 });
  },
  { deep: true },
);
onBeforeUnmount(() => {
  editor?.destroy();
  editor = undefined;
});
</script>

<template>
  <section class="trace-explorer" aria-label="执行轨迹追踪">
    <header class="explorer-heading">
      <h2>执行轨迹追踪<span v-if="simulated"> · 模拟轨迹</span></h2>
      <span>{{ presentation.nodes.length }} 个环节</span>
    </header>
    <div class="explorer-panes">
      <section class="trace-pane" aria-label="轨迹追踪图">
        <header class="pane-heading">
          <h3>轨迹追踪图</h3>
          <span>点击环节定位 JSON</span>
        </header>
        <div ref="graphContainer" class="graph-scroll" tabindex="0" aria-label="轨迹追踪图，可滚动">
          <p v-if="!presentation.nodes.length" class="empty-trace">尚未记录执行环节</p>
          <div v-else class="trace-graph" :style="{ minWidth: `${graphWidth}px` }">
            <svg
              class="trace-connections"
              width="100%"
              :height="presentation.nodes.length * rowHeight"
              aria-hidden="true"
            >
              <path v-for="edge in connections" :key="edge.id" :d="edge.path" />
            </svg>
            <ol class="trace-nodes">
              <li
                v-for="node in presentation.nodes"
                :key="node.id"
                :style="{ height: `${rowHeight}px` }"
              >
                <span
                  class="node-dot"
                  :class="node.status"
                  :style="{ left: `${node.depth * indent + 8}px` }"
                  aria-hidden="true"
                />
                <button
                  class="trace-node"
                  :class="{ selected: selectedId === node.id }"
                  :style="{ marginLeft: `${node.depth * indent + 24}px` }"
                  :aria-pressed="selectedId === node.id"
                  :aria-label="`${node.name}，${node.operationType}，${statusLabel(node.status)}，${durationLabel(node.durationMs)}`"
                  @click="selectNode(node.id)"
                >
                  <span class="node-label">
                    <strong :title="node.name">{{ node.name }}</strong>
                    <span class="node-meta"
                      ><span>{{ node.operationType }}</span
                      ><span :class="['node-status', node.status]">{{
                        statusLabel(node.status)
                      }}</span></span
                    >
                    <small v-if="node.orphan">未找到父环节</small>
                  </span>
                  <span class="node-timing">
                    <span>{{ durationLabel(node.durationMs) }}</span>
                    <span
                      v-if="node.offsetPercent !== null && node.durationPercent !== null"
                      class="time-track"
                      aria-hidden="true"
                    >
                      <span
                        :class="['time-bar', node.status]"
                        :style="{
                          left: `${node.offsetPercent}%`,
                          width: `${node.durationPercent}%`,
                        }"
                      />
                    </span>
                  </span>
                </button>
              </li>
            </ol>
          </div>
        </div>
      </section>
      <section class="trace-pane json-pane" aria-label="完整 Trace JSON 面板">
        <header class="pane-heading">
          <h3>完整 Trace JSON</h3>
          <span role="status">{{
            selectedNode ? `已定位：${selectedNode.name}` : '只读 · 支持搜索和折叠'
          }}</span>
        </header>
        <div ref="editorContainer" class="trace-editor" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.trace-explorer {
  margin-top: 20px;
  min-width: 0;
  border: 1px solid #dfe8e5;
  border-radius: 14px;
  background: #fff;
  overflow: hidden;
}
.explorer-heading,
.pane-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #e8edea;
}
.explorer-heading h2 {
  margin: 0;
  font-size: 18px;
}
.explorer-heading > span,
.pane-heading > span {
  color: #60746a;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.explorer-panes {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
}
.trace-pane {
  min-width: 0;
}
.json-pane {
  border-left: 1px solid #e8edea;
}
.pane-heading {
  min-height: 56px;
  box-sizing: border-box;
  padding: 12px 16px;
}
.pane-heading h3 {
  margin: 0;
  font-size: 14px;
  flex-shrink: 0;
}
.graph-scroll,
.trace-editor {
  height: 65vh;
  min-height: 360px;
}
.graph-scroll {
  overflow: auto;
}
.trace-graph {
  position: relative;
}
.trace-connections {
  position: absolute;
  inset: 0;
  pointer-events: none;
  fill: none;
  stroke: #9caea5;
  stroke-width: 1.5;
}
.trace-nodes {
  position: relative;
  padding: 0;
  margin: 0;
  list-style: none;
}
.trace-nodes li {
  position: relative;
  display: flex;
  align-items: center;
  padding-right: 10px;
  box-sizing: border-box;
}
.node-dot {
  position: absolute;
  top: 40px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7a8c83;
}
.node-dot.ok,
.time-bar.ok {
  background: #008670;
}
.node-dot.error,
.time-bar.error {
  background: #c23f3f;
}
.trace-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 1;
  min-width: 0;
  height: 76px;
  padding: 10px;
  border: 1px solid #e1e9e5;
  border-radius: 8px;
  background: white;
  text-align: left;
  color: #253d31;
  cursor: pointer;
}
.trace-node:hover {
  background: #f5faf7;
}
.trace-node.selected {
  background: #e8f7f0;
  border-color: #008670;
}
.trace-node:focus-visible,
.graph-scroll:focus-visible {
  outline: 2px solid #008670;
  outline-offset: -2px;
}
.node-label {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 4px;
}
.node-label strong {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: #60746a;
}
.node-label small {
  color: #8c5b16;
  font-size: 11px;
}
.node-status.ok {
  color: #00715e;
}
.node-status.error {
  color: #b02e2e;
}
.node-timing {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 110px;
  flex-shrink: 0;
  font-size: 12px;
  text-align: right;
  color: #60746a;
}
.time-track {
  position: relative;
  display: block;
  height: 6px;
  background: #edf1ef;
  overflow: hidden;
  border-radius: 3px;
}
.time-bar {
  position: absolute;
  top: 0;
  height: 100%;
  min-width: 2px;
  background: #7a8c83;
}
.empty-trace {
  padding: 20px;
  color: #60746a;
}
@media (max-width: 760px) {
  .explorer-panes {
    grid-template-columns: minmax(0, 1fr);
  }
  .json-pane {
    border-left: 0;
    border-top: 1px solid #e8edea;
  }
  .graph-scroll {
    height: 40vh;
    min-height: 240px;
  }
}
</style>
