/**
 * Conversation 的公开类型。
 *
 * 为什么这些类型长在组件旁边，而不是 `shared/types/index.ts`：
 *   - 那个文件的职责是「与后端 server/src/shared/types 对照的领域模型副本」。
 *     而 `TurnEntry`（折叠体里的条目）是**纯渲染概念**，后端没有对应物 ——
 *     把它塞进去会模糊掉那个文件「只做契约镜像」的定位。
 *   - 消息形状**有**后端对应物（server/docs/04-api/4.04-消息.md §2 的 Message），
 *     但这里的是它的一层瘦投影（`text` 而非 `content`、没有 seq）。真接 WS 时它会整体
 *     换掉，放在渲染它的组件旁边，改的时候只有一个文件要动。
 *   - 更不能反过来让 shared/ 去 import features/ —— shared 不能依赖 feature，
 *     这条规矩见 Icon.tsx 的文件头。
 */

/** 一条过程条目 / 一个评估用例的推进状态 */
export type StepStatus = 'pending' | 'running' | 'done' | 'failed';

/** 技能调用轨迹里的一项，如 harness-create 正在跑 */
export interface SkillTraceItem {
  /** 技能名，取自 agent-genesis/skills，如 harness-create */
  skill: string;
  status: StepStatus;
  detail?: string;
}

/** 一次工具调用（`tool_use`，结果到达后补上 `output`） */
export interface ToolEntry {
  kind: 'tool';
  toolCallId?: string;
  toolName: string;
  /** 引擎给的原始入参；展示时按 command / file_path 之类取摘要 */
  input?: unknown;
  /** `tool_result` 的原始输出：可能是字符串，也可能是 SDK 的内容块数组 */
  output?: unknown;
  isError?: boolean;
  status: StepStatus;
}

/** 一段思考（`thinking`） */
export interface ThinkingEntry {
  kind: 'thinking';
  text: string;
  status: StepStatus;
}

/**
 * 折叠体里的一个过程条目。
 *
 * 三种成员：技能轨迹、工具调用、思考。以后加子智能体之类，**只往这个联合里加成员**：
 * 折叠壳（procbar / proc / more）与 Conversation 一行都不用动，
 * Entry.tsx 里按 kind 加一个分支即可。
 *
 * 用交叉而不是把字段抄一遍：`SkillTraceItem` 是既有的、别处（评估面板）也在用的形状，
 * 抄一份就等于埋了个「改了这边忘了那边」的坑。
 */
export type TurnEntry = ({ kind: 'skill' } & SkillTraceItem) | ToolEntry | ThinkingEntry;

/** 消息里带进来的一条本地路径（就是发送框上的附件 chip，落到消息上仍是个路径） */
export interface MessageFile {
  id: string;
  /** 本地路径，如 ~/workspace/weather-agent/CLAUDE.md */
  name: string;
}

export type ConversationRole = 'user' | 'assistant';

/* ---------- 挂起的审批 / 提问 ---------- */

/** 审批卡上的三个可选项。服务端内部还有 'aborted'，但客户端只能传这三个 */
export type WaitDecision = 'approved' | 'approved_all' | 'rejected';

export interface WaitOption {
  label: string;
  description?: string;
}

/**
 * AskUserQuestion 的一道题。
 *
 * 形状与服务端 `QuestionItem` 一致，但**不 import 那个 DTO**：这两个文件分属
 * 「协议镜像」与「渲染概念」两层，转换只发生在 `shared/live/map-message.ts`。
 * `question` 同时也是 answers 的 key（后端约定用问题原文），所以这里别改成 id。
 */
export interface WaitQuestion {
  header: string;
  question: string;
  options?: WaitOption[];
  multiSelect?: boolean;
}

/**
 * 一条消息上挂着的等待应答。
 *
 * 只表达**挂起**这一瞬：结算之后这个字段就没了 —— 审批是一次性动作，卡片直接消失；
 * 提问的答案换成 `answeredLine` 的一句话。所以卡片组件不需要处理「已结算」这种生命周期，
 * 也就没有 status 字段。
 */
export type WaitRequest =
  | {
      kind: 'approval';
      toolName?: string;
      title: string;
      description?: string;
      input?: unknown;
      /** 缺省表示允许「全部允许」；只有引擎明确禁止时才是 false */
      allowAll?: boolean;
    }
  | {
      kind: 'interactive';
      toolName?: string;
      questions: WaitQuestion[];
    };

/**
 * 一帧对话消息。
 *
 * 保持**一维列表**：服务端本来就是按 (sessionId, seq) 排一张消息表，
 * 「一轮」的折叠只是渲染层的分组（见 turn.ts 的 groupTurns）—— 别把它做进数据模型。
 */
export interface ConversationMessage {
  id: string;
  role: ConversationRole;
  text: string;
  /** 展示用时间，如 "14:32" */
  time: string;
  /** 用户消息随正文带进来的附件；端侧服务下没有上传，落库也只是路径 */
  files?: MessageFile[];
  /** 助手消息上挂的过程条目；有它才画折叠条 */
  entries?: TurnEntry[];
  /** 挂起、等用户应答的审批 / 提问；只在挂起期间存在 */
  wait?: WaitRequest;
  /**
   * 这条消息是因提问结算的（正文就是那句「✓ 已回答：…」）。
   *
   * 它只影响样式：结算行比普通回答弱一档，避免一条系统文案看起来像模型说的话。
   * 历史里已经结算的消息也会带这个标记，所以不能拿它做「刚刚发生」的判断。
   */
  waitSettled?: boolean;
}

/**
 * 渲染层把消息分组成「一轮」。
 *
 * 分组只为一件事：让「提问」和「它的应答」靠得比两轮之间更近
 * （滚动区 gap 20px，轮内 ask → reply 只隔 10px）。
 * 它**不是**数据模型，groupTurns 的产物用完就扔。
 */
export interface ConversationTurn {
  /** 折叠状态的 key 前缀：取这一轮第一条消息的 id */
  id: string;
  /** 起头的那条用户消息；会话开头直接就是助手消息时没有 */
  ask?: ConversationMessage;
  /** 这一轮里的助手消息，可能多条 */
  replies: ConversationMessage[];
}
