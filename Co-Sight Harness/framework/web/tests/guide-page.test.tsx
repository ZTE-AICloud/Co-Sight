/**
 * 使用说明页（`/guide`）与侧栏入口。
 *
 * 这里测的是"入口接没接上、页面的动作是不是真的执行了"：
 * - 侧栏底部那个问号是链接还是装饰；
 * - 三步里的按钮分别打开模型设置、工作区设置、回到会话页；
 * - 常见问题能不能展开。
 *
 * 词条本身由 `i18n.test.ts` 的"中英叶子键完全一致"守住，这里不重复抄文案。
 */

import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { enUS } from '../src/i18n/messages/en-US';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { useUiStore } from '../src/stores/ui';
import { envelope, jsonResponse, renderApp, resetUiStore } from './helpers/render';

const HEALTH_OK = envelope({
  status: 'ok',
  version: '0.1.0',
  uptimeSeconds: 1,
  cosightHome: '/home/x/.cosight-harness',
  database: 'sqlite',
});

/** 只有 null 合法的单例接口：当前模型 / 工作区 / 代理 / 知识库路由。 */
const NULLABLE_PATHS = new Set([
  '/api/models/active',
  '/api/workspaces/active',
  '/api/agent-proxies/default',
  '/api/rag-knowledge/active',
]);

/** 裸数组返回的列表接口（见 settings 面板的取数约定）。 */
const LIST_PATHS = new Set([
  '/api/models',
  '/api/workspaces',
  '/api/agent-proxies',
  '/api/rag-knowledge',
]);

/**
 * 说明页本身只读词条，但侧栏「最近」与"打开设置"会打接口。
 * 未知请求直接 reject：用例没预料的调用应该当场暴露，而不是被一句空信封糊过去。
 */
function stubApi(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const pathname = new URL(input, 'http://localhost').pathname;

      if (pathname === '/api/smart-factory/v1/sessions/list') {
        return Promise.resolve(jsonResponse({ items: [], total: 0 }));
      }
      if (pathname === '/health') {
        return Promise.resolve(jsonResponse(HEALTH_OK));
      }
      if (pathname === '/modules') {
        return Promise.resolve(jsonResponse(envelope({ modules: [], invalid: [] })));
      }
      if (LIST_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope([])));
      }
      if (NULLABLE_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope(null)));
      }
      return Promise.reject(new Error(`用例没有打桩这个请求：${input}`));
    }),
  );
}

beforeEach(() => {
  resetUiStore();
  stubApi();
});

describe('使用说明入口', () => {
  it('侧栏底部有链接，点击后进入 /guide 并渲染说明页', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/');

    // 侧栏与模块清单是两条取数线；等入口出现即可，不必等首页模块先落地。
    const entry = await screen.findByRole('link', { name: zhCN.guide.navLabel });
    // 链接而不是按钮：中键、新标签页也能把说明页打开。
    expect(entry).toHaveAttribute('href', '/guide');

    await user.click(entry);

    expect(router.state.location.pathname).toBe('/guide');
    expect(
      await screen.findByRole('heading', { level: 1, name: zhCN.guide.title }),
    ).toBeInTheDocument();
  });

  it('停在说明页时，侧栏入口是当前页', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    expect(screen.getByRole('link', { name: zhCN.guide.navLabel })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('侧栏折叠后入口只剩图标，但仍能被叫出名字', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    act(() => {
      useUiStore.setState({ sidebarCollapsed: true });
    });

    const entry = screen.getByRole('link', { name: zhCN.guide.navLabel });
    expect(entry).toHaveAttribute('title', zhCN.guide.navLabel);
    expect(entry).not.toHaveTextContent(zhCN.guide.navLabel);
  });
});

