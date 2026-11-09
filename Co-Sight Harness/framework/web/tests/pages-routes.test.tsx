/**
 * 页面与路由表：404 页、Agent 开发薄壳、导航表一致性。
 *
 * 路由部分一律走 `renderApp`（生产用的 `routes` + 真外壳），不在这里另写一份路由表：
 * 路由表写错（capability 挂错、漏了 `end`）只有跑真表才测得出来，另写一份等于把
 * 同一份信息抄两遍并让两边各自漂移。
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ModuleManifest } from 'harness-shared';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NAV_ITEMS } from '../src/app/navigation';
import { routes } from '../src/app/routes';
import { enUS } from '../src/i18n/messages/en-US';
import { zhCN } from '../src/i18n/messages/zh-CN';
import type { FakeResponse } from './helpers/render';
import { envelope, jsonResponse, renderApp, resetUiStore } from './helpers/render';

const HEALTH_OK = envelope({
  status: 'ok',
  version: '0.1.0',
  uptimeSeconds: 1,
  cosightHome: '/home/x/.cosight-harness',
  database: 'sqlite',
});
const MODULES_EMPTY = envelope({ modules: [], invalid: [] });

/**
 * 声明挂载 `history` 的模块清单。
 *
 * 只声明一个 capability，是为了能验证"路由 → capability → 模块"这条链真的接对了：
 * 所有宿主在无模块时显示的是同一句"模块尚未接入"，光看那句话分不出
 * `/history` 有没有错挂到别的 capability 上。
 *
 * 不用 `knowledge` 当夹具：`/knowledge` 现在归 `KnowledgePage`（嵌用户配置的地址），
 * 不再是模块宿主。
 */
const HISTORY_MODULE: ModuleManifest = {
  schemaVersion: 1,
  id: 'history-module',
  name: { 'zh-CN': '历史模块', 'en-US': 'History module' },
  description: { 'zh-CN': '会话历史', 'en-US': 'Session history' },
  version: '1.0.0',
  entry: 'https://modules.example.com/history/index.html',
  allowedOrigins: ['https://modules.example.com'],
  mounts: [{ capability: 'history', path: '/history' }],
  icon: null,
  healthcheck: null,
};

/** 同上，但挂的是首页的 `conversation` 能力。 */
const CONVERSATION_MODULE: ModuleManifest = {
  ...HISTORY_MODULE,
  id: 'conversation-module',
  name: { 'zh-CN': '会话模块', 'en-US': 'Conversation module' },
  description: { 'zh-CN': '会话对话', 'en-US': 'Chat' },
  entry: 'https://modules.example.com/conversation/index.html',
  mounts: [{ capability: 'conversation', path: '/' }],
};

/**
 * 按 URL 分发 fetch 打桩。
 *
 * 共享的 `stubFetch` 只支持"固定响应"或"固定顺序"，而一个页面级用例同时会打
 * 好几个接口（外壳 + 页面 + 弹窗）。用顺序就得依赖"谁先发"这种实现细节，
 * 换个渲染顺序用例就红，且红的原因与被测行为无关。
 *
 * 未打桩的 URL 直接 reject：多出来的请求是"用例没预料的调用"，应该立刻暴露。
 */
function stubApi(endpoints: readonly { path: string; response: FakeResponse }[]): void {
  /*
   * 侧栏「最近」是外壳级请求：任何 `renderApp` 用例都会打一次 smart-factory 的
   * 会话列表。它不是被测页面的一部分，统一给空列表。
   */
  const all = [
    { path: '/api/smart-factory/v1/sessions/list', response: jsonResponse({ items: [], total: 0 }) },
    ...endpoints,
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const endpoint = all.find((candidate) => input.includes(candidate.path));
      if (endpoint === undefined) {
        return Promise.reject(new Error(`用例没有打桩这个请求：${input}`));
      }
      return Promise.resolve(endpoint.response);
    }),
  );
}

/** 按点分路径取词条。取不到返回 undefined。 */
function lookupMessage(dictionary: object, key: string): string | undefined {
  let node: unknown = dictionary;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) {
      return undefined;
    }
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'string' ? node : undefined;
}

function mountedFrame(): HTMLIFrameElement {
  const frame = document.querySelector<HTMLIFrameElement>('iframe');
  if (frame === null) {
    throw new Error('没有渲染出 iframe：模块没有被挂载');
  }
  return frame;
}

beforeEach(() => {
  /*
   * store 初值取自 `navigator.languages`，而 jsdom 报的是 `en-US`——不复位的话
   * 本文件按中文查询的断言（导航文案、页标题）全都会失败，且失败信息看起来像是
   * 文案写错了。这里统一复位成 `DEFAULT_LOCALE`，语言本身由 i18n 的用例去测。
   */
  resetUiStore();
  stubApi([
    { path: '/health', response: jsonResponse(HEALTH_OK) },
    { path: '/modules', response: jsonResponse(MODULES_EMPTY) },
  ]);
});

