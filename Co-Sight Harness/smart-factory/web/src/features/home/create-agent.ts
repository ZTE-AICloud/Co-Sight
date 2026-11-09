import { msg } from '../../i18n/useI18n';
import { agentsApi } from '../../shared/api/agents';
import type { AgentCreateResult } from '../../shared/api/agents';
import { ApiError } from '../../shared/api/client';
import { workspacesApi } from '../../shared/api/workspaces';
import { stripHarnessCommand } from '../../shared/commands/harness-prompt';

/**
 * 首页的「登记一个专家」：把用户那句话（或只挂的文件）变成创建接口要的
 * `{ workspaceId, name, description, tags, init }`。
 * 名字与描述取用户那句话，没有正文时用文件名兜；归属工作区取框架当前生效的那个，
 * 来源不用带（服务端恒写 `source='user'`）；用户原话与模型 id 随 `init` 交给后端，
 * 由它建初始化会话并校验模型 —— 首轮消息不在这里、也不在后端落库，
 * 由设计页补发（见 `HomePage` 的跳转 state）。
 * 这些都在这里定。
 *
 * 为什么这件事有单独一个文件：创建接口的 name 是**必填且唯一**的，而首页只让用户
 * 说一句话，没有第二个框让他填名字 —— 取名字、撞名怎么办这两条策略得有人负责。
 * 页面（HomePage）只管「点击 → 跳转 → 失败怎么显示」，不掺和命名规则。
 *
 * 名字只影响卡片上那行字：它不是身份（身份是后端发的 `agt_<uuid>`），
 * 用户也不用它做任何事，所以宁可给个稳定但粗糙的默认值，也不要拦着不让创建。
 */

/**
 * 名字截到这个长度为止（不是接口上限）。
 *
 * 接口上限是 40（契约 5.01 的 `Agent.name`），但那是在卡片标题上：
 * 24 个字已经足够把「天气智能体」这类短语装下，再长在卡片上就撑破一行了。
 */
const NAME_MAX = 24;

/**
 * 描述的上限，与后端 `Agent.description` 一致（契约 5.01，后端超了直接 400）。
 *
 * 首页只有一个框，用户往里写的是**需求**，不是摘要 —— 写长了是正常的，
 * 拦着不让建不对，悄悄丢掉后半截也不对。所以这里截的是**卡片摘要**这一面：
 * 全文不丢：`init.input` 照传全文（后端原样落进 `Agent.initialInput`），
 * 同时随路由 state 交给设计页当首轮 —— 设计页的助手拿它接着问，
 * 卡片上只显示这句截断的摘要。
 */
const DESCRIPTION_MAX = 120;

/**
 * 开头的套话，一层一层削：代词 → 情态/客气 → 动词 → 量词。
 *
 * 顺序就是它在中文里的顺序（「我 | 要 | 做 | 一个 …」），所以拆成四层按序 replace，
 * 而不是写一条大正则 —— 后者出了偏差看不出是哪一层吃的字。
 *
 * 单字动词（做/写/建/搭/弄/整/造）**必须跟着量词**才削：「建个仓库助手」要削掉「建个」，
 * 而「建站助手」「整体架构助手」里的首字是名字的一部分，削了就成了「站助手」。
 * 多字动词没有这个歧义（没人拿「创建」当名字开头），所以直接削。
 */
const LEAD_FILLER: RegExp[] = [
  /^(?:我们|我|你|俺)\s*/,
  /^(?:要|想要|想|需要|希望|请|帮我|帮忙|麻烦你?|给我)\s*/,
  /^(?:创建|新建|生成|搭建|设计|实现|开发|编写)\s*(?:一)?(?:个|款|只|套|种|些)?\s*/,
  /^(?:做|写|造|弄|建|搭|整)(?:一)?(?:个|款|只|套|种|些)\s*/,
  /^一(?:个|款|只|套|种|些)\s*/,
  // 英文界面下用户用英文提需求：与上面几层同义，按「客气语 → 动词 → 冠词」削。
  // 中文正则对英文输入本来就不命中，加这几条只影响英文，不改中文的行为。
  /^(?:please\s+)?(?:can you\s+|could you\s+)?(?:help me\s+)?/i,
  /^(?:i\s+(?:want|need|would like)\s+(?:to\s+)?)?/i,
  /^(?:create|build|make|design|develop|write|generate)\s+(?:me\s+)?(?:a|an|the)?\s*/i,
];

/** 名字取到第一个断句为止：一句话里的后半截是要求，不是名字 */
const NAME_STOP = /[\n。！？!?；;，,、：:.]/;

/**
 * 剥掉正文开头的一条 slash 命令（连它后面的知识检索参数一起）。
 *
 * 首页预置需求会默认挂上 `harness-create`，选了知识检索时还会带
 * `--knowledge-workflow-id <id>`；这些都随首轮发给会话（**必须保留**），
 * 但卡片上的名字与摘要不该出现它们 —— 名字取到第一个断句，`:` 会把命令截成
 * `/agent-genesis`，参数留下来则会让名字变成 `--knowledge-workflow-id …`。
 * 所以只在「展示字段」上剥掉，规则与生产会话共用一份（见 `harness-prompt.ts`）。
 */
