import request from '../../utils/request'

export type EngineHealth = { status?: string; service?: string }
export type EvaluationTarget = { id: string; name: string; type: 'Agent' | 'Skill'; version: string; description: string; updatedAt: string }
export type EngineEvaluator = { id: string; name: string; version: string; kind: string; dimension: string; metric: string; severity: string }
export type EvaluatorSource = { evaluator_id: string; implementation_id: string; source_path: string; source: string }

export const getEngineHealth = () => request.get<never, EngineHealth>('/evaluation/health')
export const listEvaluationTargets = () => request.get<never, EvaluationTarget[]>('/evaluation/targets')
export const listEngineEvaluators = () => request.get<never, EngineEvaluator[]>('/evaluation/evaluators')
export const getEvaluatorSource = (evaluatorId: string) => request.get<never, EvaluatorSource>(`/evaluation/evaluators/${evaluatorId}/source`)
export const listEngineDatasets = () => request.get('/evaluation/datasets')
export const listEngineRuns = () => request.get('/evaluation/runs')
export const launchEngineRun = (payload: { version: string; dataset_id: string; dataset_version: number; evaluator_ids?: string[] }) => request.post('/evaluation/runs', payload)
