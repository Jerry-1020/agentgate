import { test, expect } from '@playwright/test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join, dirname } from 'node:path';
import { spawnSync } from 'node:child_process';

const script = resolve('scripts/check-summary-coverage.mjs');
const files = [
  'src/api/evaluation-summaries.ts', 'src/views/evaluation/utils/summary-query.ts',
  'src/views/evaluation/composables/use-summary-query.ts',
  'src/views/evaluation/components/OverviewMetrics.vue',
  'src/views/evaluation/components/TaskList.vue', 'src/views/evaluation/index.vue',
];
for (const scenario of ['pass', 'missing', 'branch', 'lines']) {
  test(`coverage gate rejects incomplete evidence: ${scenario}`, () => {
    const root = realpathSync(mkdtempSync(join(tmpdir(), 'summary-coverage-gate-')));
    try {
      const frontend = join(root, 'frontend');
      const raw = join(root, 'runtime/summary-coverage/raw');
      mkdirSync(raw, { recursive: true });
      const snapshot: Record<string, unknown> = {};
      for (const [index, file] of files.entries()) {
        const path = join(frontend, file);
        mkdirSync(dirname(path), { recursive: true });
        writeFileSync(path, 'export const answer = true ? 1 : 0;\n');
        if (scenario === 'missing' && index === 0) continue;
        const location = { start: { line: 1, column: 0 }, end: { line: 1, column: 34 } };
        snapshot[path] = { path, statementMap: { '0': location }, fnMap: {},
          branchMap: { '0': { type: 'cond-expr', line: 1, loc: location, locations: [location, location] } },
          s: { '0': scenario === 'lines' && index === 0 ? 0 : 1 }, f: {},
          b: { '0': scenario === 'branch' && index === 0 ? [1, 0] : [1, 1] } };
      }
      writeFileSync(join(raw, 'test.json'), JSON.stringify([snapshot]));
      const result = spawnSync(process.execPath, [script], { cwd: frontend, encoding: 'utf8', env: { ...process.env, FORCE_COLOR: '0' } });
      expect(result.error).toBeUndefined();
      expect(result.status, result.stdout + result.stderr).toBe(scenario === 'pass' ? 0 : 1);
      if (scenario === 'missing') expect(result.stderr).toContain('Missing coverage');
      if (scenario === 'branch') expect(result.stdout).toContain('branches 50');
      if (scenario === 'lines') expect(result.stdout).toContain('changed 0.00');
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
}
