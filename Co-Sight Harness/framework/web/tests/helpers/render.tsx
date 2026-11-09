/**
 * 测试用的渲染与打桩工具。
 *
 * 这里解决三个每个测试文件都会碰到的问题：Provider 套哪几层、Query 缓存怎么隔离、
 * 以及"后端返回什么"怎么造。三件事各写一遍的话，二十个测试文件里会漂出三种写法。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import { DEFAULT_LOCALE, type PageMeta } from 'harness-shared';
import type { ReactElement, ReactNode } from 'react';
import {
  createMemoryRouter,
  MemoryRouter,
  RouterProvider,
  type RouteObject,
} from 'react-router';
import { vi } from 'vitest';

import { routes } from '../../src/app/routes';
import { SIDEBAR_DEFAULT_WIDTH } from '../../src/lib/sidebarWidth';
import { useNewChatStore } from '../../src/stores/newChat';
import { useUiStore } from '../../src/stores/ui';

/**
 * 测试用 Query 客户端。
 *
 * 与生产配置**故意不同**的三处：
 * - `retry: false`：生产会重试一次，测试里重试只会让失败用例慢一倍、
 *   并把"第一次就失败了"这件事藏起来；
 * - `staleTime: Infinity` + `gcTime: Infinity`：测试关心的是"给定数据渲染成什么"，
 *   不关心缓存什么时候过期。让缓存稳定，用例之间才不会互相干扰；
 * - 每个用例新建一个客户端。**不要**复用 `src/api/queryClient.ts` 的单例：
 *   它会跨用例保留数据，出现"这个用例看到了上个用例造的专家"这种幽灵失败。
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY, gcTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });
}

/**
 * 把 zustand store 恢复到初值。走 persist 的 store 会把语言写进 localStorage。
 *
 * `sidebarWidth` 也要复位：store 是模块级单例，"拖过侧栏"的用例会把宽度留给
 * **下一个文件**里的用例（跨文件隔离不了单例），那边的失败信息会指向完全无关的地方。
 */
export function resetUiStore(): void {
  localStorage.removeItem('cosight.ui');
  useUiStore.setState({
    locale: DEFAULT_LOCALE,
    sidebarCollapsed: false,
    sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
    settingsOpen: false,
    settingsTab: 'general',
    // 「打开设置并直接新增」是一次性请求，跨用例残留会让下一个用例莫名停在表单上。
    settingsCreateRequested: false,
    workspaceOpen: false,
  });
  // 「新建对话」nonce 也是模块级单例：不复位的话，前一个用例点过一次，
  // 后一个用例的 iframe 初始 key 就不是 0，断言会看到意料之外的重建。
  useNewChatStore.setState({ nonce: 0 });
}

export interface RenderWithProvidersOptions {
  /** 起始路由。组件里用到 useSearchParams / useNavigate 时必传。 */
  route?: string;
  queryClient?: QueryClient;
}

/**
 * 渲染单个组件（不挂路由表），用来测原子组件与局部交互。
 *
 * 用 MemoryRouter 而不是 MockRouter：`NavLink` / `useSearchParams` / `useNavigate`
 * 都需要真实的路由上下文，打桩它们等于在测自己写的假实现。
 */
export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderResult & { queryClient: QueryClient } {
  const queryClient = options.queryClient ?? createTestQueryClient();
  const route = options.route ?? '/';

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

  return { ...result, queryClient };
}

/**
 * 渲染**完整应用**（同一条路由表 + 外壳），用来测页面与模块宿主。
 *
 * 走的是生产用的 `routes`（src/app/routes.tsx），不是测试里另写一份：
 * 路由表写错（比如 `end` 漏了、capability 对错）只有用真表才测得出来。
 * 代价是页面级用例都会连带渲染侧栏——这恰恰是想要的，侧栏与页面的联动
 * （比如点导航切页）也就在覆盖范围内了。
 */
export function renderApp(initialRoute = '/'): RenderResult & {
  queryClient: QueryClient;
  router: ReturnType<typeof createMemoryRouter>;
} {
  const queryClient = createTestQueryClient();
  const router = createMemoryRouter(routes satisfies RouteObject[], {
    initialEntries: [initialRoute],
  });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { ...result, queryClient, router };
}

/** 供只关心 providers 的 renderHook 使用。 */
export function providersFor(queryClient: QueryClient): (props: { children: ReactNode }) => ReactElement {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

/* ===================== fetch 打桩 ===================== */

/**
 * 只实现客户端真正用到的那两个成员（`status` 与 `text()`）。
 *
 * 不构造真的 `Response`：jsdom 环境里它来自 Node 还是 undici 因版本而异，
 * 而 `src/api/client.ts` 只读这两个字段。少一个依赖，就少一类环境差异导致的
 * "本机过、CI 不过"。
 */
export interface FakeResponse {
  status: number;
  text: () => Promise<string>;
}

export function jsonResponse(body: unknown, status = 200): FakeResponse {
  return { status, text: () => Promise.resolve(JSON.stringify(body)) };
}

/** 非 JSON 响应（代理配置写错时返回的 HTML 页面）。 */
export function textResponse(body: string, status = 200): FakeResponse {
  return { status, text: () => Promise.resolve(body) };
}

/** 成功信封。 */
export function envelope<T>(data: T, meta: PageMeta | null = null): unknown {
  return { success: true, data, meta };
}

/** 失败信封；字段名与服务端 `AppError` 的序列化结果一致。 */
export function errorEnvelope(
  code: string,
  messageKey: string,
  extra: { message?: string; details?: unknown; traceId?: string | null } = {},
): unknown {
  return {
    success: false,
    error: {
      code,
      messageKey,
      message: extra.message ?? 'server said something',
      details: extra.details ?? null,
      traceId: extra.traceId ?? null,
    },
  };
}

/** 按顺序返回准备好的响应，用完之后抛错（暴露"意料之外的请求"）。 */
export function stubFetchSequence(responses: readonly FakeResponse[]): ReturnType<typeof vi.fn> {
  const queue = [...responses];
  const mock = vi.fn(() => {
    const next = queue.shift();
    if (next === undefined) {
      return Promise.reject(new Error('测试准备之外的请求：请检查 stubFetchSequence 的响应数量'));
    }
    return Promise.resolve(next);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** 固定返回同一个响应。 */
export function stubFetch(response: FakeResponse | (() => FakeResponse)): ReturnType<typeof vi.fn> {
  const mock = vi.fn(() => Promise.resolve(typeof response === 'function' ? response() : response));
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** 网络层失败（后端没启动）。 */
export function stubFetchRejected(reason: unknown = new TypeError('Failed to fetch')): ReturnType<typeof vi.fn> {
  const mock = vi.fn(() => Promise.reject(reason));
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** 从 fetch 打桩里取出某次调用的 URL。 */
export function callUrl(mock: ReturnType<typeof vi.fn>, index = 0): string {
  const call = mock.mock.calls[index] as [string, ...unknown[]] | undefined;
  if (call === undefined) {
    throw new Error(`没有第 ${String(index)} 次 fetch 调用`);
  }
  return call[0];
}

/** 从 fetch 打桩里取出某次调用的 init。 */
export function callInit(mock: ReturnType<typeof vi.fn>, index = 0): RequestInit {
  const call = mock.mock.calls[index] as [string, RequestInit?] | undefined;
  return call?.[1] ?? {};
}
