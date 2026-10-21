import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import libCoverage from 'istanbul-lib-coverage';
import libReport from 'istanbul-lib-report';
import reports from 'istanbul-reports';
import sourceMaps from 'istanbul-lib-source-maps';
const directory = path.resolve('../runtime/summary-coverage');
const merged = libCoverage.createCoverageMap({});
for (const file of fs.readdirSync(path.join(directory, 'raw'))) {
  if (!file.endsWith('.json')) continue;
  for (const snapshot of JSON.parse(fs.readFileSync(path.join(directory, 'raw', file)))) merged.merge(snapshot);
}
const map = await sourceMaps.createSourceMapStore().transformCoverage(merged);
const context = libReport.createContext({ dir: directory, coverageMap: map });
for (const kind of ['json', 'html', 'text-summary']) reports.create(kind).execute(context);
const files = [
  'src/api/evaluation-summaries.ts', 'src/views/evaluation/utils/summary-query.ts',
  'src/views/evaluation/composables/use-summary-query.ts',
  'src/views/evaluation/components/OverviewMetrics.vue',
  'src/views/evaluation/components/TaskList.vue', 'src/views/evaluation/index.vue',
];
let failed = false;
for (const file of files) {
  const absolute = path.resolve(file);
  if (!map.files().includes(absolute)) { console.error(`Missing coverage: ${file}`); failed = true; continue; }
  const fc = map.fileCoverageFor(absolute), summary = fc.toSummary();
  let changed = new Set();
  let tracked = true;
  try { execFileSync('git', ['ls-files', '--error-unmatch', file], { stdio: 'ignore' }); }
  catch { tracked = false; }
  if (tracked) {
    const diff = execFileSync('git', ['diff', '--unified=0', 'HEAD', '--', file], { encoding: 'utf8' });
    for (const match of diff.matchAll(/^@@.*\+(\d+)(?:,(\d+))? @@/gm)) {
      const start = Number(match[1]), count = Number(match[2] ?? 1);
      for (let i = start; i < start + count; i++) changed.add(String(i));
    }
  } else changed = new Set(Object.keys(fc.getLineCoverage()));
  const changedCounts = Object.entries(fc.getLineCoverage()).filter(([line]) => changed.has(line));
  const changedPct = changedCounts.length ? 100 * changedCounts.filter(([,count]) => count > 0).length / changedCounts.length : 100;
  console.log(file, 'lines', summary.lines.pct, 'branches', summary.branches.pct, 'changed', changedPct.toFixed(2));
  if (summary.lines.pct < 80 || summary.branches.pct < 80 || changedPct < 80) failed = true;
}
if (failed) process.exitCode = 1;
