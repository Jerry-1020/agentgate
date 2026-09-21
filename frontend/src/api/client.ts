import { httpRequest } from '../utils/request';
export { ApiError } from '../utils/request';
import type { DatasetSummary, DatasetVersion, EvaluationCase } from '../views/datasets/types/index';
import type { EvaluationRun } from '../views/evaluation/types/run';

export interface Version {
  id: string;
  label: string;
}
export type DatasetOption = DatasetSummary;
export interface EvaluatorOption {
  id: string;
  name: string;
  kind: 'rule' | 'llm_judge' | 'hybrid';
  version: string;
  dimension: string;
  metric: string;
  severity: 'standard' | 'blocking';
  implementation_id: string;
  implementation_version: string;
  config: Record<string, unknown>;
}
export type Outcome = 'pass' | 'fail' | 'review' | 'not_applicable' | 'error';
export interface CheckResult {
  id: string;
  name: string;
  turn_id: string | null;
  expectation_id: string | null;
  outcome: Outcome;
  score: number | null;
  reason: string;
  expected: unknown;
  actual: unknown;
  actual_missing: boolean;
  span_ids: string[];
  failure_stage: string | null;
  failure_sequence: number | null;
  failure_span_id: string | null;
}
export interface EvaluationResult {
  id?: string;
  trace_id: string;
  case_id: string;
  evaluator_id: string;
  evaluator_name: string;
  evaluator_version?: string;
  evaluator_kind: string;
  dimension: string;
  metric: string;
  severity: 'standard' | 'blocking';
  outcome: Outcome;
  score: number | null;
  reason: string;
  primary_failure_stage?: string;
  checks: CheckResult[];
}
export type ReleaseGateReason =
  | 'threshold_met'
  | 'score_below_threshold'
  | 'missing_results'
  | 'evaluator_error'
  | 'blocking_failure'
  | 'review_required'
  | 'no_applicable_results';
export interface ReleaseGate {
  outcome: 'pass' | 'fail';
  missing_results: [string, string][];
  score: number | null;
  minimum_score: number;
  reason_code: ReleaseGateReason;
}
export interface Metric {
  key: string;
  level: 'overall' | 'kind' | 'dimension' | 'metric';
  score: number | null;
  passed: number;
  failed: number;
  reviewed: number;
  not_applicable: number;
  errors: number;
  applicable: number;
  total: number;
}
export interface Report {
  run: EvaluationRun;
  results: EvaluationResult[];
  release_gate: ReleaseGate;
  metrics: Metric[];
}
export interface TraceOutcome {
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  state: Record<string, unknown>;
}
export interface Trace {
  trace_id: string;
  case_id: string;
  spans: {
    span_id: string;
    name: string;
    operation_type: string;
    sequence: number;
    attributes: Record<string, unknown>;
  }[];
  turn_outcomes: Record<string, TraceOutcome>;
  final_state: Record<string, unknown>;
  final_output: Record<string, unknown>;
}
export interface Overview {
  total_runs: number;
  completed_runs: number;
  case_count: number;
  latest: Report | null;
}

export const request = async <T>(url: string, init?: RequestInit): Promise<T> => {
  return httpRequest<T>(url, {
    method: init?.method,
    data: init?.body,
    headers: Object.fromEntries(new Headers(init?.headers).entries()),
    signal: init?.signal ?? undefined,
  });
};

export const api = {
  overview: () => request<Overview>('/api/overview'),
  versions: () => request<Version[]>('/api/versions'),
  datasets: () => request<DatasetSummary[]>('/api/datasets'),
  evaluators: () => request<EvaluatorOption[]>('/api/evaluators'),
  report: (id: string) => request<Report>(`/api/runs/${id}`),
  trace: (runId: string, caseId: string) => request<Trace>(`/api/runs/${runId}/traces/${caseId}`),
};

export type { DatasetSummary, DatasetVersion, EvaluationCase };
