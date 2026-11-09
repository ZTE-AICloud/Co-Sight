/**
 * 工作区设置行为测试（P3 / 需求 2.1）。
 *
 * 一律走 `renderApp('/')`（真实路由表 + 外壳），而不是单独渲染 `WorkspaceDialog`：
 * 这个功能的入口就是侧栏底部那一行，只有连外壳一起渲染才验证得了
 * "点入口能打开弹窗""切完之后侧栏的名字跟着变"。
 *
 * 「当前工作区」是服务端状态，所以每个用例都必须准备 `GET /api/workspaces/active`——
 * 少准备一条路由会直接炸出来，不会静默变成"没有工作区"（见下面的 stubApi）。
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Workspace } from 'harness-shared';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  envelope,
  errorEnvelope,
  jsonResponse,
  renderApp,
  resetUiStore,
  type FakeResponse,
} from './helpers/render';

/* ===================== 打桩 ===================== */

type Handler = (url: URL, init: RequestInit) => FakeResponse;

/**
 * 按 `METHOD 路径` 分派的 fetch 打桩（沿用 experts-page.test.tsx 的写法）。
 *
 * 比那边多一件事：`/api/workspaces/:id` 这种**带参数**的路径要能匹配上。
 * 只按字面量查表的话，`DELETE /api/workspaces/<uuid>` 会落到"未准备的路由"，
 * 而请求其实已经发出去了——测试会以"没删掉"的形式失败，看着像功能坏了，
 * 实际是打桩写错。段数相同、逐段比对（`:` 开头的段通配）即可。
 */
