import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

let server: ViteDevServer;
let baseURL: string;

const fixture = `<!doctype html><html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body><div id="app"></div><script type="module">
import {createApp,h,ref} from 'vue';
import Picker from '/src/views/evaluation/components/AgentTargetPicker.vue';
import '/node_modules/element-plus/dist/index.css';
const harness=window.picker={calls:[],events:[],pending:[],hold:null,fail:null,empty:null,versions:['1.0.0','1.1.0']};
const agent=(id,name,type,raw)=>({agentId:id,agentName:name,typeGroup:type,platformAgentType:raw,platformArrangeType:raw});
const catalog={
 getTeams:()=>[{teamId:'team-a',teamName:'信贷团队'},{teamId:'team-b',teamName:'服务团队'}],
 getAgents:({teamId})=>teamId==='team-a'?[agent('base-a','基础助手','base/workflow','base'),agent('workflow-a','工作流助手','base/workflow','workflow'),agent('claw-a','云虾助手','abcclaw','abcclaw'),agent('unknown','未知助手',null,'light')]:[agent('base-b','服务助手','base/workflow','base')],
 getBranches:()=>[{branchId:'root',branchName:'主分支',children:[{branchId:'child',branchName:'子分支',children:[{branchId:'leaf',branchName:'叶分支',children:[]}]}]}],
 getAgentVersions:()=>harness.versions.map(agentVersion=>({agentVersion,status:'published'})),
 getBranchVersions:({branchId})=>[{agentVersion:branchId+'-v1',status:'test'}],
};
const directory=Object.fromEntries(Object.entries(catalog).map(([name,handler])=>[name,async input=>{
 harness.calls.push({name,input});
 const result=harness.empty===name?[]:handler(input);
 const failed=harness.fail===name;
 if(harness.hold===name)await new Promise((resolve,reject)=>harness.pending.push({resolve,reject}));
 if(failed)throw {status:403,message:'Authorization: Bearer '+input.token};
 return result;
}]));
createApp({setup(){const picker=ref(null),disabled=ref(false),visible=ref(true);harness.lock=value=>disabled.value=value;harness.unmount=()=>visible.value=false;harness.read=()=>picker.value?.readSubmissionSelection()??null;
return()=>h('main',{style:'max-width:760px;padding:16px;font:14px system-ui;margin:auto'},[visible.value?h(Picker,{ref:picker,directory,disabled:disabled.value,onSelectionChange:value=>harness.events.push(value)}):null]);}}).mount('#app');
harness.ready=true;
</script></body></html>`;

test.beforeAll(async () => {
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    plugins: [
      vue(),
      {
        name: 'target-picker-test-page',
        configureServer(vite) {
          vite.middlewares.use('/__picker', async (_request, response, next) => {
            try {
              response.setHeader('Content-Type', 'text/html');
              response.end(await vite.transformIndexHtml('/__picker', fixture));
            } catch (error) {
              next(error);
            }
          });
        },
      },
    ],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw Error('Missing test server address');
  baseURL = `http://127.0.0.1:${address.port}/__picker`;
});
test.afterAll(async () => {
  await server?.close();
});
test.beforeEach(async ({ page }) => {
  await page.goto(baseURL);
  await page.waitForFunction(() => (window as any).picker?.ready);
});

async function choose(page: Page, label: string, option: string) {
  await page.getByRole('combobox', { name: label, exact: true }).press('Enter');
  await page.getByRole('option', { name: option, exact: true }).click();
  await expect(page.getByRole('option', { name: option, exact: true })).toBeHidden();
}
async function login(page: Page, token = 'test-token') {
  await page.getByLabel('请填写token', { exact: true }).fill(token);
  await page.getByRole('button', { name: '登录', exact: true }).click();
}
async function selectAgent(page: Page, group = 'base/workflow', agent = '基础助手 · base-a') {
  await login(page);
  await choose(page, '选择团队', '信贷团队 · team-a');
  await choose(page, '智能体类型', group);
  await choose(page, '选择智能体', agent);
}
const read = (page: Page) => page.evaluate(() => (window as any).picker.read());

test('token boundary, original read-only text, logout and submission locking', async ({ page }) => {
  const token = page.getByLabel('请填写token', { exact: true });
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: '选择团队', exact: true })).toBeDisabled();
  await token.fill('x'.repeat(513));
  await expect(token).toHaveValue('x'.repeat(512));
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(token).toHaveAttribute('readonly', '');
  await expect(token).toHaveValue('x'.repeat(512));
  await choose(page, '选择团队', '信贷团队 · team-a');
  expect(await page.evaluate(() => (window as any).picker.calls[0].input.token)).toBe(
    'x'.repeat(512),
  );
  await page.evaluate(() => (window as any).picker.lock(true));
  await expect(page.getByRole('button', { name: '取消登录' })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: '智能体类型' })).toBeDisabled();
  await page.evaluate(() => (window as any).picker.lock(false));
  await page.getByRole('button', { name: '取消登录' }).click();
  await expect(token).toHaveValue('');
  await expect(token).not.toHaveAttribute('readonly', '');
  expect(await read(page)).toBeNull();
});

