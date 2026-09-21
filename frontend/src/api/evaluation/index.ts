import { httpRequest } from '../../utils/request';

export type EngineHealth = { status?: string; service?: string };
export type EvaluationTarget = {
  id: string;
  name: string;
  type: 'Agent' | 'Skill';
  version: string;
  description: string;
  updatedAt: string;
};
export type EngineEvaluator = {
  id: string;
  name: string;
  version: string;
  kind: string;
  dimension: string;
  metric: string;
  severity: string;
};
export type EvaluatorSource = {
  evaluator_id: string;
  implementation_id: string;
  source_path: string;
  source: string;
};

export const getEngineHealth = (): Promise<EngineHealth> => httpRequest('/evaluation/health');
export const listEvaluationTargets = (): Promise<EvaluationTarget[]> =>
  httpRequest('/evaluation/targets');
export const listEngineEvaluators = (): Promise<EngineEvaluator[]> =>
  httpRequest('/evaluation/evaluators');
export const getEvaluatorSource = (evaluatorId: string): Promise<EvaluatorSource> =>
  httpRequest(`/evaluation/evaluators/${encodeURIComponent(evaluatorId)}/source`);
export const listEngineDatasets = (): Promise<unknown> => httpRequest('/evaluation/datasets');
export const listEngineRuns = (): Promise<unknown> => httpRequest('/evaluation/runs');
export const launchEngineRun = (payload: {
  version: string;
  dataset_id: string;
  dataset_version: number;
  evaluator_ids?: string[];
}): Promise<unknown> => httpRequest('/evaluation/runs', { method: 'POST', data: payload });
