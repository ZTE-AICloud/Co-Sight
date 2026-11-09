/**
 * 冒烟用例：真实浏览器 + 真实后端。
 *
 * 只钉两件在 jsdom 里**测不到**的事，别的一律留给组件测试（跑得快、失败信息准）：
 *  1. 外壳在真实布局下不塌（侧栏固定、主面板内滚、没有整页横向滚动）；
 *  2. 设置弹窗的 Tab 焦点陷阱在真实 Tab 顺序下成立。
 *
 * 内容页断言的是「模块尚未接入」而不是某一页的具体内容：宿主不再自己渲染专家页
 * （D44，专家列表在 smart-factory 的 `/agents`），冒烟也不该依赖那个模块起没起。
 * 同理，用例**不依赖任何数据**：写死某个专家名会在换 seed 时碎掉。
 */

import { expect, test } from '@playwright/test';

test('外壳：侧栏导航可用，主面板由模块宿主接管', async ({ page }) => {
  await page.goto('/');

  const nav = page.getByRole('navigation', { name: '主导航' });
  await expect(nav.getByRole('link', { name: '专家' })).toBeVisible();

  // 首页 = 会话对话页。内容由模块提供：装了会话模块时主面板里是 iframe，
  // 没装时是兜底文案——两种都算"路由存在且主面板被接管"，冒烟不该只认其中一种。
  // （路由存在、内容由模块提供，这两件事必须分开。）
  await expect(page.locator('main iframe').or(page.getByText('模块尚未接入'))).toBeVisible();

  // 侧栏固定、主面板内滚：整个文档不该出现横向滚动条。
  const hasHorizontalScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalScroll).toBe(false);
});

test('导航：点击侧栏切换页面并更新选中态', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '专家' }).click();

  await expect(page).toHaveURL(/\/experts$/);
  // 这一条只钉路由与选中态：`/experts` 的内容由模块提供，装没装模块是运行环境的事
  // （本机上可能已经注册过 smart-factory），不该让冒烟的结果跟着变。
  // 只有当前页高亮：首页项靠 `end` 才不会同时亮着。
  await expect(page.getByRole('link', { name: '专家' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('link', { name: '新建对话' })).not.toHaveAttribute('aria-current', 'page');
});

test('设置：弹窗打开后焦点被限制在弹窗内，Esc 关闭并归还焦点', async ({ page }) => {
  await page.goto('/');

  const opener = page.getByRole('button', { name: '打开设置' });
  await opener.click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('tab', { name: '通用设置' })).toBeVisible();

  // Tab 一圈之后焦点仍应留在弹窗里（焦点陷阱），否则键盘用户会tab 到背后的页面上。
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press('Tab');
    const inside = await dialog.evaluate((node) => node.contains(document.activeElement));
    expect(inside).toBe(true);
  }

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  // 关闭后焦点回到入口按钮：不还回去的话，键盘用户得从头 Tab 一遍。
  await expect(opener).toBeFocused();
});

test('设置：切到英文后界面文案与导航一起变', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '打开设置' }).click();

  await page.getByRole('radio', { name: 'English' }).click();
  await page.keyboard.press('Escape');

  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav.getByRole('link', { name: 'Experts' })).toBeVisible();
  // 语言落在本机（persist），刷新后不该弹回中文。
  await page.reload();
  await expect(page.getByRole('link', { name: 'Experts' })).toBeVisible();
});