test('reject malformed token without silently modifying it', async ({ page }) => {
  for (const value of [' token ', 'line\nbreak', 'Bearer secret']) {
    await login(page, value);
    await expect(page.getByRole('alert')).toContainText('原始 token');
    await expect(page.getByLabel('请填写token', { exact: true })).toHaveValue(value);
    await expect(page.getByRole('combobox', { name: '选择团队', exact: true })).toBeDisabled();
  }
  expect(await page.evaluate(() => (window as any).picker.calls)).toEqual([]);
});

for (const [name, id, rawType] of [
  ['基础助手', 'base-a', 'base'],
  ['工作流助手', 'workflow-a', 'workflow'],
]) {
  test(`${rawType} selects an exact version without branch and emits no token`, async ({
    page,
  }) => {
    await selectAgent(page, 'base/workflow', `${name} · ${id}`);
    await expect(page.getByRole('combobox', { name: 'branchId' })).toBeDisabled();
    expect(await read(page)).toBeNull();
    await choose(page, '智能体版本', '1.1.0 · published');
    expect(await read(page)).toMatchObject({
      token: 'test-token',
      target: {
        teamId: 'team-a',
        agentId: id,
        platformArrangeType: rawType,
        typeGroup: 'base/workflow',
        branchId: null,
        branchName: null,
        agentVersion: '1.1.0',
      },
    });
    const calls = await page.evaluate(() => (window as any).picker.calls);
    expect(calls.map((call: any) => call.name)).toEqual([
      'getTeams',
      'getAgents',
      'getAgentVersions',
    ]);
    expect(calls[2].input).toEqual({ token: 'test-token', agentId: id });
    expect(JSON.stringify(await page.evaluate(() => (window as any).picker.events))).not.toContain(
      'test-token',
    );
    await page.evaluate(() => {
      (window as any).picker.read().target.agentId = 'tampered';
      (window as any).picker.lock(true);
    });
    expect((await read(page)).target.agentId).toBe(id);
  });
}

test('abcclaw includes nested branch identity, queries branch versions and invalidates on branch change', async ({
  page,
}) => {
  await selectAgent(page, 'abcclaw', '云虾助手 · claw-a');
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  await choose(page, 'branchId', '↳ ↳ 叶分支 · leaf');
  await choose(page, '智能体版本', 'leaf-v1 · test');
  expect((await read(page)).target).toMatchObject({
    agentId: 'claw-a',
    branchId: 'leaf',
    agentVersion: 'leaf-v1',
  });
  expect(await page.evaluate(() => (window as any).picker.calls.at(-1))).toEqual({
    name: 'getBranchVersions',
    input: { token: 'test-token', agentId: 'claw-a', branchId: 'leaf' },
  });
  await choose(page, 'branchId', '主分支 · root');
  expect(await read(page)).toBeNull();
  await choose(page, '智能体版本', 'root-v1 · test');
  expect((await read(page)).target.branchId).toBe('root');
});

test('type, agent and team changes clear dependent selection without transient mixed targets', async ({
  page,
}) => {
  await selectAgent(page);
  await choose(page, '智能体版本', '1.0.0 · published');
  await page.evaluate(() => {
    (window as any).picker.events.length = 0;
  });
  await choose(page, '选择智能体', '工作流助手 · workflow-a');
  expect(await read(page)).toBeNull();
  const events = await page.evaluate(() => (window as any).picker.events);
  expect(events.filter((value: any) => value?.agentId === 'workflow-a')).toEqual([]);
  expect(events.at(-1)).toBeNull();
  await choose(page, '智能体版本', '1.0.0 · published');
  await choose(page, '智能体类型', 'abcclaw');
  expect(await read(page)).toBeNull();
  await expect(page.getByRole('combobox', { name: 'branchId' })).toBeDisabled();
  await choose(page, '选择团队', '服务团队 · team-b');
  await expect(page.getByRole('combobox', { name: '选择智能体', exact: true })).toBeDisabled();
  await choose(page, '智能体类型', 'base/workflow');
  await choose(page, '选择智能体', '服务助手 · base-b');
  await choose(page, '智能体版本', '1.0.0 · published');
  expect((await read(page)).target).toMatchObject({ teamId: 'team-b', agentId: 'base-b' });
});

test('mismatched and unknown types stay visible but cannot produce a target', async ({ page }) => {
  await selectAgent(page, 'base/workflow', '云虾助手 · claw-a');
  await expect(page.getByRole('alert')).toContainText('不一致');
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  await choose(page, '选择智能体', '未知助手 · unknown');
  await expect(page.getByRole('alert')).toContainText('暂不支持');
  expect(await read(page)).toBeNull();
});

