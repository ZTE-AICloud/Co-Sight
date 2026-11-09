/**
 * SettingsDialog：可访问性语义、页签键盘、焦点管理，以及"哪些是真功能、哪些是诚实占位"。
 *
 * 组件级用例走 `renderWithProviders`：弹窗与外壳是解耦的——它只读 zustand 里的
 * `settingsTab`，"开关"在 AppShell 手里。挂整个应用只会让这些用例白白多背上
 * 首页模块宿主的那一次 `/api/modules` 请求。
 *
 * 但**焦点管理**那两条必须走 `renderApp`：它们要有一个真实的触发元素和一次真实的
 * 卸载。"关闭后焦点回到打开它的按钮"只有真的点了那个按钮才算数；自己搭一个假的
 * 开合宿主，测的就成了自己写的那段假实现。
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsDialog } from '../src/components/shell/SettingsDialog';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { SETTINGS_TABS, useUiStore } from '../src/stores/ui';
import {
  envelope,
  jsonResponse,
  renderApp,
  renderWithProviders,
  resetUiStore,
  stubFetchRejected,
  type FakeResponse,
} from './helpers/render';

/**
 * 页签文案从词表取而不是在测试里再抄一份：这里要钉的是"点哪个页签切到哪块内容"，
 * 不是文案本身。文案写死在测试里，将来改一个字就会让这些用例以"找不到元素"失败，
 * 失败信息指向的是无关的方向。
 */
const TAB_LABELS = zhCN.settings.nav;

const COSIGHT_HOME = '/home/x/.cosight-harness';
const VERSION = '0.1.0';

const MODULES_EMPTY = envelope({ modules: [], invalid: [] });
const HEALTH_OK = envelope({
  status: 'ok',
  version: VERSION,
  uptimeSeconds: 1,
  cosightHome: COSIGHT_HOME,
  database: 'sqlite',
});

/** 两个常驻取数的配置面板的列表接口（内容不重要：本文件测的是弹窗与页签，不是面板本身）。 */
const MODELS_EMPTY = envelope([]);
const RAG_KB_EMPTY = envelope([]);

/** Agent 代理面板直连 smart-factory 的 `/engine/detail`（裸 JSON，无框架信封）。 */
const ENGINE_DETAIL = {
  engine: 'claude-cli',
  cwd: '/home/me/work',
  version: '2.1.311',
  commandCount: 24,
};

/**
 * 按 `METHOD 路径` 分派 fetch 打桩（与 `module-host.test.tsx` 的 `stubRoutes` 同形）。
 *
 * 在这里按路由分发有两个理由：
 *
 * - 设置弹窗里的模型 / 知识库两个面板**一挂载就各拉一次列表**（与当前停在哪个页签
 *   无关，理由见 `SettingsDialog` 里那段注释），再算上弹窗自己的 `/api/health`，
 *   打开设置就是三个接口；Agent 代理面板只在切到它的页签时才取引擎详情。
 *   用固定响应的话，面板会把一份"健康信息"当成列表拿到手，渲染时炸掉。
 * - 走 `renderApp` 的用例还要再加上应用外壳的订阅（侧栏的 `/api/workspaces/active`）。
 *   用 `stubFetchSequence` 按到达顺序发牌的话，外壳那一枪会把牌吃掉，失败方向指向
 *   完全无关的地方——`module-host.test.tsx` 里踩过一次，这条注释就是那次留下的路标。
 *
 * 未准备的路由直接 reject：多出来的请求是"用例没预料的调用"，应该立刻说出来。
 */
function stubApi(routes: Record<string, FakeResponse>): ReturnType<typeof vi.fn> {
  const mock = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input, 'http://localhost');
    const key = `${init?.method ?? 'GET'} ${url.pathname}`;
    const response = routes[key];
    if (response === undefined) {
      return Promise.reject(new Error(`用例没有打桩这个路由：${key}`));
    }
    return Promise.resolve(response);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

