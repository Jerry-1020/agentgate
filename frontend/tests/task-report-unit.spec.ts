import { test, expect } from '@playwright/test';
import {
  scoreColumns,
  columnScore,
  sampleSummary,
  csvCell,
  traceSeconds,
  groupEvaluatorResults,
  comparisonScoreGroups,
  type EvaluatorSnapshot,
} from '../src/views/evaluation/utils/task-report';
import { selectableEvaluator } from '../src/views/evaluation/utils/evaluator-display';
import type { Comparison, EvaluatorSummary } from '../src/api/evaluations';
import type { EvaluationResult, Report } from '../src/api/client';
import {
  llmCheckDetails,
  llmScoringBasis,
} from '../src/views/evaluation/utils/report-presentation';
import { readFileSync } from 'node:fs';
const result = (id: string, score: number | null, outcome = 'pass') =>
  ({ evaluator_id: id, score, outcome }) as EvaluationResult;

const judgeResult = {
  ...result('judge', 0.2, 'fail'),
  evaluator_version: '1',
  evaluator_kind: 'llm_judge',
} as EvaluationResult;
const judgeSnapshot = {
  id: 'judge',
  name: '回答质量',
  version: '1',
  kind: 'llm_judge',
  content_sha256: 'snapshot',
  implementation_id: 'answer_quality',
  implementation_version: '1',
  config: {
    instruction: '按业务规范评分。',
    pass_threshold: 0.8,
    rubric: {
      correctness: 'The answer is consistent with the supplied inputs and execution evidence.',
    },
  },
} satisfies EvaluatorSnapshot;

test('LLM scoring basis uses the pinned version and translates built-in criteria', () => {
  const basis = llmScoringBasis(judgeResult, [
    {
      ...judgeSnapshot,
      version: '2',
      config: { pass_threshold: 0.9, rubric: { custom: '新标准' } },
    },
    judgeSnapshot,
  ]);
  expect(basis.instruction).toBe('按业务规范评分。');
  expect(basis.passThreshold).toBe(0.8);
  expect(basis.criteria).toEqual([
    {
      name: '正确性',
      description: '回答应与提供的用户输入和执行证据一致，不得与事实矛盾。',
      weight: null,
    },
  ]);
  expect(
    llmScoringBasis({ ...judgeResult, evaluator_version: '3' }, [judgeSnapshot]),
  ).toMatchObject({
    instruction: '',
    criteria: [],
    passThreshold: null,
  });
  expect(
    llmScoringBasis({ ...judgeResult, evaluator_version: undefined }, [judgeSnapshot])
      .passThreshold,
  ).toBeNull();
});

test('LLM threshold distinguishes zero, known defaults and unavailable configuration', () => {
  const basisFor = (config: EvaluatorSnapshot['config'], implementationId = 'answer_quality') =>
    llmScoringBasis(judgeResult, [
      { ...judgeSnapshot, config, implementation_id: implementationId },
    ]);
  expect(basisFor({ pass_threshold: 0 })).toMatchObject({
    passThreshold: 0,
    usesDefaultThreshold: false,
  });
  expect(basisFor({})).toMatchObject({ passThreshold: 0.8, usesDefaultThreshold: true });
  expect(basisFor(undefined).passThreshold).toBeNull();
  expect(basisFor({}, 'custom').passThreshold).toBeNull();
  expect(basisFor({ pass_threshold: '80' }).passThreshold).toBeNull();
});

test('LLM standards preserve custom content, dimension prompts and weights', () => {
  const config = { rubric: { custom: '自定义评分要求', zero: 0, disabled: false } };
  expect(
    llmScoringBasis(judgeResult, [{ ...judgeSnapshot, config }]).criteria.map((c) => c.description),
  ).toEqual(['自定义评分要求', '0', 'false']);
  const dimensions = [
    {
      id: 'custom',
      name: '风险识别',
      description: '识别风险。',
      prompt: '遗漏关键风险扣分。',
      weight: 100,
    },
  ];
  expect(
    llmScoringBasis(judgeResult, [{ ...judgeSnapshot, config: { dimensions } }]).criteria,
  ).toEqual([{ name: '风险识别', description: '识别风险。\n遗漏关键风险扣分。', weight: 100 }]);
});

