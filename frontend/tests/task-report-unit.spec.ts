import { test, expect } from '@playwright/test';
import {
  scoreColumns,
  columnScore,
  sampleSummary,
  csvCell,
  traceSeconds,
  groupEvaluatorResults,
  type EvaluatorSnapshot,
} from '../src/views/evaluation/utils/task-report';
import { selectableEvaluator } from '../src/views/evaluation/utils/evaluator-display';
import type { EvaluatorSummary } from '../src/api/evaluations';
import type { EvaluationResult } from '../src/api/client';
const result = (id: string, score: number | null, outcome = 'pass') =>
  ({ evaluator_id: id, score, outcome }) as EvaluationResult;
test('columns follow pinned evaluators, not a hardcoded set', () => {
  const columns = scoreColumns({
    primary_evaluator_ids: ['a', 'b'],
    evaluator_specs: [
      { id: 'a', name: '自定义规则', kind: 'rule' },
      {
        id: 'b',
        name: '贷款回答可信度',
        kind: 'llm_judge',
        config: { rubric: { safety: '安全', correctness: '正确' } },
      },
      { id: 'dependency', name: '依赖', kind: 'rule' },
    ],
  });
  expect(columns.map((c) => c.name)).toEqual(['自定义规则', '贷款回答可信度']);
  expect(columnScore([result('a', 0)], columns[0])).toBe(0);
  expect(columnScore([result('b', 0.79, 'fail')], columns[1])).toBe(0.79);
});
test('error is not converted to pass when other evaluators return 100', () => {
  expect(sampleSummary([result('a', 1), result('b', null, 'error')], ['a', 'b'])).toEqual({
    outcome: 'error',
    score: 1,
  });
});
test('absent, skipped, failed and pending results keep distinct states', () => {
  expect(sampleSummary([], ['a']).outcome).toBe('pending');
  expect(sampleSummary([result('a', null, 'not_applicable')], ['a'])).toEqual({
    outcome: 'not_applicable',
    score: null,
  });
  expect(sampleSummary([result('a', 0, 'fail')], ['a']).outcome).toBe('fail');
  expect(sampleSummary([result('a', 1)], ['a', 'b']).outcome).toBe('pending');
});
test('dependent evaluator scores never contribute to primary average', () => {
  expect(
    sampleSummary([result('a', 0.8), result('b', 0.6), result('child', 0)], ['a', 'b']).score,
  ).toBe(0.7);
});
test('CSV quotes newlines and prevents spreadsheet formula interpretation', () => {
  expect(csvCell('=1+2')).toBe('"\'=1+2"');
  expect(csvCell('a,"b"\nc')).toBe('"a,""b""\nc"');
  expect(csvCell(0)).toBe('"0"');
  expect(csvCell(null)).toBe('""');
});
test('duration requires actual case span timestamps', () => {
  expect(traceSeconds(null)).toBeNull();
  expect(
    traceSeconds({
      spans: [
        {
          operation_type: 'case',
          started_at: '2026-09-19T00:00:00Z',
          ended_at: '2026-09-19T00:00:02Z',
        },
      ],
    }),
  ).toBe(2);
  expect(traceSeconds({ spans: [{ operation_type: 'case' }] })).toBeNull();
});

test('each LLM evaluator exposes its actual score without fabricating rubric scores', () => {
  const columns = scoreColumns({
    primary_evaluator_ids: ['judge-a', 'judge-b'],
    evaluator_specs: [
      {
        id: 'judge-a',
        name: '事实评估',
        kind: 'llm_judge',
        config: { rubric: { facts: '事实', reason: '原因' } },
      },
      {
        id: 'judge-b',
        name: '安全评估',
        kind: 'llm_judge',
        config: { rubric: { safety: '安全' } },
      },
    ],
  });
  expect(columns).toHaveLength(2);
  const results = [result('judge-b', 1), result('judge-a', 0, 'fail')];
  expect(columns.map((c) => columnScore(results, c))).toEqual([0, 1]);
  expect(columnScore([], columns[0])).toBeNull();
  expect(columnScore([result('judge-a', null, 'error')], columns[0])).toBeNull();
});

test('LLM group results bind children to the pinned version and preserve independent records', () => {
  const parent = { ...result('group', 0.7), evaluator_version: '2', case_id: 'case' };
  const childA = {
    ...result('child-a', 1),
    evaluator_version: '1',
    case_id: 'case',
    judge_record: { raw_response: 'A' },
  };
  const childB = {
    ...result('child-b', 0.5, 'fail'),
    evaluator_version: '2',
    case_id: 'case',
    judge_record: { raw_response: 'B' },
  };
  const unrelated = { ...result('rule', 1), case_id: 'case' };
  const specs = [
    {
      id: 'group',
      version: '2',
      kind: 'llm_group',
      children: [
        { evaluator_id: 'child-a', evaluator_version: '1', weight: 0.4 },
        { evaluator_id: 'child-b', evaluator_version: '2', weight: 0.6 },
      ],
    },
  ] as EvaluatorSnapshot[];
  const grouped = groupEvaluatorResults([childB, parent, unrelated, childA], specs);
  expect(grouped.map((g) => g.result.evaluator_id)).toEqual(['group', 'rule']);
  expect(
    grouped[0].children.map((c) => [
      c.result.evaluator_id,
      c.weight,
      c.result.judge_record?.raw_response,
    ]),
  ).toEqual([
    ['child-a', 0.4, 'A'],
    ['child-b', 0.6, 'B'],
  ]);
  expect(sampleSummary([parent, childA, childB], ['group']).score).toBe(0.7);
  expect(
    groupEvaluatorResults([{ ...childA, evaluator_version: '3' }, parent], specs),
  ).toHaveLength(2);
  expect(groupEvaluatorResults([childA], specs)[0].result).toBe(childA);
});

test('only published enabled top-level LLM groups are offered to tasks', () => {
  const group = {
    id: 'group',
    enabled: true,
    latest_version: '1',
    kind: 'llm_group',
  } as EvaluatorSummary;
  expect(selectableEvaluator(group)).toBe(true);
  expect(selectableEvaluator({ ...group, enabled: false })).toBe(false);
  expect(selectableEvaluator({ ...group, latest_version: null, has_draft: true })).toBe(false);
  expect(selectableEvaluator({ ...group, kind: 'llm_judge', owner_evaluator_id: 'parent' })).toBe(
    false,
  );
  expect(selectableEvaluator({ ...group, kind: 'hybrid' })).toBe(false);
});
