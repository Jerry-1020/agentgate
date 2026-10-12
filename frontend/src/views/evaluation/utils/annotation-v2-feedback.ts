import type { AnnotationTask } from '../../../stores/modules/review';
import type { JsonValue } from '../../datasets/types';
import type { Trace } from '../../../api/client';
import { defaultOutputPath, type RawCase } from './annotation-feedback';

export function annotatedV2Case(
  source: RawCase,
  trace: Trace,
  task: AnnotationTask,
  prefix: string,
): RawCase {
  const result: RawCase = JSON.parse(JSON.stringify(source));
  if (Object.keys(trace.turn_outcomes).some((id) => !source.turns.some((t) => t.id === id)))
    throw Error('样本轮次已变化，请核对后再操作。');
  for (const turn of result.turns) {
    const annotations = task.v2Annotations?.[prefix + '/' + turn.id];
    const dataset = task.template.v2?.dataset.enabled ? annotations?.dataset : undefined;
    if (dataset?.expected?.trim()) {
      const outputs = turn.expectations.filter((e) => e.kind === 'output');
      const paths = [...new Set(outputs.map((e) => (e.kind === 'output' ? e.path : null)))];
      if (paths.length > 1)
        throw Error('该轮存在多个输出路径，请先在原测评集中确认要修订的输出路径。');
      const path = paths.length
        ? paths[0]
        : defaultOutputPath(trace.turn_outcomes[turn.id]?.output ?? trace.final_output) || null;
      let expected: JsonValue = dataset.expected;
      if (path === null) {
        try {
          expected = JSON.parse(dataset.expected);
        } catch {
          throw Error('完整输出为结构化内容，请将人工期望回答填写为有效 JSON。');
        }
      }
      turn.expectations = turn.expectations.filter(
        (e) => !(e.kind === 'output' && e.path === path),
      );
      turn.expectations.push({
        id: 'human-v2-output-' + turn.id,
        kind: 'output',
        name: 'V2人工标注输出期望',
        path,
        condition: { kind: 'equals', expected },
      });
    }
    const marker = '\n【V2人工标注 ' + task.template.id + '】';
    const endMarker = '\n【V2人工标注结束】';
    const start = turn.notes.indexOf(marker);
    const end = start < 0 ? -1 : turn.notes.indexOf(endMarker, start);
    if (end >= 0)
      turn.notes = turn.notes.slice(0, start) + turn.notes.slice(end + endMarker.length);
    turn.notes +=
      marker +
      '\n' +
      JSON.stringify({
        source: prefix,
        dataset,
        evaluator: task.template.v2?.evaluator.enabled ? annotations?.evaluator : undefined,
      }) +
      endMarker;
  }
  return result;
}
export function hasV2Expected(task: AnnotationTask, prefix: string, turnIds: string[]) {
  return (
    !!task.template.v2?.dataset.enabled &&
    turnIds.some((id) => task.v2Annotations?.[prefix + '/' + id]?.dataset?.expected?.trim())
  );
}
