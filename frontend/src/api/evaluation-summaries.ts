import { httpRequest } from '../utils/request';
export type TaskKind = 'single' | 'ab' | 'stability';
export type RunState = 'pending' | 'scheduled' | 'running' | 'completed' | 'failed' | 'cancelled';
export interface OverviewSummary {
  task_count: number;
  pending_summary_task_count: number;
  pending_dataset_count: number;
  average_score: number | null;
  scored_run_count: number;
  completed_sample_count: number;
  dataset_count: number;
  dataset_sample_count: number;
}
export interface RunListSummary {
  run_id: string;
  status: RunState;
  summary_pending: boolean;
  target_name: string | null;
  target_version: string | null;
  dataset_name: string | null;
  dataset_version: number | null;
  evaluator_kinds: string[];
  scoring_mode: string | null;
  total_cases: number | null;
  completed_cases: number | null;
  overall_score: number | null;
  gate_reason: string | null;
}
export interface TaskListSummary {
  id: string;
  task_id: string | null;
  name: string;
  kind: TaskKind;
  created_at: string;
  status: RunState;
  summary_pending: boolean;
  total_cases: number | null;
  completed_cases: number | null;
  previous_run_count: number;
  runs: RunListSummary[];
}
export interface TaskSummaryPage {
  items: TaskListSummary[];
  total: number;
  page: number;
  page_size: number;
}
export interface SummaryQuery {
  start_at?: string;
  end_at?: string;
}
export interface TaskSummaryQuery extends SummaryQuery {
  page: number;
  page_size: number;
  keyword?: string;
  status?: RunState;
  kind?: TaskKind;
}
export interface TaskAction {
  runId: string;
  taskId: string | null;
  action: 'cancel' | 'rerun';
}
export const getOverviewSummary = (params: SummaryQuery, signal?: AbortSignal) =>
  httpRequest<OverviewSummary>('/evaluation-overview/summary', { params, signal });
export const getTaskSummaries = (params: TaskSummaryQuery, signal?: AbortSignal) =>
  httpRequest<TaskSummaryPage>('/evaluation-task-summaries', { params, signal });
