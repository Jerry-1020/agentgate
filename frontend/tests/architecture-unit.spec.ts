import { test, expect } from '@playwright/test';
import { createPinia } from 'pinia';
import { http } from '../src/utils/request';
import { request as evaluationRequest } from '../src/api/evaluations';
import { useTaskLinksStore } from '../src/stores/modules/task-links';
import { useSettingsPreviewStore } from '../src/stores/modules/model-preview';

test('shared task links are owned by Pinia and remain isolated between app instances', async () => {
  const previous = http.defaults.adapter;
  try {
    http.defaults.adapter = async config => ({
      data: [{ id: 'task-a', kind: 'single', run_ids: ['run-a'], static_report_ids: [] }],
      status: 200, statusText: 'OK', headers: {}, config,
    });
    const first = useTaskLinksStore(createPinia());
    const second = useTaskLinksStore(createPinia());
    await first.refreshTaskLinks();
    expect(first.readTaskLinks()[0].runIds).toEqual(['run-a']);
    expect(second.readTaskLinks()).toEqual([]);
  } finally { http.defaults.adapter = previous; }
});

test('model preview state uses Pinia without sharing mutable seed data across apps', () => {
  const first = useSettingsPreviewStore(createPinia());
  const second = useSettingsPreviewStore(createPinia());
  first.catalog.teams[0].name = 'changed';
  expect(second.catalog.teams[0].name).not.toBe('changed');
});


test('single task static report association survives reload with its exact descriptor', async () => {
  const previous = http.defaults.adapter;
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { dispatchEvent: () => true } });
  const stored = { id: 'task-a', name: 'Loan task', kind: 'single', run_ids: ['run-a'], static_report_ids: [] as string[] };
  try {
    http.defaults.adapter = async config => {
      let data: unknown;
      if (config.method === 'put') {
        Object.assign(stored, JSON.parse(config.data));
        data = stored;
      } else if (config.url === '/evaluation-tasks') data = [stored];
      else if (config.url === '/skill-analysis/reports/report-a') data = { report: { target_ref: { external_version_id: 'v1' }, target_descriptor_sha256: 'exact-target-hash' } };
      else throw Error('Unexpected request ' + config.url);
      return { data, status: 200, statusText: 'OK', headers: {}, config };
    };
    const store = useTaskLinksStore(createPinia());
    await store.saveTaskLink({ id: 'task-a', name: 'Loan task', kind: 'single', runIds: ['run-a'], staticReports: [{ version: 'v1', descriptorHash: 'exact-target-hash', reportId: 'report-a' }] });
    const reloaded = useTaskLinksStore(createPinia());
    await reloaded.refreshTaskLinks();
    expect(reloaded.readTaskLinks()).toEqual([{ id: 'task-a', name: 'Loan task', kind: 'single', runIds: ['run-a'], staticReports: [{ version: 'v1', descriptorHash: 'exact-target-hash', reportId: 'report-a' }] }]);
  } finally {
    http.defaults.adapter = previous;
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

// Render the actual SFC without a browser; verify public markup for each graph shape.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { parse, compileScript } from '@vue/compiler-sfc';
import ts from 'typescript';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
const localRequire = createRequire(import.meta.url);
const structureFile = new URL('../src/views/evaluation/components/TargetStructure.vue', import.meta.url);
const structureScript = compileScript(parse(readFileSync(structureFile, 'utf8')).descriptor,
  { id: 'structure-test', inlineTemplate: true }).content;
const structureCode = ts.transpileModule(structureScript,
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const structureModule = { exports: {} as { default?: any } };
new Function('require', 'module', 'exports', structureCode)((id: string) =>
  id.includes('/api/evaluations') ? { request: () => { throw Error('unexpected network'); } } : localRequire(id),
structureModule, structureModule.exports);
async function renderStructure(topology: object) {
  return renderToString(createSSRApp(structureModule.exports.default, {
    descriptor: { content_sha256: 'snapshot', metadata: { topology } }, hideSource: true,
  }));
}
const workflowTopology = {
  composition: '工作流 · 条件分支',
  nodes: [
    { id: 'extract', kind: 'workflow', label: '信息提取', description: '提取', node_type: 'llm' },
    { id: 'act', kind: 'workflow', label: '执行动作', description: '办理', node_type: 'tool' },
    { id: 'end', kind: 'workflow', label: '生成回复', description: '回答', node_type: 'llm' },
  ],
  edges: [
    { source: 'extract', target: 'act', relation: '资料齐全' },
    { source: 'extract', target: 'end', relation: '缺资料' },
    { source: 'act', target: 'end', relation: '下一步' },
  ],
};
test('workflow graph renders directed flow, conditions and execution node types', async () => {
  const html = await renderStructure(workflowTopology);
  expect(html).toContain('工作流 · 条件分支');
  expect(html).toContain('资料齐全');
  expect(html).toContain('缺资料');
  expect(html).toContain('marker-end="url(#structure-arrow-');
  expect(html).toContain('流程节点 信息提取');
  expect(html).toContain('node-llm');
  expect(html).toContain('node-tool');
  expect(html).not.toContain('无法分层');
});
test('base and skill topology retain their own layers without invented workflow', async () => {
  for (const hasSkill of [false, true]) {
    const html = await renderStructure({
      composition: hasSkill ? 'Agent → Skill → Tool' : 'Agent → Tool',
      nodes: [{ id: 'a', kind: 'agent', label: 'Agent', description: 'Agent' },
        ...(hasSkill ? [{ id: 's', kind: 'skill', label: '贷款申请', description: '申请' }] : []),
        { id: 't', kind: 'tool', label: 'submit_application', description: '提交' }],
      edges: [{ source: 'a', target: hasSkill ? 's' : 't', relation: 'uses' },
        ...(hasSkill ? [{ source: 's', target: 't', relation: 'binds' }] : [])],
    });
    expect(html).toContain(hasSkill ? 'Agent → Skill → Tool' : 'Agent → Tool');
    expect(html).not.toContain('workflow-explainer');
    expect(html).not.toContain('流程节点');
    expect(html.includes('node-skill')).toBe(hasSkill);
  }
});
test('cyclic workflow renders all nodes without an invented execution order', async () => {
  const html = await renderStructure({ ...workflowTopology, edges: [
    ...workflowTopology.edges, { source: 'end', target: 'extract', relation: '重试' },
  ] });
  expect(html).toContain('此图含循环或无法分层的连线');
  for (const node of workflowTopology.nodes) expect(html).toContain('流程节点 ' + node.label);
  expect(html).not.toContain('NaN');
});


test('explicit evaluator versions respect local disabled preferences before POST', async () => {
  const previous = http.defaults.adapter;
  const storage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  let calls = 0;
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: () => JSON.stringify(['final-output']),
  } });
  try {
    http.defaults.adapter = async config => {
      calls++;
      return { data: {}, status: 202, statusText: 'Accepted', headers: {}, config };
    };
    for (const path of ['/evaluations', '/bank-evaluations', '/stability-experiments']) {
      await expect(evaluationRequest(path, 'POST', {
        evaluator_refs: [{ evaluator_id: 'final-output', evaluator_version: '1' }],
      })).rejects.toThrow('已在当前浏览器禁用');
      expect(calls).toBe(0);
    }
    await evaluationRequest('/evaluations', 'POST', {
      evaluator_refs: [{ evaluator_id: 'enabled-custom', evaluator_version: '1' }],
    });
    expect(calls).toBe(1);
  } finally {
    http.defaults.adapter = previous;
    if (storage) Object.defineProperty(globalThis, 'localStorage', storage);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});
