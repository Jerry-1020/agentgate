import type { Trace } from '../../../api/client';
import type {
  AnnotationTask,
  AnnotationTarget,
  MessageAnnotation,
  ToolAnnotation,
} from '../../../stores/modules/review';
import type { EvaluationRun } from '../types/run';
import type { EvaluationCase, SerializedExpectation, JsonValue } from '../../datasets/types';

export type RawCase = Omit<EvaluationCase, 'turns'> & {
  turns: {
    id: string;
    input: Record<string, JsonValue>;
    notes: string;
    expectations: SerializedExpectation[];
  }[];
};
export type ToolCall = Trace['spans'][number] & { turnId: string | null };

export function matchesAnnotationTarget(run: EvaluationRun, target: AnnotationTarget): boolean {
  const snapshot = run.manifest.target;
  const config = snapshot.invocation_config;
  if (!config || run.status !== 'completed') return false;
  if (target.localExecution) return target.loginMode === 'external' &&
    snapshot.ref.source_id === target.localExecution.sourceId &&
    snapshot.adapter_type === target.localExecution.adapterType &&
    snapshot.ref.external_target_id === target.agentId &&
    snapshot.ref.external_version_id === target.agentVersion;
  if (snapshot.adapter_type === 'local_bank' || snapshot.adapter_type === 'demo_loan') return false;
  return (
    snapshot.ref.external_target_id === target.agentId &&
    snapshot.ref.external_version_id === target.agentVersion &&
    (config.team_id ?? '') === target.teamId &&
    (config.branch_id ?? null) === target.branchId &&
    config.type_group === target.typeGroup &&
    (target.loginMode === 'external'
      ? snapshot.adapter_type === 'agent_platform_mock'
      : snapshot.adapter_type !== 'agent_platform_mock' && config.simulated !== true)
  );
}

export function toolCalls(trace: Trace): ToolCall[] {
  const spans = new Map(trace.spans.map((s) => [s.span_id, s]));
  return trace.spans
    .filter((s) => s.operation_type === 'tool')
    .sort((a, b) => a.sequence - b.sequence)
    .map((s) => {
      let current: Trace['spans'][number] | undefined = s;
      const seen = new Set<string>();
      let turnId: string | null = null;
      while (current && !seen.has(current.span_id)) {
        seen.add(current.span_id);
        const id = current.attributes['agentgate.turn.id'];
        if (typeof id === 'string' && id in trace.turn_outcomes) {
          turnId = id;
          break;
        }
        current = current.parent_span_id ? spans.get(current.parent_span_id) : undefined;
      }
      return { ...s, turnId };
    });
}

export function scoresComplete(
  scores: Record<string, number | null> | undefined,
  dimensions: string[],
  min: number,
  max: number,
) {
  return dimensions.every(
    (key) =>
      typeof scores?.[key] === 'number' &&
      Number.isFinite(scores[key]) &&
      scores[key]! >= min &&
      scores[key]! <= max,
  );
}

export function defaultOutputPath(output: Record<string, unknown>): string {
  return 'output' in output ? 'output' : 'answer' in output ? 'answer' : '';
}

function outputExpectation(
  annotation: MessageAnnotation,
  id: string,
): SerializedExpectation | null {
  if (!annotation.expected.trim()) return null;
  const path = annotation.expectedPath?.trim() ?? 'output';
  if (path && path.split('.').some((part) => !part.trim()))
    throw Error('输出字段路径必须是有效的点分路径。');
  const mode = annotation.expectedMode ?? 'equals';
  if (!path && mode !== 'json') throw Error('比较完整输出时请选择 JSON 相等。');
  let condition: Extract<SerializedExpectation, { kind: 'output' }>['condition'];
  if (mode === 'json') {
    try {
      condition = { kind: 'equals', expected: JSON.parse(annotation.expected) };
    } catch {
      throw Error('人工期望不是有效 JSON。');
    }
  } else if (mode === 'matches_pattern' || mode === 'contains') {
    const pattern =
      mode === 'contains'
        ? annotation.expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        : annotation.expected;
    try {
      new RegExp(pattern);
    } catch {
      throw Error('人工期望正则表达式无效。');
    }
    condition = { kind: 'matches_pattern', pattern };
  } else condition = { kind: 'equals', expected: annotation.expected };
  return { id, kind: 'output', name: '人工标注输出期望', path: path || null, condition };
}

