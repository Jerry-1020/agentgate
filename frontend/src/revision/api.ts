import {applyEvaluatorPreference,assertLocallyEnabled} from './evaluator-preferences'
import type { Report, Trace } from '../upstream/api/client'
import type { DatasetSummary } from '../upstream/types/dataset'
import type { EvaluationRun, RunProgress } from '../upstream/types/run'
export type { Report, Trace, DatasetSummary, EvaluationRun, RunProgress }
export type Kind = 'rule' | 'llm_judge' | 'hybrid'
export interface EvaluatorSummary {
  id: string; name: string; description: string; kind: Kind; source: string;
  enabled: boolean; latest_version: string | null; has_draft: boolean;
  dimension: string; metric: string; implementation_id: string; implementation_version: string;
}
export interface Definition {
  kind: Kind; dimension: string; metric: string; severity: string;
  implementation_id: string; implementation_version: string; config: Record<string, unknown>;
  children: { evaluator_id: string; evaluator_version: string; weight: number | null }[];
  combination: string | null; version?: string; content_sha256?: string;
}
export interface EvaluatorDetail { evaluator: EvaluatorSummary; latest: Definition | null; draft: Definition | null }
export interface Overview { total_runs: number; completed_runs: number; running_runs: number; pending_runs: number; failed_runs: number; cancelled_runs: number; dataset_count: number; case_count: number }
export interface RunSamples { run: Report['run']; results: Report['results']; complete: boolean }
export interface Comparison {
 baseline_run_id: string; candidate_run_id: string; overall_score_delta: number | null;
 metric_deltas: { level: string; key: string; baseline: {score: number|null}; candidate: {score: number|null}; score_delta: number|null }[];
 case_deltas: {case_id:string; evaluator_id:string; baseline_outcome:string; candidate_outcome:string; change:string}[];
}
export async function request<T>(path: string, method = 'GET', body?: unknown, timeoutMs = 30000): Promise<T> {
  if(method==='POST'){
    if(path==='/evaluations')assertLocallyEnabled((body as {evaluator_ids?:string[]})?.evaluator_ids??[])
    if(path==='/run-comparisons')assertLocallyEnabled(((body as {evaluators?:{id:string}[]})?.evaluators??[]).map(e=>e.id))
    if(/^\/runs\/[^/]+\/rerun$/.test(path)){const manifest=await request<{primary_evaluator_ids:string[]}>(path.replace(/\/rerun$/,'/manifest'));assertLocallyEnabled(manifest.primary_evaluator_ids)}
  }
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch('/api' + path, { method, signal: controller.signal,
      headers: body === undefined ? {} : {'Content-Type':'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body) })
    const data = response.status === 204 ? undefined : await response.json().catch(() => null)
    if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail ?? `服务响应 HTTP ${response.status}`))
    return data as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时，请刷新查询状态后再决定是否重试。')
    throw error
  } finally { window.clearTimeout(timer) }
}
export const api = {
  overview: () => request<Overview>('/overview'),
  runs: () => request<EvaluationRun[]>('/runs?limit=200'),
  datasets: () => request<DatasetSummary[]>('/datasets'),
  evaluators: () => request<EvaluatorSummary[]>('/evaluators?include_disabled=true').then(items=>items.map(applyEvaluatorPreference)),
  evaluator: (id:string) => request<EvaluatorDetail>(`/evaluators/${encodeURIComponent(id)}`).then(detail=>({...detail,evaluator:applyEvaluatorPreference(detail.evaluator)})),
  versions: () => request<{id:string;label:string}[]>('/versions'),
  report: (id:string) => request<Report>(`/runs/${encodeURIComponent(id)}`),
  samples: (id:string) => request<RunSamples>(`/runs/${encodeURIComponent(id)}/samples`),
  status: (id:string) => request<RunProgress>(`/runs/${encodeURIComponent(id)}/status`),
  trace: (id:string, caseId:string) => request<Trace>(`/runs/${encodeURIComponent(id)}/traces/${encodeURIComponent(caseId)}`),
}
export const kindLabel = (kind:string) => ({rule:'规则评估器',llm_judge:'LLM 评估器',hybrid:'复合评估器'}[kind] ?? kind)
export const statusLabel = (value:string) => ({pending:'排队中',running:'运行中',completed:'运行完成',failed:'执行异常',cancelled:'已取消',scheduled:'已预约',pass:'通过',fail:'未通过',review:'待复核',not_applicable:'不适用',error:'评估异常'}[value] ?? value)
export const score = (value: number | null | undefined) => value == null ? '—' : (value * 100).toFixed(1)
export const pretty = (value:unknown) => JSON.stringify(value, null, 2)
export const metricLabel = (key:string) => ({overall:'综合得分',rule:'规则评估得分',llm_judge:'模型评估得分',hybrid:'复合评估得分',routing:'路由',tool_use:'工具使用',state:'状态',answer:'回答',safety:'策略合规',skill_routing_accuracy:'技能路由正确性',tool_coverage:'必需工具覆盖',forbidden_tool_compliance:'禁用工具合规',tool_argument_accuracy:'工具参数正确性',final_state_match:'最终状态匹配',final_output_match:'最终输出匹配',policy_compliance:'策略合规'} as Record<string,string>)[key]??key
