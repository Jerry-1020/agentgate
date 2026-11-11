import type { EvaluationCase, EvaluationResult } from '../../../api/client';
import { kindLabel, statusLabel } from '../../../api/evaluations';
import type { ExportRun, TaskExportData, TaskExportKind } from './task-export-data';
import { comparisonScoreGroups, sampleSummary, type EvaluatorSnapshot } from './task-report';
import { comparisonReasons, historicalScoreGroups } from './historical-comparison';
import { llmCheckDetails, sameJson } from './report-presentation';
import { dimensionNames } from './evaluator-display';

export type ExportValue = string | number | null;
export type ExportRow = Record<string, ExportValue>;
export interface TaskExportTable {
  columns: string[];
  rows: ExportRow[];
}
export const taskExportOptions: {
  value: TaskExportKind;
  label: string;
  description: string;
  ab?: boolean;
}[] = [
  {
    value: 'full',
    label: '完整测评结果',
    description: '每个样本的一轮一行，包含对话、汇总和全部评估器结果',
  },
  {
    value: 'ab_metrics',
    label: '指标对比',
    description: '每个指标一行，查看 A/B 得分和分数差',
    ab: true,
  },
  {
    value: 'ab_items',
    label: '样本结果对比',
    description: '每个样本 × 每个评估器一行，查看两侧结果变化',
    ab: true,
  },
  {
    value: 'ab_conditions',
    label: '执行条件差异',
    description: '每个具体差异一行；一致的类别只保留一行说明',
    ab: true,
  },
];
const secrets =
  /(?:^|_)(?:api_key|access_token|refresh_token|authorization|password|secret|client_secret|credential_ref|credential_id|credentials|cookie|token)$/i;
const secretKey = (key: string) => secrets.test(key.replace(/([a-z])([A-Z])/g, '$1_$2'));
const labels: Record<string, string> = {
  absent_tool: '禁止调用的工具',
  required_tool: '必须调用的工具',
  allowed_tools: '允许的工具',
  calls: '调用记录',
  arguments: '调用参数',
  scope: '检查范围',
  execution_path: '执行路径',
  dataset_name: '测评集名称',
  dataset_description: '测评集说明',
  cases: '样本列表',
  txt: '文本',
  text: '文本',
  output: '输出',
  input: '输入',
  answer: '回答',
  response: '回答',
  content: '内容',
  expected: '预期值',
  actual: '实际值',
  kind: '类型',
  path: '字段',
  condition: '要求',
  fields: '字段规则',
  tool: '工具',
  mode: '方式',
  required: '必须',
  forbidden: '禁止',
  tool_call: '工具调用',
  final_state: '最终状态',
  final_output: '最终输出',
  skill: 'Skill',
  policy: '策略',
  name: '名称',
  description: '描述',
  version: '版本',
  state: '状态',
  status: '状态',
  result: '结果',
  reason: '原因',
  score: '得分',
  confidence: '置信度',
  verdict: '判定',
  violations: '问题',
  criterion: '评分项',
  detail: '说明',
  dimensions: '评分维度',
  equals: '等于',
  not_equals: '不等于',
  contains: '包含',
  not_contains: '不包含',
  pattern: '匹配规则',
  regex: '正则匹配',
  one_of: '属于',
  allowed: '允许值',
  must_be_missing: '字段必须不存在',
  pass_threshold: '通过分数',
  min_confidence: '最低置信度',
  rubric: '评分标准',
  instruction: '评分说明',
  input_selection: '评估证据范围',
  full_trajectory: '完整轨迹',
  weight: '权重',
  combination: '组合方式',
  weighted_score: '加权评分',
  all: '全部通过',
  any: '任一通过',
  metric: '计分项',
  dimension: '评分类别',
  minimum_score: '最低通过分数',
  timeout_seconds: '超时秒数',
  max_retries: '重试次数',
  max_parallel_cases: '样本并发数',
  category: '样本类型',
  difficulty: '难度',
  tags: '场景',
  notes: '说明',
  initial_state: '初始状态',
  expectations: '预期要求',
  turns: '对话轮次',
  config: '配置',
  children: '子评估器',
  severity: '重要程度',
  blocking: '阻断项',
  standard: '普通项',
  implementation_id: '评估方式',
  implementation_version: '实现版本',
  'p1-equal-mean': '等权平均',
  'release-gate': '任务通过判定',
  ...dimensionNames,
};
function protect(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(protect);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, secretKey(k) ? '[已隐藏]' : protect(v)]),
    );
  if (typeof value === 'string')
    return value
      .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [已隐藏]')
      .replace(
        /((?:api[_-]?key|access[_-]?token|password|authorization|client[_-]?secret)\s*[=:]\s*["']?)[^\s,"';}]+/gi,
        '$1[已隐藏]',
      );
  return value;
}
function readable(value: unknown): string {
  if (value == null || (typeof value === 'string' && !value.trim())) return '-';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value))
    return value.length ? value.map((v, i) => `${i + 1}. ${readable(v)}`).join('\n') : '-';
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    const condition = value as Record<string, unknown>;
    if (condition.kind === 'equals' && entries.length === 2 && 'expected' in condition)
      return `等于 ${readable(condition.expected)}`;
    if (
      entries.length === 1 &&
      ['txt', 'text', 'output', 'answer', 'response', 'content'].includes(entries[0][0])
    )
      return readable(entries[0][1]);
    return entries.length
      ? entries
          .map(
            ([k, v]) =>
              `${labels[k] ?? k}：${['kind', 'mode', 'verdict'].includes(k) && typeof v === 'string' ? (labels[v] ?? statusLabel(v)) : readable(v)}`,
          )
          .join('\n')
      : '-';
  }
  return String(value);
}
export const exportText = (value: unknown) => readable(protect(value));
const points = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? null : Number((v * 100).toFixed(1));
const changeLabel = (v: string | null) =>
  ({ improvement: '改善', regression: '退化', unchanged: '不变', changed: '变化' })[v ?? ''] ??
  '未产生变化结论';
