import type { DatasetVersion } from '../../datasets/types/index';

export type RunStatus = 'scheduled' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface EvaluationRun {
  id: string;
  status: RunStatus;
  manifest: {
    selected_case_ids?: string[] | null;
    primary_evaluator_ids: string[];
    evaluator_specs?: {
      id: string;
      name: string;
      kind: string;
      version: string;
      content_sha256: string;
    }[];
    target: {
      adapter_type?: string;
      invocation_config?: Record<string, unknown>;
      descriptor_sha256: string;
      display_name: string;
      ref: {
        source_id: string;
        target_type: string;
        external_target_id: string;
        external_version_id: string;
      };
    };
    dataset: DatasetVersion;
  };
  created_at: string;
  scheduled_for?: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface RunProgress {
  run_id: string;
  status: RunStatus;
  dataset_id: string;
  dataset_version: number;
  dataset_name: string;
  target_name: string;
  target_version: string;
  total_cases: number;
  completed_cases: number;
  progress: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error: string | null;
  queue_position: number | null;
}

export type RunStatusCounts = Record<RunStatus, number>;

export interface RunActivity {
  status_counts: RunStatusCounts;
  queued: RunProgress[];
  running: RunProgress[];
  recent: RunProgress[];
}
