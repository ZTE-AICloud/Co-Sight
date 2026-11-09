/**
 * 模型设置面板（设置 → 模型设置）。
 *
 * 这些用例的重心**不在界面上**：面板做错的代价几乎都落在请求体里，而请求体在
 * 屏幕上一个字都看不到。留空的密钥被映射成空串（服务端 422）、编辑时多送了一个
 * `apiKey`（用户没打算改的密钥被覆盖）、数值被当成字符串送上去——三种都是"界面
 * 看起来完全正常"的故障。所以每个写操作都解出请求体来断言。
 *
 * 文案一律从词表取（同 `settings-dialog.test.tsx`）：这里钉的是"点哪个按钮发生
 * 什么"，不是文案本身。写死在测试里的话，改一个字就会让用例以"找不到元素"失败，
 * 而失败信息指向一个与被测行为无关的方向。
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ModelConfig } from 'harness-shared';
import { beforeEach, describe, expect, it } from 'vitest';

import { ModelSettingsPanel } from '../src/features/models/ModelSettingsPanel';
import { emptyModelDraft, validateModelDraft } from '../src/features/models/modelForm';
import { enUS } from '../src/i18n/messages/en-US';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { useUiStore } from '../src/stores/ui';
import { stubConfigApi } from './helpers/configApi';
import {
  envelope,
  errorEnvelope,
  jsonResponse,
  renderWithProviders,
  resetUiStore,
  stubFetchSequence,
} from './helpers/render';

const M = zhCN.settings.model;
const FORM = zhCN.settings.form;

/** 词条里带 `{name}` / `{field}` 的句子，断言前先按调用点的实参填好。 */
function fill(template: string, values: Record<string, string>): string {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replace(`{${key}}`, value),
    template,
  );
}

const ACTIVE_MODEL: ModelConfig = {
  id: '11111111-1111-4111-8111-111111111111',
  provider: 'openai',
  label: '内部 Qwen3-32B',
  baseUrl: null,
  modelName: 'qwen3-32b',
  apiKeyMasked: 'sk-••••',
  hasApiKey: true,
  isActive: true,
  temperature: 0.7,
  topP: 1,
  maxOutputTokens: null,
  contextWindow: null,
  timeoutSeconds: 120,
  createdAt: '2026-01-01T00:00:00.000Z',
  updatedAt: '2026-01-02T00:00:00.000Z',
};

const SPARE_MODEL: ModelConfig = {
  ...ACTIVE_MODEL,
  id: '22222222-2222-4222-8222-222222222222',
  provider: 'ollama',
  label: '本地 Ollama',
  modelName: 'qwen3:8b',
  apiKeyMasked: null,
  hasApiKey: false,
  isActive: false,
  baseUrl: 'http://localhost:11434/v1',
};

const LIST_OK = jsonResponse(envelope([ACTIVE_MODEL, SPARE_MODEL]));
const LIST_EMPTY = jsonResponse(envelope([]));

/** 有配置、但一条生效的都没有（都被停用）。 */
const PAUSED_MODEL: ModelConfig = {
  ...SPARE_MODEL,
  id: '55555555-5555-4555-8555-555555555555',
  label: '备用 Qwen3-8B',
};
const LIST_ALL_PAUSED = jsonResponse(envelope([{ ...ACTIVE_MODEL, isActive: false }, PAUSED_MODEL]));

function renderPanel(): void {
  renderWithProviders(<ModelSettingsPanel />);
}

/** 行内操作按钮的可访问名（带资源名，见 `settings.model.action.*`）。 */
function rowAction(template: string, name: string): string {
  return fill(template, { name });
}

/**
 * 「推理参数」那个 `<details>`。
 *
 * 用 `selector: 'summary'` 定位，因为同一个标题在页面里出现两次：`<summary>` 里
 * 是给人看的，`<fieldset>` 的 `<legend>` 里是 `visually-hidden` 给读屏用的。
 */
function advancedSection(): HTMLDetailsElement {
  const summary = screen.getByText(M.advanced.title, { selector: 'summary' });
  return summary.closest('details') as HTMLDetailsElement;
}

