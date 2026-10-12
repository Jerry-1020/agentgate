import type { Report } from '../../../api/client';
import { sampleSummary } from './task-report';

export type AnnotationListRow = {
  key: string;
  taskId: string;
  taskName: string;
  name: string;
  score: number | null;
  badCase: boolean;
  status: string;
  evaluatedAt: string | null;
};
export type AnnotationListFilters = {
  taskId: string;
  name: string;
  status: string;
  scoreMin: string;
  scoreMax: string;
  from: string;
  to: string;
  badOnly: boolean;
};
export const emptyAnnotationFilters = (): AnnotationListFilters => ({
  taskId: '',
  name: '',
  status: '',
  scoreMin: '',
  scoreMax: '',
  from: '',
  to: '',
  badOnly: false,
});
export function annotationCaseScore(report: Report, caseId: string) {
  const results = report.results.filter((r) => r.case_id === caseId);
  const primary = report.run.manifest.primary_evaluator_ids;
  const summary = sampleSummary(results, primary);
  return {
    score: summary.score === null || summary.outcome === 'pending' ? null : summary.score * 100,
    badCase: results.some(
      (r) => primary.includes(r.evaluator_id) && ['fail', 'error', 'review'].includes(r.outcome),
    ),
  };
}
export function annotationFilterError(f: AnnotationListFilters): string {
  for (const value of [f.scoreMin, f.scoreMax]) {
    if (
      value !== '' &&
      (!Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 100)
    )
      return '综合分范围需在 0—100 之间。';
  }
  if (f.scoreMin !== '' && f.scoreMax !== '' && Number(f.scoreMin) > Number(f.scoreMax))
    return '最低综合分不能高于最高综合分。';
  if (f.from && f.to && f.from > f.to) return '开始日期不能晚于结束日期。';
  return '';
}
export function matchesAnnotationFilters(row: AnnotationListRow, f: AnnotationListFilters) {
  if (annotationFilterError(f)) return false;
  if (f.taskId && row.taskId !== f.taskId) return false;
  if (f.name && !row.name.toLowerCase().includes(f.name.trim().toLowerCase())) return false;
  if (f.status && row.status !== f.status) return false;
  if (f.badOnly && !row.badCase) return false;
  if (f.scoreMin !== '' && (row.score === null || row.score < Number(f.scoreMin))) return false;
  if (f.scoreMax !== '' && (row.score === null || row.score > Number(f.scoreMax))) return false;
  if (f.from || f.to) {
    const time = row.evaluatedAt ? Date.parse(row.evaluatedAt) : NaN;
    if (!Number.isFinite(time)) return false;
    if (f.from && time < new Date(f.from + 'T00:00:00').getTime()) return false;
    if (f.to && time > new Date(f.to + 'T23:59:59.999').getTime()) return false;
  }
  return true;
}