const stripLeadCommand = stripHarnessCommand;

/**
 * 撞名后挂在名字后面的短码长度：4 位 base36 ≈ 167 万种。
 *
 * 不做「…2 / …3 / …4」的逐号试探 —— 那是拿请求去猜一个**只有后端知道的序号**：
 * 请求数随同名数量线性涨，而试探必须有上限，于是撞到上限仍然重名时这个入口就**永久
 * 失效**（「天气智能体」这类高频预置先坏：连点 5 次之后再也建不出来）。短码不依赖
 * 任何已知状态，一次就够。
 */
const SHORT_CODE_LEN = 4;

/**
 * 从需求原文里取一个名字。
 *
 * 两条规则，都只为「卡片上那行字能看」：
 * 1. 削掉开头的套话（见 LEAD_FILLER）
 * 2. 取到第一个断句为止，再截断
 *
 * **这不是「智能命名」**，只是一条稳定的兜底：用户不满意就去改描述（描述才是需求本身）。
 */
export function deriveName(prompt: string): string {
  const text = prompt.trim();
  let rest = stripLeadFiller(text);

  const [head] = rest.split(NAME_STOP);
  if (head !== undefined && head.trim() !== '') rest = head;

  // 带引号/括号的名字（「会议助手」）把壳去掉
  rest = rest
    .replace(/^[「『"'（(【[]+/, '')
    .replace(/[」』"'）)】\]]+$/, '')
    .trim();

  // 整句都被削没了（比如原文就是「帮我做一个」）就退回原文，别拿空串去建
  return truncate(rest === '' ? text : rest, NAME_MAX);
}

/**
 * 登记一个专家。
 *
 * 从一句话取名；撞名**不逐号试探**，而是给名字挂一个短码再发一次，**至多两次请求**：
 *
 *   第一次「天气智能体」    → 409
 *   第二次「天气智能体 k7x2」→ 几乎必然成功（见 SHORT_CODE_LEN）
 *
 * 为什么不试探「…2 / …3 / …4」：那是请求数随同名数量线性涨的猜序号游戏，且有上限
 * —— 上限一撞上，这个入口就永久失败（见 SHORT_CODE_LEN 的注释）。代价是撞名时名字
 * 带短码、不好看；但名字只影响卡片上那行字，它不是身份（身份是后端发的 `agt_<uuid>`），
 * 所以「宁可名字粗糙，也不要拦着创建」。
 *
 * 冲突不能弹回给用户：首页没有第二个框让他改名，弹个 409 等于把路堵死。真会撞 ——
 * 首页那四个预置需求连点两次就是同一句话，第二次必然 409。
 *
 * 只有 409（契约里的 CONFLICT）才改写名字；其余错误（400 / 后端没起 / 网络）直接抛给页面。
 */
export async function createAgentFromPrompt(
  prompt: string,
  modelId: string,
  /** 发送框里挂的附件路径（`ComposerAttachment.name` 就是路径）；只有附件时用第一份取名字 */
  attachments: string[] = [],
): Promise<AgentCreateResult> {
  const text = prompt.trim();
  /*
   * 展示字段（名字 / 卡片摘要）用剥掉开头命令之后的需求；发给会话的仍是全文（见 init.input）。
   * 只剩命令、没有正文时退回全文，别让名字变成空串（取名字的兜底见 nameFromFile）。
   */
  const demand = stripLeadCommand(text);
  const display = demand !== '' ? demand : text;
  // 卡片摘要截到上限；取名与首轮仍用（剥过命令的）全文，别让摘要规则渗进取名
  const description = truncate(display, DESCRIPTION_MAX);
  const base = demand !== '' ? deriveName(display) : nameFromFile(attachments[0]);

  /**
   * 归属工作区：**只认框架的当前生效工作区**，没有就报错，不拿列表第一个兜底 ——
   * 兜底会让「界面上显示的工作区」和「实际建进去的工作区」悄悄分叉。
   * 工作区的创建与切换在框架界面完成，这里不提供选择器。
   *
   * 放在两次尝试**之前**取一次：撞名重试换的只是名字，归属工作区不会变。
   * 列表端点本身不可用时抛的是后端给的 502 人话（框架没起 / 令牌不对），照原样往上抛。
   */
  const workspaceId = await resolveWorkspaceId();

  /**
   * 只有名字会变，其余每次都一样 —— 所以两次尝试共用一个构造函数，别把描述复制两份。
   *
   * 来源不用带：用户建的智能体在后端恒为 `source='user'`，由服务端写；
   * `tags` 只放用户标签，`自定义` / `内置` 是保留字（写进去会 400）。
   */
  const create = (name: string) =>
    agentsApi.create({
      workspaceId,
      name,
      // 卡片摘要（≤ 120，契约 5.01）；需求全文走 init.input 与路由 state，不在这里
      description,
      tags: [],
      /*
       * 初始化参数随创建一起交给后端：
       * - input 传全文（不传被截断的摘要），后端落进 Agent.initialInput；
       * - attachments 传 `[{ path }]`（与 messages/send 同一形状，后端共用一份校验），
       *   落进 Agent.initialAttachments 的是校验后的真实路径；
       * - modelId 是这场会话的模型，设计页打开时选择器就有值。
       *
       * 三者都**不落消息、不起 run**：首轮由设计页连上实时通道后补发，用户才能看到
       * 初始化过程。落库是为了路由 state 丢失（刷新 / 从列表再次进入）时还能恢复首轮。
       * 模型只传 id（不传模型名 / 端点 / 密钥）：id → 模型配置的解析在后端。
       */
      init: { input: text, modelId, attachments: attachments.map((path) => ({ path })) },
    });

  try {
    return await create(base);
  } catch (err) {
    if (!isConflict(err)) throw err;
  }

  try {
    return await create(nameWithShortCode(base));
  } catch (err) {
    // 第二次还是 409：短码撞上的概率约百万分之一，真走到这里多半说明重名的量级
    // 已经超出「加个后缀」能解决的范围。此时**别把「天气智能体 k7x2」这个用户从没
    // 打过的名字当结论报给他**（上一版就是这么报的，荒谬且没法动手）—— 换成一句人话。
    // 其余错误（后端没起 / 网络）照原样抛，它们的原因比我们的猜测有用
    if (isConflict(err)) {
      throw new Error(msg('home.nameTaken', { name: base }));
    }
    throw err;
  }
}

/**
 * 取这次创建要挂的工作区。
 *
 * 创建接口的 `workspaceId` 是必填的 —— 智能体的产物目录就落在该工作区下，
 * 没有工作区等于没有地方放产物，所以这里**不猜、也不留空**：框架没有当前工作区时
 * 直接把原因说清楚，而不是让后端回一句「workspaceId 必填」。
 *
 * 不拿「列表第一个」兜底：那等于在用户没选工作区时替他选了一个，
 * 专家页却严格按当前工作区展示 —— 建完回到列表就找不到刚建的智能体。
 */
async function resolveWorkspaceId(): Promise<string> {
  const { items, activeId } = await workspacesApi.list();
  if (activeId === null) {
    throw new Error(msg('home.noWorkspace'));
  }

  // activeId 指向一个已不存在的项：框架读取端会自愈清指针，这里只把结论说清楚
  if (!items.some((item) => item.id === activeId)) {
    throw new Error(msg('home.staleWorkspace'));
  }
  return activeId;
}

function stripLeadFiller(text: string): string {
  let rest = text;
  // 套话是好几个字叠着的（「帮我做一个」），一遍削一层。
  // 遍数写死 4 是防「削了又长回来」这类正则意外，不是真指望用到第 4 遍。
  for (let pass = 0; pass < 4; pass += 1) {
    const before = rest;
    LEAD_FILLER.forEach((pattern) => {
      rest = rest.replace(pattern, '');
    });
    if (rest === before) break;
  }
  return rest;
}

function isConflict(err: unknown): boolean {
  // 契约里重名是 409 + CONFLICT（5.01 的 `/agents` POST 的 409 响应）
  return err instanceof ApiError && (err.status === 409 || err.code === 'CONFLICT');
}

/** 挂短码的名字：「天气智能体」→「天气智能体 k7x2」（长名字先让出后缀的位） */
function nameWithShortCode(base: string): string {
  const tail = ` ${shortCode()}`;
  return `${truncate(base, NAME_MAX - tail.length)}${tail}`;
}

/**
 * 4 位 base36 短码。
 *
 * 不用加密级随机：这里只为「两个候选别撞上」，不是安全用途。`padEnd` 兜住
 * `Math.random()` 转 36 进制后不足 4 位的情况（如 0.25 → "9"）。
 */
function shortCode(): string {
  return Math.random().toString(36).slice(2, 2 + SHORT_CODE_LEN).padEnd(SHORT_CODE_LEN, '0');
}

/**
 * 截断处补省略号，让「被截过」看得出来。
 *
 * 按**码点**退到边界（`slice` 会把代理对劈成半个 emoji，落库后就是乱码），
 * 但长度仍按 UTF-16 码元算 —— 后端上限用的也是 `String.length`，两边得同一把尺子。
 */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  let head = '';
  for (const char of text) {
    if (head.length + char.length > max - 1) break;
    head += char;
  }
  return `${head}…`;
}

/**
 * 只挂附件、没有正文时，用文件名兜一个名字。
 *
 * 用户在首页直接扔一个文件就发，是在说「就用这个」，不是「给这个起个名」——
 * 所以名字取文件名（去扩展名），不拦着他先去补一句话。
 * `.env` 这类整个名字就是扩展名的，去掉会变空：退回完整文件名。
 */
function nameFromFile(path: string | undefined): string {
  if (path === undefined || path === '') return msg('home.newAgentName');
  const parts = path.split(/[/\\]/);
  const file = parts[parts.length - 1] ?? '';
  const stem = file.replace(/\.[^.]+$/, '');
  return truncate(stem === '' ? file : stem, NAME_MAX) || msg('home.newAgentName');
}
