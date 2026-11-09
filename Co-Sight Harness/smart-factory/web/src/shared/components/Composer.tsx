/**
 * Composer：把一轮内容攒起来、提交出去的输入面板。
 *
 * 形状对齐邮件 / IM 的 composer —— 正文 + 附件 + 工具栏（左 `+`，右 状态 / 模型选择 / 主按钮）。
 * 「发送」只是它最常见的提交形态：有可中止动作时主按钮也可以变成「停止」。
 *
 * 首页与智能体创建页共用一份，差异全走 props：
 * 首页 = 大输入卡片（hero）+ 行内附件 chip；
 * 创建页 = 侧栏紧凑版（compact）+ 运行中的停止态 + 附件另起一行。
 * 两页右下角都是同一个**模型选择器**（model），语义固定，不再做成通用 selector。
 *
 * 正文用 contenteditable 而不是 textarea —— 要给「@ 添加上下文」「/ 调用技能」这类
 * **行内 token** 留位置：它们是正文的一部分，跟文字混排、能删、能移动光标，textarea 做不了。
 * 代价是正文子节点不能交给 React 管：受控重渲染会把光标顶跑。所以这里的分工是：
 *
 *   - 打字时 DOM 是真相，onChange 只负责往上报。
 *   - 父组件把同一个值回传（受控回写）→ 与 DOM 相同 → 不回写 → 光标不动。
 *   - 预置需求、发送后清空这类外部改动 → 与 DOM 不同 → 写进 DOM 并把光标摆到末尾。
 *   - lastEmitted 记着我们自己报出去的值，免得父组件慢一拍就被当成外部改动。
 *
 * 行内 token（chip / 未来的命令 / @上下文）两种放法（chipPlacement）：
 *
 *   - `inline`（默认，首页与创建页对话）：token 是正文流里的一块，插在光标处，
 *     跟着文字一起换行 —— 用户说的「把这个文件和这句话一起发」本来就该是一句话。
 *     代价是它不能交给 React 渲染（正文子节点一旦受控光标就乱），
 *     所以 token 的建 / 拆全在 DOM 上做，state 只跟着 DOM 对齐。
 *   - `block`：token 单独排一行，正文外面。只有显式传 chipPlacement="block" 才用
 *     （早期附件显示整条绝对路径时，窄侧栏需要这个；现在 chip 只显示文件名，默认不需要）。
 *
 * 左侧 `+` 自带菜单，但**路径从页面来**（`pickFile`）：端侧形态下附件就是一个本机绝对路径，
 * 由页面挂的 `FilePicker` 去本地服务列目录。Composer 只把拿到的路径攒着，
 * 页面在 onSubmit 时一次拿到最终那份；不传 `pickFile` 就不渲染 `+`。
 *
 * ⚠️ 往后加功能时的分层原则（别把它们全塞成 props）：
 *   - 本次提交的参数（模型 / 编辑模式）→ 走 model / 新 prop
 *   - 行内 token（/命令、@上下文、技能引用）→ **复用本文件的行内 token 机制**，
 *     与 chip 同源；它们不进 React 受控渲染
 *   - 候选浮层（命令补全、@ 候选）→ **独立组件**（现在是 `CommandMenu`），
 *     Composer 只负责触发时机 / 光标锚点；词表是调用方传进来的**数据**，
 *     不是塞进 props 的界面结构（见文件末尾的分层说明）
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useI18n } from '../../i18n/useI18n';
import { fileNameOf } from '../file-name';
import { CommandMenu } from './CommandMenu';
import type { CommandAnchor } from './CommandMenu';
import { FILE_BADGE_SVG, FileChip } from './FileChip';
import { Icon, iconPath } from './Icon';
import type { IconName } from './Icon';
import './Composer.css';

/** 带进对话的一个本地路径：端侧服务下没有上传，附件就是一个路径字符串 */
export interface ComposerAttachment {
  id: string;
  /** **绝对路径**，服务端文件选择器给出的原值；发送时原样带给后端 */
  name: string;
}

/** token 放哪：inline = 进正文流（默认），block = 正文外面另起一行（显式指定才用） */
export type ComposerChipPlacement = 'inline' | 'block';

/**
 * `/` 菜单里的一条命令。
 *
 * **词表由使用方填**（见 `shared/commands/preset-commands.ts`）：Composer 不认识任何
 * 具体技能，只负责「打了 `/` → 过滤 → 选中后插成行内 token」。这样预览阶段将来接
 * 「这个智能体自带的技能」时，换的只是调用方传进来的数组，输入组件一行不用动。
 */
export interface ComposerCommand {
  /** 插进正文的字面量，含前导 `/`：`/goldeval:agent-eval` */
  value: string;
  /** 菜单第二行说明；不传就只显示命令名 */
  description?: string;
}

/** 附件 id 的自增号：同一毫秒里连点两下不该重号 */
let attachmentSeq = 0;

/** 把选择器给的绝对路径包成 Composer 的附件形状（页面拿 `pickFile` 的返回值用它收口）。 */
export function attachmentOfPath(path: string): ComposerAttachment {
  attachmentSeq += 1;
  return { id: `att-${Date.now().toString(36)}-${attachmentSeq}`, name: path };
}

/**
 * 右下角模型选择器。
 *
 * **这个位置在语义上就是「模型」**，不做成通用 selector —— 通用口子会诱使页面
 * 往里塞「运行模式」这类不属于这里的东西。
 *
 * 模型清单由页面传入（见 useModels），Composer 不自己拉数据：
 * 拉数据会让它从纯展示组件变成有数据依赖的组件，那是另一个层级的事。
 *
 * **清单的三种状态（加载中 / 拉失败 / 空）由这个组件统一表达**，页面只把事实传进来
 * （loading / error）。不留给页面各画一条提示 —— 那样两页迟早写成两个样（首页红条、
 * 创建页只置灰，就是这么分叉的），而且提示该出现在用户要点的那个控件上，不是页面另一头。
 */
export interface ComposerModel {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  /** 触发器上的图标，不传则只显示当前模型名 */
  icon?: IconName;
  /** 触发器 title / aria-label，默认「模型」 */
  label?: string;
  /** 清单还在路上：显示「加载中…」并置灰 */
  loading?: boolean;
  /** 清单拉失败时的人话（页面从 useModels 拿）：显示「模型清单加载失败」，详细原因进 title */
  error?: string | null;
}

/** 提交给页面的这一轮内容：正文 + 挂着待发的附件 */
export interface ComposerSubmit {
  text: string;
  /** 提交完 Composer 就把自己的附件清空，页面拿到的是这一轮的快照 */
  attachments: ComposerAttachment[];
}

