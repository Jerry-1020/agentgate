import { toEditorCase } from '../../../api/datasets';
import type { EvaluationCase, JsonObject } from '../types/index';

export const sampleFileFormats = [
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'json', label: 'JSON' },
  { value: 'csv', label: 'CSV' },
] as const;
export type SampleFileFormat = (typeof sampleFileFormats)[number]['value'];

export interface ImportIssue {
  location: string;
  sheet?: string;
  row?: number;
  column?: string;
  sampleName?: string;
  sampleKey?: string;
  turn?: number;
  field: string;
  path?: string;
  message: string;
}
export const MAX_IMPORT_ISSUES = 200;
export class SampleImportError extends Error {
  readonly name = 'SampleImportError';
  constructor(
    message: string,
    readonly issues: ImportIssue[] = [],
    readonly totalIssues = issues.length,
    readonly sampleCount = 0,
    readonly fileLevel = !issues.length,
  ) {
    super(message);
  }
}

interface Source {
  path: string;
  sampleKey: string;
  sampleName?: string;
  turn?: number;
  sheet?: string;
  row?: number;
  columns?: Record<string, string>;
  invalid: Set<string>;
}
interface CaseSource {
  sample: Source;
  turns: Source[];
}
const fieldNames: Record<string, string> = {
  name: '样本名称',
  category: '样本分类',
  difficulty: '难度',
  tags: '标签',
  initial_state: '初始状态',
  turns: '轮次',
  turn_order: '轮次顺序',
  input: '输入内容',
  expectations: '期望结果',
  case_id: '样本编号',
  case_notes: '样本备注',
  turn_id: '轮次编号',
  turn_notes: '轮次备注',
  expected: '预期输出',
};
const fieldColumns: Record<string, string> = {
  name: 'case_name',
  tags: 'tags_json',
  initial_state: 'initial_state_json',
  input: 'input_json',
  expectations: 'expectations_json',
  turns: 'turn_order',
};
function diagnostics() {
  const issues: ImportIssue[] = [];
  const samples = new Set<string>();
  let totalIssues = 0;
  return {
    add(source: Source, field: string, message: string, suffix = field) {
      totalIssues++;
      samples.add(source.sampleKey);
      const column = source.columns?.[fieldColumns[field] ?? field];
      const path = source.path + (suffix ? '.' + suffix : '');
      const location = source.sheet
        ? column
          ? source.sheet + '!' + column + source.row
          : source.sheet + ' 第 ' + source.row + ' 行'
        : source.row
          ? 'CSV 第 ' + source.row + ' 行'
          : path;
      issues.push({
        location,
        sheet: source.sheet,
        row: source.row,
        column,
        sampleName: source.sampleName,
        sampleKey: source.sampleKey,
        turn: source.turn,
        field: fieldNames[field] ?? field,
        path,
        message,
      });
      issues.sort((a, b) => (a.row ?? 0) - (b.row ?? 0));
      if (issues.length > MAX_IMPORT_ISSUES) issues.pop();
    },
    finish() {
      if (totalIssues)
        throw new SampleImportError(
          '发现 ' + totalIssues + ' 处错误：' + issues[0].message,
          issues,
          totalIssues,
          samples.size,
          false,
        );
    },
  };
}
type Diagnostics = ReturnType<typeof diagnostics>;
function fileError(message: string): never {
  throw new SampleImportError(message);
}
function messageOf(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function blankSample(name = '新样本'): EvaluationCase {
  return {
    id: crypto.randomUUID(),
    name,
    category: 'positive',
    difficulty: 'medium',
    tags: [],
    notes: '',
    initial_state: {},
    turns: [
      {
        id: crypto.randomUUID(),
        input: { query: '' },
        expected_skill: null,
        expectations: [],
        required_tools: [],
        forbidden_tools: [],
        policy_rules: [],
        notes: '',
      },
    ],
  };
}
function object(v: unknown): v is JsonObject {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}
function json(value: unknown, fallback: unknown) {
  return value == null || value === ''
    ? fallback
    : typeof value === 'string'
      ? JSON.parse(value)
      : value;
}
function validateExpectation(e: any) {
  const nonempty = (v: unknown) => typeof v === 'string' && !!v.trim();
  if (e.kind === 'execution_path') {
    if (
      !['workflow', 'tool', 'skill'].includes(e.scope) ||
      !Array.isArray(e.expected) ||
      e.expected.some((v: unknown) => !nonempty(v))
    )
      throw Error('执行路径期望格式错误');
    if (e.scope !== 'tool' && !e.expected.length) throw Error('执行路径不能为空');
    if (e.scope === 'skill') {
      if (
        e.expected.length !== 1 ||
        !Array.isArray(e.allowed_tools) ||
        e.allowed_tools.some((v: unknown) => !nonempty(v))
      )
        throw Error('Skill 检查需要单个技能和允许工具列表');
    } else if (e.allowed_tools != null) throw Error('只有 Skill 检查支持允许工具列表');
    return;
  }
  if (e.kind === 'tool_call') {
    if (!nonempty(e.tool) || !['required', 'forbidden'].includes(e.mode))
      throw Error('工具期望缺少 tool 或 mode');
    return;
  }
  if (e.kind === 'policy') {
    if (!nonempty(e.policy_id)) throw Error('策略期望缺少 policy_id');
    return;
  }
  if (e.kind === 'state' && !nonempty(e.path)) throw Error('状态期望缺少 path');
  if (e.kind === 'output' && e.path !== null && typeof e.path !== 'string')
    throw Error('输出期望需要 path（可为 null）');
  if (
    e.kind === 'tool_argument' &&
    (!nonempty(e.tool) ||
      !nonempty(e.path) ||
      !['first', 'last', 'any', 'all'].includes(e.occurrence))
  )
    throw Error('工具参数期望格式错误');
  const c = e.condition;
  if (!object(c)) throw Error('期望缺少 condition');
  const valid =
    c.kind === 'equals'
      ? 'expected' in c
      : c.kind === 'must_be_missing'
        ? true
        : c.kind === 'within_tolerance'
          ? typeof c.expected === 'number' && typeof c.epsilon === 'number' && c.epsilon >= 0
          : c.kind === 'within_range'
            ? (c.minimum === null || typeof c.minimum === 'number') &&
              (c.maximum === null || typeof c.maximum === 'number') &&
              (c.minimum !== null || c.maximum !== null)
            : c.kind === 'matches_pattern'
              ? typeof c.pattern === 'string'
              : c.kind === 'one_of'
                ? Array.isArray(c.allowed) && c.allowed.length > 0
                : c.kind === 'matches_json_schema'
                  ? object(c.json_schema)
                  : false;
  if (!valid) throw Error('期望 condition 格式错误');
}
function columnName(index: number): string {
  let name = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26))
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}
const sampleNameHeaders = ['case_name', 'name', '样本名称'];
function sampleNameHeader(values: Record<string, unknown>) {
  return sampleNameHeaders.find((header) => values[header] != null) ?? 'case_name';
}
function columnsFor(headers: string[]) {
  const columns: Record<string, string> = Object.create(null);
  headers.forEach((header, i) => {
    const key = header.trim();
    if (Object.prototype.hasOwnProperty.call(columns, key)) fileError('表头重复：' + header);
    columns[key] = columnName(i);
  });
  if (!columns.input_json && columns.query) columns.input_json = columns.query;
  return columns;
}
interface TableRow {
  values: Record<string, unknown>;
  source: Source;
  formulas?: { field: string; column: string }[];
}
function csvRows(text: string, report: Diagnostics): TableRow[] {
  const records: { values: string[]; line: number }[] = [];
  let row: string[] = [],
    field = '',
    quoted = false,
    closed = false,
    line = 1,
    start = 1;
  text = text.replace(/^\uFEFF/, '');
  function endRow() {
    row.push(field);
    if (row.some((value) => value !== '')) records.push({ values: row, line: start });
    row = [];
    field = '';
    closed = false;
  }
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
          closed = true;
        }
      } else {
        field += c;
        if (c === '\n' || (c === '\r' && text[i + 1] !== '\n')) line++;
      }
    } else if (c === ',' || c === '\n' || c === '\r') {
      if (c === ',') {
        row.push(field);
        field = '';
        closed = false;
      } else {
        endRow();
        if (c === '\r' && text[i + 1] === '\n') i++;
        line++;
        start = line;
      }
    } else if (c === '"') {
      if (field || closed) fileError('CSV 第 ' + line + ' 行引号位置错误');
      quoted = true;
    } else {
      if (closed) fileError('CSV 第 ' + line + ' 行结束引号后存在非法字符');
      field += c;
    }
  }
  if (quoted) fileError('CSV 第 ' + start + ' 行存在未闭合引号');
  endRow();
  const headers = records.shift()?.values.map((value) => value.trim()) ?? [];
  if (
    !headers.length ||
    headers.some((value) => !value) ||
    new Set(headers).size !== headers.length
  )
    fileError('CSV 表头为空或重复');
  const columns = columnsFor(headers);
  if (records.length > 2000) fileError('请选择 1—2000 行样本');
  const result: TableRow[] = [];
  records.forEach((record, i) => {
    const values = Object.fromEntries(headers.map((h, j) => [h, record.values[j]]));
    const sampleName = String(values[sampleNameHeader(values)] ?? '').trim();
    const source: Source = {
      path: 'records[' + i + ']',
      row: record.line,
      columns,
      sampleName: sampleName || undefined,
      sampleKey: values.case_id ? 'id:' + String(values.case_id) : 'row:' + record.line,
      invalid: new Set(),
    };
    if (record.values.length !== headers.length) {
      report.add(
        source,
        '整行',
        '列数与表头不匹配：应为 ' + headers.length + ' 列，实际为 ' + record.values.length + ' 列',
        '',
      );
    } else result.push({ values, source });
  });
  return result;
}
export function parseCsv(text: string): Record<string, string>[] {
  const report = diagnostics();
  const rows = csvRows(text, report);
  report.finish();
  return rows.map((row) => row.values as Record<string, string>);
}
function readJson(
  value: unknown,
  fallback: unknown,
  field: string,
  source: Source,
  report: Diagnostics,
) {
  if (source.invalid.has(field)) return fallback;
  try {
    return json(value, fallback);
  } catch {
    source.invalid.add(field);
    report.add(source, field, 'JSON 格式错误，请使用双引号并检查括号、逗号是否完整');
    return fallback;
  }
}
function tableSamples(rows: TableRow[], report: Diagnostics): EvaluationCase[] {
  if (rows.length > 2000) fileError('请选择 1—2000 行样本');
  if (!rows.length) {
    report.finish();
    fileError('请选择 1—2000 行样本');
  }
  const groups = new Map<string, { value: any; source: CaseSource }>();
  rows.forEach(({ values: r, source, formulas = [] }) => {
    const nameHeader = sampleNameHeader(r);
    const name = String(r[nameHeader] ?? '').trim();
    if (nameHeader !== 'case_name' && source.columns)
      source.columns = { ...source.columns, case_name: source.columns[nameHeader] };
    source.sampleName = name || undefined;
    const key = r.case_id ? 'id:' + String(r.case_id) : source.sampleKey;
    source.sampleKey = key;
    let group = groups.get(key);
    if (!group) {
      source.path = 'cases[' + groups.size + ']';
      group = {
        value: {
          ...blankSample(name),
          category: r.category || 'positive',
          difficulty: r.difficulty || 'medium',
          tags: readJson(r.tags_json, [], 'tags', source, report),
          initial_state: readJson(r.initial_state_json, {}, 'initial_state', source, report),
          notes: String(r.case_notes ?? ''),
          turns: [],
        },
        source: { sample: source, turns: [] },
      };
      groups.set(key, group);
    } else if (name && name !== group.value.name && !source.invalid.has('name')) {
      report.add(source, 'name', '同一样本编号的名称不一致，请统一样本名称');
    }
    const c = group.value;
    const order =
      r.turn_order == null || r.turn_order === '' ? c.turns.length + 1 : Number(r.turn_order);
    const turnSource: Source = {
      ...source,
      path: group.source.sample.path + '.turns[' + c.turns.length + ']',
      turn: Number.isInteger(order) && order > 0 ? order : c.turns.length + 1,
    };
    formulas.forEach(({ field, column }) =>
      report.add(
        {
          ...turnSource,
          columns: { ...turnSource.columns, [fieldColumns[field] ?? field]: column },
        },
        field,
        '请将公式转换为值后导入',
      ),
    );
    if (!name && !source.invalid.has('name') && group.source.sample !== source)
      report.add(source, 'name', '缺少样本名称，请填写样本名称');
    if (!Number.isInteger(order) || order < 1 || c.turns.some((turn: any) => turn._order === order))
      if (!source.invalid.has('turn_order'))
        report.add(turnSource, 'turn_order', '轮次顺序必须为不重复的正整数');
    const input = readJson(
      r.input_json,
      r.query !== undefined ? { query: String(r.query) } : null,
      'input',
      turnSource,
      report,
    );
    const expectations = readJson(r.expectations_json, [], 'expectations', turnSource, report);
    if (Array.isArray(expectations) && r.expected != null && r.expected !== '')
      expectations.push({
        id: crypto.randomUUID(),
        name: '人工期望输出',
        kind: 'output',
        path: null,
        condition: { kind: 'equals', expected: String(r.expected) },
      });
    c.turns.push({
      id: String(r.turn_id || crypto.randomUUID()),
      input,
      expectations,
      notes: String(r.turn_notes ?? ''),
      _order: order,
      _source: turnSource,
    });
  });
  const values: unknown[] = [],
    sources: CaseSource[] = [];
  for (const group of groups.values()) {
    group.value.turns.sort((a: any, b: any) => a._order - b._order);
    group.source.turns = group.value.turns.map((turn: any) => turn._source);
    group.value.turns = group.value.turns.map(({ _order, _source, ...turn }: any) => turn);
    values.push(group.value);
    sources.push(group.source);
  }
  return normalizedCases(values, report, sources);
}
export function rowsToSamples(rows: Record<string, unknown>[]): EvaluationCase[] {
  const report = diagnostics();
  return tableSamples(
    rows.map((row, i) => {
      const values = Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key.trim(), value]),
      );
      return {
        values,
        source: {
          path: 'records[' + i + ']',
          sampleKey: 'row:' + (i + 2),
          row: i + 2,
          columns: columnsFor(Object.keys(row)),
          invalid: new Set(),
        },
      };
    }),
    report,
  );
}
function normalizedCases(
  value: unknown,
  report: Diagnostics,
  sources?: CaseSource[],
  prefix = 'cases',
): EvaluationCase[] {
  if (!Array.isArray(value) || !value.length || value.length > 1000)
    fileError('样本必须是包含 1—1000 项的数组');
  const cases: any[] = [];
  value.forEach((raw, i) => {
    const source = sources?.[i]?.sample ?? {
      path: prefix + '[' + i + ']',
      sampleKey: 'case:' + i,
      sampleName: object(raw) && typeof raw.name === 'string' ? raw.name : undefined,
      invalid: new Set<string>(),
    };
    if (!object(raw)) {
      report.add(source, '样本', '样本必须是 JSON 对象', '');
      return;
    }
    if (
      (!raw.name || typeof raw.name !== 'string' || !raw.name.trim()) &&
      !source.invalid.has('name')
    )
      report.add(source, 'name', '缺少样本名称，请填写非空名称');
    const c: any = { ...blankSample(), ...raw, id: crypto.randomUUID() };
    if (
      !source.invalid.has('category') &&
      !['positive', 'negative', 'boundary'].includes(c.category)
    )
      report.add(source, 'category', '样本分类须为 positive、negative 或 boundary');
    if (!source.invalid.has('difficulty') && !['easy', 'medium', 'hard'].includes(c.difficulty))
      report.add(source, 'difficulty', '难度须为 easy、medium 或 hard');
    if (!source.invalid.has('initial_state') && !object(c.initial_state))
      report.add(source, 'initial_state', '初始状态必须是 JSON 对象');
    if (
      !source.invalid.has('tags') &&
      (!Array.isArray(c.tags) || c.tags.some((tag: unknown) => typeof tag !== 'string'))
    )
      report.add(source, 'tags', '标签必须是字符串组成的 JSON 数组');
    if (!Array.isArray(raw.turns) || !raw.turns.length) {
      report.add(source, 'turns', '缺少轮次，请至少填写一轮对话');
      return;
    }
    c.turns = raw.turns.map((turn: any, j: number) => {
      const turnSource = sources?.[i]?.turns[j] ?? {
        ...source,
        path: source.path + '.turns[' + j + ']',
        turn: j + 1,
        invalid: new Set<string>(),
      };
      if (!object(turn)) {
        report.add(turnSource, '轮次', '轮次必须是 JSON 对象', '');
        return turn;
      }
      if (!turnSource.invalid.has('input') && !object(turn.input))
        report.add(turnSource, 'input', '输入内容必须是 JSON 对象，请填写 input_json 或 query');
      if (!turnSource.invalid.has('expectations')) {
        if (!Array.isArray(turn.expectations))
          report.add(turnSource, 'expectations', '期望结果必须是 JSON 数组');
        else
          turn.expectations.forEach((expectation: any, k: number) => {
            const path = 'expectations[' + k + ']';
            const allowed = [
              'output',
              'state',
              'tool_argument',
              'tool_call',
              'skill_route',
              'policy',
              'execution_path',
            ];
            if (!object(expectation) || !allowed.includes(String(expectation.kind)))
              report.add(turnSource, 'expectations', '存在未知期望类型，请参考模板填写 kind', path);
            else
              try {
                validateExpectation(expectation);
              } catch (error) {
                report.add(turnSource, 'expectations', messageOf(error), path);
              }
          });
      }
      return {
        id: crypto.randomUUID(),
        input: turn.input,
        expectations: Array.isArray(turn.expectations)
          ? turn.expectations.map((expectation: any) => ({
              ...expectation,
              id: crypto.randomUUID(),
              name: expectation?.name ?? null,
            }))
          : [],
        notes: turn.notes ?? '',
      };
    });
    cases.push(c);
  });
  report.finish();
  return cases.map(toEditorCase);
}
export function normalizeCases(value: unknown): EvaluationCase[] {
  return normalizedCases(value, diagnostics());
}
export async function parseSampleFile(file: {
  name: string;
  size: number;
  arrayBuffer: () => Promise<ArrayBuffer>;
}): Promise<EvaluationCase[]> {
  if (file.size > 10 * 1024 * 1024) fileError('文件不能超过10MB');
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (/\.json$/i.test(file.name)) {
      const value = JSON.parse(new TextDecoder().decode(bytes));
      const version = object(value) && object(value.version) ? value.version : undefined;
      const prefix = Array.isArray(value)
        ? ''
        : version?.cases != null
          ? 'version.cases'
          : 'cases';
      return normalizedCases(
        Array.isArray(value) ? value : (version?.cases ?? value?.cases),
        diagnostics(),
        undefined,
        prefix,
      );
    }
    if (/\.csv$/i.test(file.name)) {
      const report = diagnostics();
      return tableSamples(
        csvRows(new TextDecoder('utf-8', { fatal: true }).decode(bytes), report),
        report,
      );
    }
    if (/\.xlsx$/i.test(file.name)) {
      const { unzipSync } = await import('fflate');
      let expanded = 0,
        entries = 0;
      unzipSync(bytes, {
        filter(entry) {
          expanded += entry.originalSize;
          if (++entries > 1000 || expanded > 40 * 1024 * 1024)
            fileError('Excel 解压大小或文件数量超限');
          return false;
        },
      });
      const ExcelJS = await import('exceljs');
      const book = new ExcelJS.default.Workbook();
      await book.xlsx.load(bytes as any);
      const sheet = book.getWorksheet('Cases') ?? book.worksheets[0];
      if (!sheet || sheet.rowCount > 2001) fileError('Excel 为空或超过2000行');
      const headers: string[] = [];
      sheet.getRow(1).eachCell({ includeEmpty: true }, (cell, index) => {
        headers[index - 1] = cell.text;
      });
      if (!headers.length || new Set(headers).size !== headers.length)
        fileError('Excel 表头为空或重复');
      const columns = columnsFor(headers),
        report = diagnostics(),
        rows: TableRow[] = [];
      sheet.eachRow((row, number) => {
        if (number === 1) return;
        const values: Record<string, unknown> = Object.create(null);
        const source: Source = {
          path: 'records[' + rows.length + ']',
          sampleKey: 'row:' + number,
          sheet: sheet.name,
          row: number,
          columns,
          invalid: new Set(),
        };
        headers.forEach((header, j) => {
          values[header.trim()] = row.getCell(j + 1).text;
        });
        const nameHeader = sampleNameHeader(values);
        source.sampleKey = values.case_id ? 'id:' + String(values.case_id) : 'row:' + rows.length;
        const order = Number(values.turn_order);
        if (Number.isInteger(order) && order > 0) source.turn = order;
        const formulas: { field: string; column: string }[] = [];
        headers.forEach((header, j) => {
          if (!row.getCell(j + 1).formula) return;
          const key = header.trim();
          let field = Object.keys(fieldColumns).find((name) => fieldColumns[name] === key) ?? key;
          if (key === 'query') field = 'input';
          if (sampleNameHeaders.includes(key)) field = 'name';
          formulas.push({ field, column: columnName(j) });
          if (field === 'name' && key !== nameHeader) return;
          if (key !== 'query' || !values.input_json) source.invalid.add(field);
        });
        rows.push({ values, source, formulas });
      });
      return tableSamples(rows, report);
    }
    fileError('仅支持 Excel (.xlsx)、JSON、CSV');
  } catch (error) {
    if (error instanceof SampleImportError) throw error;
    const prefix = /\.json$/i.test(file.name)
      ? 'JSON 文件格式错误'
      : /\.xlsx$/i.test(file.name)
        ? 'Excel 文件无法读取'
        : '文件无法读取';
    fileError(prefix + '：' + messageOf(error));
  }
}