/**
 * 展开表单里默认收起的「推理参数」。
 *
 * `userEvent` 在 jsdom 里不会因为内容被折起来就拒绝输入（jsdom 没有排版，
 * 也就不会把 `<details>` 里收起的内容标成不可见），所以**不展开也能敲进去**。
 * 用例仍然显式点这一下，是为了让它们走真实用户的路径：哪天收起改成"不渲染子节点"
 * 或者换成自己实现的可折叠容器，这些用例照旧成立，不会以一堆"找不到输入框"失败。
 */
async function expandAdvanced(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByText(M.advanced.title, { selector: 'summary' }));
}

describe('模型设置面板 — 列表', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('每行显示名称、当前使用徽标与密钥状态', async () => {
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    expect(await screen.findByText(ACTIVE_MODEL.label)).toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);

    const [active, spare] = rows as [HTMLElement, HTMLElement];

    /*
     * 「当前使用」是**互斥**状态，只有一行该有它。只断言"存在"的话，
     * 把徽标渲染到每一行上也能通过。
     */
    expect(within(active).getByText(M.activeBadge)).toBeInTheDocument();
    expect(within(spare).queryByText(M.activeBadge)).toBeNull();

    /*
     * 次要信息里必须带上密钥状态：D26 下界面上读不到密钥本身，
     * 用户判断"这条到底配没配过"只有这一个来源。
     */
    expect(active).toHaveTextContent(M.provider.openai);
    expect(active).toHaveTextContent(ACTIVE_MODEL.modelName);
    expect(active).toHaveTextContent(M.keyConfigured);
    expect(spare).toHaveTextContent(M.keyMissing);

    /*
     * 已经是当前使用的那一行**不该**再有「设为当前使用」：一个点下去不改变任何
     * 状态的按钮，会让人怀疑刚才那一下没生效。
     */
    expect(
      within(active).queryByRole('button', {
        name: rowAction(M.action.activate, ACTIVE_MODEL.label),
      }),
    ).toBeNull();
    expect(
      within(spare).getByRole('button', {
        name: rowAction(M.action.activate, SPARE_MODEL.label),
      }),
    ).toBeInTheDocument();
  });

  it('一个都没有时显示空态，并保留「新增模型」入口', async () => {
    stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    expect(await screen.findByText(M.empty.title)).toBeInTheDocument();
    expect(screen.getByText(M.empty.hint)).toBeInTheDocument();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    // 空态下入口必须还在：只给一句"还没有"而不给下一步该做什么，用户会卡在这里。
    expect(screen.getByRole('button', { name: M.create })).toBeInTheDocument();
  });

  it('加载失败显示错误面板，点「重试」会再发一次请求', async () => {
    const user = userEvent.setup();
    /*
     * 顺序打桩在这里是合适的：要钉的正是"第一次失败了，点重试之后第二次成功"。
     * 测试用的 Query 客户端 `retry: false`，所以第一次失败不会自己重发。
     */
    const mock = stubFetchSequence([
      jsonResponse(errorEnvelope('upstream_unavailable', 'error.upstream_unavailable'), 503),
      LIST_OK,
    ]);

    renderPanel();

    const panel = await screen.findByRole('alert');
    expect(within(panel).getByText(M.error.title)).toBeInTheDocument();
    // 失败原因来自服务端 messageKey 的翻译，不是"出错了"这种没有信息量的话。
    expect(within(panel).getByText(zhCN.error.upstream_unavailable)).toBeInTheDocument();
    // 失败时不能同时出现空态：那会让用户以为数据没了，而不是"没读到"。
    expect(screen.queryByText(M.empty.title)).toBeNull();

    await user.click(within(panel).getByRole('button', { name: zhCN.error.retry }));

    expect(await screen.findByText(ACTIVE_MODEL.label)).toBeInTheDocument();
    expect(mock.mock.calls).toHaveLength(2);
  });
});

