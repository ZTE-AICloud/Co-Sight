/**
 * 模块宿主（`ModuleHost`）测试。
 *
 * 宿主是"框架"与"别人的模块"之间唯一的接触面，这里测的是**接口**而不是外观：
 * 什么时候嵌 iframe、地址怎么拼、拼错时给出什么状态、以及沙箱给了多少权限。
 * 这四件事出问题的方式都很隐蔽（白屏、模块收到了错误的语言、权限给多了），
 * 靠肉眼点页面很难发现。
 */

import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ModelConfig, ModuleManifest, Workspace } from 'harness-shared';
import { describe, expect, it, vi } from 'vitest';

import { modelKeys } from '../src/api/models';
import { workspaceKeys } from '../src/api/workspaces';
import { useNewChatStore } from '../src/stores/newChat';
import { useUiStore } from '../src/stores/ui';
import {
  envelope,
  errorEnvelope,
  jsonResponse,
  renderApp,
  stubFetch,
  type FakeResponse,
} from './helpers/render';

/**
 * 按 `METHOD 路径` 分派的打桩。
 *
 * 只有「清单接口失败」那一个用例需要它：`stubFetchSequence` 是按**请求到达顺序**
 * 发牌的，而应用外壳自己也会发一次 `GET /api/workspaces/active`，于是那张 500
 * 可能被外壳吃掉、清单反而是成功的——测试会以「找不到错误提示」的形式失败，
 * 而这个方向跟真正的原因（打桩发错了牌）毫无关系。
 */
function stubRoutes(routes: Record<string, () => FakeResponse>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(input, 'http://localhost');
      const key = `${init.method ?? 'GET'} ${url.pathname}`;
      const handler = routes[key] ?? SHELL_ROUTES[key];
      if (handler === undefined) {
        throw new Error(`测试未准备的路由：${key}`);
      }
      return Promise.resolve(handler());
    }),
  );
}

/**
 * 侧栏「最近」是**外壳级**请求：任何走 `renderApp` 的用例都会打一次
 * smart-factory 的会话列表。它不是被测页面的一部分，所以统一给一个空列表，
 * 免得每个用例都要重复准备这一条。
 */
const SHELL_ROUTES: Record<string, () => FakeResponse> = {
  'GET /api/smart-factory/v1/sessions/list': () => jsonResponse({ items: [], total: 0 }),
};

/** 造一份合法清单；只写关心的字段，其余给一套能过校验的值。 */
function manifest(overrides: Partial<ModuleManifest> = {}): ModuleManifest {
  return {
    schemaVersion: 1,
    id: 'rag-studio',
    name: { 'zh-CN': '知识库', 'en-US': 'Knowledge Base' },
    description: { 'zh-CN': '个人与团队知识库', 'en-US': 'Personal and team knowledge base' },
    version: '1.2.0',
    entry: 'https://kb.example.com/app/index.html?theme=dark',
    allowedOrigins: ['https://kb.example.com'],
    /*
     * 用 `history` 当夹具：`/knowledge` 现在归 `KnowledgePage`（嵌用户配的地址），
     * 不再是模块宿主。`history` 路由的行为与它原先覆盖的完全相同。
     */
    mounts: [{ capability: 'history', path: '/history' }],
    icon: null,
    healthcheck: null,
    ...overrides,
  };
}

/** `/api/modules` 的成功响应；宿主只读 `modules` 这一段。 */
function modulesResponse(manifests: readonly ModuleManifest[]): ReturnType<typeof jsonResponse> {
  return jsonResponse(envelope({ modules: manifests, invalid: [] }));
}

/** 取当前渲染出的 iframe（没有就报错，避免断言里到处写 `?.`）。 */
function frame(): HTMLIFrameElement {
  // 按标题找，但**不写死语言**：标题是 `{name} 模块` 还是 `{name} module`
  // 取决于当前界面语言，而"页面上那个被嵌进来的模块"与语言无关。
  return screen.getByTitle(/(?:模块|module)$/);
}

function frameUrl(): URL {
  return new URL(frame().src);
}

