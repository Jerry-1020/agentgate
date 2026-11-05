import { httpRequest } from '../utils/request';
import type { Report } from './evaluations';

export interface HistoricalScoreRow {
  level: 'overall' | 'kind' | 'evaluator' | 'case';
  key: string;
  case_id: string | null;
  baseline_score: number | null;
  candidate_score: number | null;
  baseline_outcome: string | null;
  candidate_outcome: string | null;
  comparable: boolean;
  reasons: string[];
  score_delta: number | null;
  change: 'improvement' | 'regression' | 'unchanged' | 'changed' | null;
}
export interface HistoricalComparison {
  baseline_run_id: string;
  candidate_run_id: string;
  baseline_gate: Report['release_gate'];
  candidate_gate: Report['release_gate'];
  gate_reasons: string[];
  score_rows: HistoricalScoreRow[];
  case_rows: HistoricalScoreRow[];
}
export interface HistoricalComparisonRequest {
  comparison_id: string;
  baseline_task_id: string;
  baseline_run_id: string;
  candidate_task_id: string;
  candidate_run_id: string;
}
export const createHistoricalComparison = (data: HistoricalComparisonRequest) =>
  httpRequest<{ id: string }>('/evaluation-tasks/history-comparisons', { method: 'POST', data });
export const readHistoricalComparison = (id: string) =>
  httpRequest<HistoricalComparison>(`/evaluation-tasks/${encodeURIComponent(id)}/comparison`);