/**
 * 弹窗本体需要的接口（健康检查 + 模型 / 知识库列表 + Agent 代理的引擎详情）。
 * `health` 可换成别的响应（失败档）。
 *
 * 引擎详情虽然不一定被请求（面板只在切到 Agent 代理页签时才取数），这里照样桩上：
 * 切了页签的用例不该因为"路由没准备"而红，而"该不该请求"由专门那条用例钉住。
 *
 * 不含 `/api/workspaces/active`：这个 `beforeEach` 下的用例用 `renderWithProviders`
 * 渲染，没有外壳、也就没有那次订阅。真多出来请求的话，让它按"未准备的路由"报出来
 * 比悄悄兜住更好。
 */
function stubDialogApi(health: FakeResponse = jsonResponse(HEALTH_OK)): ReturnType<typeof vi.fn> {
  return stubApi({
    'GET /api/health': health,
    'GET /api/models': jsonResponse(MODELS_EMPTY),
    'GET /api/rag-knowledge': jsonResponse(RAG_KB_EMPTY),
    'GET /api/smart-factory/v1/engine/detail': jsonResponse(ENGINE_DETAIL),
  });
}

/** 三个 panel 都在 DOM 里（未激活的用 `hidden` 藏起来），按 id 取回。 */
function panelsById(): Map<string, HTMLElement> {
  return new Map(
    screen.getAllByRole('tabpanel', { hidden: true }).map((panel) => [panel.id, panel]),
  );
}

