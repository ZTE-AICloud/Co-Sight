/**
 * RAG 知识库面板（设置 → RAG 知识库）。
 *
 * 与模型/代理面板的重心相同（断言请求体而不是界面），另外多守四件事：
 *
 * - **`isActive` 只在新建时出现在请求体里**。编辑走的 `PATCH` 不带它，因为切换可用项
 *   是行上的独立动作；混进保存里会让"只是改个名字"顺手换掉正在用的那条，而界面上
 *   看不出任何异常。这一条只能对着序列化之后的请求体断。
 * - **地址不能内嵌账号密码**。它是唯一有安全含义的字段，前端就挡住，不等 422。
 * - **列表行上没有「打开」**：打开入口只有侧栏「知识库」一个（见 `KnowledgeNavItem`），
 *   行上再多一个，两处的行为迟早会漂成不一样。
 * - **删掉可用项要说后果**：服务端不会自动补位。
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { RagKnowledgeBase } from 'harness-shared';
import { beforeEach, describe, expect, it } from 'vitest';

import { RagKnowledgeSettingsPanel } from '../src/features/rag-knowledge/RagKnowledgeSettingsPanel';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { useUiStore } from '../src/stores/ui';
import { stubConfigApi } from './helpers/configApi';
import {
  envelope,
  errorEnvelope,
  jsonResponse,
  renderWithProviders,
  resetUiStore,
} from './helpers/render';

const P = zhCN.settings.ragKnowledge;
const FORM = zhCN.settings.form;

function fill(template: string, values: Record<string, string>): string {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replace(`{${key}}`, value),
    template,
  );
}

const LONG_DESCRIPTION = '这条说明故意写得比列表行放得下的长度长很多，用来验证进 DOM 之前就截断。'.repeat(4);
const LONG_ROUTE = `https://kb.example.com/${'segment/'.repeat(20)}deep`;
const ACTIVE_DESCRIPTION = '产品问答与规格参数';

const ACTIVE_KB: RagKnowledgeBase = {
  id: '55555555-5555-4555-8555-555555555555',
  name: '产品知识库',
  routeUrl: 'https://kb.example.com/kb/42',
  username: 'kb-admin',
  passwordMasked: '**********',
  hasPassword: true,
  apiKeyMasked: '**********',
  hasApiKey: true,
  description: ACTIVE_DESCRIPTION,
  isActive: true,
  createdAt: '2026-01-01T00:00:00.000Z',
  updatedAt: '2026-01-02T00:00:00.000Z',
};

const SPARE_KB: RagKnowledgeBase = {
  id: '66666666-6666-4666-8666-666666666666',
  name: '研究知识库',
  routeUrl: LONG_ROUTE,
  username: null,
  passwordMasked: null,
  hasPassword: false,
  apiKeyMasked: null,
  hasApiKey: false,
  description: LONG_DESCRIPTION,
  isActive: false,
  createdAt: '2026-01-03T00:00:00.000Z',
  updatedAt: '2026-01-03T00:00:00.000Z',
};

const LIST_OK = jsonResponse(envelope([ACTIVE_KB, SPARE_KB]));
const LIST_EMPTY = jsonResponse(envelope([]));

function renderPanel(): void {
  renderWithProviders(<RagKnowledgeSettingsPanel />);
}

function rowAction(template: string, name: string): string {
  return fill(template, { name });
}

/**
 * API Key 那栏的提示语元素。
 *
 * 它和密码那栏的通用句子**逐字相同**（两栏都走 D26 的 `*Unset` / `*Set`），
 * `getByText` 必然会同时命中两个。按 `-hint` 的 id 取，断的才是"这一栏到底写了什么"。
 */
function apiKeyHint(): HTMLElement {
  const element = document.getElementById('rag-knowledge-form-api-key-hint');
  if (element === null) {
    throw new Error('API Key 的提示语元素不在 DOM 里：表单没打开？');
  }
  return element;
}

