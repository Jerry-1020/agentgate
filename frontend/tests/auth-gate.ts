import { expect, type Page } from '@playwright/test';

// 全应用用例的登录前置：路由守卫将未登录访问重定向到欢迎页，这里统一走行外登录。
// 仅做同源哈希导航的用例在首次进入时调用一次即可（store 为内存态，哈希跳转不重载）。
export async function passAuthGate(page: Page) {
  const heading = page.getByRole('heading', { name: '欢迎页面' });
  if (await heading.isVisible().catch(() => false)) {
    await page.getByRole('button', { name: '行外Login' }).click();
    await expect(heading).toBeHidden();
  }
}