describe('模型设置面板 — 新建', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('表单顶掉列表（不是追加在下面），取消后回到列表', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));

    expect(screen.getByRole('heading', { name: M.createTitle })).toBeInTheDocument();
    expect(screen.queryByText(ACTIVE_MODEL.label)).toBeNull();

    await user.click(screen.getByRole('button', { name: FORM.cancel }));
    expect(await screen.findByText(ACTIVE_MODEL.label)).toBeInTheDocument();
  });

  /*
   * 「设为当前使用」的初值随"当前有没有生效模型"变。这是全表单唯一一处"初值取决于
   * 列表内容"的地方，三种情况都钉住：一条都没有、已有生效、全被停用。
   *
   * 每个用例都先等列表落地再点「新增」——判断依据是已加载的列表数据，列表没回来时
   * 面板按"有生效模型"处理（宁可让用户手动拨一下，也不让新建的一条顶掉正在用的）。
   */
  it('一条模型都没有时，「设为当前使用」默认打开，保存即生效', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_EMPTY });
    renderPanel();

    expect(await screen.findByText(M.empty.title)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: M.create }));

    expect(screen.getByRole('switch', { name: M.advanced.isActive })).toBeChecked();

    await user.type(screen.getByLabelText(M.field.label), '内部 Qwen3-32B');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    // 首次配置不需要"保存完再点一次「设为当前使用」"。
    expect(api.body('POST', '/api/models')).toMatchObject({ isActive: true });
  });

  it('已有当前使用的模型时，「设为当前使用」默认关闭', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    expect(await screen.findByText(ACTIVE_MODEL.label)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: M.create }));

    // 不悄悄顶掉用户正在用的那条；要换，用户自己拨这个开关。
    expect(screen.getByRole('switch', { name: M.advanced.isActive })).not.toBeChecked();
  });

  it('模型都在停用时，「设为当前使用」同样默认打开', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_ALL_PAUSED });
    renderPanel();

    expect(await screen.findByText(PAUSED_MODEL.label)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: M.create }));

    // 平台本来就没有可用模型，默认打开不会顶掉谁。
    expect(screen.getByRole('switch', { name: M.advanced.isActive })).toBeChecked();
  });

  it('请求体：空白栏落到契约默认值与 null，数值是 number，密钥为 null', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.type(screen.getByLabelText(M.field.label), '  内部 Qwen3-32B  ');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: M.create })).toBeInTheDocument();

    /*
     * 整份比对而不是逐个键挑着看：多送一个键同样是故障（服务端 schema 是
     * `strict` 与否都会改变行为），逐键断言看不出来。
     *
     * 这里同时钉住了三件事：
     * - 名称被 trim 过（服务端 schema 也是 `.trim()`，两边口径必须一致，
     *   否则界面上显示的和库里存的会是两个字符串）；
     * - 数值是 **number**：`toEqual` 对 0.7 与 '0.7' 是不等的；
     * - 留空的 `baseUrl` / `apiKey` 是 `null` 而不是空串——**空串会被服务端
     *   按 `min(1)` 判成 422**，用户看到的是"参数校验未通过"这种没有指向的话。
     */
    expect(api.body('POST', '/api/models')).toEqual({
      provider: 'anthropic',
      label: '内部 Qwen3-32B',
      modelName: 'qwen3-32b',
      baseUrl: null,
      isActive: false,
      temperature: 0.7,
      topP: 1,
      timeoutSeconds: 120,
      maxOutputTokens: null,
      contextWindow: null,
      apiKey: null,
    });
  });

  it('供应商只有一个 Anthropic 选项，填了的值按填的送：数字解析成 number', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));

    /*
     * 产品约束：模型设置只支持 Anthropic。这条断言钉的是"其他类型**不在可选项里**"，
     * 而不是"选了也不生效"——下拉里留着一串选不动的选项，只会让人以为是坏了。
     */
    const providerSelect = screen.getByLabelText(M.field.provider);
    expect(providerSelect).toHaveValue('anthropic');
    expect(
      Array.from((providerSelect as HTMLSelectElement).options).map((option) => option.value),
    ).toEqual(['anthropic']);

    await user.type(screen.getByLabelText(M.field.label), '本地模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3:8b');
    await user.type(screen.getByLabelText(M.field.baseUrl), 'http://localhost:11434/v1');
    await expandAdvanced(user);
    // 先清空再敲：数值栏预填了契约默认值，直接 type 会追加成 `0.71.5` 这种值。
    await user.clear(screen.getByLabelText(M.advanced.temperature));
    await user.type(screen.getByLabelText(M.advanced.temperature), '1.5');
    await user.type(screen.getByLabelText(M.advanced.maxOutputTokens), '4096');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(await screen.findByRole('button', { name: M.create })).toBeInTheDocument();

    const body = api.body('POST', '/api/models');
    expect(body).toMatchObject({
      provider: 'anthropic',
      baseUrl: 'http://localhost:11434/v1',
      temperature: 1.5,
      maxOutputTokens: 4096,
    });
  });

  it('缺必填项时不发请求，错误挂在该字段上', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    /*
     * 只说"没通过"是没用的：错误要挂在**具体那一栏**上（`FieldShell` 用
     * `role="alert"` 播报，并经由 `aria-describedby` 关联到输入框），
     * 而请求**一个都不能发**——把必然被驳回的请求发出去，用户拿到的是一句
     * "参数校验未通过"，还得自己猜是哪一栏。
     */
    expect(
      await screen.findByText(fill(FORM.required, { field: M.field.label })),
    ).toBeInTheDocument();
    expect(api.calls()).toHaveLength(1); // 只有最初那一次列表 GET

    // 补上之后错误消失，再提交就发出去了（错误提示不能一直挂着）。
    await user.type(screen.getByLabelText(M.field.label), '内部模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');
    expect(screen.queryByText(fill(FORM.required, { field: M.field.label }))).toBeNull();

    await user.click(screen.getByRole('button', { name: FORM.save }));
    expect(await screen.findByRole('button', { name: M.create })).toBeInTheDocument();
    expect(api.has('POST', '/api/models')).toBe(true);
  });

  it('数值越界时报错并说明范围，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.type(screen.getByLabelText(M.field.label), '内部模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');

    /*
     * 用真实用户敲得出来的值：`type="number"` 的输入框会做值净化，字母根本留不在
     * `.value` 里（见下面"校验函数的边界"那一段）。而"5 超出了 0–2"是完全可达的，
     * 也是服务端的 `.max(2)` 会驳回的那一种。
     */
    await expandAdvanced(user);
    const temperature = screen.getByLabelText(M.advanced.temperature);
    await user.clear(temperature);
    await user.type(temperature, '5');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(
      await screen.findByText(
        fill(M.invalidRange, { field: M.advanced.temperature, min: '0', max: '2' }),
      ),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/models')).toBe(false);
  });

  it('整数栏填了小数时报错，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.type(screen.getByLabelText(M.field.label), '内部模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');
    await expandAdvanced(user);
    await user.type(screen.getByLabelText(M.advanced.maxOutputTokens), '1.5');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    /*
     * `1.5` 必须被拒，而不是被悄悄取整成 1 或 2：用户敲下去的数和存下来的数
     * 得是同一个，否则他会以为"我明明填了 1.5"。
     */
    expect(
      await screen.findByText(
        fill(FORM.invalidPositiveInteger, { field: M.advanced.maxOutputTokens }),
      ),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/models')).toBe(false);
  });

  it('网关地址填了非 http(s) 协议就报错，不发请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.type(screen.getByLabelText(M.field.label), '内部模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');
    await user.type(screen.getByLabelText(M.field.baseUrl), 'ftp://x');
    await user.click(screen.getByRole('button', { name: FORM.save }));

    /*
     * `ftp://x` 在 `new URL` 下是合法的，所以只靠"能不能解析"判不出来——
     * 服务端用的是 `z.url({ protocol: /^https?$/ })`，前端必须同一条口径。
     */
    expect(
      await screen.findByText(fill(FORM.invalidUrl, { field: M.field.baseUrl })),
    ).toBeInTheDocument();
    expect(api.has('POST', '/api/models')).toBe(false);
  });
});