describe('ModuleHost：清单未就绪时的三种状态', () => {
  it('清单还在路上时显示加载态，而不是空白', async () => {
    stubFetch(modulesResponse([]));

    renderApp('/history');

    // 同步断言：这一刻 fetch 的 promise 还没落地，页面必须是"正在加载"而不是空屏。
    expect(screen.getByRole('status')).toHaveTextContent('正在加载模块…');
    await screen.findByText('模块尚未接入');
  });

  it('清单里没有该能力时说明"尚未接入"，并且不嵌 iframe', async () => {
    // 路由是**存在**的，缺的是提供内容的模块——所以这里不能是 404，
    // 也不该出现一个指向空地址的 iframe。
    stubFetch(modulesResponse([]));

    renderApp('/history');

    expect(await screen.findByText('模块尚未接入')).toBeInTheDocument();
    expect(screen.queryByTitle(/模块$/)).not.toBeInTheDocument();
  });

  it('有模块、但挂的不是这个能力时，同样按"尚未接入"处理', async () => {
    const wrongMount = manifest({ mounts: [{ capability: 'observability', path: '/observability' }] });
    stubFetch(modulesResponse([wrongMount]));

    renderApp('/history');

    expect(await screen.findByText('模块尚未接入')).toBeInTheDocument();
  });

  it('清单请求失败时给出错误与重试，且重试成功后能嵌进来', async () => {
    const user = userEvent.setup();
    // 服务端 5xx 与"后端还没起来"是两种不同的失败，这里取前者（信封形式）。
    let moduleAttempts = 0;
    stubRoutes({
      'GET /api/workspaces/active': () => jsonResponse(envelope(null)),
      'GET /api/modules': () => {
        moduleAttempts += 1;
        return moduleAttempts === 1
          ? jsonResponse(errorEnvelope('internal', 'error.internal'), 500)
          : modulesResponse([manifest()]);
      },
    });

    renderApp('/history');

    expect(await screen.findByRole('alert')).toHaveTextContent('模块未能加载');
    expect(screen.queryByTitle(/模块$/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重试' }));

    await waitFor(() => {
      expect(screen.getByTitle('知识库 模块')).toBeInTheDocument();
    });
    // 重试是真的又打了一次清单接口，而不是复用了上一次的失败结果。
    expect(moduleAttempts).toBe(2);
  });
});

describe('ModuleHost：iframe 地址拼装', () => {
  it('以 entry 为基址，补上语言与当前页面的查询串，并保留 entry 自己的查询串', async () => {
    stubFetch(modulesResponse([manifest()]));

    renderApp('/history?tab=browse');

    await screen.findByTitle('知识库 模块');
    const url = frameUrl();

    // entry 自带的 ?theme=dark 必须留着：很多 dev server 靠它切环境。
    // 手写 `entry + '?' + x` 会拼出两个问号并丢掉它。
    expect(url.searchParams.get('theme')).toBe('dark');
    // 语言是宿主唯一主动传给模块的参数（见 ModuleHost 头部说明：不做 postMessage 协议）。
    expect(url.searchParams.get('locale')).toBe('zh-CN');
    // 宿主页面上的查询串原样带下去，这样模块刷新/换链接能复现同一屏。
    expect(url.searchParams.get('tab')).toBe('browse');
    expect(`${url.origin}${url.pathname}`).toBe('https://kb.example.com/app/index.html');
  });

  it('声明了 entryPath 时落到模块内的那一页，并保留 entry 的查询串', async () => {
    const experts = manifest({
      id: 'smart-factory',
      name: { 'zh-CN': '智慧工厂', 'en-US': 'Smart Factory' },
      // 专家页是模块前端的 /agents，而不是 entry 指向的首页。
      mounts: [{ capability: 'experts', path: '/experts', entryPath: '/agents' }],
    });
    stubFetch(modulesResponse([experts]));

    renderApp('/experts');

    await screen.findByTitle('智慧工厂 模块');
    const url = frameUrl();
    expect(`${url.origin}${url.pathname}`).toBe('https://kb.example.com/agents');
    expect(url.searchParams.get('capability')).toBe('experts');
    expect(url.searchParams.get('locale')).toBe('zh-CN');
    // entry 的 ?theme=dark 是开发服务器的环境开关，换页面不该丢掉。
    expect(url.searchParams.get('theme')).toBe('dark');
  });

  it('切换界面语言后 iframe 地址与标题跟着换', async () => {
    stubFetch(modulesResponse([manifest()]));

    renderApp('/history');
    await screen.findByTitle('知识库 模块');

    act(() => {
      useUiStore.setState({ locale: 'en-US' });
    });

    expect(frameUrl().searchParams.get('locale')).toBe('en-US');
    // 模块名取自清单的本地化字段、句式取自词表，所以标题整个换掉。
    expect(screen.getByTitle('Knowledge Base module')).toBeInTheDocument();
  });
});

const AGENT_DEV = manifest({
  id: 'agent-dev',
  name: { 'zh-CN': 'Agent 开发', 'en-US': 'Agent Dev' },
  entry: 'https://agent.example.com/index.html',
  allowedOrigins: ['https://agent.example.com'],
  mounts: [{ capability: 'agent-dev', path: '/agent-dev' }],
});

/** 只造测试关心的字段；其余给一份能过契约的值。 */
function model(id: string, label: string): ModelConfig {
  return {
    id,
    provider: 'openai',
    label,
    baseUrl: null,
    modelName: `model-${label}`,
    apiKeyMasked: null,
    hasApiKey: false,
    isActive: true,
    temperature: 0.7,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 120,
    createdAt: '2026-01-01T00:00:00.000Z',
    updatedAt: '2026-01-01T00:00:00.000Z',
  };
}

function workspace(id: string, name: string, defaultModelId: string | null = null): Workspace {
  return {
    id,
    name,
    directory: null,
    defaultModelId,
    defaultAgentId: null,
    createdAt: '2026-01-01T00:00:00.000Z',
    updatedAt: '2026-01-01T00:00:00.000Z',
  };
}

/**
 * 上下文接口的固定响应。`renderApp` 会同时渲染外壳，侧栏也要读当前工作区，
 * 所以即使被测页面不订阅，这三个接口也得有桩。
 */
function stubContext(
  manifests: readonly ModuleManifest[],
  activeModel: ModelConfig | null,
  activeWorkspace: Workspace | null,
): void {
  stubRoutes({
    'GET /api/modules': () => modulesResponse(manifests),
    'GET /api/models/active': () => jsonResponse(envelope(activeModel)),
    'GET /api/workspaces/active': () => jsonResponse(envelope(activeWorkspace)),
  });
}

describe('ModuleHost：模型 / 工作区切换后刷新', () => {

  it('切换全局模型后 Agent 开发页重建 iframe，模块会重新请求结果', async () => {
    stubContext(
      [AGENT_DEV],
      model('11111111-1111-4111-8111-111111111111', 'A'),
      workspace('22222222-2222-4222-8222-222222222222', '空间 A'),
    );

    const { queryClient } = renderApp('/agent-dev');

    await screen.findByTitle('Agent 开发 模块');
    const before = frame();

    act(() => {
      queryClient.setQueryData(modelKeys.active(), model('33333333-3333-4333-8333-333333333333', 'B'));
    });

    await waitFor(() => {
      expect(frame()).not.toBe(before);
    });
  });

  it('切换工作区后同样重建；评估页（同一路由的 mode=evaluate）一并生效', async () => {
    stubContext(
      [AGENT_DEV],
      model('11111111-1111-4111-8111-111111111111', 'A'),
      workspace('22222222-2222-4222-8222-222222222222', '空间 A'),
    );

    const { queryClient } = renderApp('/agent-dev?expert=opaque-expert&mode=evaluate');

    await screen.findByTitle('Agent 开发 模块');
    const before = frame();

    act(() => {
      queryClient.setQueryData(
        workspaceKeys.active(),
        workspace('44444444-4444-4444-8444-444444444444', '空间 B'),
      );
    });

    await waitFor(() => {
      expect(frame()).not.toBe(before);
    });
    // 刷新只换 iframe 节点，`mode` / `expert` 仍原样转发给模块。
    expect(frameUrl().searchParams.get('mode')).toBe('evaluate');
    expect(frameUrl().searchParams.get('expert')).toBe('opaque-expert');
  });

  it('工作区自己的默认模型变化也算切换（无需另切全局模型）', async () => {
    stubContext(
      [AGENT_DEV],
      model('11111111-1111-4111-8111-111111111111', 'A'),
      workspace('22222222-2222-4222-8222-222222222222', '空间 A', null),
    );

    const { queryClient } = renderApp('/agent-dev');

    await screen.findByTitle('Agent 开发 模块');
    const before = frame();

    act(() => {
      queryClient.setQueryData(
        workspaceKeys.active(),
        workspace(
          '22222222-2222-4222-8222-222222222222',
          '空间 A',
          '33333333-3333-4333-8333-333333333333',
        ),
      );
    });

    await waitFor(() => {
      expect(frame()).not.toBe(before);
    });
  });

  it('不订阅上下文的宿主（如历史）不会被刷新', async () => {
    const history = manifest();
    stubContext(
      [history],
      model('11111111-1111-4111-8111-111111111111', 'A'),
      workspace('22222222-2222-4222-8222-222222222222', '空间 A'),
    );

    const { queryClient } = renderApp('/history');

    await screen.findByTitle('知识库 模块');
    const before = frame();

    act(() => {
      queryClient.setQueryData(modelKeys.active(), model('33333333-3333-4333-8333-333333333333', 'B'));
      queryClient.setQueryData(
        workspaceKeys.active(),
        workspace('44444444-4444-4444-8444-444444444444', '空间 B'),
      );
    });

    // 缓存确实变了（上面两行），但这个宿主没有把上下文接进 key。
    expect(frame()).toBe(before);
  });
});

describe('ModuleHost：新建对话', () => {
  it('nonce 变化时重建对话 iframe（同一路由点击也能回到空态）', async () => {
    const conversation = manifest({
      id: 'viewer',
      name: { 'zh-CN': '会话', 'en-US': 'Conversation' },
      entry: 'http://localhost:4830/?theme=dark',
      allowedOrigins: ['http://localhost:4830'],
      mounts: [{ capability: 'conversation', path: '/' }],
    });
    stubFetch(modulesResponse([conversation]));

    renderApp('/');
    await screen.findByTitle('会话 模块');
    const before = frame();

    act(() => {
      useNewChatStore.getState().requestNewChat();
    });

    // key 变了：React 销毁旧 iframe、建新的，浏览器因此重新加载模块（回到空态）。
    expect(frame()).not.toBe(before);
  });
});

describe('ModuleHost：沙箱权限', () => {
  it('给出恰好够用的白名单，只放行用户激活的顶层跳转', async () => {
    stubFetch(modulesResponse([manifest()]));

    renderApp('/history');
    await screen.findByTitle('知识库 模块');

    const sandbox = frame().getAttribute('sandbox') ?? '';
    // allow-scripts：模块是前端应用；
    // allow-same-origin：让模块保持**自己的**源，否则它读写不了自己的 localStorage/cookie；
    // allow-forms / allow-popups：模块内的表单与"在新窗口打开"；
    // allow-downloads：模块要能导出会话 / 结果文件；
    // allow-top-navigation-by-user-activation：用户主动点时模块可以整页回宿主页面。
    expect(sandbox).toBe(
      'allow-scripts allow-same-origin allow-forms allow-popups allow-downloads allow-top-navigation-by-user-activation',
    );
    // 无用户激活的顶层跳转仍然不给：模块不能让整个工作台自己跳走。
    expect(sandbox).not.toMatch(/(^|\s)allow-top-navigation(\s|$)/);
    // 剪贴板是模块里复制代码/结果需要的，其余能力（摄像头、地理位置…）一律不给。
    expect(frame()).toHaveAttribute('allow', 'clipboard-read; clipboard-write');
  });
});