function stubApi(handlers: Record<string, Handler>): ReturnType<typeof vi.fn> {
  function resolve(method: string, pathname: string): Handler | undefined {
    const direct = handlers[`${method} ${pathname}`];
    if (direct !== undefined) {
      return direct;
    }
    const segments = pathname.split('/');
    for (const [key, handler] of Object.entries(handlers)) {
      const [keyMethod, pattern] = key.split(' ');
      if (keyMethod !== method || pattern === undefined || !pattern.includes(':')) {
        continue;
      }
      const patternSegments = pattern.split('/');
      if (
        patternSegments.length === segments.length &&
        patternSegments.every((segment, index) => segment.startsWith(':') || segment === segments[index])
      ) {
        return handler;
      }
    }
    return undefined;
  }

  const mock = vi.fn((input: string, init: RequestInit = {}) => {
    const url = new URL(input, 'http://localhost');
    const method = init.method ?? 'GET';
    const handler = resolve(method, url.pathname);
    if (handler === undefined) {
      throw new Error(`测试未准备的路由：${method} ${url.pathname}`);
    }
    return Promise.resolve(handler(url, init));
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** 模块宿主在 `/` 上会拉清单，所以每个用例都要备这一条。 */
const MODULES_EMPTY: Handler = () => jsonResponse(envelope({ modules: [], invalid: [] }));

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: '00000000-0000-4000-8000-00000000000a',
    name: '周报助手开发',
    directory: '/home/me/projects/demo',
    defaultModelId: null,
    defaultAgentId: null,
    createdAt: '2026-01-01T00:00:00.000Z',
    updatedAt: '2026-01-01T00:00:00.000Z',
    ...overrides,
  };
}

interface ApiOptions {
  workspaces?: readonly Workspace[];
  active?: Workspace | null;
  /** 覆盖某条路由；键形如 `POST /api/workspaces`。 */
  override?: Record<string, Handler>;
}

/** 备好工作区弹窗会用到的全部读接口，并返回 fetch 打桩。 */
function stubWorkspacesApi(options: ApiOptions = {}): ReturnType<typeof vi.fn> {
  const list = options.workspaces ?? [workspace()];
  const active = options.active === undefined ? (list[0] ?? null) : options.active;
  return stubApi({
    'GET /api/modules': MODULES_EMPTY,
    // 侧栏「最近」：外壳级请求，与工作区无关；这个文件走 renderApp，每个用例都会发。
    'GET /api/smart-factory/v1/sessions/list': () => jsonResponse({ items: [], total: 0 }),
    'GET /api/workspaces': () => jsonResponse(envelope(list)),
    'GET /api/workspaces/active': () => jsonResponse(envelope(active)),
    'GET /api/models': () => jsonResponse(envelope([])),
    'GET /api/agent-proxies': () => jsonResponse(envelope([])),
    'POST /api/workspaces': (_url, init) =>
      jsonResponse(envelope(workspace({ ...(JSON.parse(String(init.body)) as object) } as Partial<Workspace>))),
    'POST /api/workspaces/:id/activate': () => jsonResponse(envelope(active)),
    'PATCH /api/workspaces/:id': () => jsonResponse(envelope(active)),
    'DELETE /api/workspaces/:id': () => jsonResponse(envelope({ id: active?.id ?? 'x', deleted: true })),
    /*
     * 系统目录选择器：默认按"用户点了取消"返回。这条路由**必须**备好——
     * 没备的话，点「选择目录」会在测试里炸成"未准备的路由"，看着像功能没做。
     * 需要"选中了某个路径"的用例用 `override` 换掉它。
     */
    'POST /api/workspaces/pick-directory': () => jsonResponse(envelope({ path: null })),
    ...options.override,
  });
}

/** 从打桩里找出某次调用（按方法 + 路径片段），拿它的 URL 与 init。 */
function findCall(
  mock: ReturnType<typeof vi.fn>,
  method: string,
  pathPart: string,
): { url: URL; init: RequestInit } | null {
  const call = mock.mock.calls.find(([input, init]) => {
    const url = new URL(String(input), 'http://localhost');
    /*
     * 用 `=== 或 endsWith` 而不是 `includes`：`/api/workspaces` 是 `/api/workspaces/pick-directory`
     * 的**前缀**，`includes` 会把目录选择那次请求当成"建工作区"。
     */
    const matched = url.pathname === pathPart || url.pathname.endsWith(pathPart);
    return (init?.method ?? 'GET') === method && matched;
  });
  if (call === undefined) {
    return null;
  }
  const [input, init] = call as [string, RequestInit?];
  return { url: new URL(input, 'http://localhost'), init: init ?? {} };
}

/**
 * 所有目录选择请求（按调用顺序）。
 *
 * 单独一条而不是复用 `findCall`：有的用例会调用两次（点一次、再点一次），
 * `findCall` 只给第一次，断言"第二次传了什么"就会看错。
 */
function pickerCalls(mock: ReturnType<typeof vi.fn>): { url: URL; init: RequestInit }[] {
  return mock.mock.calls
    .filter(([input]) => new URL(String(input), 'http://localhost').pathname === '/api/workspaces/pick-directory')
    .map(([input, init]) => ({
      url: new URL(String(input), 'http://localhost'),
      init: (init ?? {}) as RequestInit,
    }));
}

function bodyOf(call: { init: RequestInit } | null): Record<string, unknown> {
  if (call === null) {
    throw new Error('没有找到这次调用');
  }
  return JSON.parse(String(call.init.body)) as Record<string, unknown>;
}

/** 打开工作区弹窗，等列表出现。 */
async function openDialog(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  await user.click(await screen.findByRole('button', { name: /打开工作区设置/ }));
  return screen.findByRole('dialog', { name: '工作区设置' });
}

/** 打开「新建工作区」表单（选择目录的用例都从这张空白表单开始）。 */
async function openCreateForm(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  const dialog = await openDialog(user);
  await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));
  return screen.findByRole('dialog', { name: '新建工作区' });
}

afterEach(() => {
  resetUiStore();
  vi.unstubAllGlobals();
});

/* ===================== 侧栏入口 ===================== */