describe('模型设置面板 — 推理参数的折叠', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('默认收起，点标题展开；标题上那句说明在收起时也看得到', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));

    /*
     * 默认收起是这块设计的全部意义：推理参数的值绝大多数人不动，摊开来只会把
     * 「保存」推出一屏。断言 `open` 而不是"看不见输入框"——jsdom 不做排版，
     * 收起的内容依然在 DOM 里，用可见性断言等于什么都没测。
     */
    expect(advancedSection().open).toBe(false);

    // 收起了就得说明为什么可以不管它，否则看着像"还有东西没填完"。
    expect(screen.getByText(M.advanced.collapsedHint)).toBeInTheDocument();

    await expandAdvanced(user);
    expect(advancedSection().open).toBe(true);
    expect(screen.getByLabelText(M.advanced.temperature)).toBeInTheDocument();
  });

  it('收起状态下提交，出错会把推理参数撑开', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.type(screen.getByLabelText(M.field.label), '内部模型');
    await user.type(screen.getByLabelText(M.field.modelName), 'qwen3-32b');

    // 用户改错了值又把区域合上——这是"错误落在看不见的地方"的唯一到达路径，
    // 也是这一次收起的代价。不撑开的话，用户点保存得不到任何反馈。
    await expandAdvanced(user);
    await user.clear(screen.getByLabelText(M.advanced.temperature));
    await user.type(screen.getByLabelText(M.advanced.temperature), '5');
    await user.click(screen.getByText(M.advanced.title, { selector: 'summary' }));
    expect(advancedSection().open).toBe(false);

    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(advancedSection().open).toBe(true);
    expect(
      await screen.findByText(
        fill(M.invalidRange, { field: M.advanced.temperature, min: '0', max: '2' }),
      ),
    ).toBeInTheDocument();
    // 请求照旧不发：这里是"撑开让用户改"，不是"放它过去"。
    expect(api.has('POST', '/api/models')).toBe(false);
  });

  it('只有上层字段出错时不动折叠状态', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(await screen.findByRole('button', { name: M.create }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    await screen.findByText(fill(FORM.required, { field: M.field.label }));
    // 上层字段的错误本来就在眼前，顺手把这一节撑开会把用户刚看的表单顶走。
    expect(advancedSection().open).toBe(false);
  });
});