describe('RAG 知识库面板 — 列表', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('每行显示名称、可用徽标、截断后的地址与说明', async () => {
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    expect(await screen.findByText(ACTIVE_KB.name)).toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    const [active, spare] = rows as [HTMLElement, HTMLElement];

    expect(within(active).getByText(P.activeBadge)).toBeInTheDocument();
    // 「当前可用」是状态徽标，不是每条都有的装饰：同时出现两个会让用户以为有两个可用项。
    expect(within(spare).queryByText(P.activeBadge)).toBeNull();

    expect(active).toHaveTextContent(ACTIVE_KB.routeUrl);
    expect(active).toHaveTextContent(ACTIVE_DESCRIPTION);

    /*
     * 地址与说明都在**进 DOM 之前**截断（地址可到 2048 字符），完整内容留在
     * `title` 里：只靠 CSS 省略号的话 DOM 里仍是全文，读屏会逐行念完。
     */
    const routeText = within(spare).getByTitle(LONG_ROUTE);
    expect(routeText.textContent?.endsWith('…')).toBe(true);
    expect(routeText.textContent?.length).toBeLessThan(LONG_ROUTE.length);

    const descriptionText = within(spare).getByTitle(LONG_DESCRIPTION);
    expect(descriptionText.textContent?.endsWith('…')).toBe(true);
  });

  it('列表行上没有「打开」入口，只有侧栏那一处', async () => {
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    expect(await screen.findByText(ACTIVE_KB.name)).toBeInTheDocument();
    // 打开地址的入口在侧栏「知识库」；设置里再放一个，两处迟早会变成两种行为。
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('已是可用项的行不显示「设为可用」', async () => {
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    expect(
      await screen.findByRole('button', {
        name: rowAction(P.action.activate, SPARE_KB.name),
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', {
        name: rowAction(P.action.activate, ACTIVE_KB.name),
      }),
    ).toBeNull();
  });

  it('一个都没有时显示空态，并保留「新增知识库」入口', async () => {
    stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    expect(await screen.findByText(P.empty.title)).toBeInTheDocument();
    expect(screen.getByText(P.empty.hint)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: P.create })).toBeInTheDocument();
  });

  it('加载失败显示错误面板，且不显示空态', async () => {
    stubConfigApi({
      list: jsonResponse(errorEnvelope('not_implemented', 'error.not_implemented.default'), 501),
    });
    renderPanel();

    const panel = await screen.findByRole('alert');
    expect(within(panel).getByText(P.error.title)).toBeInTheDocument();
    expect(within(panel).getByText(zhCN.error.not_implemented.default)).toBeInTheDocument();
    // 失败时把空态盖掉：两个同时出现会让用户以为"配置本来就没有"。
    expect(screen.queryByText(P.empty.title)).toBeNull();
  });
});

describe('RAG 知识库面板 — 新建', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('默认不勾「设为可用」，空白说明送 null', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));

    // 新建表单有生效开关，编辑表单没有（见下一个 describe）。
    expect(screen.getByRole('switch', { name: P.field.isActive })).not.toBeChecked();

    // 没有服务端默认密钥时，API Key 的提示就是通用的 D26 那句。
    await waitFor(() => {
      expect(apiKeyHint()).toHaveTextContent(P.field.apiKeyUnset);
    });

    await user.type(screen.getByLabelText(P.field.name), '  产品知识库  ');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'https://kb.example.com/kb/42');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: P.create })).toBeInTheDocument();
    expect(api.body('POST', '/api/rag-knowledge')).toEqual({
      name: '产品知识库',
      routeUrl: 'https://kb.example.com/kb/42',
      // 账号密码留空都是 null（"不设置"），不是空串——服务端对密码是 min(1)。
      username: null,
      password: null,
      apiKey: null,
      description: null,
      // 默认 false：新增常常只是想把地址存下来，替用户激活会换掉正在用的那条。
      isActive: false,
    });
  });

  it('填了用户名与密码时一起送出去', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.type(screen.getByLabelText(P.field.name), '产品知识库');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'https://kb.example.com/kb/42');
    await user.type(screen.getByLabelText(P.field.username), ' admin ');
    await user.type(screen.getByLabelText(P.field.password), 'admin');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: P.create })).toBeInTheDocument();
    expect(api.body('POST', '/api/rag-knowledge')).toMatchObject({
      // 账号两侧空白由前端去掉；密码原样送（不做 trim，理由同模型密钥）。
      username: 'admin',
      password: 'admin',
    });
  });

  it('勾上「设为可用」时请求体里是 true', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.type(screen.getByLabelText(P.field.name), '产品知识库');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'https://kb.example.com/kb/42');
    await user.click(screen.getByRole('switch', { name: P.field.isActive }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: P.create })).toBeInTheDocument();
    expect(api.body('POST', '/api/rag-knowledge')).toMatchObject({ isActive: true });
  });

  it('缺必填项时各报各的，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByText(fill(FORM.required, { field: P.field.name }))).toBeInTheDocument();
    expect(
      screen.getByText(fill(FORM.required, { field: P.field.routeUrl })),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/rag-knowledge')).toBe(false);
  });

  it('非 http(s) 协议报"要以 http 开头"，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.type(screen.getByLabelText(P.field.name), '产品知识库');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'javascript:alert(1)');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(
      await screen.findByText(fill(FORM.invalidUrl, { field: P.field.routeUrl })),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/rag-knowledge')).toBe(false);
  });

  it('地址内嵌账号密码时报专门的一条，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.type(screen.getByLabelText(P.field.name), '产品知识库');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'https://user:pass@kb.example.com/');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    /*
     * 不能复用"要以 http:// 开头"：这条地址本身是合法的，用户要改的只是别把凭据
     * 写进地址里；说成格式错误会让人反复检查那段没问题的前缀。
     */
    expect(
      await screen.findByText(fill(FORM.invalidUrlCredentials, { field: P.field.routeUrl })),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/rag-knowledge')).toBe(false);
  });
});

