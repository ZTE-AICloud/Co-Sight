/**
 * 后端 `Message` → `ConversationMessage` 的投影。
 *
 * `ConversationMessage` 是渲染用的**瘦投影**（`text` 而非 `content`、没有 `seq`），
 * 它自己那份文件头就写了「真接 WS 时它会整体换掉」—— 这里就是那个换法：**换的是喂进组件的
 * 数据，组件一行不动**。
 *
 * 为什么单独一个模块而不是塞进 Hook：这段映射是「协议 → 界面」的翻译，创建页收编真会话、
 * 或做产品运行入口时要复用的正是它（连同 `shared/live` 与 `shared/api/sessions`）。
 * 它原来长在调试页下，创建页要用时就搬到了这里 —— 不用在 feature 之间互相 import
 * （依赖方向只能是 feature → shared）。
 *
 * 本期**只把能自然落进对话流的东西映射过去**：
 *   - `text`／`error`          → 正文气泡
 *   - `approval`／`tool_interactive` 挂起 → 一张内联应答卡（`wait`）
 *   - `approval` 结算 → **不进对话流**：审批是一次性动作，工具条目的结果已经说明了它
 *   - `tool_interactive` 结算 → 一行「✓ 已回答：…」（`waitSettled`）
 *   - `thinking`／`tool_use`／`tool_result` → 合成一条只带 `entries` 的助手消息（过程折叠）
 *
 * 过程消息的合并是**渲染层**的事：服务端一条工具调用、一条工具结果各存一行，
 * 但界面上它们属于同一个折叠条。合成规则见 `toConversationMessages` 里的注释。
 */

import type {
  ConversationMessage,
  MessageFile,
  ToolEntry,
  TurnEntry,
  WaitRequest,
} from '../components/Conversation/types';
import type { ApprovalContent, InteractiveContent, Message } from '../api/sessions';
import type { Locale } from '../../i18n/locale';
import { translate } from '../../i18n/translate';
import type { MessageKey, MessageParams } from '../../i18n/types';

type Translate = (key: MessageKey, params?: MessageParams) => string;

/** 正在流式到来的那一段正文（来自 `chat.delta` 的缓冲，还没被落库的 `message` 覆盖） */
export interface LiveSegment {
  runId: string;
  text: string;
}

/** 挂起消息的一句话摘要，对话流与调试面板共用 */
export function pendingSummary(message: Message, t: Translate): string {
  if (message.type === 'approval') {
    const content = message.content as { title?: string; toolName?: string };
    if (content.title !== undefined && content.title !== '') return content.title;
    return content.toolName
      ? t('conversation.wait.needApprovalWithTool', { tool: content.toolName })
      : t('conversation.wait.needApproval');
  }
  const content = message.content as { questions?: { question: string }[] };
  const first = content.questions?.[0]?.question;
  return first
    ? t('conversation.wait.needAnswerWithQuestion', { question: first })
    : t('conversation.wait.needAnswer');
}

/** 提问结算后的一句话：答案是用户提供的内容，留在对话里读起来才连贯 */
function answeredLine(message: Message, t: Translate): string | null {
  if (message.type !== 'tool_interactive') return null;

  const summary = pendingSummary(message, t);
  if (message.status === 'aborted') {
    const source = (message.content as { decisionSource?: string }).decisionSource;
    return source === 'restart'
      ? t('conversation.wait.settled.questionAbortedWithRestart', { summary })
      : t('conversation.wait.settled.questionAborted', { summary });
  }
  const answers = (message.content as { answers?: Record<string, string[]> }).answers;
  const listSeparator = t('common.listSeparator');
  const clauseSeparator = t('common.clauseSeparator');
  const text = answers
    ? Object.entries(answers)
        .map(([question, values]) => `${question} → ${values.join(listSeparator)}`)
        .join(clauseSeparator)
    : '';
  return t('conversation.wait.settled.answered', { answer: text || summary });
}

/**
 * 挂起消息 → 应答卡。
 *
 * 只有 pending 才返回：审批结算后卡片直接消失，提问结算后换成一行 `answeredLine`。
 * `title` 是渲染侧的必填字段（卡片头要有一句话），服务端理论上恒有；缺了就用工具名兜底。
 */
function toWaitRequest(message: Message, t: Translate): WaitRequest | undefined {
  if (message.status !== 'pending') return undefined;

  if (message.type === 'approval') {
    const content = message.content as ApprovalContent;
    return {
      kind: 'approval',
      title: content.title || content.toolName || t('conversation.wait.needApproval'),
      ...(content.toolName !== undefined ? { toolName: content.toolName } : {}),
      ...(content.description !== undefined ? { description: content.description } : {}),
      ...(content.input !== undefined ? { input: content.input } : {}),
      ...(content.allowAll !== undefined ? { allowAll: content.allowAll } : {}),
    };
  }

  if (message.type === 'tool_interactive') {
    const content = message.content as InteractiveContent;
    return {
      kind: 'interactive',
      ...(content.toolName !== undefined ? { toolName: content.toolName } : {}),
      questions: Array.isArray(content.questions) ? content.questions : [],
    };
  }

  return undefined;
}

