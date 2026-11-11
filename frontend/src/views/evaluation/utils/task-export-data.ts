import type { EvaluationCase, Report, Trace } from '../../../api/client';
import type { Comparison, RunSamples, SampleResourceUsage } from '../../../api/evaluations';
import type { HistoricalComparison } from '../../../api/historical-comparisons';
import { ApiError, httpRequest } from '../../../utils/request';

export type TaskExportKind = 'full' | 'ab_metrics' | 'ab_items' | 'ab_conditions';

export interface TaskExportRequest {
  runIds: string[];
  taskId?: string;
  taskName?: string;
  runSide?: 'A任务' | 'B任务';
  historyTaskId?: string;
  kind: TaskExportKind;
}
export interface ExportRun {
  side: string;
  samples: RunSamples;
  report: Report | null;
  cases: EvaluationCase[];
  resources: SampleResourceUsage[];
  traces: Record<string, Trace>;
  warnings: { caseId?: string; message: string }[];
}
export interface TaskExportData {
  request: TaskExportRequest;
  exportedAt: string;
  runs: ExportRun[];
  comparison: Comparison | null;
  historical: HistoricalComparison | null;
}
export type ExportRead = <T>(path: string, signal: AbortSignal) => Promise<T>;
const read: ExportRead = (path, signal) => httpRequest(path, { method: 'GET', signal });
const terminal = new Set(['completed', 'failed', 'cancelled']);
export function checkExportCancelled(signal: AbortSignal) {
  if (signal.aborted) throw new Error('已取消导出');
}
function optionalReadError(error: unknown, signal: AbortSignal) {
  checkExportCancelled(signal);
  if (error instanceof ApiError && [401, 403].includes(error.status)) throw error;
}
export async function loadTaskExport(
  request: TaskExportRequest,
  signal: AbortSignal,
  progress: (message: string) => void = () => {},
  get: ExportRead = read,
): Promise<TaskExportData> {
  if (
    request.runIds.length < 1 ||
    request.runIds.length > 2 ||
    new Set(request.runIds).size !== request.runIds.length
  )
    throw new Error('请选择一个单任务或一组 A/B 任务');
  if (request.kind === 'full' && request.runIds.length !== 1)
    throw new Error('完整结果导出需要选择一个任务');
  if (request.kind.startsWith('ab_') && request.runIds.length !== 2)
    throw new Error('A/B 对比导出需要两个任务结果');
  const data: TaskExportData = {
    request: structuredClone(request),
    exportedAt: new Date().toISOString(),
    runs: [],
    comparison: null,
    historical: null,
  };
  for (const [index, id] of request.runIds.entries()) {
    checkExportCancelled(signal);
    progress('正在读取任务结果…');
    const path = `/runs/${encodeURIComponent(id)}`;
    let samples = await get<RunSamples>(path + '/samples', signal);
    if (samples.run.id !== id) throw new Error('运行记录不匹配，请刷新后重试');
    if (!terminal.has(samples.run.status)) throw new Error('请在任务完成、失败或取消后导出报告');
    const report = samples.run.status === 'completed' ? await get<Report>(path, signal) : null;
    if (report) {
      if (report.run.id !== id || report.run.status !== 'completed')
        throw new Error('任务结果已变化，请刷新后重试');
      samples = { run: report.run, results: report.results, complete: true };
    }
    const manifest = samples.run.manifest;
    const scope = manifest.selected_case_ids;
    const cases = manifest.dataset.cases.filter((c) => scope == null || scope.includes(c.id));
    const run: ExportRun = {
      side: request.runIds.length === 1 ? (request.runSide ?? '单任务') : index ? 'B任务' : 'A任务',
      samples,
      report,
      cases,
      resources: [],
      traces: {},
      warnings: [],
    };
    if (request.kind === 'full')
      try {
        const usage = await get<{ items: SampleResourceUsage[] }>(
          path + '/sample-resource-usage',
          signal,
        );
        if (!Array.isArray(usage.items)) throw new Error('资源统计格式不完整');
        run.resources = usage.items;
      } catch (error) {
        optionalReadError(error, signal);
        run.warnings.push({ message: '资源统计读取失败，Token 和耗时未导出；可重新导出重试。' });
      }
    data.runs.push(run);
  }
  if (!data.runs.some((r) => r.cases.length)) throw new Error('所选范围内没有可导出的样本');
  if (
    ['ab_metrics', 'ab_items'].includes(request.kind) &&
    data.runs.length === 2 &&
    data.runs.every((r) => r.report)
  ) {
    const [a, b] = request.runIds;
    if (request.historyTaskId)
      data.historical = await get<HistoricalComparison>(
        `/evaluation-tasks/${encodeURIComponent(request.historyTaskId)}/comparison`,
        signal,
      );
    else
      data.comparison = await get<Comparison>(
        '/run-comparisons?' + new URLSearchParams({ baseline_run_id: a, candidate_run_id: b }),
        signal,
      );
    const comparison = data.historical ?? data.comparison;
    if (comparison?.baseline_run_id !== a || comparison?.candidate_run_id !== b)
      throw new Error('对比结果与所选 A/B 任务不匹配，请刷新后重试');
  }
  if (request.kind === 'full') {
    const jobs = data.runs.flatMap((run) => run.cases.map((c) => ({ run, caseId: c.id })));
    let next = 0,
      done = 0;
    await Promise.all(
      Array.from({ length: Math.min(3, jobs.length) }, async () => {
        while (next < jobs.length) {
          checkExportCancelled(signal);
          const { run, caseId } = jobs[next++];
          try {
            const trace = await get<Trace>(
              `/runs/${encodeURIComponent(run.samples.run.id)}/traces/${encodeURIComponent(caseId)}`,
              signal,
            );
            if (trace.case_id !== caseId) throw new Error('轨迹样本不匹配');
            run.traces[caseId] = trace;
          } catch (error) {
            optionalReadError(error, signal);
            run.warnings.push({
              caseId,
              message:
                error instanceof ApiError && error.status === 404
                  ? '未保存执行轨迹，实际输入输出未记录。'
                  : '执行轨迹读取失败，实际输入输出未导出；可重新导出重试。',
            });
          }
          progress(`正在读取样本对话 ${++done} / ${jobs.length}`);
        }
      }),
    );
  }
  checkExportCancelled(signal);
  return data;
}