describe('RAG 知识库面板 — 编辑', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('请求体里没有 isActive（切换可用项是行上的动作）', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, SPARE_KB.name),
      }),
    );

    expect(screen.getByLabelText(P.field.name)).toHaveValue(SPARE_KB.name);
    // 编辑态不显示生效开关：`PATCH` 不改它，放一个"改了也不生效"的开关比不放更糟。
    expect(screen.queryByRole('switch')).toBeNull();

    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).not.toContain('isActive');
    expect(api.body('PATCH', `/api/rag-knowledge/${SPARE_KB.id}`)).toMatchObject({
      name: SPARE_KB.name,
      routeUrl: LONG_ROUTE,
      description: LONG_DESCRIPTION,
    });
  });

  it('说明清空 = 送 null', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, ACTIVE_KB.name),
      }),
    );
    await user.clear(screen.getByLabelText(P.field.description));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).toContain('"description":null');
  });

  it('密码留空 = 保持原密码（PATCH 里没有 password 键）', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, ACTIVE_KB.name),
      }),
    );

    // 编辑态把账号带出来，密码栏永远是空的（D26：明文读不到）。
    expect(screen.getByLabelText(P.field.username)).toHaveValue(ACTIVE_KB.username);
    expect(screen.getByLabelText(P.field.password)).toHaveValue('');
    expect(screen.getByText(P.field.passwordSet)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).not.toContain('password');
    expect(api.body('PATCH', `/api/rag-knowledge/${ACTIVE_KB.id}`)).toMatchObject({
      username: ACTIVE_KB.username,
    });
  });

  it('点「清除密码」后 PATCH 带 password: null', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, ACTIVE_KB.name),
      }),
    );
    await user.click(screen.getByRole('button', { name: P.field.clearPassword }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).toContain('"password":null');
  });

  it('保存失败时在面板里报出来，表单不被关掉', async () => {
    const user = userEvent.setup();
    stubConfigApi({
      list: LIST_OK,
      write: () => jsonResponse(errorEnvelope('conflict', 'error.conflict.default'), 409),
    });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, SPARE_KB.name),
      }),
    );
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(
      await screen.findByText(fill(FORM.saveFailed, { reason: zhCN.error.conflict.default })),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: FORM.save })).toBeInTheDocument();
  });
});

describe('RAG 知识库面板 — API Key', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('新建时填了 API Key 就一起送出去', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));
    await user.type(screen.getByLabelText(P.field.name), '产品知识库');
    await user.type(screen.getByLabelText(P.field.routeUrl), 'https://kb.example.com/kb/42');
    await user.type(screen.getByLabelText(P.field.apiKey), 'ragk_test_key');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: P.create })).toBeInTheDocument();
    expect(api.body('POST', '/api/rag-knowledge')).toMatchObject({
      // 与密码同理：原样送出，不做 trim。
      apiKey: 'ragk_test_key',
    });
  });

  it('编辑时留空 = 保持原密钥（PATCH 里没有 apiKey 键）', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, ACTIVE_KB.name),
      }),
    );

    // D26：读侧只有"配没配"，明文永不回显。
    expect(screen.getByLabelText(P.field.apiKey)).toHaveValue('');
    expect(apiKeyHint()).toHaveTextContent(P.field.apiKeySet);

    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).not.toContain('apiKey');
  });

  it('点「清除 API Key」后 PATCH 带 apiKey: null', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.edit, ACTIVE_KB.name),
      }),
    );
    await user.click(screen.getByRole('button', { name: P.field.clearApiKey }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).toContain('"apiKey":null');
  });

  it('服务端预置了默认密钥时，"留空"的含义不同，提示语跟着变', async () => {
    const user = userEvent.setup();
    stubConfigApi({
      list: LIST_EMPTY,
      defaults: jsonResponse(envelope({ hasDefaultApiKey: true })),
    });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: P.create }));

    /*
     * 默认那句"留空表示不设置"在这里是错的：留空会用上服务端预置的那一枚。
     * 用户按错误提示理解，会以为自己刚保存的配置没生效。
     */
    await waitFor(() => {
      expect(apiKeyHint()).toHaveTextContent(P.field.apiKeyUnsetDefault);
    });
    expect(apiKeyHint()).not.toHaveTextContent(P.field.apiKeyUnset);
  });
});

