import { test, expect } from '@playwright/test';
import ExcelJS from 'exceljs';
import { readFileSync } from 'node:fs';
import {
  loadTaskExport,
  type ExportRead,
  type TaskExportKind,
  type TaskExportData,
} from '../src/views/evaluation/utils/task-export-data';
import {
  taskExportExcel,
  taskExportFilename,
  taskExportTable,
  exportText,
} from '../src/views/evaluation/utils/task-export';
import { ApiError, http } from '../src/utils/request';
import { pinia } from '../src/stores';
import { useAuthStore } from '../src/stores/modules/auth';
const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/llm-group-report.json', import.meta.url), 'utf8'),
);
const report = (id = 'run-a', status = 'completed') => {
  const r = structuredClone(fixture.report);
  r.run.id = id;
  r.run.status = status;
  r.results.forEach((x: any) => (x.run_id = id));
  return r;
};
function reader(reports = [report()], missing = false) {
  const calls: string[] = [];
  const get: ExportRead = async <T>(path: string) => {
    calls.push(path);
    const r = reports.find((x) => path.startsWith(`/runs/${x.run.id}`));
    if (!r) throw Error(`Unexpected read: ${path}`);
    if (path.endsWith('/samples'))
      return { run: r.run, results: r.results, complete: r.run.status === 'completed' } as T;
    if (path.endsWith('/sample-resource-usage')) {
      if (missing) throw new ApiError(500, 'resources unavailable');
      return {
        items: [
          {
            case_id: 'conciseness-number',
            total_tokens: 0,
            token_status: 'available',
            duration_ms: 1234,
            duration_source: 'case_span',
          },
        ],
      } as T;
    }
    if (path.includes('/traces/')) {
      if (missing) throw new ApiError(404, 'trace unavailable');
      const id = decodeURIComponent(path.split('/').at(-1)!);
      const c = r.run.manifest.dataset.cases.find((x: any) => x.id === id);
      return {
        case_id: id,
        spans: [],
        turn_outcomes: Object.fromEntries(
          c.turns.map((t: any) => [
            t.id,
            { input: { txt: '实际输入' }, output: { txt: '实际回答' }, state: {} },
          ]),
        ),
      } as T;
    }
    return r as T;
  };
  return { calls, get };
}
const request = (kind: TaskExportKind = 'full') => ({
  runIds: ['run-a'],
  taskName: '贷款测评',
  taskId: 'task-1',
  kind,
});
const load = (r = report(), kind: TaskExportKind = 'full', missing = false) =>
  loadTaskExport(request(kind), new AbortController().signal, undefined, reader([r], missing).get);
