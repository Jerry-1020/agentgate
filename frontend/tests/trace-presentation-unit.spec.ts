import assert from 'node:assert/strict';
import { test } from '@playwright/test';
import type { Trace } from '../src/api/evaluations';
import { buildTracePresentation as build } from '../src/views/evaluation/utils/trace-presentation';
type Span = Trace['spans'][number] & { parent_span_id: string | null };
const span = (
  id: string,
  parent: string | null = null,
  sequence = 0,
  extra: Record<string, unknown> = {},
): Span => ({
  span_id: id,
  parent_span_id: parent,
  name: id,
  operation_type: 'tool',
  sequence,
  attributes: {},
  ...extra,
});
const trace = (spans: Span[]): Trace => ({
  trace_id: 'test',
  case_id: 'case',
  spans,
  turn_outcomes: {},
  final_output: {},
  final_state: {},
});
function verify(source: Trace, result: ReturnType<typeof build>) {
  assert.deepEqual(JSON.parse(result.json), source);
  assert.equal(result.json, JSON.stringify(source, null, 2));
  assert.equal(result.nodes.length, source.spans.length);
  assert.equal(new Set(result.nodes.map((n) => n.id)).size, source.spans.length);
  result.nodes.forEach((n, i) => {
    if (n.parentIndex !== null) {
      assert.ok(n.parentIndex < i);
      assert.equal(n.depth, result.nodes[n.parentIndex].depth + 1);
    } else assert.equal(n.depth, 0);
  });
  source.spans.forEach((s) => {
    const r = result.spanRanges.get(s.span_id);
    assert.ok(r);
    assert.deepEqual(JSON.parse(result.json.slice(r.from, r.to)), s);
  });
}
test('父子顺序、多根、原始 spans 不重排', () => {
  const input = trace([
    span('child', 'parent', 0),
    span('parent', null, 9),
    span('sibling', 'parent', 3),
    span('other', null, 2),
  ]);
  const result = build(input);
  verify(input, result);
  assert.deepEqual(
    result.nodes.map((n) => n.id),
    ['other', 'parent', 'child', 'sibling'],
  );
  assert.deepEqual(
    result.nodes.map((n) => n.parentIndex),
    [null, null, 1, 1],
  );
});
test('缺失父节点、自环和多节点循环', () => {
  const input = trace([
    span('orphan', 'missing'),
    span('self', 'self'),
    span('a', 'b'),
    span('b', 'c'),
    span('c', 'a'),
    span('leaf', 'a'),
  ]);
  const result = build(input);
  verify(input, result);
  assert.equal(result.nodes.find((n) => n.id === 'orphan').orphan, true);
  assert.equal(result.nodes.find((n) => n.id === 'self').orphan, false);
  assert.equal(result.nodes.filter((n) => n.parentIndex === null).length, 3);
});
test('同级同 sequence 保留原顺序', () => {
  const input = trace([span('p', null, 8), span('b', 'p', 1), span('a', 'p', 1)]);
  const result = build(input);
  verify(input, result);
  assert.deepEqual(
    result.nodes.map((n) => n.id),
    ['p', 'b', 'a'],
  );
});
test('定位忽略嵌套同名字段、转义、换行及 Unicode', () => {
  const input = {
    prefix: { spans: [{ span_id: 'b' }] },
    ...trace([
      span('a', null, 1, {
        attributes: { span_id: 'b', spans: [{ span_id: 'a' }], text: '中文😀\n"span_id":"b"\\' },
      }),
      span('b', null, 0),
    ]),
    unknown_field: { preserved: true },
  };
  verify(input, build(input));
});
test('时间归一化和错误状态', () => {
  const input = trace([
    span('p', null, 0, {
      started_at: '2026-09-29T00:00:00Z',
      ended_at: '2026-09-29T00:00:10Z',
      status: 'ok',
    }),
    span('c', 'p', 1, {
      started_at: '2026-09-29T00:00:02Z',
      ended_at: '2026-09-29T00:00:05Z',
      status: 'error',
    }),
  ]);
  const result = build(input);
  verify(input, result);
  assert.deepEqual(
    result.nodes.map((n) => [n.durationMs, n.offsetPercent, n.durationPercent, n.status]),
    [
      [10000, 0, 100, 'ok'],
      [3000, 20, 30, 'error'],
    ],
  );
});
test('缺失、非法及倒置时间不伪造耗时', () => {
  const input = trace([
    span('none'),
    span('missing', null, 1, { started_at: '2026-09-29T00:00:00Z' }),
    span('bad', null, 2, { started_at: 'bad', ended_at: 'bad' }),
    span('reverse', null, 3, {
      started_at: '2026-09-29T00:00:03Z',
      ended_at: '2026-09-29T00:00:02Z',
    }),
  ]);
  const result = build(input);
  verify(input, result);
  for (const n of result.nodes) {
    assert.equal(n.durationMs, null);
    assert.equal(n.offsetPercent, null);
    assert.equal(n.durationPercent, null);
  }
});
test('零耗时与跨时区', () => {
  const result = build(
    trace([
      span('zero', null, 0, {
        started_at: '2026-09-29T08:00:00+08:00',
        ended_at: '2026-09-29T00:00:00Z',
      }),
    ]),
  );
  assert.deepEqual(
    [result.nodes[0].durationMs, result.nodes[0].offsetPercent, result.nodes[0].durationPercent],
    [0, 0, 0],
  );
});
test('空 Trace 和未知字段保留', () => {
  const input = { ...trace([]), unknown: { text: '保留' } };
  const result = build(input);
  verify(input, result);
  assert.equal(result.spanRanges.size, 0);
});
test('冻结输入不被修改', () => {
  const input = trace([span('b', 'a'), span('a')]);
  function freeze(v: unknown) {
    if (v && typeof v === 'object') {
      Object.values(v).forEach(freeze);
      Object.freeze(v);
    }
  }
  freeze(input);
  const snapshot = JSON.stringify(input);
  verify(input, build(input));
  assert.equal(JSON.stringify(input), snapshot);
});
test('6000 层无递归栈溢出且均可定位', () => {
  const input = trace(
    Array.from({ length: 6000 }, (_, i) => span(String(i), i ? String(i - 1) : null, i)),
  );
  const result = build(input);
  verify(input, result);
  assert.equal(result.nodes.at(-1).depth, 5999);
});
test('混合关系所有节点保留且父节点先于子节点', () => {
  let seed = 17;
  const random = () => {
    seed = (seed * 48271) % 2147483647;
    return seed;
  };
  for (let run = 0; run < 60; run++) {
    const spans = Array.from({ length: 50 }, (_, i) =>
      span(String(i), String(random() % 55), random() % 6),
    );
    const input = trace(spans);
    const result = build(input);
    verify(input, result);
    assert.deepEqual(build(input).nodes, result.nodes);
  }
});