describe('SettingsDialog — 弹窗语义与页签', () => {
  beforeEach(() => {
    /*
     * 必须显式复位：store 初值取自 `navigator.languages`，而 jsdom 报的是 `en-US`，
     * 于是不复位的话本文件里所有按中文名查询的断言都会找不到元素——失败信息看起来
     * 像是文案写错了，实际是语言环境不对。
     */
    resetUiStore();
    stubDialogApi();
  });

  it('是一个带可访问名的模态对话框，名字来自标题元素', () => {
    renderWithProviders(<SettingsDialog />);

    const dialog = screen.getByRole('dialog');
    // aria-modal 是"遮罩后面不该被读到"的声明；少它的话读屏软件仍会把侧栏念出来。
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName(zhCN.settings.title);

    /*
     * 断言 aria-labelledby 指向标题元素本身，而不是只断言"可访问名对得上"。
     * 后者靠的是同一个字符串被写了两遍（id 的引用 + 标题文本），将来改标题时
     * 两处会漂；前者钉住的是"名字只有一个来源"。
     */
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBe('settings-title');
    expect(document.getElementById(labelledBy ?? '')).toHaveTextContent(zhCN.settings.title);
  });

  it('每个页签与每个 panel 一一对应，未激活的用 hidden 藏起（全部渲染）', () => {
    renderWithProviders(<SettingsDialog />);

    const tablist = screen.getByRole('tablist');
    expect(tablist).toHaveAttribute('aria-orientation', 'vertical');

    /*
     * 页签顺序必须等于 SETTINGS_TABS：这份列表同时是 openSettings(tab) 的合法取值来源，
     * 顺序写反会让"打开到模型设置"落到别的页签上，而视觉上只是左右两个按钮换了位置，
     * 很难在评审里看出来。
     */
    expect(within(tablist).getAllByRole('tab').map((tab) => tab.id)).toEqual(
      SETTINGS_TABS.map((value) => `settings-tab-${value}`),
    );

    /*
     * 所有 panel 全部渲染、只隐藏。这条钉的是"隐藏"而不是"条件渲染"：
     * 换成 `{tab === 'x' && <section/>}` 时下面的 hidden:true 查询会立刻变成 1，
     * 而只断言"当前 panel 可见"的话，两种实现都通过。
     */
    const panels = panelsById();
    expect(panels.size).toBe(SETTINGS_TABS.length);
    // 对可访问性树而言只有当前页签的那一块存在，读屏软件不会念到另外两块。
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);

    for (const value of SETTINGS_TABS) {
      const tab = screen.getByRole('tab', { name: TAB_LABELS[value] });
      expect(tab).toHaveAttribute('aria-controls', `settings-panel-${value}`);
      expect(tab).toHaveAttribute('aria-selected', String(value === 'general'));
      expect(panels.get(`settings-panel-${value}`)).toHaveAttribute('aria-labelledby', tab.id);
    }

    expect(panels.get('settings-panel-general')).not.toHaveAttribute('hidden');
    expect(panels.get('settings-panel-model')).toHaveAttribute('hidden');
    expect(panels.get('settings-panel-agentProxy')).toHaveAttribute('hidden');
  });

  it('点击页签切换：store 的 settingsTab 变化，对应 panel 变为可见', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsDialog />);

    await user.click(screen.getByRole('tab', { name: TAB_LABELS.model }));

    expect(useUiStore.getState().settingsTab).toBe('model');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-model');
    expect(screen.getByRole('tab', { name: TAB_LABELS.general })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('初始页签由 store 决定（面板关掉后原样重开）', () => {
    useUiStore.setState({ settingsTab: 'agentProxy' });
    renderWithProviders(<SettingsDialog />);

    expect(screen.getByRole('tab', { name: TAB_LABELS.agentProxy })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-agentProxy');
  });

  it('方向键 / Home / End 移动即激活，焦点跟着走', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsDialog />);

    // 整组只有一个 Tab 停靠点，所以要从当前选中项出发才符合真实键盘路径。
    screen.getByRole('tab', { name: TAB_LABELS.general }).focus();

    await user.keyboard('{ArrowDown}');
    expect(useUiStore.getState().settingsTab).toBe('model');
    expect(screen.getByRole('tab', { name: TAB_LABELS.model })).toHaveFocus();
    // "移动即激活"：焦点换了但内容区没换，是这类控件最常见的实现错位。
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-model');

    // 末项是「观测设置」（SETTINGS_TABS 的最后一项）；`End` 落到它。
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: TAB_LABELS.observation })).toHaveFocus();
    expect(useUiStore.getState().settingsTab).toBe('observation');

    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: TAB_LABELS.general })).toHaveFocus();
    expect(useUiStore.getState().settingsTab).toBe('general');

    // 两端循环：在首项上再往前，应落到末项而不是卡住。
    await user.keyboard('{ArrowUp}');
    expect(useUiStore.getState().settingsTab).toBe('observation');
    expect(screen.getByRole('tab', { name: TAB_LABELS.observation })).toHaveFocus();
  });

  it('Esc 关闭弹窗，焦点在页签上时同样有效', async () => {
    const user = userEvent.setup();
    // 先把开关摆成"已打开"：否则初始值本来就是 false，这个断言无论 Esc 有没有用都会通过。
    useUiStore.setState({ settingsOpen: true });
    renderWithProviders(<SettingsDialog />);

    /*
     * Esc 的监听挂在遮罩层上，靠事件冒泡从弹窗内部收上来。先让焦点落在页签按钮
     * （而不是弹窗容器）上，验证的是"焦点停在哪个子元素上都关得掉"——任何一层
     * 顺手写的 stopPropagation 都会让这里失败。
     */
    screen.getByRole('tab', { name: TAB_LABELS.general }).focus();
    await user.keyboard('{Escape}');

    expect(useUiStore.getState().settingsOpen).toBe(false);
  });

  it('点遮罩关闭，点弹窗内部不关闭', async () => {
    const user = userEvent.setup();
    useUiStore.setState({ settingsOpen: true });
    renderWithProviders(<SettingsDialog />);

    // 遮罩是 role="presentation"：它对可访问性树不可见，但确实是一个可点的元素。
    const overlay = screen.getByRole('presentation');
    const dialog = screen.getByRole('dialog');

    await user.click(within(dialog).getByRole('heading', { name: zhCN.settings.general.aboutSection }));
    expect(useUiStore.getState().settingsOpen).toBe(true);

    await user.pointer({ keys: '[MouseLeft]', target: overlay });
    expect(useUiStore.getState().settingsOpen).toBe(false);
  });
});

