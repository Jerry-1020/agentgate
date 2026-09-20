export type TaskStatus = '等待中' | '运行中' | '已完成' | '已失败' | '已终止';
export type TargetType = 'Agent' | 'Skill';

export interface VersionedTarget {
  id: string;
  name: string;
  type: TargetType;
  version: string;
  description: string;
  updatedAt: string;
}
export interface Dataset {
  id: string;
  name: string;
  version: string;
  cases: number;
  source: string;
  scope: string;
  updatedAt: string;
}
export interface Evaluator {
  id: string;
  name: string;
  version: string;
  kind: '规则' | 'LLM' | '复合';
  coverage: string;
  status: '已启用' | '已停用' | '草稿';
}
export interface EvalTask {
  id: string;
  name: string;
  target: VersionedTarget;
  dataset: Dataset;
  evaluator: Evaluator;
  status: TaskStatus;
  passRate: number | null;
  createdAt: string;
  config: string;
}