describe('NotFoundPage', () => {
  it('未知地址渲染 404 页而不是空白，返回按钮回到首页', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/nope');

    // "路由不存在"与"模块没接入"必须能分辨：用户下一步该做的事完全不同（改地址 vs 找模块）。
    expect(screen.getByText(zhCN.error.notFound.title)).toBeInTheDocument();
    expect(screen.getByText(zhCN.error.notFound.hint)).toBeInTheDocument();
    expect(screen.queryByText(zhCN.module.missing.title)).toBeNull();

    await user.click(screen.getByRole('button', { name: zhCN.error.notFound.back }));

    expect(router.state.location.pathname).toBe('/');
    expect(screen.queryByText(zhCN.error.notFound.title)).toBeNull();
  });
});

describe('AgentDevPage', () => {
  it('没有模块清单时显示"模块尚未接入"，而不是 404', async () => {
    renderApp('/agent-dev');

    /*
     * 路由存在、内容由模块提供，这两件事必须分开（routes.tsx 的注释）。
     * 所以这里断言的是 missing，而不是 notFound——写成 404 会让同事以为地址写错了。
     */
    expect(await screen.findByText(zhCN.module.missing.title)).toBeInTheDocument();
    expect(screen.getByText(zhCN.module.missing.hint)).toBeInTheDocument();
    expect(screen.queryByText(zhCN.error.notFound.title)).toBeNull();
  });
});

describe('路由表与模块挂载', () => {
  /*
   * `/knowledge` 不在这一组里：它不是模块宿主，内容由用户在设置里配的地址决定
   * （`KnowledgePage` 自己的用例覆盖，见 knowledge-page.test.tsx）。
   */
  it.each(['/', '/experts', '/history', '/observability'] as const)(
    '%s 渲染模块宿主占位（路由存在，只是内容没来）',
    async (path) => {
      renderApp(path);

      expect(await screen.findByText(zhCN.module.missing.title)).toBeInTheDocument();
      expect(screen.queryByText(zhCN.error.notFound.title)).toBeNull();
      expect(document.querySelector('iframe')).toBeNull();
    },
  );

  it('/experts 挂 experts 模块，并落到清单声明的 entryPath', async () => {
    /*
     * 专家页不再是框架的原生页面（C1 已改）：它和别的页面一样由模块提供。
     * smart-factory 的专家列表在 `/agents`，清单用 `entryPath` 指过去——
     * 这条同时钉住"路由 → capability → 模块"与"capability → 模块内页面"两段。
     */
    const expertsModule: ModuleManifest = {
      ...HISTORY_MODULE,
      id: 'smart-factory',
      name: { 'zh-CN': '智慧工厂', 'en-US': 'Smart Factory' },
      entry: 'https://modules.example.com/sf/index.html',
      mounts: [{ capability: 'experts', path: '/experts', entryPath: '/agents' }],
    };
    stubApi([
      { path: '/modules', response: jsonResponse(envelope({ modules: [expertsModule], invalid: [] })) },
      { path: '/health', response: jsonResponse(HEALTH_OK) },
    ]);

    renderApp('/experts');

    await waitFor(() => {
      expect(document.querySelector('iframe')).not.toBeNull();
    });
    expect(mountedFrame().src).toBe(
      'https://modules.example.com/agents?locale=zh-CN&capability=experts',
    );
    expect(screen.queryByText(zhCN.module.missing.title)).toBeNull();
  });

  it('/ 的 index 路由挂的是 conversation 模块', async () => {
    stubApi([
      {
        path: '/modules',
        response: jsonResponse(envelope({ modules: [CONVERSATION_MODULE], invalid: [] })),
      },
      { path: '/health', response: jsonResponse(HEALTH_OK) },
    ]);
    renderApp('/');

    /*
     * index 路由没有 path 可写，只能是 `{ index: true }`。挂错 capability 的话首页
     * 会永远显示"模块尚未接入"——而这是用户看到的第一屏。
     */
    await waitFor(() => {
      expect(document.querySelector('iframe')).not.toBeNull();
    });
    expect(screen.queryByText(zhCN.module.missing.title)).toBeNull();
    // locale 由宿主拼进模块 URL（模块自己不去猜界面语言），顺带把这一条也钉上。
    expect(mountedFrame().src).toBe(
      'https://modules.example.com/conversation/index.html?locale=zh-CN&capability=conversation',
    );
  });

  it('/history 挂 history 模块，/observability 保持未接入', async () => {
    stubApi([
      {
        path: '/modules',
        response: jsonResponse(envelope({ modules: [HISTORY_MODULE], invalid: [] })),
      },
      { path: '/health', response: jsonResponse(HEALTH_OK) },
    ]);

    const { unmount } = renderApp('/history');
    await waitFor(() => {
      expect(document.querySelector('iframe')).not.toBeNull();
    });
    expect(mountedFrame().src).toBe(
      'https://modules.example.com/history/index.html?locale=zh-CN&capability=history',
    );
    unmount();

    /*
     * 反向断言：只声明了 history 的清单不该让每个宿主都长出 iframe。
     * 少了这一条，"pickModuleForCapability 被绕过、所有宿主都挂第一个模块"也能过。
     */
    renderApp('/observability');
    expect(await screen.findByText(zhCN.module.missing.title)).toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();
  });
});