describe('SettingsDialog — 通用设置是真功能', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('语言切换写进 store，并且界面立刻换语言', async () => {
    const user = userEvent.setup();
    const mock = stubDialogApi();
    renderWithProviders(<SettingsDialog />);

    const group = within(screen.getByRole('tabpanel')).getByRole('radiogroup', {
      name: zhCN.settings.general.language,
    });
    expect(within(group).getByRole('radio', { name: '简体中文' })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    await user.click(within(group).getByRole('radio', { name: 'English' }));

    /*
     * 断言 store 而不是只看界面文字变了：语言是全局状态（D28），界面换了而 store
     * 没换的话，当下看起来正常，问题要等到"刷新后变回中文"才暴露——而那时候
     * 排查的人多半不会想到设置弹窗。
     */
    expect(useUiStore.getState().locale).toBe('en-US');
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeInTheDocument();

    // 语言名自译：中文用户找 "English"、英文用户找 "简体中文"，所以两个标签
    // 在任何界面语言下都不翻译。翻成 "英语" 会让英文用户在自家界面里找不到自己的语言。
    expect(within(group).getByRole('radio', { name: '简体中文' })).toBeInTheDocument();

    /*
     * 原本钉的是"这一次渲染只打了 /api/health"（`callUrl(mock, 0)`）。现在设置里
     * 多了几个一挂载就拉列表的面板，请求不再只有一个，所以要保住的含义换一种说法：
     *
     * - 通用设置的信息来自服务端（`/api/health` 确实被打了），不是写死在界面里；
     * - 切语言**只改本机状态**（D28），不产生任何写请求。
     *
     * 第二条按"全是 GET"来断言，而不是逐个列 URL 白名单：白名单每加一个只读接口
     * 就会红一次（外壳新增一次订阅就够），而红的原因与本用例要测的行为无关。
     */
    const urls = mock.mock.calls.map((call) => String(call[0]));
    expect(urls).toContain('/api/health');
    expect(mock.mock.calls.filter((call) => (call[1]?.method ?? 'GET') !== 'GET')).toHaveLength(0);
  });

  it('显示服务端实际生效的数据目录与版本', async () => {
    stubDialogApi();
    renderWithProviders(<SettingsDialog />);

    /*
     * 显示的是服务端给的路径，不是配置模板里的默认值：COSIGHT_HOME 配错时，
     * 这里往往是唯一能一眼看出实际生效值的地方，所以断言的是服务端返回的那个字符串。
     */
    const home = await screen.findByText(COSIGHT_HOME);
    // title 兜住长路径被样式截断的情况（样式负责截断，title 负责仍可读全）。
    expect(home).toHaveAttribute('title', COSIGHT_HOME);
    expect(screen.getByText(VERSION)).toBeInTheDocument();
  });

  it('拿不到健康数据时显示占位符，而不是编造目录与版本', async () => {
    stubFetchRejected();
    renderWithProviders(<SettingsDialog />);

    /*
     * 后端没起来时两处都必须是 '—'。这条防的是"给个看起来合理的默认值"——
     * 那样用户配错 COSIGHT_HOME 时看到的会是默认路径，误以为配置生效了。
     */
    expect(await screen.findAllByText('—')).toHaveLength(2);
    expect(screen.queryByText(COSIGHT_HOME)).toBeNull();
  });
});

