import { test, expect } from '@playwright/test';
import {
  annotatedCase,
  matchesAnnotationTarget,
  toolCalls,
  scoresComplete,
  type RawCase,
} from '../src/views/evaluation/utils/annotation-feedback';
import type { Trace } from '../src/api/client';
import type { AnnotationTask, AnnotationTarget } from '../src/stores/modules/review';

const source: RawCase = {
  id: 'case',
  name: '样本',
  initial_state: {},
  category: 'positive',
  difficulty: 'easy',
  tags: [],
  notes: '',
  turns: [
    {
      id: 't1',
      input: { txt: '问题' },
      notes: '原始备注',
      expectations: [
        {
          id: 'state',
          kind: 'state',
          name: null,
          path: 'ok',
          condition: { kind: 'equals', expected: true },
        },
        {
          id: 'old-output',
          kind: 'output',
          name: null,
          path: 'output',
          condition: { kind: 'equals', expected: '旧答案' },
        },
      ],
    },
  ],
};
const trace: Trace = {
  trace_id: 'trace',
  case_id: 'case',
  final_state: {},
  final_output: { output: 'actual' },
  turn_outcomes: { t1: { input: { txt: '问题' }, output: { output: 'actual' }, state: {} } },
  spans: [
    {
      span_id: 'turn',
      name: 'turn',
      operation_type: 'turn',
      sequence: 0,
      attributes: { 'agentgate.turn.id': 't1' },
    },
    {
      span_id: 'chain',
      parent_span_id: 'turn',
      name: 'chain',
      operation_type: 'chain',
      sequence: 1,
      attributes: {},
    },
    {
      span_id: 'tool',
      parent_span_id: 'chain',
      name: 'credit',
      operation_type: 'tool',
      sequence: 2,
      attributes: { arguments: { id: 1 } },
    },
  ],
};
const makeTask = (): AnnotationTask => ({
  id: 'task',
  name: '模板',
  description: '',
  app: { source_id: 'x', target_type: 'agent', external_target_id: 'a', name: 'a' },
  template: {
    id: 'template',
    name: '模板',
    description: '',
    min: 0,
    max: 5,
    message: [{ key: 'accuracy', text: '准确性' }],
    tools: [{ key: 'correct', text: '正确性' }],
    messageTags: [],
    toolTags: [],
  },
  annotations: {
    'run/case/t1': {
      scores: { accuracy: 5 },
      tags: [],
      note: '人工备注',
      expected: '人工.*答案',
      expectedMode: 'contains',
      expectedPath: 'output',
    },
  },
  toolAnnotations: {
    'run/case/tool': {
      scores: { correct: 0 },
      tags: [],
      note: '需修正',
      expectation: 'required',
      argumentsExpected: '{"id":2}',
      occurrence: 'all',
    },
  },
});