describe('模型设置面板 — 编辑', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('密钥栏留空时请求体里**没有** apiKey 这个键', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.edit, ACTIVE_MODEL.label),
      }),
    );

    // 编辑态的密钥框必然是空的（D26 读不到明文），"已配置"由提示语表达。
    const secret = screen.getByLabelText(M.field.apiKey);
    expect(secret).toHaveValue('');
    expect(screen.getByText(M.field.apiKeySet)).toBeInTheDocument();
    // 模型标识是回填的——不回填的话，用户一保存就把模型标识清空了。
    expect(screen.getByLabelText(M.field.modelName)).toHaveValue(ACTIVE_MODEL.modelName);

    await user.click(screen.getByRole('button', { name: FORM.save }));

    const patch = api.calls().find((call) => call.method === 'PATCH');
    /*
     * 断言**序列化之后的字符串**里没有这个键，而不是断言它等于 undefined：
     * `undefined` 在 `JSON.stringify` 里会被丢掉，服务端据此保持原密钥（D26 的
     * 三态之一）。写成"等于 undefined"的话，把空串映射进请求体也能通过。
     */
    expect(patch?.body).not.toContain('apiKey');

    // 其余字段照常送，且是"整条替换"的语义（PATCH 里给了的键就是新值）。
    expect(api.body('PATCH', `/api/models/${ACTIVE_MODEL.id}`)).toMatchObject({
      label: ACTIVE_MODEL.label,
      modelName: ACTIVE_MODEL.modelName,
      isActive: true,
      temperature: 0.7,
      timeoutSeconds: 120,
    });
  });

  it('编辑历史遗留的非 Anthropic 模型：表单收敛到 Anthropic，保存时也送 Anthropic', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    // ACTIVE_MODEL 的供应商是 openai（历史上存下来的）。下拉里只有 Anthropic，
    // 原值留着就会显示成"一项都不选中"，而保存又把旧类型原样发回去。
    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.edit, ACTIVE_MODEL.label),
      }),
    );

    expect(screen.getByLabelText(M.field.provider)).toHaveValue('anthropic');

    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(api.body('PATCH', `/api/models/${ACTIVE_MODEL.id}`)).toMatchObject({
      provider: 'anthropic',
    });
  });

  it('点过「清除密钥」再保存，请求体里是 "apiKey": null；再点一次可以撤销', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.edit, ACTIVE_MODEL.label),
      }),
    );

    const clear = screen.getByRole('button', { name: M.field.clearKey });
    await user.click(clear);

    /*
     * 关键：这一步**不立即生效**。用户点「清除密钥」的真实动机常常只是
     * "想改个名字时顺手点错了"，而密钥一旦删掉服务端也读不回来（明文不回显），
     * 只能重新去供应商那里生成。所以它只是一个待保存的意图，按钮文字要明说
     * "这一步还没有发生"，并且可以点回去撤销。
     */
    expect(screen.getByRole('button', { name: M.field.clearKeyPending })).toBeInTheDocument();
    expect(api.has('PATCH', `/api/models/${ACTIVE_MODEL.id}`)).toBe(false);

    await user.click(screen.getByRole('button', { name: M.field.clearKeyPending }));
    expect(screen.getByRole('button', { name: M.field.clearKey })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: M.field.clearKey }));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    const patch = api.calls().find((call) => call.method === 'PATCH');
    // `null` 是"清除"那一态，和"保持"（键不出现）必须是两个可分辨的请求体。
    expect(patch?.body).toContain('"apiKey":null');
  });

  it('清空可空字段 = 送 null，清空非空字段 = 不送这个键', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.edit, SPARE_MODEL.label),
      }),
    );

    /*
     * 两个方向都要钉：
     * - 网关地址是可空的，清空它就是"用供应商官方地址"，所以要送 `null`；
     * - 温度不可空，清空它没有 `null` 可表达，最合理的解读是"别动它"，
     *   所以要**整个键不送**——送一个数字等于替用户做了主。
     * 只测其中一个方向的话，另一侧写成"空串/0"都不会被发现。
     */
    await user.clear(screen.getByLabelText(M.field.baseUrl));
    await expandAdvanced(user);
    await user.clear(screen.getByLabelText(M.advanced.temperature));
    await user.click(screen.getByRole('button', { name: FORM.save }));

    const raw = api.calls().find((call) => call.method === 'PATCH')?.body ?? '';
    expect(raw).toContain('"baseUrl":null');
    expect(raw).not.toContain('temperature');
  });

  it('保存失败时在面板里报出来，不吞掉', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({
      list: LIST_OK,
      write: () => jsonResponse(errorEnvelope('validation_failed', 'error.validation_failed'), 422),
    });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.edit, ACTIVE_MODEL.label),
      }),
    );
    await user.click(screen.getByRole('button', { name: FORM.save }));

    expect(
      await screen.findByText(
        fill(FORM.saveFailed, { reason: zhCN.error.validation_failed }),
      ),
    ).toBeInTheDocument();
    // 表单不能因为保存失败就被关掉——用户刚敲的东西还在里面。
    expect(screen.getByRole('button', { name: FORM.save })).toBeInTheDocument();
    expect(api.has('PATCH', `/api/models/${ACTIVE_MODEL.id}`)).toBe(true);
  });
});

