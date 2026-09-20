import { toEditorCase } from '../../../api/datasets';
import type { EvaluationCase, JsonObject } from '../types/index';

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
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [],
    field = '',
    quoted = false,
    closed = false;
  text = text.replace(/^\uFEFF/, '');
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
      } else field += c;
    } else if (c === ',' || c === '\n' || c === '\r') {
      row.push(field);
      field = '';
      closed = false;
      if (c !== ',') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        if (row.some((v) => v !== '')) rows.push(row);
        row = [];
      }
    } else if (c === '"') {
      if (field || closed) throw Error('CSV 引号位置错误');
      quoted = true;
    } else {
      if (closed) throw Error('CSV 结束引号后存在非法字符');
      field += c;
    }
  }
  if (quoted) throw Error('CSV 存在未闭合引号');
  row.push(field);
  if (row.some((v) => v !== '')) rows.push(row);
  const headers = rows.shift()?.map((s) => s.trim()) ?? [];
  if (!headers.length || headers.some((s) => !s) || new Set(headers).size !== headers.length)
    throw Error('CSV 表头为空或重复');
  return rows.map((r, i) => {
    if (r.length !== headers.length) throw Error('CSV 第 ' + (i + 2) + ' 行列数不匹配');
    return Object.fromEntries(headers.map((h, j) => [h, r[j]]));
  });
}
export function rowsToSamples(rows: Record<string, unknown>[]): EvaluationCase[] {
  if (!rows.length || rows.length > 2000) throw Error('请选择 1—2000 行样本');
  const groups = new Map<string, any>();
  rows.forEach((r, i) => {
    const name = String(r.case_name ?? r.name ?? r['样本名称'] ?? '').trim();
    if (!name) throw Error('第 ' + (i + 2) + ' 行缺少 case_name / name');
    const key = r.case_id ? 'id:' + String(r.case_id) : 'row:' + i;
    let c = groups.get(key);
    if (!c) {
      c = {
        ...blankSample(name),
        category: r.category || 'positive',
        difficulty: r.difficulty || 'medium',
        tags: json(r.tags_json, []),
        notes: String(r.case_notes ?? ''),
        initial_state: json(r.initial_state_json, {}),
        turns: [],
      };
      groups.set(key, c);
    }
    if (c.name !== name) throw Error('同一 case_id 的名称不一致');
    const input = json(r.input_json, r.query !== undefined ? { query: String(r.query) } : null);
    if (!object(input)) throw Error('第 ' + (i + 2) + ' 行需要 input_json 对象或 query');
    const expectations = json(r.expectations_json, []) as any[];
    if (!Array.isArray(expectations)) throw Error('expectations_json 必须是数组');
    if (r.expected != null && r.expected !== '')
      expectations.push({
        id: crypto.randomUUID(),
        name: '人工期望输出',
        kind: 'output',
        path: null,
        condition: { kind: 'equals', expected: String(r.expected) },
      });
    const order =
      r.turn_order == null || r.turn_order === '' ? c.turns.length + 1 : Number(r.turn_order);
    if (!Number.isInteger(order) || order < 1 || c.turns.some((t: any) => t._order === order))
      throw Error('turn_order 必须为不重复的正整数');
    c.turns.push({
      id: String(r.turn_id || crypto.randomUUID()),
      input,
      expectations,
      notes: String(r.turn_notes ?? ''),
      _order: order,
    });
  });
  return normalizeCases(
    [...groups.values()].map((c) => ({
      ...c,
      turns: c.turns
        .sort((a: any, b: any) => a._order - b._order)
        .map(({ _order, ...t }: any) => t),
    })),
  );
}
export function normalizeCases(value: unknown): EvaluationCase[] {
  if (!Array.isArray(value) || !value.length || value.length > 1000)
    throw Error('样本必须是包含 1—1000 项的数组');
  return value.map((raw, i) => {
    if (
      !object(raw) ||
      typeof raw.name !== 'string' ||
      !raw.name.trim() ||
      !Array.isArray(raw.turns) ||
      !raw.turns.length
    )
      throw Error('样本 ' + (i + 1) + ' 缺少名称或轮次');
    const c: any = { ...blankSample(), ...raw, id: crypto.randomUUID() };
    if (
      !['positive', 'negative', 'boundary'].includes(c.category) ||
      !['easy', 'medium', 'hard'].includes(c.difficulty) ||
      !object(c.initial_state) ||
      !Array.isArray(c.tags) ||
      c.tags.some((t: unknown) => typeof t !== 'string')
    )
      throw Error('样本分类、难度、初始状态或标签格式错误');
    c.turns = c.turns.map((t: any) => {
      if (!object(t) || !object(t.input) || !Array.isArray(t.expectations))
        throw Error('轮次需要 input 对象及 expectations 数组');
      const allowed = ['output', 'state', 'tool_argument', 'tool_call', 'skill_route', 'policy'];
      if (t.expectations.some((e: any) => !object(e) || !allowed.includes(String(e.kind))))
        throw Error('存在未知期望类型');
      t.expectations.forEach(validateExpectation);
      return {
        id: crypto.randomUUID(),
        input: t.input,
        expectations: t.expectations.map((e: any) => ({
          ...e,
          id: crypto.randomUUID(),
          name: e.name ?? null,
        })),
        notes: t.notes ?? '',
      };
    });
    return toEditorCase(c);
  });
}
export async function parseSampleFile(file: {
  name: string;
  size: number;
  arrayBuffer: () => Promise<ArrayBuffer>;
}): Promise<EvaluationCase[]> {
  if (file.size > 10 * 1024 * 1024) throw Error('文件不能超过10MB');
  const bytes = new Uint8Array(await file.arrayBuffer());
  async function parse(name: string, data: Uint8Array): Promise<EvaluationCase[]> {
    if (/\.json$/i.test(name)) {
      const v = JSON.parse(new TextDecoder().decode(data));
      return normalizeCases(Array.isArray(v) ? v : (v.version?.cases ?? v.cases));
    }
    if (/\.csv$/i.test(name))
      return rowsToSamples(parseCsv(new TextDecoder('utf-8', { fatal: true }).decode(data)));
    if (/\.xlsx$/i.test(name)) {
      const { unzipSync } = await import('fflate');
      let expanded = 0,
        entries = 0;
      unzipSync(data, {
        filter(entry) {
          expanded += entry.originalSize;
          if (++entries > 1000 || expanded > 40 * 1024 * 1024)
            throw Error('Excel 解压大小或文件数量超限');
          return false;
        },
      });
      const ExcelJS = await import('exceljs');
      const book = new ExcelJS.default.Workbook();
      await book.xlsx.load(data as any);
      const sheet = book.getWorksheet('Cases') ?? book.worksheets[0];
      if (!sheet || sheet.rowCount > 2001) throw Error('Excel 为空或超过2000行');
      const headers = (sheet.getRow(1).values as unknown[]).slice(1).map(String);
      if (new Set(headers).size !== headers.length) throw Error('Excel 表头重复');
      const rows: Record<string, unknown>[] = [];
      sheet.eachRow((row, n) => {
        if (n === 1) return;
        const r: Record<string, unknown> = {};
        headers.forEach((h, j) => {
          const c = row.getCell(j + 1);
          if (c.formula) throw Error('请将公式转换为值后导入');
          r[h] = c.text;
        });
        rows.push(r);
      });
      return rowsToSamples(rows);
    }
    throw Error('仅支持 JSON、CSV、Excel(.xlsx)，或包含这些文件的ZIP');
  }
  if (!/\.zip$/i.test(file.name)) return parse(file.name, bytes);
  const { unzipSync } = await import('fflate');
  let size = 0,
    count = 0;
  const files = unzipSync(bytes, {
    filter(entry) {
      if (entry.name.endsWith('/')) return false;
      if (
        entry.name.startsWith('/') ||
        entry.name.split('/').includes('..') ||
        !/\.(json|csv|xlsx)$/i.test(entry.name)
      )
        throw Error('ZIP 包含不支持的文件或非法路径');
      size += entry.originalSize;
      if (++count > 20 || size > 20 * 1024 * 1024 || entry.originalSize > 10 * 1024 * 1024)
        throw Error('ZIP 解压大小或文件数量超限');
      return true;
    },
  });
  const result: EvaluationCase[] = [];
  for (const [name, data] of Object.entries(files)) result.push(...(await parse(name, data)));
  if (!result.length || result.length > 1000) throw Error('ZIP 样本总数须为1—1000');
  return result;
}