describe('侧栏的工作区入口', () => {
  it('显示当前工作区的名字', async () => {
    stubWorkspacesApi({ workspaces: [workspace({ name: '周报助手开发' })], active: workspace({ name: '周报助手开发' }) });
    renderApp('/');

    expect(await screen.findByRole('button', { name: '周报助手开发（打开工作区设置）' })).toBeInTheDocument();
  });

  it('一个工作区都没有时显示「未选择工作区」，而不是留空或报错', async () => {
    stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    expect(
      await screen.findByRole('button', { name: '未选择工作区（打开工作区设置）' }),
    ).toBeInTheDocument();
  });

  it('读当前工作区失败时说"失败"，不说"未选择"——两者原因完全不同', async () => {
    stubApi({
      'GET /api/modules': MODULES_EMPTY,
      'GET /api/workspaces/active': () => {
        throw new Error('后端没起来');
      },
    });
    renderApp('/');

    expect(
      await screen.findByRole('button', { name: '工作区列表加载失败（打开工作区设置）' }),
    ).toBeInTheDocument();
  });
});

/* ===================== 列表 ===================== */

describe('工作区列表', () => {
  it('当前工作区带徽标，其他工作区提供「切换到此工作区」', async () => {
    const user = userEvent.setup();
    const first = workspace({ id: '00000000-0000-4000-8000-00000000000a', name: '甲工作区' });
    const second = workspace({ id: '00000000-0000-4000-8000-00000000000b', name: '乙工作区' });
    stubWorkspacesApi({ workspaces: [first, second], active: first });
    renderApp('/');

    const dialog = await openDialog(user);
    const rows = within(dialog).getAllByRole('listitem');
    expect(rows).toHaveLength(2);

    expect(within(rows[0] as HTMLElement).getByText('当前使用')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).queryByRole('button', { name: '切换到此工作区' })).toBeNull();
    expect(within(rows[1] as HTMLElement).getByRole('button', { name: '切换到此工作区' })).toBeInTheDocument();
  });

  it('没有绑定目录的行说「未绑定目录」，不是空白', async () => {
    const user = userEvent.setup();
    stubWorkspacesApi({ workspaces: [workspace({ directory: null })], active: workspace({ directory: null }) });
    renderApp('/');

    const dialog = await openDialog(user);
    expect(within(dialog).getByText('未绑定目录')).toBeInTheDocument();
  });

  it('一个工作区都没有时给空态与下一步，而不是一张空白列表', async () => {
    const user = userEvent.setup();
    stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    expect(await within(dialog).findByText('还没有工作区')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '新建工作区' })).toBeInTheDocument();
  });

  it('列表加载失败时给重试，点重试会再请求一次', async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const mock = stubWorkspacesApi({
      override: {
        'GET /api/workspaces': () => {
          attempts += 1;
          throw new Error('炸了');
        },
      },
    });
    renderApp('/');

    const dialog = await openDialog(user);
    const retry = await within(dialog).findByRole('button', { name: '重试' });
    expect(attempts).toBeGreaterThanOrEqual(1);

    const before = attempts;
    await user.click(retry);
    await waitFor(() => {
      expect(attempts).toBeGreaterThan(before);
    });
    expect(mock).toBeDefined();
  });
});

/* ===================== 切换 ===================== */

describe('切换工作区', () => {
  it('点「切换到此工作区」发 POST /api/workspaces/:id/activate', async () => {
    const user = userEvent.setup();
    const first = workspace({ id: '00000000-0000-4000-8000-00000000000a', name: '甲工作区' });
    const second = workspace({ id: '00000000-0000-4000-8000-00000000000b', name: '乙工作区' });
    const mock = stubWorkspacesApi({ workspaces: [first, second], active: first });
    renderApp('/');

    const dialog = await openDialog(user);
    const rows = within(dialog).getAllByRole('listitem');
    await user.click(within(rows[1] as HTMLElement).getByRole('button', { name: '切换到此工作区' }));

    await waitFor(() => {
      expect(findCall(mock, 'POST', `/${second.id}/activate`)).not.toBeNull();
    });
  });
});