describe('使用说明页', () => {
  it('/guide 是宿主自己的页面，不显示 404 或"模块尚未接入"', async () => {
    renderApp('/guide');

    expect(
      await screen.findByRole('heading', { level: 1, name: zhCN.guide.title }),
    ).toBeInTheDocument();
    expect(screen.queryByText(zhCN.error.notFound.title)).toBeNull();
    expect(screen.queryByText(zhCN.module.missing.title)).toBeNull();
  });

  it('目录的锚点与各章节的 id 一一对应', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const toc = screen.getByRole('navigation', { name: zhCN.guide.tocLabel });
    const hrefs = within(toc)
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'))
      .filter((href): href is string => href !== null);

    expect(hrefs).toStrictEqual(['#quickstart', '#model', '#workspace', '#modules', '#faq']);
    for (const href of hrefs) {
      expect(document.querySelector(href)).not.toBeNull();
    }
  });

  it('功能地图里每个模块都有入口截图', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const modules = within(
      screen.getByRole('region', { name: zhCN.guide.modules.title }),
    );

    const shots = modules.getAllByRole('img');
    expect(shots).toHaveLength(5);
    for (const shot of shots) {
      expect(shot.getAttribute('src')).toBeTruthy();
      // alt 是改版后换图的线索，不能为空。
      expect(shot.getAttribute('alt')).toBeTruthy();
    }

    // 截图是按钮：点击在当前页放大，不跳新标签页。
    const buttons = modules.getAllByRole('button');
    expect(buttons).toHaveLength(5);
    for (const button of buttons) {
      expect(button).toHaveAttribute('type', 'button');
    }
  });

  it('点击截图在当前页打开预览，再点一下关闭', async () => {
    const user = userEvent.setup();
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const modules = within(
      screen.getByRole('region', { name: zhCN.guide.modules.title }),
    );
    const [firstShot] = modules.getAllByRole('img');
    const alt = firstShot?.getAttribute('alt') ?? '';

    await user.click(modules.getAllByRole('button')[0]!);

    const dialog = screen.getByRole('dialog', { name: alt });
    expect(within(dialog).getByRole('img', { name: alt })).toBeInTheDocument();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);

    // 再点一次图片（冒泡到预览层）收起。
    await user.click(within(dialog).getByRole('img', { name: alt }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('预览可以用 Esc 关闭', async () => {
    const user = userEvent.setup();
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const modules = within(
      screen.getByRole('region', { name: zhCN.guide.modules.title }),
    );
    await user.click(modules.getAllByRole('button')[0]!);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('目录默认高亮第一节，并提供章节序号', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const toc = screen.getByRole('navigation', { name: zhCN.guide.tocLabel });
    const links = within(toc).getAllByRole('link');

    expect(links[0]).toHaveAttribute('aria-current', 'location');
    expect(links[0]).toHaveTextContent('01');
    for (const link of links.slice(1)) {
      expect(link).not.toHaveAttribute('aria-current');
    }
  });

  it('三步的按钮分别打开模型设置、工作区设置与对话页', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    // 页头的「去配置模型」与第一步的按钮同名；这里只点三步里的那个。
    const quickstart = within(
      screen.getByRole('region', { name: zhCN.guide.quickstart.title }),
    );

    await user.click(
      quickstart.getByRole('button', { name: zhCN.guide.quickstart.model.action }),
    );
    expect(useUiStore.getState().settingsOpen).toBe(true);
    expect(useUiStore.getState().settingsTab).toBe('model');

    // 关掉弹窗再点下一步：设置弹窗有焦点陷阱，盖着它点不到后面的按钮。
    act(() => {
      useUiStore.setState({ settingsOpen: false });
    });

    await user.click(
      quickstart.getByRole('button', { name: zhCN.guide.quickstart.workspace.action }),
    );
    expect(useUiStore.getState().workspaceOpen).toBe(true);

    act(() => {
      useUiStore.setState({ workspaceOpen: false });
    });

    await user.click(
      quickstart.getByRole('button', { name: zhCN.guide.quickstart.chat.action }),
    );
    expect(router.state.location.pathname).toBe('/');
  });

  it('常见问题默认收起，点开后能看到答案', async () => {
    const user = userEvent.setup();
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    const question = screen.getByText(zhCN.guide.faq.knowledgeQ);
    const details = question.closest('details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');

    await user.click(question);

    expect(details).toHaveAttribute('open');
    expect(screen.getByText(zhCN.guide.faq.knowledgeA)).toBeInTheDocument();
  });

  it('切换英文后页面与入口文案一起换', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: zhCN.guide.title });

    act(() => {
      useUiStore.setState({ locale: 'en-US' });
    });

    expect(
      screen.getByRole('heading', { level: 1, name: enUS.guide.title }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: enUS.guide.navLabel })).toBeInTheDocument();
    expect(screen.queryByText(zhCN.guide.title)).toBeNull();
  });
});