/**
 * 一次性「把这些内容放回发送框」的请求。
 *
 * 典型场景：首页交接过来的首轮补发失败 —— 那句话与附件来自路由 state，
 * Composer 从来没拿到过它们，页面只能再递进来一次。`key` 变化才生效，
 * 同一个请求不会被重复应用。
 */
export interface ComposerReplay {
  key: number;
  text: string;
  /** 绝对路径；已经挂在框里的同一路径不会重复挂 */
  paths: string[];
}

/**
 * 一次性「用这段内容替换发送框」的请求（`key` 变化才生效）。
 *
 * 与 `replay` 的区别是语义：replay 是**补发失败**把原话还回来（只在框空着时写正文）；
 * fill 是用户主动换内容（首页点预置需求），等于设置 `value` —— 直接覆盖，
 * 但多一个「开头的命令 token」。
 *
 * 为什么不能只靠改 `value`：正文 token 是 DOM 原子件（见文件头），外部改 value
 * 走的是 `textContent = value`，命令只能变成一段普通文字。首页预置需求要的正是
 * 「`/harness-create` 是一颗能整块删的 token，需求正文接在后面」。
 */
export interface ComposerFill {
  key: number;
  /** 命令后面的正文 */
  text: string;
  /** 放在正文开头的命令；不传 = 纯文字 */
  command?: ComposerCommand;
}

/**
 * 一轮最多挂多少个附件：与服务端 `ATTACHMENTS_MAX` 同值（session.service.ts）。
 * 到顶就把 `+` 收掉 —— 与其让用户挂满 21 个再被 400 拒绝，不如入口就不给。
 */
const MAX_ATTACHMENTS = 20;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  /**
   * 提交这一轮。
   *
   * 返回 Promise 时，Composer 等它落定再决定要不要把内容还回来：
   * `false`（或抛错）= 这一轮实际没出去（通道没连上、服务端校验不过），
   * 正文与附件会被重新写回发送框，用户不用重选文件；`true` / 不返回 = 已接受。
   */
  onSubmit: (payload: ComposerSubmit) => void | Promise<boolean>;
  placeholder?: string;
  /** hero = 首页的大输入卡片，compact = 创建页侧栏（默认） */
  variant?: 'hero' | 'compact';

  /**
   * 主按钮形态 + 整体锁：
   * - false（默认）：主按钮是发送键
   * - true：有**可中止**的动作在跑 → 主按钮变停止键（走 onStop），其余控件置灰
   */
  running?: boolean;
  onStop?: () => void;

  /**
   * 只锁交互、不改主按钮形态：没有可中止的动作时用。
   *
   * 典型场景：首页点了发送，创建请求已经在路上 —— 后端该建还是会建，
   * 摆一个按不动的停止键比按钮短暂可点更糟，所以主按钮保持箭头但点不动，
   * `+` / 模型选择 / 附件移除 / 编辑区 一并冻结。
   *
   * 与 running 正交：running=true 时整体已锁，disabled 无额外意义。
   */
  disabled?: boolean;

  /**
   * 锁住时是否仍允许编辑正文。
   * - false（默认）：locked 时编辑区也冻结（contentEditable=false）
   * - true：locked 时只锁工具栏（+ / 模型选择 / 附件移除 / 主按钮），正文仍可输入。
   *   生成中想让用户先改下一句时用这个。
   */
  editableWhileLocked?: boolean;

  /** 当前为什么发不出去，如「正在生成…」「等待你批准…」 */
  status?: string;

  /**
   * 外部条件挡住发送时的原因，**只锁发送键与 Enter，不锁编辑区**。
   *
   * 典型场景：没有可用模型 —— 会话根本跑不起来，但用户仍该能把需求打完。
   * 非空时主按钮禁用；没有 `status` 时，这个原因显示在状态位。
   */
  sendBlockedReason?: string | null;

  /**
   * 右下角模型选择器；不传则不渲染（比如某些不希望切模型的场景）。
   * 语义固定为「模型」，不再做通用 selector。
   */
  model?: ComposerModel;

  /** token 放哪，默认 `inline`（见文件头注释） */
  chipPlacement?: ComposerChipPlacement;

  /**
   * 打开本机文件选择器，返回选中的文件；`null` = 用户取消。
   *
   * **Composer 不自己拉文件数据**：它只负责「点 `+` 之后问页面要一个路径」。
   * 选择器长什么样、数据从哪来（`shared/api/fs.ts`）都是页面的事 —— 与模型清单同理，
   * 拉数据会让纯展示组件变成有数据依赖的组件。
   * 不传就没有 `+` 入口（只有附件没有落点的页面不该摆一个假的按钮）。
   */
  pickFile?: () => Promise<ComposerAttachment | null>;
  /**
   * `/` 菜单的词表。**不传或空数组 = 这个发送框不支持 `/`**，按普通字符输入。
   *
   * 只填数据，不填行为：触发时机、光标锚点、键盘上下 / 回车、插入后的 token 都由
   * Composer 管（见 `ComposerCommand`）。所以「首页 / 生成 / 评估用预设、预览用智能体
   * 自带技能」这种差异只体现在调用方传进来的数组上。
   */
  commands?: ComposerCommand[];
  /**
   * 把内容放回发送框的一次性请求（首轮补发失败时由页面发来）。
   * 与用户自己挂附件不同：正文只在框还空着时写回，附件按路径去重、受上限约束。
   */
  replay?: ComposerReplay | null;
  /**
   * 一次性「用这段内容替换发送框」的请求（首页预置需求用）。
   * 与外部改 value 同义，只是额外允许在开头摆一颗命令 token（见 `ComposerFill`）。
   */
  fill?: ComposerFill | null;
  /**
   * 工具栏左侧、`+` 之后的附加控件（当前用于「知识检索」）。
   *
   * 它属于「本次提交的参数」，与 `model` 同层：控件不参与提交，选中值由页面持有，
   * 发送时由页面拼进命令（`--knowledge-workflow-id`），因此**不进正文的行内 token**。
   * 首页与创建页共用同一个槽位，两处的外观与位置才一致。
   */
  accessory?: ReactNode;
  /**
   * 「发送框里有没有东西」（正文或附件）变化时上报一次。
   * 附件由 Composer 自己攒，页面从 value 上看不到它 —— 首页的吉祥物靠这个睁眼。
   */
  onContentChange?: (hasContent: boolean) => void;
}