describe('RAG 知识库面板 — 设为可用', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('POST 到 /rag-knowledge/:id/activate，而不是 PATCH 列表接口', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.activate, SPARE_KB.name),
      }),
    );

    expect(api.has('POST', `/api/rag-knowledge/${SPARE_KB.id}/activate`)).toBe(true);
    expect(api.calls().some((call) => call.method === 'PATCH')).toBe(false);
  });

  it('失败时在面板里报出来', async () => {
    const user = userEvent.setup();
    stubConfigApi({
      list: LIST_OK,
      write: () => jsonResponse(errorEnvelope('forbidden', 'error.forbidden'), 403),
    });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.activate, SPARE_KB.name),
      }),
    );

    expect(
      await screen.findByText(fill(FORM.actionFailed, { reason: zhCN.error.forbidden.default })),
    ).toBeInTheDocument();
  });
});

describe('RAG 知识库面板 — 删除', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('确认框初始焦点在「取消」，点取消不发 DELETE', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.remove, SPARE_KB.name),
      }),
    );

    expect(screen.getByRole('dialog', { name: FORM.deleteConfirmTitle })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: FORM.cancel })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: FORM.cancel }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.calls().some((call) => call.method === 'DELETE')).toBe(false);
  });

  it('确认之后才发 DELETE，且删的是那一行', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.remove, SPARE_KB.name),
      }),
    );
    await user.click(screen.getByRole('button', { name: FORM.delete }));

    expect(api.has('DELETE', `/api/rag-knowledge/${SPARE_KB.id}`)).toBe(true);
    expect(api.has('DELETE', `/api/rag-knowledge/${ACTIVE_KB.id}`)).toBe(false);
  });

  it('删的是可用项时，确认语要说明"删完就没有可用的了"', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(P.action.remove, ACTIVE_KB.name),
      }),
    );

    // 服务端不会自动把别的一条改成可用，前端也不替用户选，所以必须说清后果。
    expect(screen.getByRole('dialog', { name: FORM.deleteConfirmTitle })).toHaveTextContent(
      P.deleteActiveWarning,
    );

    await user.click(screen.getByRole('button', { name: FORM.cancel }));
    await user.click(
      screen.getByRole('button', { name: rowAction(P.action.remove, SPARE_KB.name) }),
    );
    expect(screen.getByRole('dialog', { name: FORM.deleteConfirmTitle })).not.toHaveTextContent(
      P.deleteActiveWarning,
    );
  });
});

describe('RAG 知识库面板 — 从侧栏「知识库」进来时直接新增', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('带一次性请求挂载时直接展开新增表单，并预勾「设为可用」', async () => {
    stubConfigApi({ list: LIST_EMPTY });
    // 侧栏/知识库页在跳过来之前写下这个标记（见 `knowledge-page.test.tsx`）。
    useUiStore.setState({ settingsCreateRequested: true });

    renderPanel();

    // 不等用户再点一次「新增知识库」：点菜单的人想要的是一张能填的表单。
    expect(await screen.findByRole('heading', { name: P.createTitle })).toBeInTheDocument();
    /*
     * 唯一一处默认勾上它。不勾的话，用户照提示填完、保存，侧栏「知识库」仍然是
     * 按钮——"新建了却还是打不开"，这条链路最容易漏的就是这一步。
     */
    expect(screen.getByRole('switch', { name: P.field.isActive })).toBeChecked();
    // 只是打开表单，不能顺手建一条空记录。
    expect(screen.queryByText(P.empty.title)).toBeNull();
  });

  it('请求只生效一次：消费后关掉表单不会又弹回来', async () => {
    stubConfigApi({ list: LIST_EMPTY });
    useUiStore.setState({ settingsCreateRequested: true });

    renderPanel();
    await screen.findByRole('heading', { name: P.createTitle });

    // 标记必须被清掉，否则之后任何一次重新挂载面板都会莫名其妙地停在表单上。
    expect(useUiStore.getState().settingsCreateRequested).toBe(false);

    await userEvent.setup().click(screen.getByRole('button', { name: FORM.cancel }));

    expect(await screen.findByText(P.empty.title)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: P.createTitle })).toBeNull();
  });

  it('面板自己的「新增知识库」不受影响：仍然默认不勾「设为可用」', async () => {
    stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    await userEvent.setup().click(await screen.findByRole('button', { name: P.create }));

    // 从设置里主动新增的人可能只是在存一条备用地址，替用户激活会换掉正在用的那条。
    expect(screen.getByRole('switch', { name: P.field.isActive })).not.toBeChecked();
  });
});