/** 展示用时间：`14:32`。后端给的是 ISO，这里只取时分（按当前语言格式化） */
function timeLabel(iso: string, locale: Locale): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

export interface ProjectionOptions {
  /** 界面语言：对话流里的系统文案与时间格式都按它出 */
  locale: Locale;
  /** 当前流式中的那段正文；不传或空串则不追加 */
  live?: LiveSegment | null;
  /**
   * 此刻正在跑的那个 run；不传 / null 表示没有任何 run 在跑。
   *
   * 用来给**没等到 `tool_result` 的工具条目**收尾：run 以失败 / 中止结束（含服务重启）时，
   * 在途的工具调用不会有结果落库 —— 尤其是 `Agent`（子智能体）这种长调用，父 run 结束时
   * 它直接被掐断。不收尾的话那条会永远转圈，跟「会话已经结束」自相矛盾。
   *
   * 判据按 run 而不是「有没有结果」：同一个 run 里子智能体自己的工具调用会穿插进来，
   * 不能因为后面还有消息就认定前一条已完成。
   */
  activeRunId?: string | null;
}

/**
 * 组对话流。入参 `messages` 必须已按 `seq` 升序（排序是 Hook 的事，见那边的三条铁律）。
 */
export function toConversationMessages(
  messages: Message[],
  options: ProjectionOptions,
): ConversationMessage[] {
  const { locale, live, activeRunId = null } = options;
  const t: Translate = (key, params) => translate(locale, key, params);
  const projected: ConversationMessage[] = [];

  /** 还挂着 `running` 的工具条目 + 它属于哪个 run，循环结束后统一收尾（见 activeRunId） */
  const unresolved: { entry: ToolEntry; runId: string | null }[] = [];

  /**
   * 连续的过程消息（thinking / tool_use / tool_result）合成**一条只带 entries 的助手消息**。
   *
   * 服务端把每个思考块、每次工具调用、每个工具结果各落一条 message，但它们本身不该
   * 各占一个气泡 —— 它们在界面上是「这一轮的过程」，折叠成一条折叠条。
   *
   * 分组规则：碰到文本 / 错误就收束；审批消息**不**收束（一次工具调用的
   * tool_use 与 tool_result 之间往往夹着审批卡）。合成消息的 id 取第一条过程消息的 id，
   * 所以后续工具结果到达时是更新同一条，而不是新插一条。
   */
  let processMessage: ConversationMessage | null = null;
  /** toolCallId → 条目；结果可能在审批之后才到，靠它挂回原来的调用条目 */
  const toolEntries = new Map<string, ToolEntry>();

  function openProcessGroup(message: Message): TurnEntry[] {
    if (processMessage === null) {
      const group: ConversationMessage = {
        id: `process-${message.id}`,
        role: 'assistant',
        text: '',
        time: timeLabel(message.createdAt, locale),
        entries: [],
      };
      processMessage = group;
      projected.push(group);
      return (group.entries ??= []);
    }
    return (processMessage.entries ??= []);
  }

  function closeProcessGroup() {
    processMessage = null;
  }

  for (const message of messages) {
    const time = timeLabel(message.createdAt, locale);

    if (message.role === 'user' && message.type === 'text') {
      closeProcessGroup();
      const text = (message.content as { text?: string }).text ?? '';
      // 附件是消息自己的字段（服务端落库时写进 content.files）：历史、实时帧、刷新后都一致，
      // 不再依赖发送方在本机另存一份
      const files = (message.content as { files?: MessageFile[] }).files;
      // 空白正文又没附件 = 什么都没有，投影出来就是一条只剩头像的空行（见下面的 text 分支）
      if (text.trim() === '' && (files === undefined || files.length === 0)) continue;
      projected.push({ id: message.id, role: 'user', text, time, files });
      continue;
    }

    if (message.type === 'error') {
      // 失败时服务端先落一条 system/error 再落 failed 终态（顺序保证：查到的 failed 一定配得上这条）
      closeProcessGroup();
      projected.push({
        id: message.id,
        role: 'assistant',
        text: (message.content as { message?: string }).message ?? t('conversation.unknownError'),
        time,
      });
      continue;
    }

    if (message.type === 'approval' || message.type === 'tool_interactive') {
      if (message.status === 'pending') {
        /* 挂起期间是一张卡（正文为空）；结算后卡片整个消失，见下面两条分支 */
        const wait = toWaitRequest(message, t);
        if (wait !== undefined) {
          projected.push({ id: message.id, role: 'assistant', text: '', time, wait });
        }
        continue;
      }

      /*
       * 审批结算（含「全部允许」后的每一条 `approved_all_auto` 审计）**不进对话流**。
       *
       * 审批是一次性动作：它落在哪次工具调用上，过程折叠条里的那条工具条目已经说明了
       * （通过就是结果，拒绝就是失败 + 错误输出）。再补一行结算不但重复，还会把这条
       * 消息排到仍在追加条目的过程组**后面** —— 最后一轮于是被当成「没有过程」，折叠条
       * 停在「已完成」，底下多出一条「正在执行」的尾巴。留痕仍在调试页的原始消息表里。
       */
      if (message.type === 'approval') continue;

      const text = answeredLine(message, t);
      if (text) {
        projected.push({ id: message.id, role: 'assistant', text, time, waitSettled: true });
      }
      continue;
    }

    if (message.type === 'thinking') {
      const text = (message.content as { text?: string }).text ?? '';
      if (text !== '') {
        openProcessGroup(message).push({ kind: 'thinking', text, status: 'done' });
      }
      continue;
    }

    if (message.type === 'tool_use') {
      const content = message.content as {
        toolCallId?: string;
        toolName?: string;
        input?: unknown;
      };
      const entry: ToolEntry = {
        kind: 'tool',
        ...(content.toolCallId !== undefined ? { toolCallId: content.toolCallId } : {}),
        toolName: content.toolName ?? t('conversation.entry.tool'),
        ...(content.input !== undefined ? { input: content.input } : {}),
        // 结果还没到：折叠条显示「正在执行」，并且会自动摊开
        status: 'running',
      };
      openProcessGroup(message).push(entry);
      unresolved.push({ entry, runId: message.runId });
      if (content.toolCallId !== undefined) toolEntries.set(content.toolCallId, entry);
      continue;
    }

    if (message.type === 'tool_result') {
      const content = message.content as {
        toolCallId?: string;
        output?: unknown;
        isError?: boolean;
      };
      const isError = content.isError === true;
      const target =
        content.toolCallId !== undefined ? toolEntries.get(content.toolCallId) : undefined;

      if (target !== undefined) {
        // 挂回原调用条目：整条过程只留一行，不另起一条「结果」
        target.output = content.output;
        target.isError = isError;
        target.status = isError ? 'failed' : 'done';
      } else {
        openProcessGroup(message).push({
          kind: 'tool',
          toolName: t('conversation.entry.toolResult'),
          ...(content.output !== undefined ? { output: content.output } : {}),
          isError,
          status: isError ? 'failed' : 'done',
        });
      }
      continue;
    }

    if (message.type === 'text') {
      closeProcessGroup();
      const text = (message.content as { text?: string }).text ?? '';
      /*
       * 空白正文（空串 / 只有换行）不占对话流。
       *
       * 引擎偶尔会把一个空的 text 块照落一条消息，投影出来就是一个只有头像、
       * 没有折叠条也没有正文的空行。它还会把「这一轮的最后一条」占掉，
       * 于是底下再补一条「正在执行」—— 就是那种看不出是什么的空白。
       */
      if (text.trim() === '') continue;
      const isSystem = message.role === 'system';
      projected.push({
        id: message.id,
        role: isSystem ? 'assistant' : (message.role as 'user' | 'assistant'),
        text,
        time,
      });
      continue;
    }

    // 预留的 `status` 不进对话流
  }

  /*
   * 收尾：run 已经结束（或因重启直接没了）还没等到结果的工具条目，不会再等到结果了。
   * 标 `failed` 而不是留 `running` —— run 的终态本来就是失败/中止，界面上不该还在转圈；
   * 也不能当 `done`，那等于凭空说它跑完了。`null` 的 runId 不动（演示数据里没有 run）。
   */
  for (const { entry, runId } of unresolved) {
    if (entry.status === 'running' && runId !== null && runId !== activeRunId) {
      entry.status = 'failed';
    }
  }

  // 只有空白的段等同没有：第一帧往往就是一两个换行，落成占位条同样是一条空行
  if (live && live.text.trim() !== '') {
    /*
     * 流式段的占位。id 里带 runId：同一 run 的多段正文各自一段，且换 run 时不会串到上一条上。
     * 它在下一条落库的 `text` 消息到达时被**整体替换**（见 Hook 里 delta→message 的覆盖规则），
     * 所以这里不需要去重 —— 那段文字带着自己的 id 进来，这一段就消失了。
     */
    projected.push({
      id: `live-${live.runId}`,
      role: 'assistant',
      text: live.text,
      time: timeLabel(new Date().toISOString(), locale),
    });
  }

  return projected;
}
