import { jsonLanguage } from '@codemirror/lang-json';
import type { Trace } from '../../../api/evaluations';

type ObservedSpan = Trace['spans'][number] & {
  parent_span_id?: string | null;
  started_at?: string;
  ended_at?: string;
  status?: string;
};

export interface TraceNode {
  id: string;
  name: string;
  operationType: string;
  status: string;
  durationMs: number | null;
  depth: number;
  parentIndex: number | null;
  orphan: boolean;
  offsetPercent: number | null;
  durationPercent: number | null;
}

export interface TracePresentation {
  nodes: TraceNode[];
  json: string;
  spanRanges: Map<string, { from: number; to: number }>;
}

function spanTiming(span: ObservedSpan): { start: number; end: number } | null {
  if (typeof span.started_at !== 'string' || typeof span.ended_at !== 'string') return null;
  const start = Date.parse(span.started_at);
  const end = Date.parse(span.ended_at);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start ? { start, end } : null;
}

function spanRanges(json: string, spans: readonly ObservedSpan[]): TracePresentation['spanRanges'] {
  const ranges: TracePresentation['spanRanges'] = new Map();
  const root = jsonLanguage.parser.parse(json).topNode.getChild('Object');
  const property = root?.getChildren('Property').find((item) => {
    const key = item.getChild('PropertyName');
    return key && JSON.parse(json.slice(key.from, key.to)) === 'spans';
  });
  // Only direct objects in the top-level spans array identify execution nodes.
  const objects = property?.getChild('Array')?.getChildren('Object') ?? [];
  objects.forEach((object, index) => {
    ranges.set(spans[index].span_id, { from: object.from, to: object.to });
  });
  return ranges;
}

function parentIndices(spans: readonly ObservedSpan[]): (number | null)[] {
  const byId = new Map(spans.map((span, index) => [span.span_id, index]));
  const parents = spans.map((span) => byId.get(span.parent_span_id ?? '') ?? null);
  const visited = new Uint8Array(spans.length);
  for (let start = 0; start < spans.length; start++) {
    if (visited[start]) continue;
    const path: number[] = [];
    let current: number | null = start;
    while (current !== null && visited[current] === 0) {
      visited[current] = 1;
      path.push(current);
      current = parents[current];
    }
    // Cut one edge per cycle without dropping any node or changing the source Trace.
    if (current !== null && visited[current] === 1) parents[current] = null;
    path.forEach((index) => (visited[index] = 2));
  }
  return parents;
}

export function buildTracePresentation(trace: Trace): TracePresentation {
  const json = JSON.stringify(trace, null, 2);
  const spans: readonly ObservedSpan[] = trace.spans;
  const spanIds = new Set(spans.map((span) => span.span_id));
  const parents = parentIndices(spans);
  const ordered = spans
    .map((_, index) => index)
    .sort((a, b) => spans[a].sequence - spans[b].sequence || a - b);
  const children = new Map<number | null, number[]>();
  for (const index of ordered) {
    const siblings = children.get(parents[index]);
    if (siblings) siblings.push(index);
    else children.set(parents[index], [index]);
  }

  const timings = spans.map(spanTiming);
  let first = Infinity;
  let last = -Infinity;
  for (const timing of timings) {
    if (!timing) continue;
    first = Math.min(first, timing.start);
    last = Math.max(last, timing.end);
  }
  const elapsed = last - first;
  const nodes: TraceNode[] = [];
  const pending = [...(children.get(null) ?? [])].reverse().map((index) => ({
    index,
    depth: 0,
    parentIndex: null as number | null,
  }));
  while (pending.length) {
    const { index, depth, parentIndex } = pending.pop()!;
    const span = spans[index];
    const timing = timings[index];
    const offset = timing ? (elapsed > 0 ? ((timing.start - first) / elapsed) * 100 : 0) : null;
    const width = timing ? (elapsed > 0 ? ((timing.end - timing.start) / elapsed) * 100 : 0) : null;
    const displayIndex = nodes.length;
    nodes.push({
      id: span.span_id,
      name: span.name,
      operationType: span.operation_type,
      status: span.status ?? 'unset',
      durationMs: timing ? timing.end - timing.start : null,
      depth,
      parentIndex,
      orphan: !!span.parent_span_id && !spanIds.has(span.parent_span_id),
      offsetPercent: offset,
      durationPercent: width === null ? null : Math.min(width, 100 - (offset ?? 0)),
    });
    const descendants = children.get(index) ?? [];
    for (let i = descendants.length - 1; i >= 0; i--)
      pending.push({ index: descendants[i], depth: depth + 1, parentIndex: displayIndex });
  }
  return { nodes, json, spanRanges: spanRanges(json, spans) };
}