describe('模型设置面板 — 删除', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('确认框初始焦点在「取消」，点取消不发任何请求', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.remove, SPARE_MODEL.label),
      }),
    );

    expect(screen.getByRole('dialog', { name: FORM.deleteConfirmTitle })).toBeInTheDocument();
    // 危险操作的默认值必须是最安全的那个：弹窗一出现时用户的手还在"确定"附近。
    expect(screen.getByRole('button', { name: FORM.cancel })).toHaveFocus();
    expect(screen.getByText(fill(FORM.deleteConfirmMessage, { name: SPARE_MODEL.label })))
      .toBeInTheDocument();

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
        name: rowAction(M.action.remove, SPARE_MODEL.label),
      }),
    );
    // 行内按钮的可访问名带资源名（"删除「本地 Ollama」"），确认框里的确认按钮
    // 就是干净的「删除」，两者不会撞名。
    await user.click(screen.getByRole('button', { name: FORM.delete }));

    expect(api.has('DELETE', `/api/models/${SPARE_MODEL.id}`)).toBe(true);
    expect(api.has('DELETE', `/api/models/${ACTIVE_MODEL.id}`)).toBe(false);
  });

  it('删的是当前使用的那个时，确认语要说明"删完就没有当前使用的了"', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.remove, ACTIVE_MODEL.label),
      }),
    );

    /*
     * 服务端不会自动把别的模型改成"当前使用"，前端也不替用户选——
     * 那就必须把后果说出来，否则用户按下确认时以为会平滑过渡。
     */
    const dialog = screen.getByRole('dialog', { name: FORM.deleteConfirmTitle });
    expect(dialog).toHaveTextContent(M.deleteActiveWarning);

    // 不是当前使用的那一行不该带这句（否则这句话就成了无差别的噪音）。
    await user.click(screen.getByRole('button', { name: FORM.cancel }));
    await user.click(
      screen.getByRole('button', { name: rowAction(M.action.remove, SPARE_MODEL.label) }),
    );
    expect(screen.getByRole('dialog', { name: FORM.deleteConfirmTitle })).not.toHaveTextContent(
      M.deleteActiveWarning,
    );
  });

  it('删除失败时把原因报出来', async () => {
    const user = userEvent.setup();
    stubConfigApi({
      list: LIST_OK,
      write: () => jsonResponse(errorEnvelope('conflict', 'error.conflict.default'), 409),
    });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.remove, SPARE_MODEL.label),
      }),
    );
    await user.click(screen.getByRole('button', { name: FORM.delete }));

    expect(
      await screen.findByText(fill(FORM.deleteFailed, { reason: zhCN.error.conflict.default })),
    ).toBeInTheDocument();
  });
});

