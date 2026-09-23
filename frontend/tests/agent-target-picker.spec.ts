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
const harness=window.picker={calls:[],events:[],pending:[],hold:null,fail:null,empty:null,versions:['1.0.0','1.1.0'],setAuth:null};
const agent=(id,name,type,raw)=>({agentId:id,agentName:name,typeGroup:type,platformAgentType:raw,platformArrangeType:raw});
const catalog={
 getTeams:()=>[{teamId:'team-a',teamName:'信贷团队'},{teamId:'team-b',teamName:'服务团队'}],
 getAgents:({teamId})=>teamId==='team-b'?[agent('base-b','服务助手','base/workflow','base')]:[agent('base-a','基础助手','base/workflow','base'),agent('workflow-a','工作流助手','base/workflow','workflow'),agent('claw-a','云虾助手','abcclaw','abcclaw'),agent('unknown','未知助手',null,'light')],
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
createApp({setup(){const picker=ref(null),disabled=ref(false),visible=ref(true),token=ref('test-token'),teamId=ref('team-a');
harness.lock=value=>disabled.value=value;harness.unmount=()=>visible.value=false;harness.read=()=>picker.value?.readSubmissionSelection()??null;
harness.setAuth=auth=>{token.value=auth.token;teamId.value=auth.teamId;};
return()=>h('main',{style:'max-width:960px;padding:16px;font:14px system-ui;margin:auto'},[visible.value?h(Picker,{ref:picker,directory,token:token.value,teamId:teamId.value,disabled:disabled.value,onSelectionChange:value=>harness.events.push(value)}):null]);}}).mount('#app');
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
const read = (page: Page) => page.evaluate(() => (window as any).picker.read());

for (const [name, id, rawType] of [
  ['基础助手', 'base-a', 'base'],
  ['工作流助手', 'workflow-a', 'workflow'],
]) {
  test(`${rawType} selects an exact version without branch and locks the submission copy`, async ({
    page,
  }) => {
    await choose(page, '选择智能体', `${name} · ${id}`);
    await expect(page.getByRole('combobox', { name: '分支地址' })).toBeDisabled();
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
    expect(calls.map((call: any) => call.name)).toEqual(['getAgents', 'getAgentVersions']);
    expect(calls[1].input).toEqual({ token: 'test-token', agentId: id });
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
  await choose(page, '选择智能体', '云虾助手 · claw-a');
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  await choose(page, '分支地址', '↳ ↳ 叶分支 · leaf');
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
  await choose(page, '分支地址', '主分支 · root');
  expect(await read(page)).toBeNull();
  await choose(page, '智能体版本', 'root-v1 · test');
  expect((await read(page)).target.branchId).toBe('root');
});

test('agent change clears dependent selection without transient mixed targets', async ({ page }) => {
  await choose(page, '选择智能体', '基础助手 · base-a');
  await choose(page, '智能体版本', '1.0.0 · published');
  await page.evaluate(() => {
    (window as any).picker.events.length = 0;
  });
  await choose(page, '选择智能体', '工作流助手 · workflow-a');
  expect(await read(page)).toBeNull();
  const events = await page.evaluate(() => (window as any).picker.events);
  expect(events.filter((value: any) => value?.agentId === 'workflow-a' && value !== null)).toEqual(
    [],
  );
  expect(events.at(-1)).toBeNull();
  await choose(page, '智能体版本', '1.0.0 · published');
  expect((await read(page)).target.agentId).toBe('workflow-a');
});

test('unknown agent type stays visible but cannot produce a target', async ({ page }) => {
  await choose(page, '选择智能体', '未知助手 · unknown');
  await expect(page.getByRole('alert')).toContainText('暂不支持');
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: '分支地址' })).toBeDisabled();
  expect(await read(page)).toBeNull();
});

test('refresh invalidates a removed version, error is sanitized and empty state allows retry', async ({
  page,
}) => {
  await choose(page, '选择智能体', '基础助手 · base-a');
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
  await expect(await page.getByRole('alert').textContent()).not.toContain('test-token');
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

test('late version response after an auth change cannot populate the new context', async ({
  page,
}) => {
  await choose(page, '选择智能体', '基础助手 · base-a');
  await page.evaluate(() => {
    (window as any).picker.hold = 'getAgentVersions';
  });
  await page.getByRole('combobox', { name: '智能体版本' }).press('Enter');
  await expect(page.getByRole('status').filter({ hasText: '正在加载智能体版本' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.evaluate(() => (window as any).picker.setAuth({ token: 'new-token', teamId: 'team-b' }));
  await page.evaluate(() => {
    const h = (window as any).picker;
    h.hold = null;
    h.pending.shift().resolve();
  });
  await expect(page.getByRole('combobox', { name: '选择智能体' })).toBeEnabled();
  await expect(page.getByRole('combobox', { name: '智能体版本' })).toBeDisabled();
  expect(await read(page)).toBeNull();
  await choose(page, '选择智能体', '服务助手 · base-b');
  await choose(page, '智能体版本', '1.1.0 · published');
  const result = await read(page);
  expect(result.target.agentId).toBe('base-b');
  expect(result.token).toBe('new-token');
});

test('personal space passes an empty teamId through to the directory', async ({ page }) => {
  await page.evaluate(() => (window as any).picker.setAuth({ token: 'test-token', teamId: '' }));
  await page.evaluate(() => (window as any).picker.calls.length = 0);
  await page.getByRole('combobox', { name: '选择智能体' }).press('Enter');
  await page.waitForFunction(() => (window as any).picker.calls.length > 0);
  const input = await page.evaluate(() => (window as any).picker.calls[0].input);
  expect(input).toEqual({ token: 'test-token', teamId: '' });
  expect((await read(page))).toBeNull();
});

test('unmount clears the parent selection', async ({ page }) => {
  await choose(page, '选择智能体', '基础助手 · base-a');
  await choose(page, '智能体版本', '1.0.0 · published');
  expect(await read(page)).not.toBeNull();
  await page.evaluate(() => (window as any).picker.unmount());
  const events = await page.evaluate(() => (window as any).picker.events);
  expect(events.at(-1)).toBeNull();
});
