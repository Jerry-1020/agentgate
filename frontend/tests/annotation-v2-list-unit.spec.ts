import { test, expect } from '@playwright/test';
import type { Report } from '../src/api/client';
import {
  annotationCaseScore,
  annotationFilterError,
  emptyAnnotationFilters,
  matchesAnnotationFilters,
  type AnnotationListRow,
} from '../src/views/evaluation/utils/annotation-v2-list';
const row: AnnotationListRow = {
  key: 'run/case',
  taskId: 'task',
  taskName: '任务 A',
  name: '会话 A',
  score: 60,
  badCase: true,
  status: '待标注',
  evaluatedAt: '2026-09-26T23:59:59.999+08:00',
};
test('score boundaries are inclusive, zero remains valid and missing is not zero', () => {
  const f = { ...emptyAnnotationFilters(), scoreMin: '60', scoreMax: '60' };
  expect(matchesAnnotationFilters(row, f)).toBe(true);
  expect(matchesAnnotationFilters({ ...row, score: 59.99 }, f)).toBe(false);
  expect(
    matchesAnnotationFilters({ ...row, score: 0 }, { ...f, scoreMin: '0', scoreMax: '0' }),
  ).toBe(true);
  expect(
    matchesAnnotationFilters({ ...row, score: null }, { ...f, scoreMin: '0', scoreMax: '100' }),
  ).toBe(false);
  expect(matchesAnnotationFilters({ ...row, score: null }, emptyAnnotationFilters())).toBe(true);
});
test('all column filters compose and exemption changes membership', () => {
  const f = {
    ...emptyAnnotationFilters(),
    taskId: 'task',
    name: '会话',
    status: '待标注',
    badOnly: true,
  };
  expect(matchesAnnotationFilters(row, f)).toBe(true);
  for (const change of [
    { taskId: 'other' },
    { name: '无匹配' },
    { status: '免标注' },
    { badCase: false },
  ])
    expect(matchesAnnotationFilters({ ...row, ...change }, f)).toBe(false);
});
test('date filters include the full local day; absent dates never match a range', () => {
  const local = { ...row, evaluatedAt: new Date(2026, 8, 26, 23, 59, 59, 999).toISOString() };
  const f = { ...emptyAnnotationFilters(), from: '2026-09-26', to: '2026-09-26' };
  expect(matchesAnnotationFilters(local, f)).toBe(true);
  expect(
    matchesAnnotationFilters({ ...local, evaluatedAt: new Date(2026, 8, 27).toISOString() }, f),
  ).toBe(false);
  expect(matchesAnnotationFilters({ ...local, evaluatedAt: null }, f)).toBe(false);
});
test('invalid score and date ranges are explained and cannot match rows', () => {
  for (const patch of [
    { scoreMin: '90', scoreMax: '10' },
    { scoreMin: '-1' },
    { scoreMax: '101' },
    { scoreMin: 'abc' },
    { from: '2026-09-27', to: '2026-09-26' },
  ]) {
    const f = { ...emptyAnnotationFilters(), ...patch };
    expect(annotationFilterError(f)).not.toBe('');
    expect(matchesAnnotationFilters(row, f)).toBe(false);
  }
});
test('Bad Case follows primary evaluator outcomes, never a guessed score threshold', () => {
  const report = {
    run: { manifest: { primary_evaluator_ids: ['a', 'b'] } },
    results: [
      { case_id: 'c', evaluator_id: 'a', score: 0.8, outcome: 'pass' },
      { case_id: 'c', evaluator_id: 'b', score: 0.6, outcome: 'pass' },
      { case_id: 'c', evaluator_id: 'dependency', score: 0, outcome: 'fail' },
      { case_id: 'other', evaluator_id: 'a', score: 0, outcome: 'fail' },
    ],
  } as Report;
  expect(annotationCaseScore(report, 'c')).toEqual({ score: 70, badCase: false });
  report.results[1].outcome = 'review';
  expect(annotationCaseScore(report, 'c').badCase).toBe(true);
  report.results[1].outcome = 'error';
  report.results[1].score = null;
  expect(annotationCaseScore(report, 'c')).toEqual({ score: 80, badCase: true });
  expect(annotationCaseScore(report, 'missing')).toEqual({ score: null, badCase: false });
  report.results = report.results.slice(0, 1);
  expect(annotationCaseScore(report, 'c').score).toBeNull();
});