describe('模型设置面板 — 设为当前使用', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('POST 到 /models/:id/activate，而不是 PATCH 列表接口', async () => {
    const user = userEvent.setup();
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: rowAction(M.action.activate, SPARE_MODEL.label),
      }),
    );

    expect(api.has('POST', `/api/models/${SPARE_MODEL.id}/activate`)).toBe(true);
    // 走错接口（比如 PATCH isActive）在这里就会红：服务端那两个接口的语义不同
    // （activate 会把别的置为 false，PATCH 不会）。
    expect(api.calls().some((call) => call.method === 'PATCH')).toBe(false);
  });
});

describe('模型设置面板 — 校验函数的边界', () => {
  /*
   * `abc` 这类**字母**进不了 `type="number"` 的输入框：该输入框有值净化算法，
   * 非数字字符不会留在 `.value` 里（浏览器如此，jsdom 也如此）。也就是说
   * "这一栏解析不出数字"这一支从界面上摸不到——它靠这几行纯函数保住，
   * 而不是靠组件用例。这一支仍然有用：浏览器自动填充、以及将来可能出现的
   * 文本型数字栏，走的都是同一条解析路径。
   */
  it('解析不出数字时报"要填一个数字"，越界时报范围', () => {
    expect(validateModelDraft({ ...emptyModelDraft(), temperature: 'abc' }).temperature).toEqual({
      kind: 'number',
    });
    expect(validateModelDraft({ ...emptyModelDraft(), temperature: '5' }).temperature).toEqual({
      kind: 'range',
      min: 0,
      max: 2,
    });
    expect(
      validateModelDraft({ ...emptyModelDraft(), maxOutputTokens: '1.5' }).maxOutputTokens,
    ).toEqual({ kind: 'positiveInteger' });
    // 空串不是错误：它表示"没填"，三个可空字段靠它映射成 null。
    expect(validateModelDraft(emptyModelDraft()).temperature).toBeUndefined();
  });
});

describe('模型设置面板 — 语言', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('界面语言是英文时，面板文案跟着换', async () => {
    useUiStore.setState({ locale: 'en-US' });
    stubConfigApi({ list: jsonResponse(envelope([SPARE_MODEL])) });
    renderPanel();

    expect(await screen.findByText(enUS.settings.model.listSection)).toBeInTheDocument();
    // 等行真的渲染出来再断言行上的文案：小节标题是同步渲染的，列表要等请求回来。
    await screen.findByText(SPARE_MODEL.label);
    expect(screen.getByRole('button', { name: enUS.settings.model.create })).toBeInTheDocument();
    // 密钥状态与供应商、模型标识同在一行次要信息里，所以断行不断句。
    expect(screen.getAllByRole('listitem')[0]).toHaveTextContent(enUS.settings.model.keyMissing);

    // 表单里的字段名同样要翻（只翻列表是最容易漏的一处：表单是另一棵树）。
    await userEvent.setup().click(
      screen.getByRole('button', {
        name: fill(enUS.settings.model.action.edit, { name: SPARE_MODEL.label }),
      }),
    );
    expect(screen.getByRole('heading', { name: enUS.settings.model.editTitle })).toBeInTheDocument();
    expect(screen.getByLabelText(enUS.settings.model.field.modelName)).toBeInTheDocument();
  });
});