describe('导航表一致性', () => {
  it('每条 to 唯一', () => {
    const paths = NAV_ITEMS.map((item) => item.to);
    // 两条导航指向同一个地址时，两者永远同时高亮，用户分不出自己在哪。
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('每条 to 都能在外壳的子路由里找到落点', () => {
    const children = routes.at(0)?.children ?? [];
    // 子路由的 path 是相对的（'experts'），导航表写的是绝对路径（'/experts'）。
    const childPaths = [...new Set(children.flatMap((child) => (child.path === undefined ? [] : [`/${child.path}`])))];
    const hasIndexRoute = children.some((child) => child.index === true);

    for (const item of NAV_ITEMS) {
      if (item.to === '/') {
        // 首页是 index 路由，没有 path 可对——漏了它侧栏第一项就是个死链。
        expect(hasIndexRoute).toBe(true);
        continue;
      }
      expect(childPaths).toContain(item.to);
    }
  });

  it('每个 labelKey 在中英词表里都有非空值', () => {
    for (const item of NAV_ITEMS) {
      /*
       * 存在性在编译期就有保障（`NavLabelKey` 从中文词表取出，`enUS: Messages`
       * 也要求结构一致）。运行期这一条额外挡住的是**空串**：`agentDev: ''`
       * 编译得过去，但侧栏会渲染出一个点不动的空链接，界面看着像坏了。
       */
      expect(lookupMessage(zhCN, item.labelKey)).toBeTruthy();
      expect(lookupMessage(enUS, item.labelKey)).toBeTruthy();
    }
  });

  it('导航文案按定稿写法钉死字面量', () => {
    /*
     * 「专家·技能」用间隔号连接两段名词（2026-10-23）；侧栏第三条入口 2026-10-30 起
     * 改叫「Harness工程构建」，不再按「A·B」拼段。这里钉死字面量，避免手滑写成
     * `专家 · 技能`（带空格）或把产品名拆出空格。
     */
    expect(zhCN.nav.experts).toBe('专家·技能');
    expect(zhCN.nav.agentDev).toBe('Harness工程构建');
  });

  it('首页导航项用 end 精确匹配：在 /experts 上「新建对话」不得选中', async () => {
    renderApp('/experts');
    await screen.findByText(zhCN.module.missing.title);

    const nav = within(screen.getByRole('navigation', { name: zhCN.app.navLabel }));
    /*
     * 漏了 `end` 的话 `/` 会前缀匹配到所有路由，"新建对话"在任何页面上都高亮，
     * 于是侧栏永远有两项同时是选中态。这条是本文件里最值钱的一条：
     * 它的失败模式在肉眼看来只是"高亮多了一个"，很容易被当成样式问题放过。
     */
    expect(nav.getByRole('link', { name: zhCN.nav.newChat })).not.toHaveAttribute('aria-current');
    expect(nav.getByRole('link', { name: zhCN.nav.experts })).toHaveAttribute('aria-current', 'page');

    // 顺带钉住渲染出来的字面量：词表对了但 NavItem 拼错/截断的话，这里会红。
    expect(nav.getByRole('link', { name: zhCN.nav.agentDev })).toBeInTheDocument();
  });

  it('在首页「新建对话」是选中态（end 不是把首页的高亮一并关掉）', async () => {
    renderApp('/');
    await screen.findByText(zhCN.module.missing.title);

    const nav = within(screen.getByRole('navigation', { name: zhCN.app.navLabel }));
    expect(nav.getByRole('link', { name: zhCN.nav.newChat })).toHaveAttribute('aria-current', 'page');
    expect(nav.getByRole('link', { name: zhCN.nav.experts })).not.toHaveAttribute('aria-current');
  });

  it('点侧栏「新建对话」从 /experts 回到首页会话宿主', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/experts');
    await screen.findByText(zhCN.module.missing.title);

    await user.click(screen.getByRole('link', { name: zhCN.nav.newChat }));

    /*
     * 点一次导航就把整条链走完了：NavLink 的 to → 路由表的 index 路由 →
     * conversation 宿主。href 断言只能证明"地址写对了"，证明不了那个地址
     * 真的能渲染出东西。
     */
    expect(router.state.location.pathname).toBe('/');
    expect(await screen.findByText(zhCN.module.missing.title)).toBeInTheDocument();
  });
});