test('LLM child criteria come from their own snapshots in a recorded group report', () => {
  const llmGroupFixture = JSON.parse(
    readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
  );
  const report = llmGroupFixture.report as unknown as Report;
  const parent = report.results.find((r) => r.evaluator_kind === 'llm_group')!;
  const children = report.results.filter((r) => r.evaluator_kind === 'llm_judge');
  expect(llmScoringBasis(parent, report.run.manifest.evaluator_specs).combination).toContain(
    '按子评估器权重',
  );
  expect(children).toHaveLength(3);
  for (const child of children) {
    const basis = llmScoringBasis(child, report.run.manifest.evaluator_specs);
    const snapshot = report.run.manifest.evaluator_specs!.find((s) => s.id === child.evaluator_id)!;
    expect(basis.instruction).toBe(snapshot.config!.instruction);
    expect(basis.instruction).toContain('<评分标准>');
    expect(basis.passThreshold).toBe(0.8);
  }
});

test('LLM conclusions preserve actual reasons and do not fabricate scores from criteria', () => {
  const check = {
    actual_missing: false,
    expected: { rubric_sha256: 'fingerprint' },
    actual: {
      confidence: 0,
      violations: [{ criterion: 'correctness', detail: '与事实不一致。' }],
      dimensions: [{ id: 'correctness', score: 0, reason: '计算错误。', review: true }],
    },
  } as EvaluationResult['checks'][number];
  expect(llmCheckDetails(check)).toEqual({
    confidence: 0,
    violations: [{ criterion: '正确性', detail: '与事实不一致。' }],
    dimensions: [{ name: '正确性', score: 0, reason: '计算错误。', review: true }],
  });
  expect(llmCheckDetails({ ...check, actual_missing: true })).toEqual({
    confidence: null,
    violations: [],
    dimensions: [],
  });
  expect(llmCheckDetails({ ...check, actual: null })).toEqual({
    confidence: null,
    violations: [],
    dimensions: [],
  });
});

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

const comparisonFixture = {
  metric_deltas: [
    {
      level: 'overall',
      key: 'overall',
      baseline: { score: 0.4 },
      candidate: { score: 0.8 },
      score_delta: 0.4,
    },
    { level: 'kind', key: 'rule', baseline: { score: 0 }, candidate: { score: 1 }, score_delta: 1 },
  ],
} as Comparison;
const scoreResult = (
  id: string,
  kind: string,
  metric: string,
  caseId: string,
  score: number | null,
) => ({
  ...result(id, score),
  evaluator_version: '1',
  evaluator_kind: kind,
  metric,
  case_id: caseId,
});
function comparisonReport(
  specs: { id: string; kind: string }[],
  results: EvaluationResult[],
): Report {
  return {
    run: {
      manifest: {
        primary_evaluator_ids: specs.map((spec) => spec.id),
        evaluator_specs: specs.map((spec) => ({ ...spec, name: '名称 ' + spec.id, version: '1' })),
      },
    },
    results,
    metrics: [],
  } as unknown as Report;
}

