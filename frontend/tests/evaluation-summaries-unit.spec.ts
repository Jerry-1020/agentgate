import { test, expect } from '@playwright/test';
import { dayWindow, taskPath, hasActiveRuns, evaluatorStrategy } from '../src/views/evaluation/utils/summary-query';
test('calendar windows preserve local midnight and zero means unbounded', () => {
  const now = new Date(2026, 9, 21, 12);
  expect(dayWindow(1, now)).toEqual({ start_at: new Date(2026, 9, 21).toISOString() });
  expect(dayWindow(7, now)).toEqual({ start_at: new Date(2026, 9, 15).toISOString() });
  expect(dayWindow(0, now)).toEqual({});
});
test('row presentation preserves kinds, nullable task identity and running sides', () => {
  const row = { kind: 'single', task_id: 'task', runs: [{ run_id: 'run', status: 'completed' }] } as any;
  expect(taskPath(row)).toBe('tasks/task');
  expect(taskPath({ ...row, kind: 'stability', task_id: null })).toBe('stability/run');
  expect(hasActiveRuns([row])).toBe(false);
  for (const status of ['pending', 'scheduled', 'running']) expect(hasActiveRuns([{ ...row, runs: [{ status }] }])).toBe(true);
  expect(evaluatorStrategy(['rule', 'llm_judge', 'llm_group', 'hybrid'])).toBe('规则评估 + LLM 评估 + 复合评估');
});