describe('模型设置面板 — 只读详情', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('行内次要信息里有网关地址：为空时明确说"跟随默认"', async () => {
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await screen.findByText(ACTIVE_MODEL.label);
    const [active, spare] = screen.getAllByRole('listitem') as [HTMLElement, HTMLElement];

    // ACTIVE_MODEL 的 baseUrl 是 null。显示一个空字符串会让人以为"没读到"，
    // 而这里要表达的是"不填 = 用供应商的官方地址"。
    expect(active).toHaveTextContent(M.baseUrlDefault);
    expect(spare).toHaveTextContent(String(SPARE_MODEL.baseUrl));
  });

  it('点标题进只读详情：全字段都在，且不经过编辑表单', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: fill(M.action.view, { name: ACTIVE_MODEL.label }),
      }),
    );

    expect(screen.getByRole('heading', { name: M.detail.title })).toBeInTheDocument();
    // 关键：这是**只读**视图，不该出现任何输入框（进了编辑表单就有输入框了）。
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByText(M.keyConfigured)).toBeInTheDocument();
    expect(screen.getByText(String(ACTIVE_MODEL.temperature))).toBeInTheDocument();
    expect(screen.getByText(M.detail.unlimited)).toBeInTheDocument(); // maxOutputTokens: null
    expect(screen.getByText(M.detail.unset)).toBeInTheDocument(); // contextWindow: null

    // 详情顶掉了列表：否则"当前在看哪条"取决于视线，而不是状态。
    expect(screen.queryByRole('button', { name: M.create })).toBeNull();
  });

  it('详情里点「编辑」直接进表单，不会两个视图叠着', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await user.click(
      await screen.findByRole('button', {
        name: fill(M.action.view, { name: ACTIVE_MODEL.label }),
      }),
    );
    await user.click(screen.getByRole('button', { name: M.detail.back }));

    // 返回列表
    expect(await screen.findByRole('button', { name: M.create })).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: fill(M.action.view, { name: ACTIVE_MODEL.label }) }),
    );
    await user.click(screen.getByRole('button', { name: FORM.edit }));

    expect(screen.getByRole('heading', { name: M.editTitle })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: M.detail.title })).toBeNull();
  });
});

describe('模型设置面板 — 模块接入卡', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('默认折叠，且折叠时不发健康检查请求', async () => {
    const api = stubConfigApi({ list: LIST_OK });
    renderPanel();

    await screen.findByText(ACTIVE_MODEL.label);
    expect(screen.getByText(M.moduleAccess.title)).toBeInTheDocument();
    // 这块内容绝大多数人不会展开，不该在打开列表时顺带拉一次 /api/health。
    expect(api.has('GET', '/api/health')).toBe(false);
  });

  it('展开后给出接口基址、令牌文件路径与可复制的 curl', async () => {
    const user = userEvent.setup();
    stubConfigApi({ list: LIST_OK });
    renderPanel();

    await screen.findByText(ACTIVE_MODEL.label);
    await user.click(screen.getByText(M.moduleAccess.title));

    // 令牌路径取自服务端返回的实际数据目录，不是前端猜的默认值。
    expect(await screen.findByText('/tmp/cosight-home/.module-token')).toBeInTheDocument();
    expect(screen.getByText('http://localhost:3000/api/framework/v1/models')).toBeInTheDocument();

    // curl 必须指明"从文件读令牌"——写成 .env 注入正是要避免的做法。
    const curl = screen.getByText(/curl -H "Authorization: Bearer/);
    expect(curl).toHaveTextContent('/tmp/cosight-home/.module-token');
    // 权限面要在界面上说出口：这组接口**能写**，而且只读消费方不该顺手要写权限。
    // 反向的旧文案（"这组接口是只读的"）会让模块作者以为写操作无处可去而去改别人的库。
    expect(screen.getByText(M.moduleAccess.scope)).toBeInTheDocument();
  });

  it('拿不到数据目录时不编一个默认路径', async () => {
    const user = userEvent.setup();
    stubConfigApi({
      list: LIST_OK,
      health: jsonResponse(errorEnvelope('INTERNAL', 'error.internal'), 500),
    });
    renderPanel();

    await screen.findByText(ACTIVE_MODEL.label);
    await user.click(screen.getByText(M.moduleAccess.title));

    expect(await screen.findByText(M.moduleAccess.tokenFileUnknown)).toBeInTheDocument();
    // 编一个 `~/.cosight-harness/.module-token` 会让用户照着去找一个不存在的文件。
    expect(screen.queryByText(/\/\.module-token$/)).toBeNull();
  });
});