test('A/B score groups preserve three summaries and separate evaluators sharing a metric', () => {
  const specs = [
    { id: 'judge-a', kind: 'llm_judge' },
    { id: 'judge-b', kind: 'llm_judge' },
    { id: 'rule', kind: 'rule' },
  ];
  const a = comparisonReport(specs, [
    scoreResult('judge-a', 'llm_judge', 'answer', 'case-1', 0),
    scoreResult('judge-b', 'llm_judge', 'answer', 'case-1', 1),
    scoreResult('rule', 'rule', 'state', 'case-1', 0),
    { ...scoreResult('judge-a', 'llm_judge', 'answer', 'case-1', 1), evaluator_version: '2' },
  ]);
  a.metrics = [{ level: 'kind', key: 'llm_judge', score: 0.5 }] as Report['metrics'];
  const b = comparisonReport(specs, [
    scoreResult('judge-a', 'llm_judge', 'answer', 'case-1', 0.8),
    scoreResult('judge-b', 'llm_judge', 'answer', 'case-1', null),
    scoreResult('rule', 'rule', 'state', 'case-1', 1),
  ]);
  b.metrics = [{ level: 'kind', key: 'llm_judge', score: 0.8 }] as Report['metrics'];
  const groups = comparisonScoreGroups(comparisonFixture, a, b);
  expect(groups.map((group) => group.name)).toEqual(['综合得分', 'LLM评估得分', '规则评估得分']);
  expect(groups[0]).toMatchObject({ baseline: 0.4, candidate: 0.8, delta: 0.4, children: [] });
  expect(
    groups[1].children.map(({ name, baseline, candidate, delta }) => ({
      name,
      baseline,
      candidate,
      delta,
    })),
  ).toEqual([
    { name: '名称 judge-a · v1', baseline: 0, candidate: 0.8, delta: 0.8 },
    { name: '名称 judge-b · v1', baseline: 1, candidate: null, delta: null },
  ]);
  expect(groups[1].baseline).toBe(0.5);
  expect(groups[1].candidate).toBe(0.8);
  expect(groups[2].children.map((child) => child.key)).toEqual(['rule']);
});

test('A/B LLM summary combines group and judge metrics without double-counting dependency scores', () => {
  const report = comparisonReport(
    [
      { id: 'judge-a', kind: 'llm_judge' },
      { id: 'judge-b', kind: 'llm_judge' },
      { id: 'group-a', kind: 'llm_group' },
      { id: 'group-b', kind: 'llm_group' },
    ],
    [
      scoreResult('judge-a', 'llm_judge', 'answer', 'case-1', 0),
      scoreResult('judge-a', 'llm_judge', 'answer', 'case-2', 1),
      scoreResult('judge-b', 'llm_judge', 'answer', 'case-1', 1),
      scoreResult('judge-b', 'llm_judge', 'answer', 'case-2', null),
      scoreResult('group-a', 'llm_group', 'llm_group_a', 'case-1', 0.2),
      scoreResult('group-a', 'llm_group', 'llm_group_a', 'case-2', 0.4),
      scoreResult('group-b', 'llm_group', 'llm_group_b', 'case-1', 0.9),
      scoreResult('child', 'llm_judge', 'child', 'case-1', 0),
    ],
  );
  report.run.manifest.evaluator_specs!.push({
    id: 'child',
    name: '依赖',
    kind: 'llm_judge',
    version: '1',
    content_sha256: '',
  });
  report.metrics = [
    { level: 'kind', key: 'llm_judge', score: 0.75 },
    { level: 'kind', key: 'llm_group', score: 0.6 },
  ] as Report['metrics'];
  const llm = comparisonScoreGroups(comparisonFixture, report, report)[1];
  expect(llm.baseline).toBeCloseTo(0.65);
  expect(llm.delta).toBe(0);
  expect(llm.children.map((child) => child.key)).toEqual([
    'judge-a',
    'judge-b',
    'group-a',
    'group-b',
  ]);
  expect(llm.children[2].baseline).toBeCloseTo(0.3);
});

test('A/B missing scores stay empty instead of becoming zero or a fabricated difference', () => {
  const report = comparisonReport([], []);
  const groups = comparisonScoreGroups(
    { metric_deltas: [] } as unknown as Comparison,
    report,
    report,
  );
  expect(groups).toHaveLength(3);
  for (const group of groups) {
    expect(group).toMatchObject({ baseline: null, candidate: null, delta: null, children: [] });
  }
});