test('tool spans are assigned via ancestor turns; unknown or cyclic ancestry is not guessed', () => {
  expect(toolCalls(trace)[0].turnId).toBe('t1');
  const changed = structuredClone(trace);
  changed.spans[1].parent_span_id = 'chain';
  expect(toolCalls(changed)[0].turnId).toBeNull();
});
test('feedback preserves inputs and unrelated rules, escapes contains and adds explicit tool checks', () => {
  const task = makeTask();
  const result = annotatedCase(source, trace, task, 'run/case');
  expect(result.turns[0].input).toEqual(source.turns[0].input);
  expect(result.turns[0].expectations).toContainEqual(source.turns[0].expectations[0]);
  expect(result.turns[0].expectations.find((e) => e.kind === 'output')).toMatchObject({
    condition: { kind: 'matches_pattern', pattern: '人工\\.\\*答案' },
  });
  expect(result.turns[0].expectations).toContainEqual(
    expect.objectContaining({ kind: 'tool_call', tool: 'credit', mode: 'required' }),
  );
  expect(result.turns[0].expectations).toContainEqual(
    expect.objectContaining({
      kind: 'tool_argument',
      path: 'arguments',
      condition: { kind: 'equals', expected: { id: 2 } },
    }),
  );
  expect(result.turns[0].notes).toContain('人工备注');
  expect(source.turns[0].notes).toBe('原始备注');
  expect(annotatedCase(result, trace, task, 'run/case')).toEqual(result);
});
test('blank human output does not copy observed output or erase original expectations', () => {
  const task = makeTask();
  task.annotations['run/case/t1'].expected = '';
  expect(annotatedCase(source, trace, task, 'run/case').turns[0].expectations).toContainEqual(
    source.turns[0].expectations[1],
  );
});
test('bad regex/JSON and forbidden tool argument contradiction are rejected', () => {
  const task = makeTask();
  const a = task.annotations['run/case/t1'];
  a.expectedMode = 'matches_pattern';
  a.expected = '[';
  expect(() => annotatedCase(source, trace, task, 'run/case')).toThrow('正则');
  a.expectedMode = 'json';
  expect(() => annotatedCase(source, trace, task, 'run/case')).toThrow('JSON');
  a.expected = '{}';
  task.toolAnnotations!['run/case/tool'].expectation = 'forbidden';
  expect(() => annotatedCase(source, trace, task, 'run/case')).toThrow('禁止');
});
test('JSON null is an explicit value and missing annotations cannot be exported', () => {
  const task = makeTask();
  Object.assign(task.annotations['run/case/t1'], {
    expectedMode: 'json',
    expected: 'null',
    expectedPath: '',
  });
  expect(annotatedCase(source, trace, task, 'run/case').turns[0].expectations).toContainEqual(
    expect.objectContaining({
      kind: 'output',
      path: null,
      condition: { kind: 'equals', expected: null },
    }),
  );
  delete task.annotations['run/case/t1'];
  expect(() => annotatedCase(source, trace, task, 'run/case')).toThrow('保存');
});
test('all tool dimensions are required, zero valid and out-of-range invalid', () => {
  expect(scoresComplete({ a: 0, b: 5 }, ['a', 'b'], 0, 5)).toBe(true);
  expect(scoresComplete({ a: 5 }, ['a', 'b'], 0, 5)).toBe(false);
  expect(scoresComplete({ a: 6 }, ['a'], 0, 5)).toBe(false);
});
test('platform matching isolates mode, team, agent, version and branch', () => {
  const target: AnnotationTarget = {
    loginMode: 'external',
    teamId: '',
    agentId: 'a',
    agentName: 'A',
    typeGroup: 'abcclaw',
    branchId: 'main',
    agentVersion: '1',
  };
  const run: any = {
    status: 'completed',
    manifest: {
      target: {
        adapter_type: 'agent_platform_mock',
        ref: { external_target_id: 'a', external_version_id: '1' },
        invocation_config: { team_id: '', branch_id: 'main', type_group: 'abcclaw' },
      },
    },
  };
  expect(matchesAnnotationTarget(run, target)).toBe(true);
  for (const patch of [
    { branchId: 'review' },
    { agentVersion: '2' },
    { teamId: 'other' },
    { loginMode: 'bank' },
    { agentId: 'b' },
  ])
    expect(matchesAnnotationTarget(run, { ...target, ...patch } as AnnotationTarget)).toBe(false);
});

test('explicit parameter paths survive export and unassigned tool scores remain auditable', () => {
  const task = makeTask();
  task.toolAnnotations!['run/case/tool'].argumentsPath = 'application_id';
  expect(annotatedCase(source, trace, task, 'run/case').turns[0].expectations).toContainEqual(
    expect.objectContaining({ kind: 'tool_argument', path: 'application_id' }),
  );
  const orphan = structuredClone(trace);
  orphan.spans[2].parent_span_id = 'missing';
  expect(() => annotatedCase(source, orphan, task, 'run/case')).toThrow('轮次关联');
  Object.assign(task.toolAnnotations!['run/case/tool'], {
    expectation: 'none',
    argumentsExpected: '',
  });
  const exported = annotatedCase(source, orphan, task, 'run/case');
  expect(exported.notes).toContain('需修正');
  expect(annotatedCase(exported, orphan, task, 'run/case')).toEqual(exported);
});

test('conflicting expectations for repeated same-name tool calls are rejected', () => {
  const task = makeTask();
  const repeated = structuredClone(trace);
  repeated.spans.push({ ...repeated.spans[2], span_id: 'tool2', sequence: 3 });
  task.toolAnnotations!['run/case/tool2'] = {
    ...task.toolAnnotations!['run/case/tool'],
    argumentsExpected: '{"id":3}',
  };
  expect(() => annotatedCase(source, repeated, task, 'run/case')).toThrow('冲突');
});

