import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { parse, compileScript } from '@vue/compiler-sfc';
import ts from 'typescript';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createPinia } from 'pinia';
import { http } from '../src/utils/request';
import { useTaskLinksStore } from '../src/stores/modules/task-links';
import type { Report } from '../src/api/evaluations';
import type { HistoricalComparison, HistoricalScoreRow } from '../src/api/historical-comparisons';
import {
  historicalScoreGroups,
  comparisonReasons,
} from '../src/views/evaluation/utils/historical-comparison';

const report = (specs: object[]) =>
  ({
    run: {
      manifest: { evaluator_specs: specs, primary_evaluator_ids: specs.map((s: any) => s.id) },
    },
  }) as Report;
const row = (
  key: string,
  level: HistoricalScoreRow['level'],
  comparable = true,
): HistoricalScoreRow => ({
  key,
  level,
  case_id: null,
  baseline_score: 0,
  candidate_score: 0.6,
  baseline_outcome: null,
  candidate_outcome: null,
  comparable,
  reasons: comparable ? [] : ['dataset_changed'],
  score_delta: 0.6,
  change: null,
});
const comparison = (rows: HistoricalScoreRow[]) =>
  ({
    score_rows: [
      row('overall', 'overall', false),
      row('llm', 'kind', false),
      row('rule', 'kind'),
      ...rows,
    ],
  }) as HistoricalComparison;

test('aggregates show arithmetic deltas alongside condition differences and retain zero', () => {
  const groups = historicalScoreGroups(comparison([]), report([]), report([]));
  expect(groups.map((r) => r.name)).toEqual(['综合得分', 'LLM评估得分', '规则评估得分']);
  expect(groups[0]).toMatchObject({
    baseline: 0,
    candidate: 0.6,
    delta: 0.6,
    reasons: '测评集或测评集内容不同',
  });
  expect(groups[2].delta).toBe(0.6);
});

test('both frozen evaluator sets are shown, including candidate-only and changed definitions', () => {
  const left = [{ id: 'judge', name: '回答质量', version: '1', kind: 'llm_judge' }];
  const right = [
    { ...left[0], version: '2' },
    { id: 'rule', name: '规则', version: '1', kind: 'rule' },
  ];
  const groups = historicalScoreGroups(
    comparison([
      row('judge', 'evaluator', false),
      {
        ...row('rule', 'evaluator', false),
        baseline_score: null,
        score_delta: null,
        reasons: ['evaluator_missing', 'score_unavailable'],
      },
    ]),
    report(left),
    report(right),
  );
  expect(groups[1].children[0]).toMatchObject({
    name: 'A：回答质量 · 1 / B：回答质量 · 2',
    delta: 0.6,
  });
  expect(groups[2].children[0]).toMatchObject({
    name: 'A：未使用 / B：规则 · 1',
    baseline: null,
    candidate: 0.6,
    delta: null,
    reasons: '某一侧未使用该评估器；缺少可用得分',
  });
});

test('comparison reasons explain errors and missing evidence in Chinese', () => {
  expect(comparisonReasons(['result_missing', 'evaluation_error', 'gate_changed'])).toBe(
    '某一侧缺少评估结果；存在评估错误；通过条件不同',
  );
  expect(comparisonReasons(['unknown-reason'])).toBe('比较条件不完整');
});

test('execution scope shows frozen sample names without consulting a changed dataset', async () => {
  const file = new URL('../src/views/evaluation/components/ExecutionScope.vue', import.meta.url);
  const script = compileScript(parse(readFileSync(file, 'utf8')).descriptor, {
    id: 'history-scope',
    inlineTemplate: true,
  }).content;
  const code = ts.transpileModule(script, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} as { default?: any } };
  const require = createRequire(import.meta.url);
  new Function('require', 'module', 'exports', code)(
    (id: string) => {
      if (id !== 'vue') throw Error('Unexpected external dependency: ' + id);
      return require(id);
    },
    module,
    module.exports,
  );
  const manifest = {
    dataset: {
      cases: [
        { id: 'case-a', name: '执行时的样本' },
        { id: 'case-b', name: '未选样本' },
      ],
    },
    selected_case_ids: ['case-a'],
  };
  const html = await renderToString(
    createSSRApp(module.exports.default, { baseline: manifest, candidate: manifest }),
  );
  expect(html).toContain('执行用例 · 一致');
  expect(html).toContain('A任务：指定用例 · 1 条');
  expect(html).toContain('执行时的样本');
  expect(html).not.toContain('未选样本');
});

test('historical association remains distinguishable after a full refresh and direct open', async () => {
  const previous = http.defaults.adapter;
  const task = {
    id: 'history',
    kind: 'ab',
    run_ids: ['run-a', 'run-b'],
    static_report_ids: [],
    historical_comparison: true,
  };
  try {
    http.defaults.adapter = async (config) => ({
      data: config.url === '/evaluation-tasks' ? [task] : task,
      config,
      status: 200,
      statusText: 'OK',
      headers: {},
    });
    const store = useTaskLinksStore(createPinia());
    await store.refreshTaskLinks();
    expect(store.readTaskLinks()[0]).toMatchObject({
      id: 'history',
      historicalComparison: true,
      runIds: ['run-a', 'run-b'],
    });
    await store.refreshTaskLinks('history');
    expect(store.readTaskLinks()[0].historicalComparison).toBe(true);
  } finally {
    http.defaults.adapter = previous;
  }
});
