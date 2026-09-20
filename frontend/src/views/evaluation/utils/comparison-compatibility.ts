import type { EvaluationRun, Report } from '../../../api/evaluations';
import { sameJson } from './report-presentation';

type FrozenEvaluator = { id: string; name: string; version: string; content_sha256: string };
type FrozenManifest = EvaluationRun['manifest'] & {
  evaluator_specs?: FrozenEvaluator[];
  selected_case_ids?: string[] | null;
  metric_plan?: unknown;
  gate_spec?: unknown;
};
export type ComparisonIssue = { key: string; title: string; detail: string };
const manifest = (run: EvaluationRun) => run.manifest as FrozenManifest;
export function frozenEvaluators(run: EvaluationRun) {
  const m = manifest(run);
  return m.primary_evaluator_ids.map((id) => {
    const spec = m.evaluator_specs?.find((item) => item.id === id);
    return {
      id,
      version: spec?.version,
      hash: spec?.content_sha256,
      key: JSON.stringify([id, spec?.version ?? '']),
      label: (spec?.name ?? id) + (spec?.version ? ' · v' + spec.version : ' · 版本未记录'),
    };
  });
}

// Match the current backend comparison contract, including evaluator and case order.
export function comparisonIssues(a: EvaluationRun, b: EvaluationRun): ComparisonIssue[] {
  const issues: ComparisonIssue[] = [];
  const add = (key: string, title: string, detail: string) => issues.push({ key, title, detail });
  const x = manifest(a),
    y = manifest(b);
  if (a.id === b.id) add('same-run', '不能比较同一次运行', '请选择另一条已完成记录。');
  if (a.status !== 'completed' || b.status !== 'completed')
    add('status', '两侧任务尚未全部完成', '请等待运行完成后再比较。');
  const target = (m: FrozenManifest) => [
    m.target.ref.source_id,
    m.target.ref.target_type,
    m.target.ref.external_target_id,
  ];
  if (!sameJson(target(x), target(y)))
    add('target', '评测对象不同', '请选择同一智能体或 Skill 的两个运行记录，方案版本可以不同。');
  if (x.dataset.dataset_id !== y.dataset.dataset_id)
    add('dataset', '评测集不同', '请选择同一评测集、相同内容的发布版本。');
  else if (!x.dataset.content_sha256 || x.dataset.content_sha256 !== y.dataset.content_sha256)
    add('dataset-content', '评测集内容不同或快照缺失', '请选择相同内容的评测集版本。');
  const cases = (m: FrozenManifest) =>
    m.selected_case_ids ?? m.dataset.cases?.map((item) => item.id);
  if (!sameJson(cases(x), cases(y)))
    add(
      'cases',
      '执行用例或顺序不同',
      '全量运行与部分用例运行不能直接比较；两侧需要相同用例及顺序。',
    );
  const ae = frozenEvaluators(a),
    be = frozenEvaluators(b);
  if (ae.some((e) => !e.version || !e.hash) || be.some((e) => !e.version || !e.hash)) {
    add(
      'evaluators',
      '评估器快照不完整',
      '缺少本次运行使用的评估器版本或内容指纹，暂不能确认可比性。',
    );
  } else if (
    !sameJson(
      ae.map((e) => [e.id, e.version, e.hash]),
      be.map((e) => [e.id, e.version, e.hash]),
    )
  ) {
    const onlyA = ae.filter((e) => !be.some((other) => other.id === e.id)).map((e) => e.label);
    const onlyB = be.filter((e) => !ae.some((other) => other.id === e.id)).map((e) => e.label);
    const changed = ae
      .filter((e) =>
        be.some(
          (other) => other.id === e.id && (other.version !== e.version || other.hash !== e.hash),
        ),
      )
      .map((e) => e.label);
    const details = ['A 使用 ' + ae.length + ' 个，B 使用 ' + be.length + ' 个。'];
    if (onlyA.length) details.push('仅 A 包含：' + onlyA.join('、') + '。');
    if (onlyB.length) details.push('仅 B 包含：' + onlyB.join('、') + '。');
    if (changed.length) details.push('版本或定义不同：' + changed.join('、') + '。');
    if (!onlyA.length && !onlyB.length && !changed.length)
      details.push('评估器顺序不同，当前后端要求顺序一致。');
    add('evaluators', '评估器配置不一致', details.join(''));
  }
  if (!sameJson(x.metric_plan, y.metric_plan))
    add('metric-plan', '指标计算口径不同或未记录', '两侧需要使用相同的指标计划。');
  if (!sameJson(x.gate_spec, y.gate_spec))
    add('gate', '通过条件不同或未记录', '两侧需要使用相同的发布门禁配置。');
  return issues;
}

export function reportComparisonIssues(a: Report, b: Report): ComparisonIssue[] {
  const issues = comparisonIssues(a.run, b.run);
  const keys = (report: Report) =>
    report.metrics.map((item) => JSON.stringify([item.level, item.key])).sort();
  if (!sameJson(keys(a), keys(b)))
    issues.push({
      key: 'metrics',
      title: '报告指标范围不同',
      detail: '两份报告需要包含相同的指标维度与指标项。',
    });
  return issues;
}

export function comparisonErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const messages: Record<string, string> = {
    'reports use different primary Evaluators':
      '两侧使用的评估器、版本、定义或顺序不同，请重新选择配置一致的任务。',
    'reports reference different Agent or Skill targets':
      '两侧评测对象不同，请选择同一智能体或 Skill。',
    'reports reference different Datasets': '两侧评测集不同，请重新选择。',
    'reports use different Dataset content': '两侧评测集内容不同，请选择相同的发布版本。',
    'reports use different ordered Case identities': '两侧执行用例或顺序不同，请选择相同运行范围。',
    'reports use different Metric plans': '两侧指标计算口径不同，暂不能比较。',
    'reports use different release-gate specifications': '两侧通过条件不同，暂不能比较。',
    'reports contain different metric summaries': '两份报告包含的指标范围不同，暂不能比较。',
  };
  return (
    messages[raw] ??
    (/[\u4e00-\u9fff]/.test(raw) ? raw : '服务端未能完成对比，请重试或查看原始错误。')
  );
}