describe('SettingsDialog — 模型设置 / RAG 知识库 / Agent 代理配置是真面板', () => {
  beforeEach(() => {
    resetUiStore();
    stubDialogApi();
  });

  /*
   * 这两条原本钉的是"页签里写的是『待接入』的诚实说明，不是假表单"。
   * 两个面板现在已经落地，所以断言反过来了：切过去必须看到**真的配置面板**。
   * 断言里仍然保留"待接入"那几个字的不存在检查——那是同一条防线的另一半：
   * 界面接好了而说明没删干净的话，用户会看到"尚未接入"压在一个能用的表单上。
   */
  it.each([
    ['model', zhCN.settings.model.listSection, zhCN.settings.model.create],
    ['ragKnowledge', zhCN.settings.ragKnowledge.listSection, zhCN.settings.ragKnowledge.create],
    // Agent 代理配置本期只读展示本机 Claude Code，没有「新增」入口，第三个位置留 `null`。
    ['agentProxy', zhCN.settings.agentProxy.currentSection, null],
  ] as const)('%s 页签里是真的配置面板，不再是"待接入"说明', async (tab, section, create) => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsDialog />);
    await user.click(screen.getByRole('tab', { name: TAB_LABELS[tab] }));

    const panel = screen.getByRole('tabpanel');
    // 小节标题：在"待接入"说明里不可能出现。
    expect(within(panel).getByRole('heading', { name: section })).toBeInTheDocument();
    if (create === null) {
      // 有面板却没有列表小节标题的话，下面那条否定断言会"因为页面是空的"而通过，
      // 所以这里换成正向的锚点：列表标题必须在，且没有「新增」按钮。
      expect(within(panel).queryByRole('button', { name: /新增/ })).toBeNull();
    } else {
      expect(within(panel).getByRole('button', { name: create })).toBeInTheDocument();
    }

    expect(within(panel).queryByText('该模块尚未接入这一版')).toBeNull();
    expect(within(panel).queryByText('后端接口已就绪，界面按排期在后续版本补齐。')).toBeNull();
  });

  it('面板常挂但按页签取数：打开设置不打引擎接口，切到 Agent 代理页签才打', async () => {
    /*
     * 面板是**常驻挂载**的（隐藏而非条件渲染），但引擎详情不是普通列表：取一次就会让
     * smart-factory 起一个 Claude Code 探测进程（1–2 秒、200MB+）。这里钉两件事：
     * 打开设置停在通用页签时不请求它；切到 Agent 代理页签后才请求、并显示引擎名。
     */
    const user = userEvent.setup();
    const mock = stubDialogApi();
    renderWithProviders(<SettingsDialog />);

    await screen.findByText(zhCN.settings.model.empty.title);
    await screen.findByText(zhCN.settings.ragKnowledge.empty.title);

    const urls = (): string[] => mock.mock.calls.map((call) => String(call[0]));
    expect(urls()).toContain('/api/models');
    expect(urls()).toContain('/api/rag-knowledge');
    expect(urls()).not.toContain('http://127.0.0.1:4100/api/smart-factory/v1/engine/detail');

    await user.click(screen.getByRole('tab', { name: TAB_LABELS.agentProxy }));

    // Agent 代理面板没有空态：数据到手后直接显示引擎名。
    expect(
      await screen.findByText(zhCN.settings.agentProxy.engine.claudeAgentSdk),
    ).toBeInTheDocument();
    expect(urls()).toContain('http://127.0.0.1:4100/api/smart-factory/v1/engine/detail');
  });

  it('通用设置页签与三个配置页签不同：它确实有可交互控件', async () => {
    // 上一条只证明"配置面板出现了"，如果没有这一条，把几个页签都做成同一个面板也能过。
    renderWithProviders(<SettingsDialog />);

    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getAllByRole('radio')).toHaveLength(2);
  });
});

