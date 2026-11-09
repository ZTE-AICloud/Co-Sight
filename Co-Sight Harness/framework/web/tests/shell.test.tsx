/**
 * 应用外壳：侧栏（导航项 / 折叠 / 用户行）、外壳本体
 * （跳转链接、页面出口、设置弹窗的按需挂载、`<html lang>` 同步）。
 *
 * 边界：**外壳"接没接上"在这里测，接上之后的行为由各自的文件测**。
 * 比如设置弹窗，这里只验证"settingsOpen 为真时它确实被挂载"，弹窗内部的
 * 页签、Esc、焦点循环属于弹窗自己的测试文件。
 */

import { LOCALE_HTML_LANG } from 'harness-shared';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ragKnowledgeKeys } from '../src/api/ragKnowledge';
import { NAV_ITEMS } from '../src/app/navigation';
import { KnowledgeNavItem } from '../src/components/shell/KnowledgeNavItem';
import { NavItem } from '../src/components/shell/NavItem';
import { Sidebar } from '../src/components/shell/Sidebar';
import { enUS } from '../src/i18n/messages/en-US';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { useNewChatStore } from '../src/stores/newChat';
import { useUiStore } from '../src/stores/ui';
import {
  createTestQueryClient,
  envelope,
  jsonResponse,
  renderApp,
  renderWithProviders,
  resetUiStore,
} from './helpers/render';

/**
 * 从词表里按点分键取文案。
 *
 * 期望值全部来自词表本身，而不是在用例里再抄一遍字符串：这样断言的是
 * "组件确实读了词表"；词条改文案时测试不用跟着改，不会变成第二份需要同步的真相。
 * 取不到键说明用例引用了不存在的键——直接抛错，好过让断言以一句莫名其妙的
 * "expected X received undefined" 失败。
 */
function messageOf(dictionary: unknown, key: string): string {
  let node: unknown = dictionary;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) {
      break;
    }
    node = (node as Record<string, unknown>)[segment];
  }
  if (typeof node !== 'string') {
    throw new Error(`词表里没有键 ${key}`);
  }
  return node;
}

/** 默认语言（zh-CN）下的文案，也是绝大多数用例的期望值来源。 */
const zh = (key: string): string => messageOf(zhCN, key);
/** 英文词表——只用来验证"语言换了，外壳跟着换"。 */
const en = (key: string): string => messageOf(enUS, key);

/**
 * 外壳测试会碰到的所有接口共用一个响应。
 *
 * 用例关心的是外壳结构，不是各接口各自的形状，所以给一个"哪个接口都读得下去"
 * 的信封就行：`items` 给专家页、`modules` 给模块宿主、`version` / `cosightHome`
 * 给设置弹窗读的健康信息。不打桩的话 jsdom 会去发真实请求，失败信息会变成一堆
 * 与被测组件毫无关系的网络报错。
 */
const ANY_API = {
  items: [],
  modules: [],
  invalid: [],
  status: 'ok',
  version: '0.0.0-test',
  uptimeSeconds: 0,
  cosightHome: '/tmp/cosight-test',
  database: 'sqlite',
};

/*
 * 但有三个接口这个信封喂不动，必须按路径单独给值——它们的 `data` **是裸数组**
 * （`GET /models` 返回 `ModelConfig[]`，不是 `{ models: [...] }`，服务端
 * sendOk(reply, await services.models.list()) 就是这么回的）。
 *
 * 对象喂过去不是"读不到数据"而是"读到了一个不是数组的东西"：设置弹窗里
 * `const models = list.data ?? []` 之后紧跟 `models.map(...)`，`{}` 既不是 null
 * 也没有 `map`，会直接抛错把整棵树交给路由的错误边界——表现出来的症状是
 * "设置弹窗打不开"，离真正的原因很远。所以这里给空数组，让弹窗走它的空态分支。
 */
const LIST_PATHS = new Set([
  '/api/models',
  '/api/workspaces',
  '/api/agent-proxies',
  '/api/rag-knowledge',
]);

/** 单例接口（当前生效的那一个）没有数据时返回 `null`，不是空数组也不是对象。 */
const NULLABLE_PATHS = new Set([
  '/api/models/active',
  '/api/workspaces/active',
  '/api/agent-proxies/default',
  '/api/rag-knowledge/active',
]);