const builtinNames: Record<string, string> = {
  'Final State': '最终状态',
  'Final Output': '最终输出',
  'Required Tool': '必需工具',
  'Forbidden Tool': '禁止工具',
  'Tool Arguments': '工具参数',
  'Skill Routing': 'Skill 路由',
  'Policy Compliance': '策略合规',
};
const evaluatorName = (name: string) => {
  const builtin = Object.keys(builtinNames).find(
    (key) => name === key || name.startsWith(`${key} · v`) || name.startsWith(`${key} v`),
  );
  return builtin ? builtinNames[builtin] + name.slice(builtin.length) : name;
};
const specs = (run: ExportRun) => run.samples.run.manifest.evaluator_specs ?? [];
function compositeEvidence(value: unknown, run: ExportRun): string {
  if (Array.isArray(value))
    return value
      .map((item) => {
        if (!item || typeof item !== 'object') return exportText(item);
        const row = item as Record<string, unknown>;
        const spec = specs(run).find((s) => s.id === row.evaluator_id && s.version === row.version);
        return [
          spec ? `${evaluatorName(spec.name)} v${spec.version}` : '未记录名称的子评估器',
          typeof row.score === 'number' ? `${points(row.score)?.toFixed(1)}分` : '未评分',
          typeof row.outcome === 'string' ? statusLabel(row.outcome) : '未记录判定',
          typeof row.weight === 'number' ? `权重 ${points(row.weight)}%` : '',
        ]
          .filter(Boolean)
          .join('；');
      })
      .join('\n');
  if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>;
    return (
      [
        typeof row.combination === 'string'
          ? `组合方式：${labels[row.combination] ?? row.combination}`
          : '',
        typeof row.pass_threshold === 'number'
          ? `通过分数：${points(row.pass_threshold)?.toFixed(1)}`
          : '',
      ]
        .filter(Boolean)
        .join('\n') || '未记录组合要求'
    );
  }
  return exportText(value);
}
function checkDetails(result: EvaluationResult, c: EvaluationCase, run: ExportRun): string {
  const isLlm = ['llm_judge', 'llm_group'].includes(result.evaluator_kind);
  const isComposite = result.evaluator_kind === 'hybrid';
  return (
    result.checks
      .map((check, number) => {
        const detail = llmCheckDetails(check);
        const turn = c.turns.findIndex((t) => t.id === check.turn_id);
        const scope =
          check.turn_id == null ? '样本级' : turn < 0 ? '轮次未匹配' : `第 ${turn + 1} 轮`;
        const expected = isLlm
          ? '按本次任务保存的评估器评分标准判分'
          : isComposite
            ? compositeEvidence(check.expected, run)
            : exportText(check.expected);
        const actual = check.actual_missing
          ? '证据缺失'
          : isLlm
            ? [
                detail.confidence == null ? '' : `置信度：${points(detail.confidence)}%`,
                ...detail.violations.map((v) => `${v.criterion}：${v.detail}`),
                ...detail.dimensions.map(
                  (d) =>
                    `${d.name}：${d.score == null ? '未评分' : `${points(d.score)?.toFixed(1)}分`}；${d.reason}`,
                ),
              ]
                .filter(Boolean)
                .join('；') || check.reason
            : isComposite
              ? compositeEvidence(check.actual, run)
              : exportText(check.actual);
        return [
          `${number + 1}．${check.name}（${scope}）`,
          `预期：${expected}`,
          `实际：${actual}`,
          `得分：${points(check.score)?.toFixed(1) ?? '未评分'}`,
          `判定：${statusLabel(check.outcome)}`,
          `原因：${check.reason || '未记录'}`,
        ].join('｜');
      })
      .join('\n\n') || '未记录检查项'
  );
}
function sampleIdentity(run: ExportRun, c: EvaluationCase): ExportRow {
  return {
    样本序号: run.samples.run.manifest.dataset.cases.findIndex((x) => x.id === c.id) + 1,
    样本名称: c.name,
  };
}
function evaluationRows(run: ExportRun, c: EvaluationCase): EvaluationResult[] {
  const results = run.samples.results.filter((r) => r.case_id === c.id);
  const missing = specs(run).filter(
    (s) =>
      !results.some(
        (r) =>
          r.evaluator_id === s.id &&
          (r.evaluator_version == null || r.evaluator_version === s.version),
      ),
  );
  // Planned evaluators without results remain visible, with no invented score.
  return [
    ...results,
    ...missing.map((s) => ({
      case_id: c.id,
      evaluator_id: s.id,
      evaluator_version: s.version,
      evaluator_name: s.name,
      evaluator_kind: s.kind,
      score: null,
      reason: run.samples.run.error
        ? `未产生评估结果；任务异常：${run.samples.run.error}`
        : '未产生评估结果',
      checks: [],
      outcome: 'error' as const,
      trace_id: '',
      dimension: '',
      metric: '',
      severity: 'standard' as const,
    })),
  ];
}
function evaluatorKey(run: ExportRun, result: EvaluationResult): string {
  const matches = specs(run).filter((s) => s.id === result.evaluator_id);
  return `${result.evaluator_id}@${result.evaluator_version ?? (matches.length === 1 ? matches[0].version : '未记录')}`;
}
function evaluationDetail(
  result: EvaluationResult,
  c: EvaluationCase,
  run: ExportRun,
  turnId: string | undefined,
  first: boolean,
  saved: boolean,
): string {
  const knownTurns = new Set(c.turns.map((turn) => turn.id));
  const checks = result.checks.filter(
    (check) =>
      check.turn_id === turnId ||
      (first && (check.turn_id == null || !knownTurns.has(check.turn_id))),
  );
  return checks.length
    ? `检查详情：\n${checkDetails({ ...result, checks }, c, run)}`
    : saved
      ? '本轮无独立检查记录'
      : '未产生检查结果';
}
function fullRows(data: TaskExportData): TaskExportTable {
  const run = data.runs[0],
    info = run.samples.run,
    manifest = info.manifest;
  const definitions = new Map<string, { label: string; score: string; detail: string }>();
  const byCase = new Map(run.cases.map((c) => [c.id, evaluationRows(run, c)]));
  const addColumn = (key: string, name: string, version: string) => {
    if (definitions.has(key)) return;
    const base = `${evaluatorName(name)} v${version}`;
    let label = base,
      suffix = 2;
    while ([...definitions.values()].some((entry) => entry.label === label))
      label = `${base}（${suffix++}）`;
    definitions.set(key, {
      label,
      score: `${label} · 样本得分（样本级含多轮）`,
      detail: `${label} · 评估详情`,
    });
  };
  for (const spec of specs(run)) addColumn(`${spec.id}@${spec.version}`, spec.name, spec.version);
  for (const results of byCase.values())
    for (const result of results)
      addColumn(
        evaluatorKey(run, result),
        result.evaluator_name,
        result.evaluator_version ?? '未记录',
      );
  const columns = [
    ...(data.request.runSide ? ['任务侧'] : []),
    '样本序号',
    '样本名称',
    '轮次',
    '样本总轮数',
    '场景',
    '配置输入',
    '实际输入',
    '实际输出',
    '本轮预期要求',
    '样本结果（样本级含多轮）',
    '样本综合得分（样本级含多轮）',
    '样本总 Token（样本级含多轮）',
    'Token 完整性（样本级含多轮）',
    '样本耗时（秒，样本级含多轮）',
    '缺失说明',
    '任务名称',
    '被测Agent',
    'Agent版本',
    '测评集',
    '测评集版本',
    '任务状态',
    '任务启动时间',
    '任务结束时间',
    '任务异常',
    ...[...definitions.values()].flatMap((entry) => [entry.score, entry.detail]),
  ];
  const rows: ExportRow[] = [];
  for (const c of run.cases) {
    const results = byCase.get(c.id)!;
    const actualResults = run.samples.results.filter((result) => result.case_id === c.id);
    const summary = sampleSummary(actualResults, manifest.primary_evaluator_ids);
    const usage = run.resources.find((item) => item.case_id === c.id);
    const trace = run.traces[c.id];
    const turns = c.turns.length ? c.turns : [undefined];
    const keyedResults = new Map(results.map((result) => [evaluatorKey(run, result), result]));
    turns.forEach((turn, index) => {
      const first = index === 0;
      const actual = turn ? trace?.turn_outcomes?.[turn.id] : undefined;
      const turnSpans = turn
        ? (trace?.spans.filter(
            (span) =>
              span.operation_type === 'turn' && span.attributes['agentgate.turn.id'] === turn.id,
          ) ?? [])
        : [];
      const input =
        actual?.input !== undefined
          ? actual.input
          : turnSpans.length === 1
            ? turnSpans[0].attributes['trace_sdk.input']
            : undefined;
      const missing = run.warnings
        .filter((warning) => !warning.caseId || warning.caseId === c.id)
        .map((warning) => warning.message);
      if (!turn) missing.push('本样本未保存轮次');
      if (input === undefined || actual?.output === undefined)
        missing.push('本轮实际输入或输出未记录');
      const requirements = turn
        ? {
            ...(turn.original_expectations?.length
              ? { expectations: turn.original_expectations }
              : turn.expectations?.length
                ? { expectations: turn.expectations }
                : {}),
            ...(turn.required_tools?.length ? { required_tool: turn.required_tools } : {}),
            ...(turn.forbidden_tools?.length ? { absent_tool: turn.forbidden_tools } : {}),
            ...(turn.expected_skill ? { skill: turn.expected_skill } : {}),
            ...(turn.policy_rules?.length ? { policy: turn.policy_rules } : {}),
          }
        : undefined;
      const row: ExportRow = {
        ...(data.request.runSide ? { 任务侧: run.side } : {}),
        ...sampleIdentity(run, c),
        轮次: turn ? index + 1 : '未记录',
        样本总轮数: c.turns.length,
        场景: c.tags.join('、'),
        配置输入: exportText(turn?.input),
        实际输入: exportText(input),
        实际输出: exportText(actual?.output),
        本轮预期要求: exportText(businessConfig(requirements, run)),
        '样本结果（样本级含多轮）': first
          ? summary.outcome === 'pending'
            ? actualResults.length
              ? '部分评估结果'
              : '未产生评估结果'
            : statusLabel(summary.outcome)
          : '',
        '样本综合得分（样本级含多轮）': first ? points(summary.score) : null,
        '样本总 Token（样本级含多轮）': first ? (usage?.total_tokens ?? null) : null,
        'Token 完整性（样本级含多轮）': first
          ? usage?.token_status === 'available'
            ? '已采集'
            : usage?.token_status === 'partial'
              ? '部分'
              : '未采集'
          : '',
        '样本耗时（秒，样本级含多轮）':
          first && usage?.duration_ms != null
            ? Number((usage.duration_ms / 1000).toFixed(3))
            : null,
        缺失说明: [...new Set(missing)].join('；'),
        任务名称: data.request.taskName ?? '',
        被测Agent: manifest.target.display_name,
        Agent版本: manifest.target.ref.external_version_id,
        测评集: manifest.dataset.dataset_name,
        测评集版本: manifest.dataset.version,
        任务状态: statusLabel(info.status),
        任务启动时间: info.started_at,
        任务结束时间: info.completed_at,
        任务异常: info.error,
      };
      for (const [key, definition] of definitions) {
        const result = keyedResults.get(key);
        row[definition.score] = first && result ? points(result.score) : null;
        row[definition.detail] = result
          ? evaluationDetail(result, c, run, turn?.id, first, actualResults.includes(result))
          : '未产生检查结果';
      }
      rows.push(row);
    });
  }
  return { columns, rows };
}
function comparisonRows(data: TaskExportData): TaskExportTable {
  const [a, b] = data.runs,
    history = data.historical,
    comparison = data.comparison;
  const metrics = data.request.kind === 'ab_metrics';
  const columns = metrics
    ? ['指标', 'A得分', 'B得分', '分数差（B−A）', '差异说明']
    : [
        '样本名称',
        '评估器',
        'A得分',
        'B得分',
        '分数差（B−A）',
        'A结果',
        'B结果',
        '变化',
        '差异说明',
      ];
  if (!a.report || !b.report || (!history && !comparison)) return { columns, rows: [] };
  if (metrics) {
    const groups = history
      ? historicalScoreGroups(history, a.report, b.report)
      : comparisonScoreGroups(comparison!, a.report, b.report);
    return {
      columns,
      rows: groups
        .flatMap((g) => [g, ...g.children])
        .map((m) => ({
          指标: evaluatorName(m.name),
          A得分: points(m.baseline),
          B得分: points(m.candidate),
          '分数差（B−A）': points(m.delta),
          差异说明: m.reasons ?? '',
        })),
    };
  }
  const values = history
    ? history.case_rows.map((r) => ({
        caseId: r.case_id ?? '',
        evaluatorId: r.key,
        a: r.baseline_score,
        b: r.candidate_score,
        ao: r.baseline_outcome,
        bo: r.candidate_outcome,
        delta: r.score_delta,
        change: r.change,
        reason: comparisonReasons(r.reasons),
      }))
    : comparison!.case_deltas.map((r) => {
        const ar = a.samples.results.find(
            (x) => x.case_id === r.case_id && x.evaluator_id === r.evaluator_id,
          ),
          br = b.samples.results.find(
            (x) => x.case_id === r.case_id && x.evaluator_id === r.evaluator_id,
          );
        return {
          caseId: r.case_id,
          evaluatorId: r.evaluator_id,
          a: ar?.score,
          b: br?.score,
          ao: r.baseline_outcome,
          bo: r.candidate_outcome,
          delta: ar?.score == null || br?.score == null ? null : br.score - ar.score,
          change: r.change,
          reason: '',
        };
      });
  const name = (run: ExportRun, id: string) => {
    const s = specs(run).find((s) => s.id === id);
    return s ? `${evaluatorName(s.name)} v${s.version}` : '未使用';
  };
  return {
    columns,
    rows: values
      .filter((v) => [...a.cases, ...b.cases].some((c) => c.id === v.caseId))
      .map((v) => {
        const an = name(a, v.evaluatorId),
          bn = name(b, v.evaluatorId);
        return {
          样本名称: [...a.cases, ...b.cases].find((c) => c.id === v.caseId)?.name ?? '未记录名称',
          评估器: an === bn ? an : `A：${an}；B：${bn}`,
          A得分: points(v.a),
          B得分: points(v.b),
          '分数差（B−A）': points(v.delta),
          A结果: v.ao ? statusLabel(v.ao) : '未产生结果',
          B结果: v.bo ? statusLabel(v.bo) : '未产生结果',
          变化: changeLabel(v.change),
          差异说明: v.reason,
        };
      }),
  };
}
const technicalKey =
  /^(?:id|dataset_id|case_id|turn_id|expectation_id|.*_sha256|created_at|updated_at|published_at|user_.*|api_key|credential_.*|based_on_version)$/;