/* ===================== 新建 ===================== */

describe('新建工作区', () => {
  it('提交后请求体字段正确：目录留空给 null，而不是空串', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));

    const form = await screen.findByRole('dialog', { name: '新建工作区' });
    await user.type(within(form).getByLabelText('名称'), '新工作区');
    await user.click(within(form).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(findCall(mock, 'POST', '/api/workspaces')).not.toBeNull();
    });
    expect(bodyOf(findCall(mock, 'POST', '/api/workspaces'))).toMatchObject({
      name: '新工作区',
      // 空串会被服务端的 absolutePathSchema 判成非法；未填写必须是 null。
      directory: null,
      defaultModelId: null,
      defaultAgentId: null,
    });
  });

  it('界面上说清了「留空 = 框架建目录」（D32，不然用户以为留空就是不绑定）', async () => {
    /*
     * 这条断言守的是一条**文案**，看着不重要，但它挡的是一种真实的误解：
     * 在 D32 之前，"不填目录"确实等于"不绑定"；改了行为却没改文案，
     * 用户会照旧以为留空不落任何东西，然后奇怪磁盘上怎么多了一个文件夹。
     * 目录真的是框架建的这个事实，界面上只有这一处能说出来。
     */
    const user = userEvent.setup();
    stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));

    const form = await screen.findByRole('dialog', { name: '新建工作区' });
    expect(
      within(form).getByText(/留空时框架会在数据目录的工作区根下建一个同名文件夹并绑定/),
    ).toBeInTheDocument();
    // 反向那一半也要在：填了就**只绑定**，否则用户会以为填了也会去建。
    expect(within(form).getByText(/填了绝对路径则只绑定，不创建/)).toBeInTheDocument();
  });

  it('新建成功后自动切过去，不需要用户再点一次「切换」', async () => {
    const user = userEvent.setup();
    const created = workspace({ id: '00000000-0000-4000-8000-0000000000ff', name: '新工作区' });
    const mock = stubWorkspacesApi({
      workspaces: [],
      active: null,
      override: {
        'POST /api/workspaces': () => jsonResponse(envelope(created)),
        'POST /api/workspaces/:id/activate': () => jsonResponse(envelope(created)),
      },
    });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));
    const form = await screen.findByRole('dialog', { name: '新建工作区' });
    await user.type(within(form).getByLabelText('名称'), '新工作区');
    await user.click(within(form).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(findCall(mock, 'POST', `/${created.id}/activate`)).not.toBeNull();
    });
  });

  it('名称留空不提交，只在字段上报错', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));
    const form = await screen.findByRole('dialog', { name: '新建工作区' });
    await user.click(within(form).getByRole('button', { name: '保存' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('请填写名称');
    expect(findCall(mock, 'POST', '/api/workspaces')).toBeNull();
  });

  it('目录填相对路径时前端就拦住，不等服务端 422', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '新建工作区' }));
    const form = await screen.findByRole('dialog', { name: '新建工作区' });
    await user.type(within(form).getByLabelText('名称'), '新工作区');
    await user.type(within(form).getByLabelText('绑定目录'), 'projects/demo');
    await user.click(within(form).getByRole('button', { name: '保存' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('绝对路径');
    expect(findCall(mock, 'POST', '/api/workspaces')).toBeNull();
  });
});

/* ===================== 选择目录 ===================== */