test('template library and scores are restored from the same persisted snapshot', async () => {
  const { createPinia } = await import('pinia');
  const { useReviewStore } = await import('../src/stores/modules/review');
  const entries = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const storage = {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => {
      entries.set(key, value);
    },
  };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
  try {
    const first = useReviewStore(createPinia());
    const task = makeTask();
    task.template.v2 = {
      dataset: { enabled: true, criteria: [{ key: 'quality', text: '质量' }], tags: ['合格'] },
      evaluator: { enabled: false, criteria: [], tags: [] },
      agent: { enabled: true, criteria: [{ key: 'accuracy', text: '准确性' }], tags: [] },
    };
    task.v2Annotations = {
      'run/case/t1': {
        dataset: {
          scores: { quality: 100 },
          tags: ['合格'],
          note: '测评集意见',
          expected: '人工答案',
        },
        agent: { scores: { accuracy: 0 }, tags: [], note: '智能体意见' },
        evaluator: {
          scores: {},
          tags: [],
          note: '',
          evaluators: {
            llm: {
              scores: { quality: 95 },
              tags: ['合格'],
              note: '证据充分',
              optimizedPrompt: '只根据证据评分',
            },
          },
        },
      },
    };
    first.saveAnnotationTask(task);
    first.$dispose();
    const restored = useReviewStore(createPinia());
    expect(restored.annotationTasks[0].template.v2).toEqual(task.template.v2);
    expect(restored.annotationTasks[0].v2Annotations).toEqual(task.v2Annotations);
    expect(restored.annotationTemplates.find((t) => t.id === 'template')?.v2).toEqual(
      task.template.v2,
    );
    expect(restored.annotationTemplates.find((t) => t.id === 'template')?.tools).toEqual([
      { key: 'correct', text: '正确性' },
    ]);
    expect(restored.annotationTasks[0].toolAnnotations!['run/case/tool'].scores.correct).toBe(0);
    storage.setItem = () => {
      throw Error('quota');
    };
    const changed = makeTask();
    changed.name = 'unsaved';
    expect(() => restored.saveAnnotationTask(changed)).toThrow('未保存');
    expect(restored.annotationTasks[0].name).toBe('模板');
    restored.$dispose();
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});

test('hot update adds the save action to an already-open store and keeps existing annotations', async () => {
  const { createPinia, defineStore, acceptHMRUpdate } = await import('pinia');
  const { ref } = await import('vue');
  const { useReviewStore } = await import('../src/stores/modules/review');
  const entries = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => entries.set(key, value),
    },
  });
  try {
    const instance = createPinia();
    const useOldReview = defineStore('review', () => ({ annotationTasks: ref([makeTask()]) }));
    const old = useOldReview(instance);
    expect('saveAnnotationTask' in old).toBe(false);
    const hot = {
      data: {},
      invalidate: () => {
        throw Error('unexpected full reload');
      },
    };
    acceptHMRUpdate(useOldReview, hot as any)({ useReviewStore });
    const current = useReviewStore(instance);
    expect(current.annotationTasks[0].annotations).toEqual(makeTask().annotations);
    const next = makeTask();
    next.id = 'new-task';
    next.template.id = 'new-template';
    current.saveAnnotationTask(next);
    expect(current.annotationTasks.map((t) => t.id)).toEqual(['new-task', 'task']);
    expect(current.annotationTemplates.some((t) => t.id === 'new-template')).toBe(true);
    expect([...entries.values()][0]).toContain('new-task');
    current.$dispose();
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});


test('local annotation association matches historical identity and never crosses login modes', () => {
  for (const [sourceId, adapterType, agentId] of [
    ['local-bank-runtime', 'local_bank', 'loan-cloudshrimp'],
    ['agentgate-demo', 'demo_loan', 'loan-agent'],
  ] as const) {
    const target: AnnotationTarget = { loginMode: 'external', teamId: '', agentId, agentName: 'Loan',
      agentVersion: 'v1', branchId: null, typeGroup: 'abcclaw', localExecution: { sourceId, adapterType } };
    const run: any = { status: 'completed', manifest: { target: { adapter_type: adapterType,
      ref: { source_id: sourceId, external_target_id: agentId, external_version_id: 'v1' },
      invocation_config: {} } } };
    expect(matchesAnnotationTarget(run, target)).toBe(true);
    for (const patch of [{ loginMode: 'bank' as const }, { agentId: 'agent-claw' }, { agentVersion: 'v2' },
      { localExecution: { sourceId: 'other', adapterType } }, { localExecution: undefined }])
      expect(matchesAnnotationTarget(run, { ...target, ...patch })).toBe(false);
    run.status = 'failed';
    expect(matchesAnnotationTarget(run, target)).toBe(false);
  }
});