function stubAnyApi(): void {
  const mock = vi.fn((input: string, init: RequestInit = {}) => {
    const pathname = new URL(input, 'http://localhost').pathname;
    // 只看 GET：写接口的返回体是单个对象，跟这里的形状规则不是一回事。
    if ((init.method ?? 'GET') === 'GET') {
      if (LIST_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope([])));
      }
      if (NULLABLE_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope(null)));
      }
    }
    return Promise.resolve(jsonResponse(envelope(ANY_API)));
  });
  vi.stubGlobal('fetch', mock);
}

/*
 * store 是模块级单例，一个用例里点开设置会把 `settingsOpen` 留给下一个用例。
 * 本文件有多条"点完之后 store 应该是什么"的断言，不复位的话失败信息会指向
 * 完全无关的另一条用例。
 */
beforeEach(() => {
  resetUiStore();
});

describe('NavItem', () => {
  it('首页项只在首页高亮：`end` 必须只给首页', () => {
    // 不给 `end` 的话 `/` 会匹配到所有路由，"新建对话"在任何页面上都显示为选中，
    // 侧栏于是同时出现两个高亮项。这条钉住的是"精确匹配只给首页"。
    renderWithProviders(<NavItem labelKey="nav.newChat" to="/" icon="newChat" collapsed={false} />, {
      route: '/',
    });

    expect(screen.getByRole('link', { name: zh('nav.newChat') })).toHaveAttribute('aria-current', 'page');
  });

  it('首页项在子路由上不高亮', () => {
    renderWithProviders(<NavItem labelKey="nav.newChat" to="/" icon="newChat" collapsed={false} />, {
      route: '/experts',
    });

    expect(screen.getByRole('link', { name: zh('nav.newChat') })).not.toHaveAttribute('aria-current');
  });

  it('非首页项在自己的路由上高亮', () => {
    renderWithProviders(<NavItem labelKey="nav.experts" to="/experts" icon="experts" collapsed={false} />, {
      route: '/experts',
    });

    expect(screen.getByRole('link', { name: zh('nav.experts') })).toHaveAttribute('aria-current', 'page');
  });

  it('已在首页时点击「新建对话」会请求重建模块（路由不变）', async () => {
    const user = userEvent.setup();
    renderWithProviders(<NavItem labelKey="nav.newChat" to="/" icon="newChat" collapsed={false} />, {
      route: '/',
    });

    await user.click(screen.getByRole('link', { name: zh('nav.newChat') }));

    // 同一路由的 Link 导航是 no-op；重建请求必须真的发出去，
    // 否则「新建对话」在对话中点击看起来毫无反应。
    expect(useNewChatStore.getState().nonce).toBe(1);
  });

  it('折叠态藏起文字，名称改由 title 承担', () => {
    // 图标按钮没有文字时，title 是读屏软件与鼠标悬停唯一能读到名称的地方，
    // 所以折叠态必须有它——否则导航项会变成一个不可名状的图标。
    renderWithProviders(<NavItem labelKey="nav.experts" to="/experts" icon="experts" collapsed />);

    const link = screen.getByRole('link', { name: zh('nav.experts') });
    expect(link).toHaveAttribute('title', zh('nav.experts'));
    expect(link).not.toHaveTextContent(zh('nav.experts'));
  });

  it('展开态不设 title，避免与可见文字重复', () => {
    renderWithProviders(<NavItem labelKey="nav.experts" to="/experts" icon="experts" collapsed={false} />);

    expect(screen.getByRole('link', { name: zh('nav.experts') })).not.toHaveAttribute('title');
  });
});

/** 只给 `/rag-knowledge/active` 指定响应；侧栏里还有别的查询（如当前工作区）。 */
function stubActive(response: () => Promise<unknown>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const pathname = new URL(input, 'http://localhost').pathname;
      return pathname === '/api/rag-knowledge/active'
        ? response()
        : Promise.resolve(jsonResponse(envelope({})));
    }),
  );
}

function renderKnowledgeItem(): void {
  renderWithProviders(
    <KnowledgeNavItem labelKey="nav.knowledge" icon="knowledge" collapsed={false} />,
  );
}