describe('选择目录', () => {
  it('点「选择目录」让服务端弹系统对话框，选中的路径填进输入框', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({
      workspaces: [],
      active: null,
      override: {
        'POST /api/workspaces/pick-directory': () =>
          jsonResponse(envelope({ path: '/home/me/projects/picked' })),
      },
    });
    renderApp('/');

    const form = await openCreateForm(user);
    await user.click(within(form).getByRole('button', { name: '选择目录' }));

    await waitFor(() => {
      expect(bodyOf(findCall(mock, 'POST', '/api/workspaces/pick-directory'))).toEqual({
        initialPath: null,
      });
    });
    await waitFor(() => {
      expect(within(form).getByLabelText('绑定目录')).toHaveValue('/home/me/projects/picked');
    });
  });

  it('输入框为空时点它本身也打开选择器', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const form = await openCreateForm(user);
    await user.click(within(form).getByLabelText('绑定目录'));

    await waitFor(() => {
      expect(findCall(mock, 'POST', '/api/workspaces/pick-directory')).not.toBeNull();
    });
  });

  it('已经有路径时点输入框只当作普通点击——想手改的人不被对话框拦住', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const form = await openCreateForm(user);
    const input = within(form).getByLabelText('绑定目录');
    // 先聚焦再敲，避开"点空输入框会打开选择器"这条（它本身是另一个用例）。
    input.focus();
    await user.keyboard('/home/me/typed');
    expect(input).toHaveValue('/home/me/typed');

    await user.click(input);

    expect(pickerCalls(mock)).toHaveLength(0);
  });

  it('已填的路径作为起点传给选择器；取消（path=null）保持原值不变', async () => {
    const user = userEvent.setup();
    const mock = stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const form = await openCreateForm(user);
    const input = within(form).getByLabelText('绑定目录');
    input.focus();
    await user.keyboard('/home/me/typed');
    await user.click(within(form).getByRole('button', { name: '选择目录' }));

    await waitFor(() => {
      expect(pickerCalls(mock)).toHaveLength(1);
    });
    // 起点就是输入框里的值：用户多半想从同一个父目录换个兄弟目录。
    expect(bodyOf(pickerCalls(mock)[0] ?? null)).toEqual({ initialPath: '/home/me/typed' });
    // 按钮回到非等待态 = 这次选择已经结束；取消不能把输入框清空。
    await waitFor(() => {
      expect(within(form).getByRole('button', { name: '选择目录' })).toBeEnabled();
    });
    expect(input).toHaveValue('/home/me/typed');
  });

  it('这台机器弹不出对话框时说"请手动输入路径"，且不把输入框标红', async () => {
    const user = userEvent.setup();
    stubWorkspacesApi({
      workspaces: [],
      active: null,
      override: {
        'POST /api/workspaces/pick-directory': () =>
          jsonResponse(
            errorEnvelope('NOT_IMPLEMENTED', 'error.directory_picker.unavailable'),
            501,
          ),
      },
    });
    renderApp('/');

    const form = await openCreateForm(user);
    await user.click(within(form).getByRole('button', { name: '选择目录' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('请手动输入路径');
    // 坏的是"这台机器弹不出对话框"，不是用户填的值：不该带 aria-invalid。
    expect(within(form).getByLabelText('绑定目录')).not.toHaveAttribute('aria-invalid');
  });

  it('工作区名称与绑定目录都关掉了浏览器的历史下拉', async () => {
    const user = userEvent.setup();
    stubWorkspacesApi({ workspaces: [], active: null });
    renderApp('/');

    const form = await openCreateForm(user);
    // 用户看到的「默认工作区」就是浏览器保存的表单历史，autoComplete=off 是唯一关它的办法。
    expect(within(form).getByLabelText('名称')).toHaveAttribute('autocomplete', 'off');
    expect(within(form).getByLabelText('绑定目录')).toHaveAttribute('autocomplete', 'off');
  });
});

/* ===================== 未保存修改 ===================== */

describe('表单里的未保存修改', () => {
  it('改过内容再按 Esc，先问「放弃吗」而不是直接丢掉', async () => {
    const user = userEvent.setup();
    stubWorkspacesApi();
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '编辑' }));
    const form = await screen.findByRole('dialog', { name: '编辑工作区' });
    await user.type(within(form).getByLabelText('名称'), '改一下');

    await user.keyboard('{Escape}');

    // 放弃修改走的是「放弃」确认框，不是「确认删除」——两者文案不同，别串了。
    const confirm = await screen.findByRole('dialog', { name: '放弃未保存的修改？' });
    expect(within(confirm).getByText('这个表单里的修改还没有保存，离开后会丢失。')).toBeInTheDocument();
    // 危险动作的初始焦点必须在「取消」上。
    expect(within(confirm).getByRole('button', { name: '取消' })).toHaveFocus();

    // 取消之后仍然停在表单上，且刚敲的字还在。
    await user.click(within(confirm).getByRole('button', { name: '取消' }));
    expect(await screen.findByRole('dialog', { name: '编辑工作区' })).toBeInTheDocument();
    expect(within(form).getByLabelText('名称')).toHaveValue('周报助手开发改一下');
  });
});