/** 行内 token 在 DOM 上的标记，认它 = 认出正文里哪个节点是 token */
const TOKEN_ATTR = 'data-token-id';
/** token 的种类：`file` 走附件，`command` 是正文的一部分（见 readEditorText） */
const TOKEN_KIND_ATTR = 'data-token-kind';
/** 命令 token 的字面量：它要进 prompt，不能只靠节点里的可见文字（改样式时容易丢） */
const TOKEN_TEXT_ATTR = 'data-token-text';
type TokenKind = 'file' | 'command';

/** 读正文纯文本：Shift+Enter 在 Chrome 里会拆成 <div>，块之间要还原回换行 */
function readEditorText(root: HTMLElement): string {
  let text = '';

  const walk = (node: Node) => {
    node.childNodes.forEach((child) => {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent ?? '';
        return;
      }
      if (!(child instanceof HTMLElement)) return;
      if (child.hasAttribute(TOKEN_ATTR)) {
        /*
         * 附件 token 不算正文：它挂在 attachments 里单独交出去，别把文件名读成用户打的字。
         * 命令 token 相反 —— `/agent-eval` 本身就是 prompt 的一部分，必须读进去；
         * 字面量认 data-token-text，不认可见文字（两者以后可能分叉，比如加图标 / 缩写）。
         */
        if (child.getAttribute(TOKEN_KIND_ATTR) === 'command') {
          text += child.getAttribute(TOKEN_TEXT_ATTR) ?? '';
        }
        return;
      }
      if (child.tagName === 'BR') {
        text += '\n';
        return;
      }
      walk(child);
      if (child.tagName === 'DIV' || child.tagName === 'P') text += '\n';
    });
  };

  walk(root);
  return text.replace(/\n$/, '');
}

/**
 * 手搓一个行内 token 节点。
 *
 * 为什么不写成 JSX：token 得待在正文流里才能跟着文字换行，而正文子节点一旦交给 React
 * 受控渲染，打字时光标就会被顶跑（见文件头注释）。所以正文里的一切都由 DOM 说话，
 * token 也只在这里建、在 removeTokenNode 里拆，React 那边只留一份「有哪些附件」的状态。
 *
 * 现在只有 `file` 一种 kind。将来加 `/命令`、`@上下文` 时：
 *   - 这里按 kind 分支出不同的徽标 / 标签
 *   - 但**节点结构、插入方式、移除方式保持一致** —— 它们是同一种机制的不同实例
 */
function buildToken(
  file: ComposerAttachment,
  onRemove: (id: string) => void,
  removeLabel: string,
): HTMLElement {
  const token = document.createElement('span');
  // 与设计页 / 对话气泡共用同一套 chip 样式（见 FileChip）：行内只是多一档尺寸
  token.className = 'file-chip file-chip--inline';
  // 光标能停在它两边，但进不去、改不了：token 是原子件
  token.contentEditable = 'false';
  token.setAttribute(TOKEN_ATTR, file.id);
  token.setAttribute(TOKEN_KIND_ATTR, 'file' satisfies TokenKind);
  token.title = file.name;
  token.innerHTML = FILE_BADGE_SVG;

  const name = document.createElement('span');
  name.className = 'file-chip__name';
  // textContent 而不是 innerHTML：路径是从本地服务来的，别当 HTML 解析
  name.textContent = fileNameOf(file.name);
  token.append(name);

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'file-chip__x';
  remove.setAttribute('aria-label', removeLabel);
  remove.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="${iconPath('close')}" /></svg>`;
  // 不拦 mousedown 的话，光标的焦点会先被按钮抢走，用户点完 token 就丢了输入位置
  remove.addEventListener('mousedown', (event) => event.preventDefault());
  remove.addEventListener('click', () => onRemove(file.id));
  token.append(remove);

  return token;
}

/** 拆掉一个 token，连同它在正文里占的那个尾随空格 —— 别留个空档 */
function removeTokenNode(token: Element) {
  const next = token.nextSibling;
  if (next?.nodeType === Node.TEXT_NODE && (next.textContent ?? '').startsWith(' ')) {
    next.textContent = (next.textContent ?? '').slice(1);
    if (next.textContent === '') next.remove();
  }
  token.remove();
}

/** 命令 token 的自增号，与附件同一套用途（DOM 上认节点 / 删节点） */
let commandSeq = 0;

/**
 * 手搓一个命令 token：`/agent-eval` 这类东西进正文后就不该被当成普通文字改。
 *
 * 与文件 token 同一种机制（contentEditable=false 的原子件），差别只在两处：
 *   - 字面量要进 prompt → 带 `data-token-text`，由 readEditorText 读回去；
 *   - 长相是代码命令而不是文件，样式见 Composer.css 的 `.command-chip`。
 */
function buildCommandToken(
  command: ComposerCommand,
  removeLabel: string,
  onRemoved: () => void,
): HTMLElement {
  commandSeq += 1;
  const token = document.createElement('span');
  token.className = 'command-chip';
  token.contentEditable = 'false';
  token.setAttribute(TOKEN_ATTR, `cmd-${Date.now().toString(36)}-${commandSeq}`);
  token.setAttribute(TOKEN_KIND_ATTR, 'command' satisfies TokenKind);
  token.setAttribute(TOKEN_TEXT_ATTR, command.value);
  token.title = command.description ?? command.value;

  const label = document.createElement('span');
  label.className = 'command-chip__name';
  // textContent 而不是 innerHTML：词表来自使用方，别当 HTML 解析
  label.textContent = command.value;
  token.append(label);

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'command-chip__x';
  remove.setAttribute('aria-label', removeLabel);
  remove.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="${iconPath('close')}" /></svg>`;
  // 不拦 mousedown 的话，光标的焦点会先被按钮抢走，用户点完 token 就丢了输入位置
  remove.addEventListener('mousedown', (event) => event.preventDefault());
  remove.addEventListener('click', () => {
    removeTokenNode(token);
    onRemoved();
  });
  token.append(remove);

  return token;
}

/** 命令名（去掉前导 `/`）与说明一起参与过滤；翻译过的说明也能被中文搜到 */
function commandRank(command: ComposerCommand, needle: string): number {
  const value = command.value.toLowerCase();
  const name = value.startsWith('/') ? value.slice(1) : value;
  if (name.startsWith(needle) || value.startsWith(needle)) return 0;
  if (value.includes(needle)) return 1;
  if ((command.description ?? '').toLowerCase().includes(needle)) return 2;
  return -1;
}