describe('KnowledgeNavItem（侧栏「知识库」）', () => {
  const KB = {
    id: '3f2a8c1e-6b8d-4a2f-9c31-0d5e7b2f4a10',
    name: '产品知识库',
    routeUrl: 'https://kb.example.com/kb/42',
    description: null,
    isActive: true,
    createdAt: '2026-01-01T00:00:00.000Z',
    updatedAt: '2026-01-01T00:00:00.000Z',
  };

  it('配好之后在新标签页打开配置的地址', async () => {
    stubActive(() => Promise.resolve(jsonResponse(envelope(KB))));
    renderKnowledgeItem();

    const link = await screen.findByRole('link', { name: zh('nav.knowledge') });
    expect(link).toHaveAttribute('href', KB.routeUrl);
    // 知识库是宿主之外的站点：交给浏览器新开标签页，不在宿主路由里嵌套。
    expect(link).toHaveAttribute('target', '_blank');
    // 新页面拿不到 window.opener，也不能把宿主地址放进 Referer。
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('即使停在 /knowledge，外链也不冒充当前页', async () => {
    stubActive(() => Promise.resolve(jsonResponse(envelope(KB))));
    renderWithProviders(
      <KnowledgeNavItem labelKey="nav.knowledge" icon="knowledge" collapsed={false} />,
      { route: '/knowledge' },
    );

    const link = await screen.findByRole('link', { name: zh('nav.knowledge') });
    // 目标地址是外站，与宿主当前停在哪一页无关：不能高亮成"当前页"。
    expect(link).toHaveAttribute('href', KB.routeUrl);
    expect(link).not.toHaveAttribute('aria-current');
  });

  it('没配置时点它直接打开设置里的新增表单，不再先弹一层提示', async () => {
    const user = userEvent.setup();
    stubActive(() => Promise.resolve(jsonResponse(envelope(null))));
    renderKnowledgeItem();

    // 等首次取数落定：忙碌期间点击只负责重取（见组件里的注释）。
    const item = await screen.findByRole('button', { name: zh('nav.knowledge') });
    await waitFor(() => {
      expect(item).not.toHaveAttribute('aria-busy');
    });
    await user.click(item);

    expect(screen.queryByRole('dialog')).toBeNull();
    // 落到知识库页签，并且直接展开「新增」——用户点菜单就是想添加一条能用的地址。
    expect(useUiStore.getState().settingsOpen).toBe(true);
    expect(useUiStore.getState().settingsTab).toBe('ragKnowledge');
    expect(useUiStore.getState().settingsCreateRequested).toBe(true);
  });

  it('读取失败时说读取失败，确认按钮是「重试」而不是把用户送去设置', async () => {
    const user = userEvent.setup();
    stubActive(() => Promise.reject(new TypeError('Failed to fetch')));
    renderKnowledgeItem();

    const item = await screen.findByRole('button', { name: zh('nav.knowledge') });
    await waitFor(() => {
      expect(item).not.toHaveAttribute('aria-busy');
    });
    await user.click(item);

    expect(
      await screen.findByRole('dialog', { name: zh('knowledgeRoute.loadFailedTitle') }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: zh('error.retry') })).toBeInTheDocument();
    // 这条地址可能配得好好的，只是后端没起来——不能说成"没配置"，更不该打开设置。
    expect(useUiStore.getState().settingsOpen).toBe(false);
  });

  it('设置保存后菜单立即变成链接，不用重启', async () => {
    const queryClient = createTestQueryClient();
    let body: unknown = null;
    stubActive(() => Promise.resolve(jsonResponse(envelope(body))));

    renderWithProviders(
      <KnowledgeNavItem labelKey="nav.knowledge" icon="knowledge" collapsed={false} />,
      { queryClient },
    );
    const item = await screen.findByRole('button', { name: zh('nav.knowledge') });
    await waitFor(() => {
      expect(item).not.toHaveAttribute('aria-busy');
    });

    // 模拟设置里保存成功：写操作后整组键失效（见 `api/ragKnowledge.ts`）。
    body = KB;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ragKnowledgeKeys.all });
    });

    expect(await screen.findByRole('link', { name: zh('nav.knowledge') })).toHaveAttribute(
      'href',
      KB.routeUrl,
    );
  });
});