function businessConfig(value: unknown, run: ExportRun): unknown {
  if (Array.isArray(value)) return value.map((v) => businessConfig(v, run));
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(([k]) => !technicalKey.test(k) && !secretKey(k))
        .map(([k, v], i) => {
          const definition = specs(run).find((s) => s.id === k);
          const key = definition
            ? evaluatorName(definition.name)
            : /^[a-f\d]{8}-(?:[a-f\d-]{27,})$/i.test(k)
              ? `配置项 ${i + 1}`
              : (labels[k] ?? k);
          const scalar =
            typeof v === 'string'
              ? (labels[v] ?? v)
              : ['pass_threshold', 'minimum_score', 'min_confidence'].includes(k) &&
                  typeof v === 'number'
                ? points(v)
                : businessConfig(v, run);
          return [key, scalar];
        }),
    );
  return value;
}
function conditionRows(data: TaskExportData): TaskExportTable {
  const [a, b] = data.runs,
    left = a.samples.run.manifest,
    right = b.samples.run.manifest;
  const value = (run: ExportRun, key: string) =>
    (run.samples.run.manifest as unknown as Record<string, unknown>)[key];
  const scope = (run: ExportRun) =>
    [
      ...(run.samples.run.manifest.selected_case_ids ??
        run.samples.run.manifest.dataset.cases.map((c) => c.id)),
    ].sort();
  const names = (run: ExportRun, ids: string[]) =>
    ids.map(
      (id) => run.samples.run.manifest.dataset.cases.find((c) => c.id === id)?.name ?? '未记录名称',
    );
  const evaluator = (run: ExportRun, s: EvaluatorSnapshot) => ({
    名称: evaluatorName(s.name),
    版本: s.version,
    类型: kindLabel(s.kind),
    配置: businessConfig(s.config, run),
    组合方式: labels[s.combination ?? ''] ?? s.combination,
    子评估器: (s.children ?? []).map((ref) => ({
      名称: evaluatorName(
        specs(run).find((x) => x.id === ref.evaluator_id && x.version === ref.evaluator_version)
          ?.name ?? '未记录名称',
      ),
      版本: ref.evaluator_version,
      权重百分比: points(ref.weight),
    })),
  });
  const definitionNames = (run: ExportRun) =>
    run.samples.run.manifest.primary_evaluator_ids.map((id) => {
      const s = specs(run).find((x) => x.id === id);
      return s ? `${evaluatorName(s.name)} v${s.version}` : '未记录名称';
    });
  const plan = (run: ExportRun, key: string) => {
    const v = value(run, key);
    return v && typeof v === 'object'
      ? {
          方式:
            labels[String((v as Record<string, unknown>).id)] ?? (v as Record<string, unknown>).id,
          ...(businessConfig(v, run) as object),
        }
      : v;
  };
  const categories: { name: string; rawA: unknown; rawB: unknown; a: unknown; b: unknown }[] = [
    {
      name: '智能体版本',
      rawA: left.target.ref,
      rawB: right.target.ref,
      a: { 智能体: left.target.display_name, 版本: left.target.ref.external_version_id },
      b: { 智能体: right.target.display_name, 版本: right.target.ref.external_version_id },
    },
    {
      name: '执行样本范围',
      rawA: scope(a),
      rawB: scope(b),
      a: names(a, scope(a)),
      b: names(b, scope(b)),
    },
    {
      name: '测评集内容',
      rawA: left.dataset,
      rawB: right.dataset,
      a: businessConfig(left.dataset, a),
      b: businessConfig(right.dataset, b),
    },
    {
      name: '评估器及版本定义',
      rawA: left.evaluator_specs,
      rawB: right.evaluator_specs,
      a: specs(a).map((s) => evaluator(a, s)),
      b: specs(b).map((s) => evaluator(b, s)),
    },
    {
      name: '主评估器',
      rawA: left.primary_evaluator_ids,
      rawB: right.primary_evaluator_ids,
      a: definitionNames(a),
      b: definitionNames(b),
    },
    {
      name: '指标口径',
      rawA: value(a, 'metric_plan'),
      rawB: value(b, 'metric_plan'),
      a: plan(a, 'metric_plan'),
      b: plan(b, 'metric_plan'),
    },
    {
      name: '通过条件',
      rawA: value(a, 'gate_spec'),
      rawB: value(b, 'gate_spec'),
      a: plan(a, 'gate_spec'),
      b: plan(b, 'gate_spec'),
    },
    {
      name: '执行参数',
      rawA: [left.timeout_seconds, left.max_retries, left.max_parallel_cases],
      rawB: [right.timeout_seconds, right.max_retries, right.max_parallel_cases],
      a: {
        超时秒数: left.timeout_seconds,
        重试次数: left.max_retries,
        样本并发数: left.max_parallel_cases,
      },
      b: {
        超时秒数: right.timeout_seconds,
        重试次数: right.max_retries,
        样本并发数: right.max_parallel_cases,
      },
    },
  ];
  const rows: ExportRow[] = [];
  function differences(category: string, path: string[], old: unknown, next: unknown) {
    if ((old === undefined && next === undefined) || sameJson(old, next)) return;
    if (
      old &&
      next &&
      typeof old === 'object' &&
      typeof next === 'object' &&
      Array.isArray(old) === Array.isArray(next)
    ) {
      const keys = [...new Set([...Object.keys(old), ...Object.keys(next)])];
      if (keys.length) {
        for (const key of keys)
          differences(
            category,
            [...path, Array.isArray(old) ? `第 ${Number(key) + 1} 项` : key],
            (old as Record<string, unknown>)[key],
            (next as Record<string, unknown>)[key],
          );
        return;
      }
    }
    rows.push({
      条件类别: category,
      条件名称: path.join(' / ') || category,
      A任务条件: exportText(old),
      B任务条件: exportText(next),
      结果: '不同',
      差异说明:
        old === undefined
          ? 'B侧新增或A侧未记录'
          : next === undefined
            ? 'A侧存在、B侧未记录'
            : '该条件的保存值不同',
    });
  }
  for (const c of categories) {
    if (c.rawA === undefined || c.rawB === undefined) {
      rows.push({
        条件类别: c.name,
        条件名称: c.name,
        A任务条件: exportText(c.a),
        B任务条件: exportText(c.b),
        结果: '未记录',
        差异说明: '至少一侧未保存该条件',
      });
      continue;
    }
    const before = rows.length;
    differences(c.name, [], c.a, c.b);
    if (rows.length === before)
      rows.push({
        条件类别: c.name,
        条件名称: c.name,
        A任务条件: '业务配置相同',
        B任务条件: '业务配置相同',
        结果: sameJson(c.rawA, c.rawB) ? '一致' : '不同',
        差异说明: sameJson(c.rawA, c.rawB)
          ? ''
          : c.name === '执行样本范围'
            ? '样本名称相同，但来自不同的样本记录'
            : '标识或保存信息不同，业务显示内容相同',
      });
  }
  return { columns: ['条件类别', '条件名称', 'A任务条件', 'B任务条件', '结果', '差异说明'], rows };
}
function excelTable(table: TaskExportTable): TaskExportTable {
  const rows = table.rows.map((row) => ({ ...row }));
  const columns: string[] = [];
  for (const column of table.columns) {
    columns.push(column);
    const parts = rows.map((row) => {
      const value = row[column];
      if (typeof value !== 'string') return [value];
      const text = exportText(value),
        chunks: string[] = [];
      // Excel limits cell text to 32,767 characters; keep overflow in the same sample row.
      for (let start = 0; start < text.length; ) {
        let end = Math.min(start + 32767, text.length);
        if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end--;
        chunks.push(text.slice(start, end));
        start = end;
      }
      return chunks.length ? chunks : [''];
    });
    const count = parts.reduce((max, value) => Math.max(max, value.length), 1);
    for (let i = 0; i < count; i++) {
      let key = column;
      if (i) {
        let suffix = i + 1;
        key = `${column}（续${suffix}）`;
        while (table.columns.includes(key) || columns.includes(key))
          key = `${column}（续${++suffix}）`;
        columns.push(key);
      }
      rows.forEach((row, index) => {
        row[key] = parts[index][i] ?? '-';
      });
    }
  }
  return { columns, rows };
}
export function taskExportTable(data: TaskExportData): TaskExportTable {
  return excelTable(
    data.request.kind === 'ab_conditions'
      ? conditionRows(data)
      : data.request.kind === 'ab_metrics' || data.request.kind === 'ab_items'
        ? comparisonRows(data)
        : fullRows(data),
  );
}
export async function taskExportExcel(data: TaskExportData): Promise<Blob> {
  const { columns, rows } = taskExportTable(data);
  const ExcelJS = await import('exceljs');
  const book = new ExcelJS.default.Workbook();
  const sheet = book.addWorksheet(
    taskExportOptions.find((option) => option.value === data.request.kind)!.label,
  );
  sheet.properties.defaultRowHeight = 22;
  sheet.columns = columns.map((header) => ({
    header,
    key: header,
    width: Math.min(
      96,
      Math.max(
        /详情|输入|输出|要求|说明|条件/.test(header)
          ? 44
          : /时间/.test(header)
            ? 29
            : /名称|Agent|测评集/.test(header)
              ? 28
              : 14,
        [...header].reduce((width, char) => width + (char.charCodeAt(0) > 255 ? 2 : 1), 0) + 4,
      ),
    ),
  }));
  for (const values of rows) {
    const row = sheet.addRow(
      columns.map((column) => (values[column] === '' ? '-' : (values[column] ?? '-'))),
    );
    row.height = 22;
    row.eachCell({ includeEmpty: true }, (cell, index) => {
      const column = columns[index - 1];
      cell.font = { name: 'Arial', size: 11 };
      cell.alignment = { vertical: 'top', wrapText: false, shrinkToFit: false };
      if (typeof cell.value === 'number') {
        cell.numFmt = /得分|分数/.test(column) ? '0.0' : /耗时/.test(column) ? '0.###' : '0';
      } else if (
        /^任务(启动|结束)时间$/.test(column) &&
        typeof cell.value === 'string' &&
        Number.isFinite(Date.parse(cell.value))
      ) {
        cell.value = new Date(cell.value);
        cell.numFmt = 'yyyy-mm-dd hh:mm:ss" UTC"';
      }
    });
  }
  const header = sheet.getRow(1);
  header.height = 22;
  header.eachCell((cell) => {
    cell.font = { name: 'Arial', size: 11, bold: true, color: { argb: 'FFFFFFFF' } };
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF087F70' } };
    cell.alignment = {
      vertical: 'middle',
      horizontal: 'center',
      wrapText: false,
      shrinkToFit: false,
    };
  });
  const border = { style: 'thin' as const, color: { argb: 'FFD1D5DB' } };
  for (let row = 1; row <= rows.length + 1; row++) {
    for (let column = 1; column <= columns.length; column++) {
      sheet.getCell(row, column).border = {
        top: border,
        bottom: border,
        left: border,
        right: border,
      };
    }
  }
  sheet.views = [
    {
      state: 'frozen',
      ySplit: 1,
      xSplit: data.request.kind === 'full' ? (data.request.runSide ? 4 : 3) : 1,
      showGridLines: false,
    },
  ];
  sheet.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: rows.length + 1, column: columns.length },
  };
  return new Blob([new Uint8Array(await book.xlsx.writeBuffer())], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}
export function taskExportFilename(data: TaskExportData) {
  const name = (data.request.taskName || '测评任务')
    .replace(/[\\/:*?"<>|]/g, '_')
    .split('')
    .map((c) => (c.charCodeAt(0) < 32 ? '_' : c))
    .join('')
    .slice(0, 80);
  const label = taskExportOptions
    .find((o) => o.value === data.request.kind)!
    .label.replaceAll('/', '_');
  return `${name}-${label}-${data.exportedAt.replace(/[-:]/g, '').slice(0, 15)}.xlsx`;
}