async function exportedWorkbook(data: TaskExportData) {
  const file = await taskExportExcel(data);
  expect(file.type).toBe('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(await file.arrayBuffer());
  return book;
}
async function exportedRows(data: TaskExportData) {
  const sheet = (await exportedWorkbook(data)).worksheets[0];
  const headers = sheet.getRow(1).values as string[];
  return Array.from({ length: sheet.rowCount - 1 }, (_, index) =>
    Object.fromEntries(
      headers.slice(1).map((header, column) => {
        const cell = sheet.getRow(index + 2).getCell(column + 1);
        return [
          header,
          cell.value == null
            ? ''
            : typeof cell.value === 'number' && cell.numFmt === '0.0'
              ? cell.value.toFixed(1)
              : cell.value instanceof Date
                ? cell.value.toISOString()
                : String(cell.value),
        ];
      }),
    ),
  );
}
const scoreKeys = (row: Record<string, string>) =>
  Object.keys(row).filter((key) => key.includes(' · 样本得分'));
const detailKeys = (row: Record<string, string>) =>
  Object.keys(row).filter((key) => key.includes(' · 评估详情'));
const allDetails = (row: Record<string, string>) =>
  detailKeys(row)
    .map((key) => row[key])
    .join('\n');

test('full Excel has one row per sample and turn, all evaluator columns and original aggregate/resource values', async () => {
  const data = await load(),
    table = taskExportTable(data),
    rows = await exportedRows(data);
  expect(rows).toHaveLength(1);
  expect(table.columns.slice(0, 3)).toEqual(['样本序号', '样本名称', '轮次']);
  expect(rows[0]).toMatchObject({
    样本名称: '仅需要一个数字',
    轮次: '1',
    '样本综合得分（样本级含多轮）': '0.0',
    '样本总 Token（样本级含多轮）': '0',
    'Token 完整性（样本级含多轮）': '已采集',
    '样本耗时（秒，样本级含多轮）': '1.234',
    实际输入: '实际输入',
    实际输出: '实际回答',
    任务名称: '贷款测评',
  });
  expect(Object.values(rows[0]).every((value) => value.trim() !== '')).toBeTruthy();
  expect([undefined, null, '', '  ', [], {}].map(exportText)).toEqual(Array(6).fill('-'));
  expect(exportText({ empty: null, zero: 0, flag: false })).toBe('empty：-\nzero：0\nflag：否');
  expect(scoreKeys(rows[0])).toHaveLength(fixture.report.run.manifest.evaluator_specs.length);
  expect(scoreKeys(rows[0]).every((key) => rows[0][key] === '0.0')).toBeTruthy();
  const details = allDetails(rows[0]);
  expect(detailKeys(rows[0]).every((key) => rows[0][key].startsWith('检查详情：'))).toBeTruthy();
  expect(details).not.toMatch(
    /样本级评估|评估结论：|评分依据：|来源：|通过分数：|评估类型：|版本：|计分角色：|所属组合：/,
  );
  expect(details).toContain(fixture.report.results[0].checks[0].reason);
  expect(details).toContain('置信度');
  expect(details).toContain('按本次任务保存的评估器评分标准判分');
  expect(JSON.stringify(rows)).not.toMatch(/request_system_prompt|记录类型|评估器ID|运行ID/);
});
test('multiple turns export every dialogue once and never duplicate sample scores, resources or sample-level LLM checks', async () => {
  const r = report(),
    c = r.run.manifest.dataset.cases[0];
  c.turns.push({ ...c.turns[0], id: 'turn-2', input: { txt: '第二轮配置输入' } });
  const data = await load(r);
  data.runs[0].traces[c.id].turn_outcomes['turn-2'] = {
    input: { txt: '第二轮真实输入' },
    output: { txt: '第二轮真实输出' },
    state: {},
  };
  const rows = await exportedRows(data);
  expect(rows).toHaveLength(2);
  expect(rows.map((row) => [row.样本序号, row.轮次])).toEqual([
    ['1', '1'],
    ['1', '2'],
  ]);
  expect(rows[1]).toMatchObject({
    配置输入: '第二轮配置输入',
    实际输入: '第二轮真实输入',
    实际输出: '第二轮真实输出',
    '样本综合得分（样本级含多轮）': '-',
    '样本总 Token（样本级含多轮）': '-',
    '样本耗时（秒，样本级含多轮）': '-',
  });
  expect(scoreKeys(rows[1]).every((key) => rows[1][key] === '-')).toBeTruthy();
  expect(allDetails(rows[0])).toContain('（样本级）');
  expect(detailKeys(rows[1]).every((key) => rows[1][key] === '本轮无独立检查记录')).toBeTruthy();
  expect(allDetails(rows[1])).not.toContain('置信度');
});
test('Excel has fixed single-line rows, typed scores, hyphens for later-turn scores, frozen keys and filters', async () => {
  const r = report();
  r.run.manifest.dataset.cases[0].turns.push({
    ...r.run.manifest.dataset.cases[0].turns[0],
    id: 'turn-2',
  });
  const data = await load(r),
    book = await exportedWorkbook(data),
    sheet = book.worksheets[0];
  expect(book.worksheets).toHaveLength(1);
  expect(sheet.rowCount).toBe(3);
  expect(taskExportFilename(data)).toMatch(/\.xlsx$/);
  const headers = sheet.getRow(1).values as string[];
  expect(headers.join()).not.toContain('仅首轮');
  expect(headers.join()).toContain('样本级含多轮');
  sheet.eachRow((row) => {
    expect(row.height).toBe(22);
    row.eachCell((cell) => {
      expect(cell.alignment.wrapText).toBeFalsy();
      expect(cell.alignment.shrinkToFit).toBeFalsy();
    });
  });
  for (const [index, header] of headers.entries())
    if (header?.includes('得分')) {
      expect(sheet.getRow(2).getCell(index).value).toBe(0);
      expect(sheet.getRow(2).getCell(index).numFmt).toBe('0.0');
      expect(sheet.getRow(3).getCell(index).value).toBe('-');
    }
  for (const [index, header] of headers.entries())
    if (header?.includes('样本级含多轮')) {
      expect(sheet.getRow(3).getCell(index).value).toBe('-');
    }
  expect(sheet.views[0]).toMatchObject({ state: 'frozen', ySplit: 1, xSplit: 3 });
  expect(sheet.autoFilter).toBeTruthy();
});
test('rule checks stay on their matching turn; sample and unmatched checks are retained only on the first turn', async () => {
  const r = report(),
    c = r.run.manifest.dataset.cases[0],
    result = r.results[0];
  c.turns.push({ ...c.turns[0], id: 'turn-2' });
  result.evaluator_kind = 'rule';
  result.checks = [
    {
      ...result.checks[0],
      name: '首轮检查',
      turn_id: c.turns[0].id,
      expected: { kind: 'equals', expected: true },
      actual: true,
      score: 1,
      outcome: 'pass',
      reason: '首轮通过',
    },
    {
      ...result.checks[0],
      name: '第二轮检查',
      turn_id: 'turn-2',
      expected: false,
      actual: true,
      score: 0,
      outcome: 'fail',
      reason: '第二轮失败',
    },
    { ...result.checks[0], name: '全样本检查', turn_id: null, score: null },
    {
      ...result.checks[0],
      name: '孤立检查',
      turn_id: 'unknown-turn',
      actual_missing: true,
      actual: '不得冒充证据',
      score: null,
    },
  ];
  const rows = await exportedRows(await load(r)),
    first = allDetails(rows[0]),
    second = allDetails(rows[1]);
  expect(first).toContain(
    '首轮检查（第 1 轮）｜预期：等于 是｜实际：是｜得分：100.0｜判定：通过｜原因：首轮通过',
  );
  expect(second).toContain('第二轮检查（第 2 轮）');
  expect(second).toContain('得分：0.0｜判定：未通过｜原因：第二轮失败');
  expect(first).not.toContain('第二轮检查（第 2 轮）');
  expect(second).not.toContain('首轮检查（第 1 轮）');
  expect(first).toContain('全样本检查（样本级）');
  expect(first).toContain('孤立检查（轮次未匹配）');
  expect(first).toContain('实际：证据缺失｜得分：未评分');
  expect(first).not.toContain('不得冒充证据');
  expect(second).not.toContain('全样本检查');
});
test('all executed samples are loaded, including duplicate names, with unique sample and turn keys', async () => {
  const r = report();
  r.run.manifest.selected_case_ids = null;
  r.run.manifest.dataset.cases[1].name = r.run.manifest.dataset.cases[0].name;
  const io = reader([r]),
    data = await loadTaskExport(request(), new AbortController().signal, undefined, io.get);
  const rows = taskExportTable(data).rows;
  expect(rows).toHaveLength(r.run.manifest.dataset.cases.length);
  expect(new Set(rows.map((row) => `${row.样本序号}/${row.轮次}`)).size).toBe(rows.length);
  expect(io.calls.some((path) => path.endsWith('/sample-resource-usage'))).toBeTruthy();
  expect(io.calls.filter((path) => path.includes('/traces/'))).toHaveLength(rows.length);
});
test('requested sample selection from the frozen run is respected and an empty run is explicit', async () => {
  const r = report();
  r.run.manifest.selected_case_ids = ['conciseness-city'];
  expect(taskExportTable(await load(r)).rows.map((row) => row.样本名称)).toEqual([
    '仅需要一个城市名',
  ]);
  r.run.manifest.selected_case_ids = [];
  await expect(load(r)).rejects.toThrow('没有可导出的样本');
});
test('Excel preserves long multiline text in continuation columns and literal formula-like names while hiding credentials', async () => {
  const data = await load();
  data.runs[0].cases[0].name = '=HYPERLINK("x")';
  const reason = '中文,"原因"\n' + '长'.repeat(40000);
  data.runs[0].samples.results[0].checks[0].reason = reason;
  const rows = await exportedRows(data);
  expect(rows[0].样本名称).toBe('=HYPERLINK("x")');
  expect(
    detailKeys(rows[0])
      .map((key) => rows[0][key])
      .join(''),
  ).toContain(reason);
  expect(Object.keys(rows[0]).some((key) => key.endsWith('（续2）'))).toBeTruthy();
  expect(Object.values(rows[0]).every((value) => value.length <= 32767)).toBeTruthy();
  const book = await exportedWorkbook(data);
  expect(book.worksheets[0].getCell('B2').type).toBe(ExcelJS.ValueType.String);
  expect(book.worksheets[0].getCell('B2').formula).toBeUndefined();
  expect(
    exportText({ apiKey: 'secret1', password: 'secret2', access_token: 'secret3' }),
  ).not.toMatch(/secret[123]/);
  expect(exportText('Bearer abc.secret authorization=xyz')).not.toContain('abc.secret');
});
for (const status of ['failed', 'cancelled'])
  test(`${status} retains all planned turns and evaluators with missing-score hyphens`, async () => {
    const r = report('run-a', status);
    r.results = [];
    r.run.error = '执行失败说明';
    const c = r.run.manifest.dataset.cases[0];
    c.turns.push({ ...c.turns[0], id: 'turn-2' });
    const io = reader([r], true),
      data = await loadTaskExport(request(), new AbortController().signal, undefined, io.get);
    expect(io.calls).not.toContain('/runs/run-a');
    const rows = await exportedRows(data);
    expect(rows).toHaveLength(2);
    expect(scoreKeys(rows[0])).toHaveLength(r.run.manifest.evaluator_specs.length);
    expect(rows.every((row) => scoreKeys(row).every((key) => row[key] === '-'))).toBeTruthy();
    expect(rows[0]['样本结果（样本级含多轮）']).toBe('未产生评估结果');
    expect(rows[1].任务异常).toBe('执行失败说明');
    expect(allDetails(rows[0])).toContain('未产生检查结果');
  });
test('unavailable evidence is explicit and configured input never masquerades as actual input', async () => {
  const data = await load(report(), 'full', true),
    row = (await exportedRows(data))[0];
  expect(row.实际输入).toBe('-');
  expect(row.实际输出).toBe('-');
  expect(row.配置输入).not.toBe('-');
  expect(row.缺失说明).toContain('未保存执行轨迹');
  expect(row.缺失说明).toContain('资源统计读取失败');
  expect(row['样本综合得分（样本级含多轮）']).toBe('0.0');
  expect(row['样本总 Token（样本级含多轮）']).toBe('-');
});
test('missing historical turn definitions preserve one explicit sample row instead of silently losing results', async () => {
  const r = report();
  r.run.manifest.dataset.cases[0].turns = [];
  const row = taskExportTable(await load(r)).rows[0];
  expect(row.轮次).toBe('未记录');
  expect(row.缺失说明).toContain('未保存轮次');
  expect(String(row['样本综合得分（样本级含多轮）'])).toBe('0');
});
test('trace reads remain bounded to three concurrent requests', async () => {
  const r = report();
  r.run.manifest.selected_case_ids = null;
  r.run.manifest.dataset.cases = Array.from({ length: 8 }, (_, i) => ({
    ...r.run.manifest.dataset.cases[0],
    id: `c-${i}`,
  }));
  const io = reader([r]);
  let active = 0,
    max = 0;
  const get: ExportRead = async (path, signal) => {
    if (!path.includes('/traces/')) return io.get(path, signal);
    max = Math.max(max, ++active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    const value = await io.get(path, signal);
    active--;
    return value as any;
  };
  await loadTaskExport(request(), new AbortController().signal, undefined, get);
  expect(max).toBe(3);
});
for (const status of [401, 403])
  for (const endpoint of ['/traces/', '/sample-resource-usage'])
    test(`${status} on ${endpoint} aborts the full export`, async () => {
      const io = reader();
      const get: ExportRead = (path, signal) =>
        path.includes(endpoint)
          ? Promise.reject(new ApiError(status, 'denied'))
          : io.get(path, signal);
      await expect(
        loadTaskExport(request(), new AbortController().signal, undefined, get),
      ).rejects.toMatchObject({ status });
    });
test('cancellation and nonterminal state stop the full export', async () => {
  const io = reader(),
    abort = new AbortController();
  const get: ExportRead = async (path, signal) => {
    const value = await io.get(path, signal);
    if (path.includes('/traces/')) abort.abort();
    return value as any;
  };
  await expect(loadTaskExport(request(), abort.signal, undefined, get)).rejects.toThrow(
    '已取消导出',
  );
  await expect(load(report('run-a', 'running'))).rejects.toThrow('完成、失败或取消');
});
test('turn-span inputs are used only for the matching turn and ambiguous evidence is not guessed', async () => {
  const data = await load(),
    run = data.runs[0],
    c = run.cases[0],
    trace = run.traces[c.id];
  delete (trace.turn_outcomes[c.turns[0].id] as any).input;
  trace.spans = [
    {
      span_id: 'turn-evidence',
      name: 'trace_sdk.turn',
      operation_type: 'turn',
      sequence: 0,
      attributes: {
        'agentgate.turn.id': c.turns[0].id,
        'trace_sdk.input': { txt: '轨迹记录的实际输入' },
      },
    },
  ];
  expect(taskExportTable(data).rows[0].实际输入).toBe('轨迹记录的实际输入');
  trace.spans.push({ ...trace.spans[0], span_id: 'ambiguous' });
  expect(taskExportTable(data).rows[0].实际输入).toBe('-');
  trace.spans = [
    {
      ...trace.spans[0],
      attributes: { 'agentgate.turn.id': 'another-turn', 'trace_sdk.input': { txt: '其他轮次' } },
    },
  ];
  expect(taskExportTable(data).rows[0].实际输入).toBe('-');
});
test('duplicate evaluator labels and versions remain separate columns, and one A/B side retains identity', async () => {
  const r = report(),
    original = r.run.manifest.evaluator_specs[0];
  r.run.manifest.evaluator_specs.push({ ...original, id: 'duplicate' });
  r.run.manifest.evaluator_specs.push({ ...original, version: '2' });
  const data = await loadTaskExport(
    { ...request(), runSide: 'B任务' },
    new AbortController().signal,
    undefined,
    reader([r]).get,
  );
  const table = taskExportTable(data);
  expect(table.rows[0].任务侧).toBe('B任务');
  expect(new Set(table.columns).size).toBe(table.columns.length);
  const row = (await exportedRows(data))[0];
  expect(scoreKeys(row)).toHaveLength(r.run.manifest.evaluator_specs.length);
  expect(
    scoreKeys(row)
      .filter((key) => key.includes('v2'))
      .every((key) => row[key] === '-'),
  ).toBeTruthy();
});
test('composite evidence retains resolved child names, percentage weights and point scores', async () => {
  const r = report(),
    original = r.results[0];
  original.evaluator_kind = 'hybrid';
  original.checks = [
    {
      ...original.checks[0],
      expected: { combination: 'all', pass_threshold: 0.8 },
      actual: [
        {
          evaluator_id: original.evaluator_id,
          version: original.evaluator_version,
          result_id: 'internal-reference',
          score: 0.95,
          outcome: 'pass',
          weight: 0.5,
        },
      ],
    },
  ];
  const details = allDetails((await exportedRows(await load(r)))[0]);
  expect(details).toContain('全部通过');
  expect(details).toContain('80.0');
  expect(details).toContain('95.0分；通过；权重 50%');
  expect(details).not.toContain('internal-reference');
});
async function pair(kind: TaskExportKind, historical = false) {
  const a = report(),
    b = report('run-b');
  a.results[0].score = 0.9;
  b.results[0].score = 0.733333;
  a.metrics[0].score = 0.9;
  b.metrics[0].score = 0.733333;
  b.run.manifest.target.ref.external_version_id = '2';
  b.run.manifest.dataset.dataset_name = '不同测评集';
  const io = reader([a, b]);
  const sr = (key: string, level: string) => ({
    key,
    level,
    case_id: null,
    baseline_score: 0.9,
    candidate_score: 0.733333,
    baseline_outcome: 'pass',
    candidate_outcome: 'fail',
    comparable: false,
    reasons: ['dataset_changed'],
    score_delta: -0.166667,
    change: 'regression',
  });
  const comparison = historical
    ? {
        baseline_run_id: 'run-a',
        candidate_run_id: 'run-b',
        baseline_gate: a.release_gate,
        candidate_gate: b.release_gate,
        gate_reasons: ['dataset_changed'],
        score_rows: [sr('overall', 'overall'), sr('llm', 'kind'), sr('rule', 'kind')],
        case_rows: [{ ...sr(a.results[0].evaluator_id, 'case'), case_id: a.results[0].case_id }],
      }
    : {
        baseline_run_id: 'run-a',
        candidate_run_id: 'run-b',
        overall_score_delta: -0.166667,
        metric_deltas: [
          {
            level: 'overall',
            key: 'overall',
            baseline: { score: 0.9 },
            candidate: { score: 0.733333 },
            score_delta: -0.166667,
          },
        ],
        case_deltas: [
          {
            case_id: a.results[0].case_id,
            evaluator_id: a.results[0].evaluator_id,
            baseline_outcome: 'pass',
            candidate_outcome: 'fail',
            change: 'regression',
          },
        ],
      };
  const get: ExportRead = (path, signal) =>
    path.startsWith('/run-comparisons?') || path.startsWith('/evaluation-tasks/')
      ? Promise.resolve(comparison as any)
      : io.get(path, signal);
  return loadTaskExport(
    {
      ...request(kind),
      runIds: ['run-a', 'run-b'],
      ...(historical ? { historyTaskId: 'history-1' } : {}),
    },
    new AbortController().signal,
    undefined,
    get,
  );
}
for (const historical of [false, true])
  test(`${historical ? 'historical' : 'run'} A/B separates metrics, item changes and conditions with numeric one-decimal deltas`, async () => {
    const metrics = await pair('ab_metrics', historical),
      items = await pair('ab_items', historical),
      conditions = await pair('ab_conditions', historical);
    expect(taskExportTable(metrics).columns).toEqual([
      '指标',
      'A得分',
      'B得分',
      '分数差（B−A）',
      '差异说明',
    ]);
    expect((await exportedRows(metrics))[0]['分数差（B−A）']).toBe('-16.7');
    expect(taskExportTable(items).rows).toHaveLength(1);
    expect((await exportedRows(items))[0]['分数差（B−A）']).toBe('-16.7');
    expect(
      taskExportTable(conditions).rows.some(
        (r) => r.条件类别 === '测评集内容' && r.结果 === '不同',
      ),
    ).toBeTruthy();
    expect(taskExportTable(conditions).columns).not.toContain('得分');
    expect(JSON.stringify(await exportedRows(conditions))).not.toContain('content_sha256');
    expect(JSON.stringify(await exportedRows(metrics))).not.toContain('不可比较');
  });
test('condition rows disclose changed individual parameters without embedding full configuration JSON', async () => {
  const data = await pair('ab_conditions');
  data.runs[1].samples.run.manifest.timeout_seconds = 123;
  const table = taskExportTable(data),
    row = table.rows.find((r) => r.条件名称 === '超时秒数')!;
  expect(row.B任务条件).toBe('123');
  expect(row.条件类别).toBe('执行参数');
  expect(table.rows.every((r) => !String(r.A任务条件).includes('"dataset_id"'))).toBeTruthy();
  expect(table.rows.filter((r) => r.条件类别 === '指标口径')).toHaveLength(1);
});
test('partial A/B has no invented comparison, while its terminal side can export a full report', async () => {
  const io = reader([report(), report('run-b', 'cancelled')]);
  const comparison = await loadTaskExport(
    { ...request('ab_metrics'), runIds: ['run-a', 'run-b'] },
    new AbortController().signal,
    undefined,
    io.get,
  );
  expect(taskExportTable(comparison).rows).toHaveLength(0);
  const side = await loadTaskExport(
    { ...request(), runIds: ['run-b'], runSide: 'B任务' },
    new AbortController().signal,
    undefined,
    io.get,
  );
  expect(taskExportTable(side).rows[0].任务侧).toBe('B任务');
  await expect(
    loadTaskExport(
      { ...request(), runIds: ['run-a', 'run-b'] },
      new AbortController().signal,
      undefined,
      io.get,
    ),
  ).rejects.toThrow('选择一个任务');
});
for (const mode of ['external', 'bank', 'integrated'] as const)
  test(`${mode} uses existing read endpoints and current session routing`, async () => {
    const auth = useAuthStore(pinia),
      state = { ...auth.$state },
      adapter = http.defaults.adapter,
      io = reader(),
      calls: any[] = [];
    try {
      if (mode === 'external') auth.loginExternal();
      else if (mode === 'bank') auth.loginBank('bank-token', 'bank-team', '行内团队');
      else
        auth.initializePlatform({
          token: 'host-token',
          teamId: 'host-team',
          teamName: '集成团队',
          userId: 'host-user',
          userName: '用户',
        });
      http.defaults.adapter = async (config) => {
        calls.push(config);
        return {
          data: await io.get(config.url!, config.signal as AbortSignal),
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      };
      await loadTaskExport(request(), new AbortController().signal);
      expect(calls.every((c) => c.method === 'get' && c.url.startsWith('/runs/'))).toBeTruthy();
      expect(calls[0].headers.token).toBe(
        mode === 'external' ? undefined : mode === 'bank' ? 'bank-token' : 'host-token',
      );
    } finally {
      http.defaults.adapter = adapter;
      auth.$patch(state);
    }
  });