describe('Sidebar', () => {
  it('把 NAV_ITEMS 全量渲染出来，链接地址与表的 `to` 一致', () => {
    renderWithProviders(<Sidebar />);

    const nav = screen.getByRole('navigation', { name: zh('app.navLabel') });
    /*
     * 「知识库」是唯一的例外：没有可用路由时没有页面可去，渲染成按钮
     * （点了直接打开设置里的新增表单），所以链接数比表少一项。
     */
    expect(within(nav).getAllByRole('link')).toHaveLength(NAV_ITEMS.length - 1);

    for (const item of NAV_ITEMS) {
      // 名称与地址都取自 NAV_ITEMS：组件只负责把表渲染出来，不该另有一份数据。
      if (item.labelKey === 'nav.knowledge') {
        expect(within(nav).getByRole('button', { name: zh(item.labelKey) })).toBeInTheDocument();
        continue;
      }
      expect(within(nav).getByRole('link', { name: zh(item.labelKey) })).toHaveAttribute('href', item.to);
    }
  });

  it('走真实路由表时，/experts 上只有专家项是当前页', async () => {
    stubAnyApi();
    renderApp('/experts');
    // 先等接口落定：React Query 在微任务里 setState，不等就会在 act() 之外观察到中间态。
    await screen.findByText(zh('module.missing.title'));

    const current = screen.getAllByRole('link', { current: 'page' });
    // 只该有一个。首页项一旦漏了 `end`，这里会变成两个——这正是加 `end` 要防的事。
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAccessibleName(zh('nav.experts'));
  });

  it('在首页时只有「新建对话」是当前页', async () => {
    stubAnyApi();
    renderApp('/');
    await screen.findByText(zh('module.missing.title'));

    const current = screen.getAllByRole('link', { current: 'page' });
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAccessibleName(zh('nav.newChat'));
  });

  it('折叠后只剩图标，每一项仍能被叫出名字', () => {
    renderWithProviders(<Sidebar />, { route: '/experts' });
    act(() => {
      useUiStore.setState({ sidebarCollapsed: true });
    });

    for (const item of NAV_ITEMS) {
      // 「知识库」在没配置时是按钮（点了打开设置新增）；两种元素的折叠规则必须一致。
      const element =
        item.labelKey === 'nav.knowledge'
          ? screen.getByRole('button', { name: zh(item.labelKey) })
          : screen.getByRole('link', { name: zh(item.labelKey) });
      expect(element).toHaveAttribute('title', zh(item.labelKey));
      expect(element).not.toHaveTextContent(zh(item.labelKey));
    }
  });

  it('折叠后品牌区与入口文字一起收起', () => {
    renderWithProviders(<Sidebar />);
    act(() => {
      useUiStore.setState({ sidebarCollapsed: true });
    });

    // 收起的是"文字块"，不是导航本身：字标、副标题、设置入口的文字都不再渲染。
    expect(screen.queryByText(zh('app.wordmark'))).toBeNull();
    expect(screen.queryByText(zh('app.subtitle'))).toBeNull();
    expect(screen.queryByText(zh('settings.title'))).toBeNull();
    // 但设置入口还在：折叠不该让用户失去打开设置的唯一入口（只剩齿轮图标）。
    expect(screen.getByRole('button', { name: zh('user.openSettings') })).toBeInTheDocument();
  });

  it('折叠按钮切换状态，图标与名字都不随状态变（对齐 dsh）', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    const toggle = screen.getByRole('button', { name: zh('app.toggleSidebar') });
    const icon = toggle.innerHTML;
    const expandedWidth = screen.getByRole('complementary').style.width;

    await user.click(toggle);
    expect(useUiStore.getState().sidebarCollapsed).toBe(true);

    const after = screen.getByRole('button', { name: zh('app.toggleSidebar') });
    // 名字不随状态变：用户点之前就得知道这个按钮是什么，变了反而认不出来。
    // 图标也不变——deepseek-harness 在展开态、折叠态、完全隐藏后的展开按钮上
    // 用的是同一个 `panelLeft` 图标，需求 UX-1 要的就是"和它保持一致"。
    // 所以状态反馈落在**侧栏宽度**上，而不是按钮自己的外观上。
    expect(after.innerHTML).toBe(icon);
    expect(screen.getByRole('complementary').style.width).not.toBe(expandedWidth);

    await user.click(after);
    expect(useUiStore.getState().sidebarCollapsed).toBe(false);
    // 展开回来宽度要回到原来的值，不是停在折叠态的 56px。
    expect(screen.getByRole('complementary').style.width).toBe(expandedWidth);
  });

  it('导航有可访问名，侧栏里没有标题元素', () => {
    renderWithProviders(<Sidebar />);

    expect(screen.getByRole('navigation', { name: zh('app.navLabel') })).toBeInTheDocument();

    // 侧栏不是一个内容章节：出现 <h2> 之类会让读屏软件的大纲里凭空多出层级。
    // 直接断言一个标题元素都没有，比逐个排除 h1..h6 更严密。
    expect(screen.queryAllByRole('heading')).toHaveLength(0);
  });

  it('底部设置入口点击后打开设置', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    const row = screen.getByRole('button', { name: zh('user.openSettings') });
    /*
     * 入口显示的是「设置」而不是用户名：v1 无登录（D25），从前那一行上的头像 + "本地用户"
     * 是永远不变的装饰，点起来和别的东西没有任何区别。可访问名仍取 `user.openSettings`
     * （"打开设置"包含可见的"设置"，符合 Label in Name）。
     */
    expect(row).toHaveTextContent(zh('settings.title'));

    await user.click(row);
    expect(useUiStore.getState().settingsOpen).toBe(true);
  });

  it('语言切换后侧栏文案跟着换', async () => {
    stubAnyApi();
    renderApp('/experts');
    await screen.findByText(zh('module.missing.title'));

    act(() => {
      useUiStore.setState({ locale: 'en-US' });
    });

    // 侧栏订阅的是 store 里的 locale，不是启动时抓一次的快照。
    expect(screen.getByRole('link', { name: en('nav.experts') })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: zh('nav.experts') })).toBeNull();
  });
});

