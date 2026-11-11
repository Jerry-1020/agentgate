import { test, expect } from '@playwright/test';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import ExcelJS from 'exceljs';
import { zipSync, strToU8 } from 'fflate';
import {
  parseCsv,
  rowsToSamples,
  normalizeCases,
  parseSampleFile,
} from '../src/views/datasets/utils/sample-import';
import { toApiCase } from '../src/api/datasets';
Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
const file = (name: string, bytes: Uint8Array) => ({
  name,
  size: bytes.length,
  arrayBuffer: async () => Uint8Array.from(bytes).buffer,
});
const chineseHeaders = [
  '样本编号', '样本名称', '样本分类', '难度', '标签', '样本备注', '初始状态',
  '轮次编号', '轮次顺序', '输入内容', '期望结果', '轮次备注',
];
const englishHeaders = [
  'case_id', 'case_name', 'category', 'difficulty', 'tags_json', 'case_notes',
  'initial_state_json', 'turn_id', 'turn_order', 'input_json', 'expectations_json', 'turn_notes',
];
async function tableFile(format: 'xlsx' | 'csv', headers: string[], rows: (string | number)[][]) {
  if (format === 'csv') {
    const text = [headers, ...rows]
      .map((row) => row.map((value) => '"' + String(value).replace(/"/g, '""') + '"').join(','))
      .join('\r\n');
    return file('sample.csv', strToU8('\uFEFF' + text));
  }
  const workbook = new ExcelJS.Workbook();
  workbook.addWorksheet('Cases').addRows([headers, ...rows]);
  return file('sample.xlsx', new Uint8Array(await workbook.xlsx.writeBuffer()));
}

for (const format of ['xlsx', 'csv'] as const) {
  test(format + ' Chinese headers preserve all fields and sorted multi-turn expectations', async () => {
    const expectations = [{
      name: '嵌套输出', kind: 'output', path: null,
      condition: { kind: 'equals', expected: { values: [0, false, null, '中文'] } },
    }];
    const row = (order: number) => [
      'case-shared', '中文样本', 'boundary', 'hard', '["中文","多轮"]', '样本备注',
      '{"config_variables":[{"name":"enabled","value":false}]}', 'turn-' + order, order,
      JSON.stringify({ txt: '第' + order + '轮', nested: { amount: 0, enabled: false } }),
      JSON.stringify(expectations), '轮次备注' + order,
    ];
    const rows = [row(2), row(1)];
    const english = await parseSampleFile(await tableFile(format, englishHeaders, rows));
    const chinese = await parseSampleFile(await tableFile(format, chineseHeaders, rows));
    const content = (samples: typeof english) => samples.map(toApiCase).map(({ id, turns, ...sample }) => ({
      ...sample,
      turns: turns.map(({ id, expectations, ...turn }) => ({
        ...turn,
        expectations: expectations.map(({ id, ...expectation }) => expectation),
      })),
    }));
    expect(content(chinese)).toEqual(content(english));
    expect(chinese).toHaveLength(1);
    expect(chinese[0]).toMatchObject({
      name: '中文样本', category: 'boundary', difficulty: 'hard', tags: ['中文', '多轮'],
      notes: '样本备注', initial_state: { config_variables: [{ name: 'enabled', value: false }] },
    });
    expect(chinese[0].turns.map((turn) => turn.input.txt)).toEqual(['第1轮', '第2轮']);
    expect(chinese[0].turns.map((turn) => turn.notes)).toEqual(['轮次备注1', '轮次备注2']);
    expect(content(chinese)[0].turns[0].expectations).toEqual(expectations);
  });

  test(format + ' rejects duplicate Chinese and English input columns', async () => {
    const input = await tableFile(format, ['样本名称', 'input_json', '输入内容'], [
      ['中文样本', '{"txt":"hello"}', '{"txt":"你好"}'],
    ]);
    await expect(parseSampleFile(input)).rejects.toThrow(/表头.*重复/);
  });
}

test('parseCsv preserves the original trimmed Chinese headers', () => {
  expect(parseCsv(' 样本名称 , 输入内容 \n中文样本,"{""txt"":""你好""}"')).toEqual([
    { 样本名称: '中文样本', 输入内容: '{"txt":"你好"}' },
  ]);
});

test('CSV handles BOM, quotes, commas, multiline and rejects malformed input', () => {
  expect(parseCsv('\uFEFFcase_name,query\r\na,"hello,\n""world"""')[0]).toEqual({
    case_name: 'a',
    query: 'hello,\n"world"',
  });
  for (const text of ['a,a\n1,2', 'a,b\n1', 'a\n"bad']) expect(() => parseCsv(text)).toThrow();
});
test('blank case ids remain distinct while shared ids form sorted multi-turn cases', () => {
  expect(
    rowsToSamples([
      { case_id: '', case_name: 'a', query: 'one' },
      { case_id: '', case_name: 'b', query: 'two' },
    ]),
  ).toHaveLength(2);
  const sample = rowsToSamples([
    { case_id: 'x', case_name: 'a', query: 'two', turn_order: 2 },
    { case_id: 'x', case_name: 'a', query: 'one', turn_order: 1 },
  ])[0];
  expect(sample.turns.map((t) => t.input.query)).toEqual(['one', 'two']);
  expect(() =>
    rowsToSamples([
      { case_id: 'x', case_name: 'a', query: 'one', turn_order: 1 },
      { case_id: 'x', case_name: 'a', query: 'two', turn_order: 1 },
    ]),
  ).toThrow();
});
test('canonical JSON preserves route, tools, policy, output and complex checks', () => {
  const expectations = [
    { kind: 'skill_route', condition: { kind: 'one_of', allowed: ['a', 'b'] } },
    { kind: 'tool_call', tool: 'lookup', mode: 'required' },
    { kind: 'policy', policy_id: 'p' },
    { kind: 'output', path: null, condition: { kind: 'equals', expected: 'yes' } },
  ];
  const sample = normalizeCases([
    { name: 'a', turns: [{ input: { query: 'hi' }, expectations }] },
  ])[0];
  expect(toApiCase(sample).turns[0].expectations.map(({ id, name, ...e }) => e)).toEqual(
    expectations,
  );
  expect(() =>
    normalizeCases([
      { name: 'bad', turns: [{ input: {}, expectations: [{ kind: 'skill_route' }] }] },
    ]),
  ).toThrow('condition');
});
test('JSON and CSV parse into editable samples with human expectations', async () => {
  const csv = await parseSampleFile(
    file('sample.csv', strToU8('case_name,query,expected\na,hi,hello')),
  );
  expect(csv[0].turns[0].expectations[0].condition).toEqual({ kind: 'equals', expected: 'hello' });
  const json = await parseSampleFile(
    file('sample.json', strToU8(JSON.stringify({ version: { cases: [toApiCase(csv[0])] } }))),
  );
  expect(json[0].turns[0].input).toEqual({ query: 'hi' });
});
test('Excel Cases worksheet imports values but rejects formulas', async () => {
  const book = new ExcelJS.Workbook(),
    sheet = book.addWorksheet('Cases');
  sheet.addRow(['case_name', 'query', 'expected']);
  sheet.addRow(['excel', 'hi', 'hello']);
  let bytes = await book.xlsx.writeBuffer();
  expect((await parseSampleFile(file('sample.xlsx', new Uint8Array(bytes))))[0].name).toBe('excel');
  sheet.getCell('B2').value = { formula: '1+1', result: 2 };
  bytes = await book.xlsx.writeBuffer();
  await expect(parseSampleFile(file('sample.xlsx', new Uint8Array(bytes)))).rejects.toThrow('公式');
});
test('ZIP imports are rejected even when they contain a valid supported sample', async () => {
  const csv = strToU8('case_name,query\na,hi');
  await expect(parseSampleFile(file('a.zip', zipSync({ 'a.csv': csv })))).rejects.toThrow(
    '仅支持 Excel (.xlsx)、JSON、CSV',
  );
});

test('downloadable template imports single and multi-turn cases with documented fields and checks', async () => {
  const bytes = readFileSync(
    new URL('../src/assets/dataset-import-template.xlsx', import.meta.url),
  );
  const samples = await parseSampleFile(file('template.xlsx', bytes));
  expect(samples).toHaveLength(4);
  expect(samples.map((sample) => sample.turns.length)).toEqual([1, 1, 2, 1]);
  expect(
    samples.every((sample) => sample.turns.every((turn) => typeof turn.input.txt === 'string')),
  ).toBe(true);
  const cases = samples.map(toApiCase);
  expect(cases.flatMap((sample) => sample.turns.flatMap((turn) => turn.expectations))).toHaveLength(
    22,
  );
  expect(cases[0].initial_state).toEqual({ customer: 'test-low' });
  expect(cases[1].initial_state).toEqual({ customer: 'test-high' });
  expect(cases[1].turns[0].expectations).toContainEqual(
    expect.objectContaining({ kind: 'tool_call', mode: 'forbidden', tool: 'approve_loan' }),
  );
  expect(cases[2].turns[0].expectations).toContainEqual(
    expect.objectContaining({ kind: 'execution_path', scope: 'tool', expected: [] }),
  );
  expect(cases[3].turns[0].expectations).toEqual([]);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(bytes);
  const data = workbook.getWorksheet('Cases')!;
  const guide = workbook.getWorksheet('填写说明')!;
  const examples = workbook.getWorksheet('测评项示例')!;
  expect((data.getRow(1).values as string[]).slice(1)).toEqual(chineseHeaders);
  expect(guide).toBeTruthy();
  expect(examples).toBeTruthy();
  const guidance = JSON.stringify(guide.getSheetValues());
  data.getRow(1).eachCell((cell) => expect(guidance).toContain(cell.text));
});

test('downloadable CSV template uses the same 12 Chinese headers', () => {
  const csv = readFileSync(
    new URL('../src/assets/dataset-import-template.csv', import.meta.url), 'utf8',
  );
  const headers = csv.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0]
    .split(',').map((header) => header.replace(/^"|"$/g, ''));
  expect(headers).toEqual(chineseHeaders);
});

test('JSON and CSV templates match the complete Excel sample content', async () => {
  const content = (samples: ReturnType<typeof normalizeCases>) =>
    samples.map(toApiCase).map(({ id, turns, ...sample }) => ({
      ...sample,
      turns: turns.map(({ id, expectations, ...turn }) => ({
        ...turn,
        expectations: expectations.map(({ id, ...expectation }) => expectation),
      })),
    }));
  const excel = await parseSampleFile(
    file(
      'template.xlsx',
      readFileSync(new URL('../src/assets/dataset-import-template.xlsx', import.meta.url)),
    ),
  );
  for (const format of ['json', 'csv']) {
    const bytes = readFileSync(
      new URL('../src/assets/dataset-import-template.' + format, import.meta.url),
    );
    const parsed = await parseSampleFile(file('template.' + format, bytes));
    expect(content(parsed)).toEqual(content(excel));
  }
});