describe('SettingsDialog — 焦点管理（走真实外壳）', () => {
  beforeEach(() => {
    resetUiStore();
    /*
     * 走 `renderApp` 的用例：首页的模块宿主先打 /api/modules，外壳同时会为侧栏底部的
     * 「工作区设置」入口订一次当前工作区，弹窗要等用户点开设置才挂载、才打 /api/health
     * 与模型 / 知识库两个面板的列表（Agent 代理的引擎详情只在切到它的页签时才取）。
     * 按路由分发，免得用例被"谁先发"绑住。
     */
    stubApi({
      'GET /api/modules': jsonResponse(MODULES_EMPTY),
      'GET /api/health': jsonResponse(HEALTH_OK),
      'GET /api/models': jsonResponse(MODELS_EMPTY),
      'GET /api/rag-knowledge': jsonResponse(RAG_KB_EMPTY),
      'GET /api/smart-factory/v1/engine/detail': jsonResponse(ENGINE_DETAIL),
      // 还没有工作区:`envelope(null)` 才是"一个都没有"的真实形状。
      'GET /api/workspaces/active': jsonResponse(envelope(null)),
      // 侧栏「最近」：外壳级请求，与设置弹窗无关，给空列表即可。
      'GET /api/smart-factory/v1/sessions/list': jsonResponse({ items: [], total: 0 }),
    });
  });

  it('打开时焦点进入弹窗，关闭后回到触发它的元素', async () => {
    const user = userEvent.setup();
    renderApp('/');

    const trigger = screen.getByRole('button', { name: zhCN.user.openSettings });
    await user.click(trigger);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveFocus();

    await user.keyboard('{Escape}');

    // 弹窗由 AppShell 按开关卸载，所以这里能一并验证"关掉后从 DOM 里消失"。
    expect(screen.queryByRole('dialog')).toBeNull();
    /*
     * 焦点要还回触发按钮。不还的话焦点会掉到 <body>，键盘用户关掉弹窗后按 Tab
     * 会从页面最开头重新走一遍整个侧栏——这一步是本文件里最值得钉死的一条。
     */
    expect(trigger).toHaveFocus();
  });

  it('Tab 在弹窗内部正常前进，不被焦点陷阱吞掉', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await user.click(screen.getByRole('button', { name: zhCN.user.openSettings }));

    const dialog = screen.getByRole('dialog');
    await user.tab();
    expect(screen.getByRole('button', { name: zhCN.settings.close })).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    await user.tab();
    expect(screen.getByRole('tab', { name: TAB_LABELS.general })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole('radio', { name: '简体中文' })).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it('焦点陷阱：Tab 一圈后回到弹窗首项，不跑到遮罩背后', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await user.click(screen.getByRole('button', { name: zhCN.user.openSettings }));

    const dialog = screen.getByRole('dialog');
    const close = screen.getByRole('button', { name: zhCN.settings.close });
    const generalTab = screen.getByRole('tab', { name: TAB_LABELS.general });
    // 弹窗里真正能 Tab 到的只有三个：关闭按钮 → 选中页签 → 选中语言。
    // 其余页签与语言都是 tabIndex=-1，不进 Tab 序列；隐藏 panel 里的元素也不算。
    const lastTabbable = screen.getByRole('radio', { name: '简体中文' });

    await user.tab();
    expect(close).toHaveFocus();
    await user.tab();
    expect(generalTab).toHaveFocus();
    await user.tab();
    expect(lastTabbable).toHaveFocus();

    /*
     * 从**最后一个真实可 Tab 到的元素**再按一次 Tab 必须环绕回首项。
     * 这是本用例的核心：实现曾把 tabIndex=-1 的「English」单选误当成末项，
     * 于是一个真实用户按到这里时这个分支永远不成立，焦点直接掉到遮罩背后的侧栏上。
     */
    await user.tab();
    expect(close).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it('焦点陷阱：刚打开时 Shift+Tab 不会退到遮罩背后的触发按钮', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const trigger = screen.getByRole('button', { name: zhCN.user.openSettings });
    await user.click(trigger);

    // 挂载时焦点在面板容器（tabIndex=-1）上，反向环绕必须把容器也算作起点。
    expect(screen.getByRole('dialog')).toHaveFocus();

    await user.tab({ shift: true });

    expect(screen.getByRole('radio', { name: '简体中文' })).toHaveFocus();
    expect(trigger).not.toHaveFocus();
  });
});