describe('AppShell', () => {
  it('跳转链接指向 <main>，且 <main> 可以被聚焦', async () => {
    stubAnyApi();
    renderApp('/experts');
    await screen.findByText(zh('module.missing.title'));

    const main = screen.getByRole('main');
    // 直接把 href 与 main 的 id 对起来：两边各自改动而没同步时，这条会红。
    expect(screen.getByRole('link', { name: zh('app.skipToContent') })).toHaveAttribute(
      'href',
      `#${main.id}`,
    );
    // 没有 tabIndex={-1} 的目标元素无法被 href="#id" 聚焦，跳转链接就只是装饰。
    expect(main).toHaveAttribute('tabindex', '-1');
  });

  it('设置弹窗按 settingsOpen 挂载', async () => {
    stubAnyApi();
    renderApp('/experts');
    await screen.findByText(zh('module.missing.title'));

    // 关闭时不挂载：弹窗本体（含健康检查请求）在没有打开之前不该存在。
    expect(screen.queryByRole('dialog')).toBeNull();

    act(() => {
      useUiStore.setState({ settingsOpen: true });
    });

    const dialog = await screen.findByRole('dialog');
    // 顺带等弹窗里的健康检查落定，否则用例结束后才发生的更新会打在 act() 之外。
    expect(await within(dialog).findByText(ANY_API.version)).toBeInTheDocument();
  });

  it('页面内容经 <Outlet /> 渲染进 <main>', async () => {
    stubAnyApi();
    renderApp('/experts');

    const main = screen.getByRole('main');
    // 页面内容在 <main> 之内：外壳负责容器，页面（这里是模块宿主）只管内容。
    expect(await within(main).findByText(zh('module.missing.title'))).toBeInTheDocument();
  });

  it('<html lang> 跟随语言变化', async () => {
    stubAnyApi();
    renderApp('/experts');
    await screen.findByText(zh('module.missing.title'));

    // 默认语言来自 store（resetUiStore 复位成 zh-CN），映射表在契约包里。
    expect(document.documentElement.lang).toBe(LOCALE_HTML_LANG['zh-CN']);

    act(() => {
      useUiStore.setState({ locale: 'en-US' });
    });

    // 挂在外壳上才生效：lang 决定读屏软件用哪种语音读整页，
    // 切到英文后还留 zh-CN 会让整页被按中文朗读。
    expect(document.documentElement.lang).toBe(LOCALE_HTML_LANG['en-US']);
  });
});