/* ===================== 删除 ===================== */

describe('删除工作区', () => {
  it('走二次确认：初始焦点在取消，取消不发请求，确认才发 DELETE', async () => {
    const user = userEvent.setup();
    const target = workspace({ id: '00000000-0000-4000-8000-00000000000a', name: '甲工作区' });
    const mock = stubWorkspacesApi({ workspaces: [target], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '删除' }));

    const confirm = await screen.findByRole('dialog', { name: '确认删除' });
    const cancel = within(confirm).getByRole('button', { name: '取消' });
    expect(cancel).toHaveFocus();
    expect(within(confirm).getByText(/「甲工作区」将被永久删除，此操作不可撤销。/)).toBeInTheDocument();
    // 绑定了目录时要把磁盘后果说清楚：框架建的那份会删、外部绑定只解绑。
    expect(within(confirm).getByText(/框架创建的工作区目录会连同其中的文件一并删除/)).toBeInTheDocument();

    await user.click(cancel);
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '确认删除' })).toBeNull();
    });
    expect(findCall(mock, 'DELETE', `/api/workspaces/${target.id}`)).toBeNull();

    await user.click(within(dialog).getByRole('button', { name: '删除' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: '确认删除' })).getByRole('button', { name: '删除' }),
    );
    await waitFor(() => {
      expect(findCall(mock, 'DELETE', `/api/workspaces/${target.id}`)).not.toBeNull();
    });
  });

  it('没有绑定目录时不提目录，避免无中生有地吓用户', async () => {
    const user = userEvent.setup();
    const target = workspace({ name: '甲工作区', directory: null });
    stubWorkspacesApi({ workspaces: [target], active: null });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(await within(dialog).findByRole('button', { name: '删除' }));

    const confirm = await screen.findByRole('dialog', { name: '确认删除' });
    expect(within(confirm).queryByText(/工作区目录会连同/)).toBeNull();
  });

  it('删的正好是当前工作区时，把后果一并说清', async () => {
    const user = userEvent.setup();
    const target = workspace({ name: '甲工作区' });
    stubWorkspacesApi({ workspaces: [target], active: target });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole('button', { name: '删除' }));

    const confirm = await screen.findByRole('dialog', { name: '确认删除' });
    expect(within(confirm).getByText(/删除后会回到/)).toBeInTheDocument();
  });

  it('删掉当前工作区后，侧栏回到「未选择工作区」', async () => {
    const user = userEvent.setup();
    const target = workspace({ name: '甲工作区' });
    let remaining: Workspace[] = [target];
    let active: Workspace | null = target;
    stubWorkspacesApi({
      override: {
        'GET /api/workspaces': () => jsonResponse(envelope(remaining)),
        'GET /api/workspaces/active': () => jsonResponse(envelope(active)),
        'DELETE /api/workspaces/:id': () => {
          // 与服务端一致：删掉当前工作区时一并清掉当前指针。
          remaining = [];
          active = null;
          return jsonResponse(envelope({ id: target.id, deleted: true }));
        },
      },
    });
    renderApp('/');

    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole('button', { name: '删除' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: '确认删除' })).getByRole('button', { name: '删除' }),
    );

    expect(
      await screen.findByRole('button', { name: '未选择工作区（打开工作区设置）' }),
    ).toBeInTheDocument();
  });
});