// Source input and unrelated checks are preserved. Scores remain audit notes, never model truth.
export function annotatedCase(
  source: RawCase,
  trace: Trace,
  task: AnnotationTask,
  prefix: string,
): RawCase {
  const result: RawCase = JSON.parse(JSON.stringify(source));
  const calls = toolCalls(trace);
  const turns = new Set(source.turns.map((t) => t.id));
  if (Object.keys(trace.turn_outcomes).some((id) => !turns.has(id)))
    throw Error('草稿轮次已变化，请核对后再回写。');
  const toolRules = new Map<string, string>();
  for (const turn of result.turns) {
    const annotation = task.annotations[prefix + '/' + turn.id];
    if (!annotation) throw Error('请先保存该会话的全部消息标注。');
    const output = outputExpectation(annotation, 'human-output-' + turn.id);
    if (output?.kind === 'output') {
      turn.expectations = turn.expectations.filter(
        (e) => !(e.kind === 'output' && e.path === output.path),
      );
      turn.expectations.push(output);
    }
    const audit: unknown[] = [{ template: task.template.id, source: prefix, message: annotation }];
    for (const call of calls.filter((c) => c.turnId === turn.id)) {
      const review = task.toolAnnotations?.[prefix + '/' + call.span_id];
      if (!review) continue;
      audit.push({ span_id: call.span_id, tool: call.name, review });
      if (review.expectation === 'none' && !review.argumentsExpected.trim()) continue;
      if (review.expectation === 'forbidden' && review.argumentsExpected.trim())
        throw Error('禁止调用的工具不能同时配置参数期望。');
      const key = turn.id + '/' + call.name;
      const rule = JSON.stringify([
        review.expectation,
        review.argumentsExpected,
        review.argumentsPath ?? 'arguments',
        review.occurrence,
      ]);
      if (toolRules.has(key)) {
        if (toolRules.get(key) !== rule)
          throw Error('同一轮同名工具的自动规则冲突，请统一规则或只在一次调用上配置。');
        continue;
      }
      toolRules.set(key, rule);
      const id = 'human-tool-' + turn.id + '-' + call.span_id;
      if (review.expectation !== 'none') {
        turn.expectations = turn.expectations.filter(
          (e) => !(e.kind === 'tool_call' && e.tool === call.name),
        );
        turn.expectations.push({
          id,
          kind: 'tool_call',
          name: '人工工具调用期望',
          tool: call.name,
          mode: review.expectation,
        });
      }
      if (review.argumentsExpected.trim()) {
        const argumentPath = review.argumentsPath?.trim() || 'arguments';
        if (argumentPath.split('.').some((part) => !part.trim())) throw Error('工具参数路径无效。');
        let expected: JsonValue;
        try {
          expected = JSON.parse(review.argumentsExpected);
        } catch {
          throw Error('工具参数期望必须是有效 JSON。');
        }
        turn.expectations = turn.expectations.filter(
          (e) =>
            !(
              e.kind === 'tool_argument' &&
              e.tool === call.name &&
              e.path === argumentPath &&
              e.occurrence === review.occurrence
            ),
        );
        turn.expectations.push({
          id: id + '-arguments',
          name: '人工工具参数期望',
          kind: 'tool_argument',
          tool: call.name,
          path: argumentPath,
          occurrence: review.occurrence,
          condition: { kind: 'equals', expected },
        });
      }
    }
    // Replace the audit entry for this template; repeated writeback stays idempotent.
    const marker = '\n【人工标注 ' + task.template.id + '】';
    const old = turn.notes.indexOf(marker);
    if (old >= 0) {
      const end = turn.notes.indexOf('\n【人工标注结束】', old);
      if (end >= 0)
        turn.notes = turn.notes.slice(0, old) + turn.notes.slice(end + '\n【人工标注结束】'.length);
    }
    turn.notes += marker + '\n' + JSON.stringify(audit) + '\n【人工标注结束】';
  }
  const unassigned: unknown[] = [];
  for (const call of calls.filter((c) => !c.turnId)) {
    const review = task.toolAnnotations?.[prefix + '/' + call.span_id];
    if (review && (review.expectation !== 'none' || review.argumentsExpected.trim()))
      throw Error('工具调用缺少轮次关联，不能自动生成规则。');
    if (review) unassigned.push({ source: prefix, span_id: call.span_id, tool: call.name, review });
  }
  if (unassigned.length) {
    const marker = '\n【未关联轮次工具标注 ' + task.template.id + '】';
    const endMarker = '\n【工具标注结束】';
    const old = result.notes.indexOf(marker);
    const end = old < 0 ? -1 : result.notes.indexOf(endMarker, old);
    if (end >= 0)
      result.notes = result.notes.slice(0, old) + result.notes.slice(end + endMarker.length);
    result.notes += marker + '\n' + JSON.stringify(unassigned) + endMarker;
  }
  return result;
}
