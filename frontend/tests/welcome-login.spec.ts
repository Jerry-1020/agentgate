import { test, expect, type Page, type Route } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

let server: ViteDevServer;
let url: string;

const fixture = `<!doctype html><html lang="zh"><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue';
import {createRouter,createWebHashHistory,RouterView} from 'vue-router';
import ElementPlus from 'element-plus';
import {pinia} from '/src/stores/index.ts';
import {useAuthStore} from '/src/stores/modules/auth';
import Welcome from '/src/views/evaluation/Welcome.vue';
import '/node_modules/element-plus/dist/index.css';
const router=createRouter({history:createWebHashHistory(),routes:[{path:'/welcome',component:Welcome},{path:'/overview',component:{render:()=>h('main',{'data-testid':'overview'},'主页')}}]});
window.hello=()=>{const auth=useAuthStore();return {path:router.currentRoute.value.path,mode:auth.loginMode,token:auth.token,teamId:auth.teamId,teamName:auth.teamName};};
createApp({render:()=>h(RouterView)}).use(pinia).use(router).use(ElementPlus).mount('#app');
router.push('/welcome');
</script></body></html>`;

test.beforeAll(async () => {
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('..', import.meta.url)),
    define: {
      'import.meta.env.VITE_AGENT_PLATFORM_ORIGIN': JSON.stringify(''),
      'import.meta.env.VITE_ABCCLAW_PLATFORM_ORIGIN': JSON.stringify(''),
    },
    plugins: [
      vue(),
      {
        name: 'welcome-test-page',
        configureServer(vite) {
          vite.middlewares.use('/__welcome', async (_request, response, next) => {
            try {
              response.setHeader('Content-Type', 'text/html');
              response.end(await vite.transformIndexHtml('/__welcome', fixture));
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
  url = `http://127.0.0.1:${address.port}/__welcome`;
});
test.afterAll(async () => {
  await server?.close();
});
test.beforeEach(async ({ page }) => {
  await page.goto(url + '#/welcome');
  await expect(page.getByRole('heading', { name: '欢迎页面' })).toBeVisible();
});

const wrap = (data: unknown) => ({ code: '0', message: '查询成功', data });
const reply = (route: Route, value: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });

const teams = wrap({
  records: [
    { teamId: 'team-a', teamName: '本地验收团队' },
    { teamId: 'team-empty', teamName: '空团队' },
  ],
  total: 2,
  current: 1,
  size: 300,
  pages: 1,
});

test('bank login requires a well-formed token before any request', async ({ page }) => {
  for (const value of [' token ', 'line\nbreak', 'Bearer secret']) {
    await page.getByLabel('请输入行内用户token').fill(value);
    await page.getByRole('button', { name: '行内Login' }).click();
    await expect(page.getByRole('alert')).toContainText('token');
  }
  await page.getByLabel('请输入行内用户token').fill('');
  await page.getByRole('button', { name: '行内Login' }).click();
  await expect(page.getByRole('alert')).toContainText('请先输入');
});

test('bank login lists personal and team spaces, records the session and enters the main page', async ({
  page,
}) => {
  await page.route('**/web/ops/team/getTeamRole**', (route) => reply(route, teams));
  await page.getByLabel('请输入行内用户token').fill('bank-token');
  await page.getByRole('button', { name: '行内Login' }).click();
  await expect(page.getByRole('dialog', { name: '选择个人/团队空间' })).toBeVisible();
  await page.getByRole('combobox', { name: '个人/团队空间' }).press('Enter');
  await page.getByRole('option', { name: '本地验收团队 · team-a' }).click();
  await page.getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.getByTestId('overview')).toBeVisible();
  expect(await page.evaluate(() => (window as any).hello())).toMatchObject({
    path: '/overview',
    mode: 'bank',
    token: 'bank-token',
    teamId: 'team-a',
    teamName: '本地验收团队',
  });
});

test('personal space is the default and an empty team list still allows entry', async ({ page }) => {
  await page.route('**/web/ops/team/getTeamRole**', (route) =>
    reply(route, wrap({ records: [], total: 0, current: 1, size: 300, pages: 1 })),
  );
  await page.getByLabel('请输入行内用户token').fill('bank-token');
  await page.getByRole('button', { name: '行内Login' }).click();
  await expect(page.getByText('当前 token 名下没有团队，将以个人空间进入。')).toBeVisible();
  await page.getByRole('button', { name: '确认', exact: true }).click();
  expect(await page.evaluate(() => (window as any).hello())).toMatchObject({
    mode: 'bank',
    teamId: '',
  });
});

test('an invalid platform token stays on the welcome page with a sanitized message', async ({
  page,
}) => {
  await page.route('**/web/ops/team/getTeamRole**', (route) =>
    reply(route, { detail: 'Authorization: Bearer bank-token' }, 401),
  );
  await page.getByLabel('请输入行内用户token').fill('bank-token');
  await page.getByRole('button', { name: '行内Login' }).click();
  await expect(page.getByRole('alert')).toContainText('token 无效或已过期');
  expect(await page.locator('body').innerText()).not.toContain('Bearer bank-token');
  expect(await page.evaluate(() => (window as any).hello().path)).toBe('/welcome');
});

test('external login enters the main page without any directory request or token', async ({
  page,
}) => {
  let requested = false;
  await page.route('**/web/**', (route) => {
    requested = true;
    return reply(route, {});
  });
  await page.getByRole('button', { name: '行外Login' }).click();
  await expect(page.getByTestId('overview')).toBeVisible();
  expect(await page.evaluate(() => (window as any).hello())).toMatchObject({
    mode: 'external',
    token: '',
  });
  expect(requested).toBe(false);
});
