/**
 * 客户端 UI 状态（D6 = A：Zustand）。
 *
 * **这里只放客户端状态。** 服务端状态（专家列表、模型配置、工作区）一律走
 * TanStack Query（D5 = A），两者不要混：把服务端数据塞进 Zustand 会立刻产生
 * "这份数据归谁刷新"的争论，而缓存、失效、重试正是 Query 已经解决的问题。
 *
 * 三条边界，判断某个状态该不该进来：
 *   1. 刷新页面后**仍然应该保留** → 进 store（并持久化）
 *   2. 只影响当前这一屏、关掉就没了 → 用 useState
 *   3. 服务端也有 → 不进 store，走 Query
 *
 * 持久化只保留 `locale`：侧栏折叠、侧栏与工作区文件面板的宽度、以及各个面板的开关，
 * 都属于"当前会话的临时姿态"，跨会话记住反而奇怪（下次打开看到一个自己上次随手折叠过、
 * 或拖窄过一半的侧栏，会以为坏了）。
 *
 * 语言的持久化**只有 persist 这一条写入路径**。不要另外再往 localStorage 手写一份：
 * persist 用的是同步 storage，创建 store 时就完成 rehydrate，不存在"先按默认语言
 * 渲染再跳变"的问题，两套写入只会制造两个真相。
 */

import { DEFAULT_LOCALE } from 'harness-shared';
import type { Locale } from 'harness-shared';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { detectInitialLocale } from '../i18n/translate';
import { clampSidebarWidth, SIDEBAR_DEFAULT_WIDTH } from '../lib/sidebarWidth';

/**
 * 设置弹窗的页签，顺序即显示顺序。
 *
 * `ragKnowledge` 排在「模型设置」之后、「Agent 代理配置」之前：它和模型一样属于
 * "框架提供、各模块消费"的配置，读起来是同一类；代理则是执行侧的设置。
 */
export const SETTINGS_TABS = [
  'general',
  'model',
  'ragKnowledge',
  'agentProxy',
  'observation',
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number];

/** `openSettings` 的附加意图，目前只有「打开后直接展开新增表单」。 */
export interface OpenSettingsOptions {
  /**
   * 打开设置后直接展开该页签的「新增」表单。
   *
   * 用于侧栏「知识库」在**一条可用路由都没有**时的入口：用户点菜单是想看知识库，
   * 把他丢到设置列表再让他自己找「新增」是多余的一步。
   */
  create?: boolean;
}

export interface UiState {
  /** 界面语言（D28 = B）。 */
  locale: Locale;
  setLocale: (locale: Locale) => void;

  /** 侧栏折叠。稿中折叠图标在字标左侧 (24,27)。 */
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;

  /**
   * 展开态侧栏宽度（UX-2：分割线可拖拽）。
   *
   * 与 `sidebarCollapsed` 一样**不持久化**（见文件头的三条边界）：宽度是"当前这一屏
   * 临时摆出来的姿态"，下次打开看到一条上次随手拖窄的侧栏，与看到折叠的侧栏是同一类困惑。
   * 折叠态不覆盖这个值——展开回来时还是拖拽后那个宽度，不然折叠一下就把用户的调整弄丢了。
   */
  sidebarWidth: number;
  setSidebarWidth: (width: number) => void;

  /** 底部设置面板（C3 的应用级入口）。 */
  settingsOpen: boolean;
  /** 当前页签；面板关闭后仍保留，便于原样重新打开。 */
  settingsTab: SettingsTab;
  /**
   * 打开设置时附带的「直接展开新增表单」请求。面板消费后立刻清掉，
   * 否则下一次普通打开设置又会莫名其妙地停在一个空表单上。
   */
  settingsCreateRequested: boolean;
  openSettings: (tab?: SettingsTab, options?: OpenSettingsOptions) => void;
  closeSettings: () => void;
  setSettingsTab: (tab: SettingsTab) => void;
  clearSettingsCreateRequest: () => void;

  /**
   * 工作区弹窗（P3）。
   *
   * 与 `settingsOpen` 一样放在 store 而不是侧栏的局部 state：**弹窗由外壳渲染**
   * （见 AppShell），触发它的按钮在侧栏里，两者是兄弟节点，状态只能放在它们之上。
   * 不放"当前工作区"的副本——那个走服务端（`/workspaces/active`），见 api/workspaces.ts。
   */
  workspaceOpen: boolean;
  openWorkspace: () => void;
  closeWorkspace: () => void;
}

/**
 * 首次启动的语言：优先浏览器语言，判断不出来才用默认值。
 *
 * 直接读 `navigator` 而不是等一个 effect——首帧就要用正确的语言渲染，
 * 否则中文用户会看到一次英文闪烁。
 */
function detectLocale(): Locale {
  return detectInitialLocale(
    null,
    typeof navigator === 'undefined' ? [] : navigator.languages,
  );
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      locale: detectLocale(),
      setLocale: (locale) => {
        set({ locale });
      },

      sidebarCollapsed: false,
      toggleSidebar: () => {
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed }));
      },

      sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
      setSidebarWidth: (width) => {
        // 夹取放在 store 里而不是只放在手柄里：键盘、拖拽、将来的"恢复默认"三条路径
        // 都得过这一关，放在唯一的写入点上就不会有人漏掉。
        set({ sidebarWidth: clampSidebarWidth(width) });
      },

      settingsOpen: false,
      settingsTab: 'general',
      settingsCreateRequested: false,
      openSettings: (tab, options) => {
        set((state) => ({
          settingsOpen: true,
          // 不传页签 = 沿用上次停留的那一页（原行为）。
          settingsTab: tab ?? state.settingsTab,
          settingsCreateRequested: options?.create ?? false,
        }));
      },
      closeSettings: () => {
        // 关掉弹窗时一并丢掉未消费的「展开新增」请求：它只对这一次打开有效。
        set({ settingsOpen: false, settingsCreateRequested: false });
      },
      setSettingsTab: (tab) => {
        set({ settingsTab: tab });
      },
      clearSettingsCreateRequest: () => {
        set({ settingsCreateRequested: false });
      },

      workspaceOpen: false,
      openWorkspace: () => {
        set({ workspaceOpen: true });
      },
      closeWorkspace: () => {
        set({ workspaceOpen: false });
      },
    }),
    {
      name: 'cosight.ui',
      version: 1,
      // 只持久化 locale。默认 merge 就是 `{...current, ...persisted}`，
      // 恰好是想要的语义：有存过的值就用存过的，没有就用 detectLocale 的结果。
      partialize: (state) => ({ locale: state.locale }),
    },
  ),
);

/** 语言默认值，导出便于测试与"恢复默认"使用。 */
export const FALLBACK_LOCALE = DEFAULT_LOCALE;