/**
 * 按输入过滤 + 排序：前缀命中排前面，其次是名字里含、最后是说明里含。
 * 空查询 = 全量（刚打 `/` 时先把所有命令摆出来）。
 */
function filterCommands(commands: ComposerCommand[], query: string): ComposerCommand[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return commands;

  return commands
    .map((command, index) => ({ command, index, rank: commandRank(command, needle) }))
    .filter((entry) => entry.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.command);
}

/** 锚点没动就不重渲染：selectionchange 触发得很密（每次光标移动都会来） */
function sameAnchor(a: CommandAnchor, b: CommandAnchor): boolean {
  return (
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.bottom - b.bottom) < 0.5
  );
}

export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder,
  variant = 'compact',
  running = false,
  onStop,
  disabled = false,
  editableWhileLocked = false,
  status,
  sendBlockedReason,
  model,
  chipPlacement = 'inline',
  pickFile,
  commands,
  replay,
  fill,
  accessory,
  onContentChange,
}: ComposerProps) {
  const { t } = useI18n();
  const editorRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  /** 我们自己通过 onChange 报出去的最后一份文本，用来区分「回写」与「外部改动」 */
  const lastEmitted = useRef<string | null>(null);
  /**
   * 上一帧的 `value`。用来认「DOM 被 replay / fill 改过，而 props 还停在上一帧」：
   * StrictMode 会把 effect 链跑两遍，第二遍的值同步看到的是**更新前的** value，
   * 不判这一条就会把刚放回发送框的正文擦掉（设计页 replay 在 dev 下必现）。
   */
  const previousValue = useRef<string | null>(null);
  const firstRender = useRef(true);
  const [menu, setMenu] = useState<'add' | 'model' | null>(null);
  /** 待发附件：Composer 自己攒，提交时一次性交给页面 */
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  /** 已经应用过的 replay key：同一个请求只生效一次（StrictMode 的二次 effect 也不会重复挂） */
  const appliedReplay = useRef<number | null>(null);
  /** 已经应用过的 fill key，同上 */
  const appliedFill = useRef<number | null>(null);
  /**
   * `/` 候选浮层的当前状态。null = 收着。
   * `query` 是斜杠后面已经打出的那截；`anchor` 是光标在视口里的矩形。
   */
  const [suggestion, setSuggestion] = useState<{
    query: string;
    active: number;
    anchor: CommandAnchor;
  } | null>(null);
  /** 选中命令时要替换掉的那段 `/query` 的落点（光标 Range 快照） */
  const suggestionRange = useRef<Range | null>(null);
  const suggestionQuery = useRef('');

  const chipsInline = chipPlacement === 'inline';
  /** 到顶就不再给入口：服务端同样在 20 项处拒绝（见 MAX_ATTACHMENTS） */
  const atAttachmentLimit = attachments.length >= MAX_ATTACHMENTS;

  /** 整体锁：running 与 disabled 任一为真 */
  const locked = running || disabled;
  /** 编辑区是否可输入：锁住时按 editableWhileLocked 决定 */
  const editorEditable = !locked || editableWhileLocked;

  const hasAttachments = attachments.length > 0;
  const hasText = value.trim() !== '';
  /** 发送框里有没有可发的东西（正文或附件）。**与「能不能发」分开**：模型不可用时照样算有内容 */
  const hasPayload = hasText || hasAttachments;
  /** 外部条件挡住发送（如没有可用模型）：只影响发送键与 Enter，不影响编辑 */
  const blockingReason = sendBlockedReason ?? null;
  const canSend = hasPayload && blockingReason === null;
  /** 「里面有没有东西」——跟能否发送不同，运行中 / 模型不可用时照样算有内容 */
  const hasContent = hasPayload;
  /** 状态位文案：正在跑之类的临时状态优先，否则说清「为什么发不出去」 */
  const shownStatus = status ?? blockingReason;

  const currentModel = model?.options.find((option) => option.value === model.value);
  const modelError = model?.error ?? null;
  const modelLoading = model?.loading ?? false;
  /** 有 model 但一个选项都没有（且不在加载中、也不是失败）：按钮该说「无可用模型」 */
  const modelUnavailable =
    model !== undefined && !modelLoading && modelError === null && model.options.length === 0;
  /** 三种不正常的清单态都点不开菜单（点开一个空菜单体验很差） */
  const modelBlocked = modelLoading || modelError !== null || modelUnavailable;

  /**
   * 浮层当前要显示的条目。
   *
   * 由「state 里的查询 + props 里的词表」推出来，不另存一份 —— 词表换了（比如预览阶段
   * 换成智能体自带技能）下一次渲染就是新的，不用同步两处状态。
   */
  const suggestionItems = useMemo(
    () =>
      commands === undefined || suggestion === null
        ? []
        : filterCommands(commands, suggestion.query),
    [commands, suggestion],
  );

  /** 回调放 ref 里：这样下面那个 effect 只依赖 hasContent（原因见注释） */
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  });
  /** 上一次报出去的值。null = 还没报过（首帧仍要报一次） */
  const reportedContent = useRef<boolean | null>(null);
  /**
   * 「里面有没有东西」**真的变化时**上报一次。
   *
   * 不能写成 `useEffect(() => onContentChange?.(hasContent), [hasContent, onContentChange])`：
   * 页面几乎都传内联函数，每次渲染都是新引用，effect 就会每次渲染都跑一遍、把同一个值
   * 反复报上去。而页面拿这个回调做的事是「内容变了 → 上一轮的错误作废」——
   * 被这么重复上报，刚设上的错误会立刻被自己抹掉：首页创建失败不弹红条就是这么来的。
   */
  useEffect(() => {
    if (reportedContent.current === hasContent) return;
    reportedContent.current = hasContent;
    onContentChangeRef.current?.(hasContent);
  }, [hasContent]);

  /**
   * `+` 挂一个本地文件：路径由页面提供的选择器给出（本机服务列目录，见 `FilePicker`）。
   *
   * 这个函数只做「拿来一个路径 → 挂成 token」，token 的渲染、移除、参与发送条件
   * 全不用跟着改 —— 换的只是路径从哪来这件事。
   */
  async function addFile() {
    if (!pickFile) return;
    if (attachments.length >= MAX_ATTACHMENTS) return;
    const file = await pickFile();
    if (file === null) return;
    // 同一路径只挂一份：服务端发送时会去重，这里先把重复挡在界面上
    if (attachments.some((item) => item.name === file.name)) return;

    if (chipsInline) {
      insertToken(file);
      return;
    }
    setAttachments((current) => [...current, file]);
  }

  /** 光标前面那个字符，用来决定 token 前面要不要补个空格（取不到就当行首） */
  function charBeforeCaret(range: Range, editor: HTMLElement): string {
    const probe = range.cloneRange();
    probe.selectNodeContents(editor);
    probe.setEnd(range.startContainer, range.startOffset);
    return probe.toString().slice(-1);
  }

  /** 把光标摆到某个节点之后 */
  function caretAfter(node: Node, selection: Selection | null) {
    if (!selection) return;
    const range = document.createRange();
    range.setStartAfter(node);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /**
   * 把 token 插到光标处，并让光标停在它后面。
   *
   * 前后各留一个空格：token 是 inline-flex，紧贴文字会跟正文粘成一坨；
   * 空格也是光标唯一的落脚点 —— 没有它，Chrome 容易把光标画到 token 内部去。
   */
  function insertToken(file: ComposerAttachment) {
    const editor = editorRef.current;
    if (!editor) return;

    const token = buildToken(
      file,
      removeToken,
      t('common.remove', { name: file.name }),
    );
    const selection = window.getSelection();
    const range =
      selection && selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    // 光标不在正文里（比如刚点完菜单、焦点还在按钮上）就挂到末尾，别丢
    const inEditor = range ? editor.contains(range.commonAncestorContainer) : false;

    if (range && inEditor) {
      range.deleteContents();
      const lead = charBeforeCaret(range, editor).trim() === '' ? null : document.createTextNode(' ');
      const tail = document.createTextNode(' ');
      const fragment = document.createDocumentFragment();
      if (lead) fragment.append(lead);
      fragment.append(token, tail);
      range.insertNode(fragment);
      caretAfter(tail, selection);
    } else {
      const tail = document.createTextNode(' ');
      editor.append(token, tail);
      // 挂到末尾同样把光标摆到 token 后面：下一句接在文件后面写最顺手
      caretAfter(tail, selection);
    }

    setAttachments((current) => [...current, file]);
    editor.focus();
  }

  /** token 上的 × ：拆掉节点，状态跟着走 */
  function removeToken(id: string) {
    const token = editorRef.current?.querySelector(`[${TOKEN_ATTR}="${id}"]`);
    if (token) removeTokenNode(token);
    setAttachments((current) => current.filter((item) => item.id !== id));
    editorRef.current?.focus();
  }

  /**
   * 按 DOM 对齐附件列表。
   *
   * token 是原子件，一个 Backspace 就能整块删掉 —— 那时 attachments 里还留着它，
   * 就会出现「正文里看不见、却算有内容发得出去」。所以每次打字后都拿 DOM 校准一次。
   */
  function syncTokens() {
    const editor = editorRef.current;
    if (!editor) return;
    // 只认附件 token：命令 token 也在正文里，但它不是附件（见 readEditorText）
    const ids = new Set(
      Array.from(editor.querySelectorAll(`[${TOKEN_ATTR}][${TOKEN_KIND_ATTR}="file"]`)).map(
        (token) => token.getAttribute(TOKEN_ATTR) ?? '',
      ),
    );
    setAttachments((current) =>
      current.length === ids.size && current.every((item) => ids.has(item.id))
        ? current
        : current.filter((item) => ids.has(item.id)),
    );
  }

  /* ── `/` 命令补全 ────────────────────────────────────────────────────────
   *
   * 触发条件写死成「行首或空白之后的一个 `/`，且斜杠与已打出的查询都在**同一个文本节点**里」。
   * 最后这条不是为了省事：命令选中后会变成一个 token 节点，它的可见文字也是 `/xxx`；
   * 如果只对整段文本做正则，光标退到 token 后面那个空格之前时会把 token 自己当成「刚打的斜杠」，
   * 菜单又弹出来一次。文本节点这个约束一次性排掉了这种情况（token 是元素节点）。
   */

  /** 收掉浮层。锚点 / 查询一起清，避免下一次误用上一轮的 Range */
  const closeSuggestion = useCallback(() => {
    setSuggestion(null);
    suggestionRange.current = null;
    suggestionQuery.current = '';
  }, []);

  /**
   * 光标处是不是一个 `/` 命令上下文；是就给出查询与光标快照。
   *
   * 只在 `editorEditable` 时可触发：锁住时正文不爱接受输入，弹个菜单也没意义。
   */
  const commandContext = useCallback((): { query: string; range: Range } | null => {
    const editor = editorRef.current;
    if (editor === null || !editorEditable) return null;

    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.startContainer)) return null;
    // 见上方注释：斜杠必须真的在这个文本节点里
    if (range.startContainer.nodeType !== Node.TEXT_NODE) return null;

    const typed = (range.startContainer.textContent ?? '').slice(0, range.startOffset);
    const match = /(?:^|[\s\u00a0])\/([^\s/]*)$/u.exec(typed);
    if (match === null) return null;

    const query = match[1];
    if (range.startOffset < query.length + 1) return null;
    return { query, range: range.cloneRange() };
  }, [editorEditable]);

  /** 光标矩形；空行 / 取不到时退到编辑区顶部，别让浮层飘到视口原点 */
  function caretAnchor(range: Range): CommandAnchor {
    const rect = range.getBoundingClientRect();
    if (rect.width !== 0 || rect.height !== 0) {
      return { left: rect.left, top: rect.top, bottom: rect.bottom };
    }
    const editor = editorRef.current;
    if (editor === null) return { left: 0, top: 0, bottom: 0 };
    const fallback = editor.getBoundingClientRect();
    return { left: fallback.left, top: fallback.top, bottom: fallback.top + 18 };
  }

  /**
   * 拿 DOM 的真实光标位置刷新浮层。
   *
   * 打字、点选、方向键移动光标都会走到这里；没变化时返回旧 state，避免每敲一个字重渲染。
   * 查询变了就把高亮重置到第一条，只是光标位置变了则保留用户已经选中的那条。
   */
  const syncSuggestion = useCallback(() => {
    if (commands === undefined || commands.length === 0) {
      closeSuggestion();
      return;
    }

    const context = commandContext();
    if (context === null) {
      closeSuggestion();
      return;
    }
    if (filterCommands(commands, context.query).length === 0) {
      closeSuggestion();
      return;
    }

    suggestionRange.current = context.range;
    suggestionQuery.current = context.query;
    const anchor = caretAnchor(context.range);

    setSuggestion((current) => {
      if (current === null) return { query: context.query, active: 0, anchor };
      if (current.query !== context.query) return { query: context.query, active: 0, anchor };
      if (sameAnchor(current.anchor, anchor)) return current;
      return { ...current, anchor };
    });
  }, [commands, commandContext, closeSuggestion]);

  /** 把选中的命令插成行内 token，替掉用户打的那截 `/query` */
  function acceptCommand(command: ComposerCommand) {
    const editor = editorRef.current;
    const saved = suggestionRange.current;
    const query = suggestionQuery.current;
    closeSuggestion();
    if (editor === null || saved === null) return;

    const range = saved.cloneRange();
    // commandContext 已保证 `/` 与查询都在这个文本节点里，往回退这么多一定不越界
    if (range.startContainer.nodeType !== Node.TEXT_NODE) return;
    if (range.startOffset < query.length + 1) return;
    range.setStart(range.startContainer, range.startOffset - (query.length + 1));
    range.deleteContents();

    const token = buildCommandToken(
      command,
      t('common.remove', { name: command.value }),
      () => {
        // 命令是正文的一部分：拆掉它，父组件的 value 也得跟着变
        editor.focus();
        emit();
      },
    );
    const tail = document.createTextNode(' ');
    const fragment = document.createDocumentFragment();
    fragment.append(token, tail);
    range.insertNode(fragment);

    caretAfter(tail, window.getSelection());
    editor.focus();
    emit();
  }

  /**
   * 浮层开着时盯住光标：移出命令上下文就收，滚动 / 缩放要跟着重算位置。
   * 不盯着会在「用户用方向键把光标挪走、菜单还挂在那儿」时插入到错误的位置。
   */
  useEffect(() => {
    if (suggestion === null) return;
    const refresh = () => syncSuggestion();
    document.addEventListener('selectionchange', refresh);
    window.addEventListener('resize', refresh);
    window.addEventListener('scroll', refresh, true);
    return () => {
      document.removeEventListener('selectionchange', refresh);
      window.removeEventListener('resize', refresh);
      window.removeEventListener('scroll', refresh, true);
    };
  }, [suggestion, syncSuggestion]);

  /** 编辑区被锁 / 词表被撤掉时，浮层不该留在屏幕上 */
  useEffect(() => {
    if (!editorEditable) closeSuggestion();
  }, [editorEditable, closeSuggestion]);

  // 外部改 value（预置需求 / 发送后清空）才回写 DOM；打字时两边本来就相等，走到这就 return 了
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const isFirstRender = firstRender.current;
    firstRender.current = false;
    const unchanged = previousValue.current === value;
    previousValue.current = value;

    if (value === lastEmitted.current) return;
    /*
     * props 没有变化，而 DOM 正好是我们上一次 emit 的内容 —— 说明这次 DOM 是
     * replay / fill 的 effect 写进去的，别拿还没跟上的 value 覆盖它。
     */
    if (unchanged && lastEmitted.current !== null && readEditorText(editor) === lastEmitted.current) {
      return;
    }
    if (readEditorText(editor) === value) return;

    editor.textContent = value;
    // 行内 token 是正文的一部分，正文被整段换掉它们也就没了 —— 附件状态得跟上，
    // 不然会剩下「附件还在、token 却不见了」的账
    if (chipsInline) setAttachments([]);
    // 正文被整段换掉，上一轮的 `/query` 快照也失效了（Range 指向的节点已经不在树上）
    closeSuggestion();

    // 首帧挂载不抢焦点；锁住时不抢（抢了也没法编辑）
    if (isFirstRender || locked) return;
    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [value, chipsInline, locked]);

  /**
   * 页面递进来的「放回去」请求（见 `ComposerReplay`）：首轮补发失败时，
   * 这句话和附件来自路由 state，Composer 自己从来没拿到过，只能由页面再递一次。
   *
   * 与用户自己挂附件不同的是：正文只在框还空着时写回 —— 等待失败的那几秒里
   * 用户可能已经开始打下一句了，不能拿旧内容盖掉。
   */
  useEffect(() => {
    if (replay === undefined || replay === null) return;
    if (appliedReplay.current === replay.key) return;
    appliedReplay.current = replay.key;

    const editor = editorRef.current;
    if (editor === null) return;

    // 附件：同一路径只留一份，且不超过上限
    const room = Math.max(0, MAX_ATTACHMENTS - attachments.length);
    const fresh = replay.paths
      .filter((path) => !attachments.some((item) => item.name === path))
      .slice(0, room)
      .map(attachmentOfPath);

    /** 这一刻的 DOM 有没有被改过；改过就沿同一条上报路径同步父组件的 value */
    let changed = false;

    const empty = readEditorText(editor).trim() === '';
    if (replay.text !== '' && empty) {
      if (editor.firstChild === null) {
        editor.textContent = replay.text;
      } else {
        // 框里可能已经只有 token（用户先挂了文件）：插在正文前面，别把 chip 冲掉
        editor.insertBefore(document.createTextNode(`${replay.text} `), editor.firstChild);
      }
      changed = true;
    }

    if (fresh.length > 0) {
      if (chipsInline) {
        for (const file of fresh) {
          editor.append(
            buildToken(file, removeToken, t('common.remove', { name: file.name })),
            document.createTextNode(' '),
          );
        }
        // token 后面的空格也是正文的一部分：不 emit 的话父组件的 value 还停在
        // 空串，下一次外部同步（开发态 StrictMode 的二次 effect）会把它当脏节点擦掉。
        changed = true;
      }
      setAttachments((current) => [...current, ...fresh]);
    }

    if (changed) emit();
  }, [replay, attachments, chipsInline, t]);

  /**
   * 页面递进来的「换掉发送框内容」（见 `ComposerFill`）：首页点预置需求走这里。
   *
   * 覆盖式写入，语义与外部改 value 相同；差别只有「开头可以是一颗命令 token」。
   * 命令用 buildCommandToken 手搓而不是拼字符串 —— token 必须能整块删、能被
   * readEditorText 读回 prompt（见那里的注释）。
   */
  useEffect(() => {
    if (fill === undefined || fill === null) return;
    if (appliedFill.current === fill.key) return;
    appliedFill.current = fill.key;

    const editor = editorRef.current;
    if (editor === null) return;

    closeSuggestion();
    editor.textContent = '';
    if (fill.command !== undefined) {
      editor.append(
        buildCommandToken(
          fill.command,
          t('common.remove', { name: fill.command.value }),
          () => {
            // 命令是正文的一部分：拆掉它，父组件的 value 也得跟着变
            editor.focus();
            emit();
          },
        ),
        document.createTextNode(' '),
      );
    }
    if (fill.text !== '') editor.append(document.createTextNode(fill.text));

    // 与外部改 value 同一条口径：整段换内容，上一轮挂的附件就不该留着
    if (chipsInline) setAttachments([]);

    // 走同一条上报路径：父组件的 value 与 DOM（含 token 的字面量）保持一致
    emit();

    // 首帧 / 锁住时不抢焦点（与外部改 value 的处理一致）
    if (locked) return;
    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [fill, chipsInline, locked, t, closeSuggestion]);

  // 菜单：点外面或 Esc 关掉
  useEffect(() => {
    if (!menu) return;
    const onDocumentDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setMenu(null);
    };
    const onDocumentKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenu(null);
    };
    document.addEventListener('mousedown', onDocumentDown);
    document.addEventListener('keydown', onDocumentKey);
    return () => {
      document.removeEventListener('mousedown', onDocumentDown);
      document.removeEventListener('keydown', onDocumentKey);
    };
  }, [menu]);

  /** 把编辑区当前文本上报出去 */
  function emit() {
    const editor = editorRef.current;
    if (!editor) return;
    const text = readEditorText(editor);
    lastEmitted.current = text;
    onChange(text);
  }

  /**
   * 发送失败时把这一轮还回发送框。
   *
   * 提交时必须先把内容从框里收走（用户不该看到刚发的东西还挂着），但发送是异步的 ——
   * 通道没连上、服务端校验不过时这一轮其实没出去，文件不还回来用户就得重选一遍。
   *
   * 正文走 `onChange` 回写，与外部改 value 是同一条路径（DOM 是真相）；
   * 行内 token 会被整段重写冲掉，所以重新挂回去并排在正文末尾。
   */
  function restorePayload(payload: ComposerSubmit) {
    const editor = editorRef.current;
    // 已经卸载（发成功后跳走了）就没有框可还
    if (!editor) return;

    closeSuggestion();
    editor.textContent = payload.text;
    if (chipsInline) {
      for (const file of payload.attachments) {
        editor.append(
          buildToken(file, removeToken, t('common.remove', { name: file.name })),
          document.createTextNode(' '),
        );
      }
    }
    setAttachments(payload.attachments);
    lastEmitted.current = payload.text;
    onChange(payload.text);

    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }

  function submit() {
    // locked 也要挡：Enter 提交不经过按钮的 disabled（见 handleKeyDown）
    if (!canSend || locked) return;
    setMenu(null);
    closeSuggestion();
    // 正文与附件都在这一轮交出去，页面拿快照；附件随即清空，别留给下一轮
    const text = editorRef.current ? readEditorText(editorRef.current) : value;
    const payload: ComposerSubmit = { text, attachments };
    const result = onSubmit(payload);
    // 行内 token 得自己收：正文清空是由页面改 value 触发的，而首页那边提交还没接后端，
    // 谁清谁不清说不准，这里收掉最稳 —— 两种情况下画面都跟状态一致
    if (chipsInline) {
      editorRef.current?.querySelectorAll(`[${TOKEN_ATTR}]`).forEach(removeTokenNode);
    }
    setAttachments([]);

    // 页面能告诉我们「没发出去」就把这一轮还回来（见 onSubmit 的类型说明）
    if (result instanceof Promise) {
      void result.then(
        (accepted) => {
          if (accepted === false) restorePayload(payload);
        },
        () => restorePayload(payload),
      );
    }
  }

  function handleInput(event: FormEvent<HTMLDivElement>) {
    const text = readEditorText(event.currentTarget);
    lastEmitted.current = text;
    onChange(text);
    if (chipsInline) syncTokens();
    // 输入法拼字中途不弹菜单：那时正文里是拼音，等候选词落定再判断一次
    if (!(event.nativeEvent as InputEvent).isComposing) syncSuggestion();
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    // 输入法自己要用 Enter / 方向键选词，一律先让给它
    if (event.nativeEvent.isComposing) return;

    /*
     * 浮层开着时先把键盘交给自己处理：这里的 Enter 是「选中命令」，
     * 不是「发送」，不拦就会把半截 `/que` 发出去。
     */
    if (suggestion !== null && suggestionItems.length > 0) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        setSuggestion((current) =>
          current === null
            ? current
            : {
                ...current,
                active: (current.active + step + suggestionItems.length) % suggestionItems.length,
              },
        );
        return;
      }
      if ((event.key === 'Enter' && !event.shiftKey) || event.key === 'Tab') {
        event.preventDefault();
        const choice = suggestionItems[suggestion.active] ?? suggestionItems[0];
        if (choice !== undefined) acceptCommand(choice);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        closeSuggestion();
        return;
      }
    }

    if (event.key !== 'Enter' || event.shiftKey) return;
    // locked 时 Enter 不该发 —— 按钮 disabled 挡不住键盘这条路
    if (locked) return;
    event.preventDefault();
    submit();
  }

  function handlePaste(event: ReactClipboardEvent<HTMLDivElement>) {
    // 只收纯文本，别把外部 HTML 结构带进编辑区
    event.preventDefault();
    const text = event.clipboardData.getData('text/plain');
    if (text) document.execCommand('insertText', false, text);
    emit();
    syncSuggestion();
  }

  /** 点选把光标挪进一段已有的 `/xxx` 时也该弹出来（方向键移动由浮层开着时的 selectionchange 兜住） */
  function handleEditorClick() {
    syncSuggestion();
  }

  function handleEditorBlur() {
    // 点浮层里的条目不会走到这里：那一路的 mousedown 已 preventDefault，焦点没离开正文
    closeSuggestion();
  }

  return (
    <div
      ref={rootRef}
      className={`composer composer--${variant}${chipsInline ? ' composer--chips-inline' : ''}${locked ? ' composer--locked' : ''
        }`}
    >
      <div className="composer__content">
        {/* 行内 token 在正文里由 DOM 直接管，这一行是 block 变体的 */}
        {!chipsInline && hasAttachments && (
          <div className="composer__chips">
            {attachments.map((file) => (
              <FileChip
                key={file.id}
                path={file.name}
                remove={{
                  label: t('common.remove', { name: file.name }),
                  disabled: locked,
                  onRemove: () =>
                    setAttachments((current) => current.filter((item) => item.id !== file.id)),
                }}
              />
            ))}
          </div>
        )}

        <div className="composer__editor-box">
          {/* 行内 token 就摆在正文开头，占位符还浮在那儿就会压在它上面 —— 有 token 就算有内容 */}
          {!hasText && !(chipsInline && hasAttachments) && placeholder && (
            <span className="composer__placeholder">{placeholder}</span>
          )}
          <div
            ref={editorRef}
            className={`composer__editor${locked && !editableWhileLocked ? ' composer__editor--locked' : ''
              }`}
            contentEditable={editorEditable}
            role="textbox"
            aria-multiline="true"
            aria-label={placeholder ?? t('composer.inputPlaceholder')}
            aria-disabled={!editorEditable}
            aria-autocomplete={commands !== undefined && commands.length > 0 ? 'list' : undefined}
            aria-expanded={suggestion !== null}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            onClick={handleEditorClick}
            onBlur={handleEditorBlur}
          />
        </div>
      </div>

      <div className="composer__bar">
        <div className="composer__bar-left">
          {/* 没有 `pickFile` 就没有可挂的路径来源：不摆一个点了没反应的 + */}
          {/* title 挂在包裹层上：按钮 disabled 时它自己不收鼠标事件，浏览器不一定弹 title */}
          {pickFile && (
            <div
              className="composer__pop"
              title={
                atAttachmentLimit
                  ? t('composer.attachmentLimit', { max: MAX_ATTACHMENTS })
                  : undefined
              }
            >
              <button
                type="button"
                className={`composer__icon-btn${menu === 'add' ? ' composer__icon-btn--open' : ''}`}
                aria-label={t('composer.addFile')}
                aria-haspopup="menu"
                aria-expanded={menu === 'add'}
                disabled={locked || atAttachmentLimit}
                onClick={() => setMenu(menu === 'add' ? null : 'add')}
              >
                {/* 菜单开着时 + 变 ×：这个按钮同时是「打开」和「关上」，图标跟着说同一件事 */}
                {menu === 'add' ? <Icon name="close" size={16} /> : <Icon name="plus" size={18} />}
              </button>

              {menu === 'add' && (
                <div className="composer__menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    className="composer__menu-item"
                    onClick={() => {
                      setMenu(null);
                      void addFile();
                    }}
                  >
                    <Icon name="paperclip" size={17} />
                    {t('composer.addFile')}
                  </button>
                </div>
              )}
            </div>
          )}
          {accessory}
        </div>

        <div className="composer__bar-right">
          {shownStatus && <span className="composer__status">{shownStatus}</span>}

          {model && (
            // title 挂在包裹层上：按钮被 disabled 时它自己不收鼠标事件，浏览器不一定弹 title
            <div className="composer__pop" title={modelError ?? model.label ?? t('composer.model')}>
              <button
                type="button"
                className={`composer__selector${modelError === null ? '' : ' composer__selector--bad'}`}
                aria-label={
                  modelError === null
                    ? (model.label ?? t('composer.model'))
                    : t('composer.modelLoadFailedDetail', { error: modelError })
                }
                aria-haspopup="menu"
                aria-expanded={menu === 'model'}
                aria-busy={modelLoading}
                disabled={locked || modelBlocked}
                onClick={() => setMenu(menu === 'model' ? null : 'model')}
              >
                {modelError !== null ? (
                  <>
                    <Icon name="alert" size={14} />
                    {t('composer.modelLoadFailed')}
                  </>
                ) : (
                  <>
                    {model.icon && <Icon name={model.icon} size={15} />}
                    {currentModel?.label ??
                      (modelLoading
                        ? t('composer.modelLoading')
                        : modelUnavailable
                          ? t('composer.noModel')
                          : t('composer.chooseModel'))}
                    <Icon name="chevronDown" size={14} />
                  </>
                )}
              </button>

              {menu === 'model' && (
                <div className="composer__menu composer__menu--right" role="menu">
                  {model.options.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="menuitemradio"
                      aria-checked={option.value === model.value}
                      className="composer__menu-item"
                      onClick={() => {
                        setMenu(null);
                        model.onChange(option.value);
                      }}
                    >
                      {option.label}
                      {option.value === model.value && (
                        <span className="composer__menu-check">
                          <Icon name="check" size={14} />
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {running ? (
            <button
              type="button"
              className="composer__send composer__send--stop"
              aria-label={t('composer.stop')}
              onClick={onStop}
            >
              <Icon name="pause" size={16} />
            </button>
          ) : (
            <button
              type="button"
              className={`composer__send${canSend && !disabled ? ' composer__send--ready' : ''}`}
              aria-label={blockingReason ?? t('composer.send')}
              disabled={!canSend || disabled}
              onClick={submit}
            >
              <Icon name="arrowUp" size={16} />
            </button>
          )}
        </div>
      </div>

      {/* 候选浮层用 position: fixed 锚在视口坐标上，放在这里只是为了跟着组件卸载一起走 */}
      {suggestion !== null && suggestionItems.length > 0 && (
        <CommandMenu
          items={suggestionItems}
          active={suggestion.active}
          anchor={suggestion.anchor}
          label={t('composer.commandsLabel')}
          onActive={(index) =>
            setSuggestion((current) => (current === null ? current : { ...current, active: index }))
          }
          onPick={(index) => {
            const choice = suggestionItems[index];
            if (choice !== undefined) acceptCommand(choice);
          }}
        />
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * `/` 命令补全的分层（2026-10-21 落地；`@` 上下文以后照抄这一套）
 *
 * 1. 词表是**数据，不是行为**：调用方传 `commands`（见 `ComposerCommand`），
 *    本组件不认识任何具体技能。哪些页面给哪份词表由调用方决定 ——
 *    首页 / 生成 / 评估用前端预设（`shared/commands/preset-commands.ts`），
 *    预览将来接「这个智能体自带的技能」，换来换去只换那个数组。
 *
 * 2. 触发、锚点、键盘、生命周期全在本组件里：它们是同一份交互，拆给每个页面
 *    各写一遍只会写出几种略有差别的版本（谁拦 Enter、谁在失焦时收浮层）。
 *    这与「`+` / 模型选择器」的分工不同 —— 那两个是点按钮触发的下拉，锚在按钮上；
 *    这里是打字触发的，锚在光标上，生命周期跟着光标走。
 *
 * 3. 浮层本身是独立组件 `CommandMenu`：只负责画 + 报「点了第几条 / 悬停了第几条」，
 *    不碰正文，也不碰词表过滤。以后 `@` 候选可以复用它（换一套条目渲染即可）。
 *
 * 4. 选中后的命令是**行内 token**（与附件同一种机制）：DOM 原子件、能整块删，
 *    字面量存在 `data-token-text` 上由 readEditorText 读回 prompt（见那里的注释）。
 * ────────────────────────────────────────────────────────────────────────── */