test('refresh invalidates a removed version, error is sanitized and empty state allows retry', async ({
  page,
}) => {
  await selectAgent(page);
  await choose(page, '智能体版本', '1.0.0 · published');
  await page.evaluate(() => {
    (window as any).picker.versions = ['1.1.0'];
  });
  await page.getByRole('combobox', { name: '智能体版本' }).press('Enter');
  await expect(page.getByRole('option', { name: '1.1.0 · published', exact: true })).toBeVisible();
  expect(await read(page)).toBeNull();
  await page.keyboard.press('Escape');
  await page.evaluate(() => {
    (window as any).picker.fail = 'getAgentVersions';
  });
  await page.getByRole('combobox', { name: '智能体版本' }).press('Enter');
  await expect(page.getByRole('alert')).toContainText('无权访问');
  expect(await page.getByRole('alert').textContent()).not.toContain('test-token');
  await page.keyboard.press('Escape');
  await page.evaluate(() => {
    (window as any).picker.fail = null;
    (window as any).picker.empty = 'getAgentVersions';
  });
  await page.getByRole('button', { name: '重试智能体版本' }).click();
  await expect(page.getByRole('status').filter({ hasText: '暂无可选智能体版本' })).toBeVisible();
  await page.evaluate(() => {
    (window as any).picker.empty = null;
  });
  await choose(page, '智能体版本', '1.1.0 · published');
  expect((await read(page)).target.agentVersion).toBe('1.1.0');
});

test('late version response after team switch cannot populate the new context', async ({
  page,
}) => {
  await selectAgent(page);
  await page.evaluate(() => {
    (window as any).picker.hold = 'getAgentVersions';
  });
  await page.getByRole('combobox', { name: '智能体版本' }).press('Enter');
  await expect(page.getByRole('status').filter({ hasText: '正在加载智能体版本' })).toBeVisible();
  await page.keyboard.press('Escape');
  await choose(page, '选择团队', '服务团队 · team-b');
  await page.evaluate(() => {
    const h = (window as any).picker;
    h.hold = null;
    h.pending.shift().resolve();
  });
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  expect(await read(page)).toBeNull();
  await choose(page, '智能体类型', 'base/workflow');
  await choose(page, '选择智能体', '服务助手 · base-b');
  await choose(page, '智能体版本', '1.1.0 · published');
  expect((await read(page)).target.agentId).toBe('base-b');
});

test('logout rejects old success and failure responses across sessions, unmount clears parent selection', async ({
  page,
}) => {
  await login(page);
  await page.evaluate(() => {
    (window as any).picker.hold = 'getTeams';
  });
  await page.getByRole('combobox', { name: '选择团队', exact: true }).press('Enter');
  await page.waitForFunction(() => (window as any).picker.pending.length === 1);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '取消登录' }).click();
  await login(page, 'new-token');
  await page.getByRole('combobox', { name: '选择团队', exact: true }).press('Enter');
  await page.waitForFunction(() => (window as any).picker.pending.length === 2);
  await page.evaluate(() => {
    (window as any).picker.pending[0].reject({ status: 403, message: 'old-secret' });
  });
  await expect(page.getByRole('status').filter({ hasText: '正在加载团队' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.evaluate(() => {
    const h = (window as any).picker;
    h.hold = null;
    h.pending[1].resolve();
  });
  await page.getByRole('option', { name: '信贷团队 · team-a', exact: true }).click();
  await choose(page, '智能体类型', 'base/workflow');
  await choose(page, '选择智能体', '基础助手 · base-a');
  await choose(page, '智能体版本', '1.0.0 · published');
  expect((await read(page)).token).toBe('new-token');
  await page.evaluate(() => (window as any).picker.unmount());
  await expect(page.getByLabel('评测对象选择', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).picker.events.at(-1))).toBeNull();
});

test('mouse opening deduplicates an in-flight directory query', async ({ page }) => {
  await login(page);
  await page.evaluate(() => {
    (window as any).picker.hold = 'getTeams';
  });
  await page.getByText('请选择团队', { exact: true }).click();
  await page.waitForFunction(() => (window as any).picker.pending.length === 1);
  await page.keyboard.press('Escape');
  await page.getByRole('combobox', { name: '选择团队', exact: true }).press('Enter');
  expect(await page.evaluate(() => (window as any).picker.calls.length)).toBe(1);
  await page.evaluate(() => {
    const h = (window as any).picker;
    h.hold = null;
    h.pending[0].resolve();
  });
  await page.getByRole('option', { name: '信贷团队 · team-a', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '智能体类型' })).toBeEnabled();
});

test('desktop and narrow layout have no horizontal overflow', async ({ page }, testInfo) => {
  await selectAgent(page);
  await choose(page, '智能体版本', '1.0.0 · published');
  await page.screenshot({ path: testInfo.outputPath('desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 360, height: 900 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mobile.png'), fullPage: true });
});
