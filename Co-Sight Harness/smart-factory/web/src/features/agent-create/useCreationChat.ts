/**
 * 创建页各阶段的对话来源：**三个阶段都是真会话**（评估已在 2026-10-19 收编）。
 *
 * 页面只认识这个 Hook（`{ messages, running, send, stop }`），不用知道自己在跟谁说话。
 * 哪个阶段走真会话只写在 `LIVE_STAGES` 里；演示内核（`useSessionChat` / `mock.ts`）
 * 已随评估阶段一起删除，不要再在页面里造假消息。
 *
 * ── 真会话这一层做了三件事 ────────────────────────────────────────────────
 *
 * 1. **连通道**（`shared/live/useLiveSession` 的 `connect`）。创建页一进来就该连上：
 *    不连就只剩「拉一次历史」，对话跑不起来。
 * 2. **找或建这个阶段的会话**：首页交接过来的初始化会话优先（`seed.preferredSessionId`，
 *    校验 agentId / stage 后再打开）；否则 `GET sessions/list?agentId=&stage=` 取最近一条；
 *    没有就 `POST sessions/create`。**为什么要找、不是每次新建**：`sessions/create`
 *    每次都插一行新会话，进一次页面建一个，刷新一下聊天记录就没了。要找的是
 *    「这个智能体在这个阶段的那场对话」。
 *    打开之后，development 阶段若会话为空且带着原话（`seed.firstPrompt`），
 *    **补发一次首轮** —— 后端创建时不落这条消息（见 `CreationSeed`）。
 *    路由 state 刷新就没了，所以原话与附件还有第二来源：创建时落库的
 *    `Agent.initialInput` / `Agent.initialAttachments`（`stored`），只在没有路由 state 时兜底。
 * 3. **`openSession`（先订阅、再拉历史、再定 run 状态）** —— 顺序是 4.06 §7.1 定的，
 *    在 `useLiveSession` 里，这里不重复实现。
 *
 * ── 预览 / 评估沙箱 ──────────────────────────────────────────────────────
 *
 * 服务端在**每次 run 前**把开发产物重拷到预览 / 评估目录，但源没变时会跳过 ——
 * 所以「复用最近一场」意味着沙箱可能还是旧的。`restart()` 是用户手动重建沙箱的
 * 唯一入口：新建一场会话并带 `resetSandbox`（后端先删掉该阶段整个目录 —— 评估的
 * 旧报告一并消失 —— 下一次 run 前再整体重拷）+ 清空对话。同阶段的实例已有活跃
 * run 时后端回 409（沙箱不删），这时退回最近一场并提示，不把错误铺到整屏。
 *
 * **首次建会话的模型由前端解析**：服务端只收显式 `modelId`，而预览 / 评估此时
 * 还没有会话可继承。解析链是「工作区默认 → 框架生效 → 模型列表第一项」，
 * 见 `shared/api/default-model.ts`；已有会话时直接沿用它的 `modelId`。
 *
 * 预览与评估的 UI 都暴露这个动作（「重新开始预览」/「重新评估」）；评估的按钮在
 * 重建之外还立刻开跑一轮（见 `restart(prompt)` 与 `EvaluateStage`）。
 *
 * ── 三条容易踩的 ─────────────────────────────────────────────────────────
 *
 * - **等到 `conn === 'ready'` 才开会话**。`useLiveSession` 的 `openSession` 在没连上时
 *   会跳过订阅（那是给调试页的「不点连接就只看历史」用的），照那个语义接，创建页会
 *   永远收不到实时事件。所以这里就等：连上了再开。代价是连不上时连历史也看不到 ——
 *   对一页「要跟 Claude Code 对话」的界面，这个代价是对的（没通道什么都做不了）。
 * - **StrictMode 会把 effect 跑两遍**，而「建会话」不幂等。所以用 `bootedKeyRef` 认
 *   `${agentId}#${stageId}#${nonce}` 那个 key：同一场只 boot 一次，重试 / 重开靠 `nonce` 换代。
 * - **`createSession` 这里不用**：它把失败吞进 `notice` 只返回 `null`（那是调试页的用法，
 *   它有原始日志可看）。创建页要自己把原因摆出来，所以直接打 `sessionsApi.create`。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { msg } from '../../i18n/useI18n';
import type { ComposerReplay, ComposerSubmit } from '../../shared/components/Composer';
import type { WaitDecision } from '../../shared/components/Conversation/types';
import { ApiError } from '../../shared/api/client';
import { resolveDefaultModelId } from '../../shared/api/default-model';
import { backendDownHint, isBackendDown, messagesApi, sessionsApi } from '../../shared/api/sessions';
import type { Session } from '../../shared/api/sessions';
import type { LiveState } from '../../shared/live/live-client';
import { useLiveSession } from '../../shared/live/useLiveSession';
import type { ConversationMessage } from '../../shared/components/Conversation/types';
import { withKnowledgeFlag } from '../../shared/commands/harness-prompt';
import type { StageId } from './types';

/** 走真会话的阶段。三个创建阶段都在内；runtime 不在创建页上 */
const LIVE_STAGES: readonly StageId[] = ['development', 'preview', 'evaluation'];

/**
 * 阶段准入（契约 4.10）：**产物没生成完，预览 / 评估连会话都不开**。
 *
 * 不是「开了会话但不让发」—— 那样会留下一条空会话、页面上也照样摆着「预览会话」，
 * 用户会以为已经可以用了。判据由页面从 `useProductionGate` 取，这里只消费结果。
 * `development` 不受它约束：它就是产出产物的地方，必须先有会话。
 */
export interface CreationGate {
  /** 当前能不能为这个阶段开会话；development 阶段忽略 */
  ready: boolean;
  /** 不能开时的人话原因（产物未完成的理由） */
  reason?: string | null;
}

/**
 * 这个阶段背后是不是一场真会话。
 *
 * 「boot 会话」与「restart」两个守卫都用它；判据只留这一份。
 */
function isLiveStage(stageId: StageId): boolean {
  return LIVE_STAGES.includes(stageId);
}

/** 一个阶段的对话，形状与 `useLiveSession` 的投影保持一致 */
export interface SessionChat {
  /** 当前阶段的对话记录，追加顺序即时间顺序 */
  messages: ConversationMessage[];
  /** 当前阶段有没有正在跑的一轮 */
  running: boolean;
  /** `false` = 这一轮没发出去，发送框据此把正文与附件还回来 */
  send: (payload: ComposerSubmit) => Promise<boolean>;
  stop: () => void;
  /** 已加载的最早一条之前还有没有消息（打开会话只拿最近一页，见 useLiveSession） */
  hasOlder: boolean;
  /** 更早一页正在路上 */
  loadingOlder: boolean;
  /** 请求更早一页；滚到顶时由对话区调用 */
  loadOlder: () => void;
}

/** 错误提示里用的阶段名（短名，不是步骤条上的全名） */
function stageLabel(stage: StageId): string {
  switch (stage) {
    case 'development':
      return msg('create.stage.development');
    case 'preview':
      return msg('create.stage.preview');
    case 'evaluation':
      return msg('create.stage.evaluation');
    case 'runtime':
      return msg('create.stage.runtime');
  }
}

/**
 * 「没发出去 + 已放回发送框」的提示文案。
 *
 * 原因取自 `live.lastSendError()` —— 就是 `send` 刚报过的同一条：`send` 失败时
 * 已经用 `notice` 说过一次具体原因（模型不可用 / 通道断了 / 服务端拒绝……），
 * 这里再用一句通用文案盖掉它，用户就只剩「不知道为什么会失败」。
 * 没有原因时（比如本地判空这类不发请求的路径）退回原句。
 */
const REPLAY_NOTICE = {
  firstPromptReplay: { plain: 'create.chat.firstPromptReplay', withReason: 'create.chat.firstPromptReplayReason' },
  promptReplay: { plain: 'create.chat.promptReplay', withReason: 'create.chat.promptReplayReason' },
} as const;

/** 提示条只有一行：原因压平换行、过长截断（完整那条仍在 `send` 自己写的日志里） */
const REASON_MAX = 160;

function replayNotice(kind: keyof typeof REPLAY_NOTICE, reason: string | null): string {
  const keys = REPLAY_NOTICE[kind];
  if (reason === null) return msg(keys.plain);
  const flat = reason.replace(/\s+/g, ' ').trim();
  return msg(keys.withReason, { reason: flat.length > REASON_MAX ? `${flat.slice(0, REASON_MAX - 1)}…` : flat });
}

/** 当前阶段那场会话准备到哪一步 */
export type BootPhase = 'idle' | 'connecting' | 'preparing' | 'ready' | 'failed';

/** 当前阶段的实时状态（连接态 + 会话准备进度） */
export interface CreationLink {
  /** 实时通道的连接态 */
  conn: LiveState;
  /** 会话准备工作到哪一步 */
  phase: BootPhase;
  /** 准备失败的人话原因（后端没起 / 查不到智能体 / 建会话被挡） */
  error: string | null;
  /** 一次性提示：被挡下的动作、附件没有出网这类「说一声就好」的事 */
  notice: string | null;
  dismissNotice: () => void;
  /** 准备失败的出口：重来一次（连不上时顺带立刻重连，不等退避） */
  retry: () => void;
}

/**
 * 首页交给设计页的一次性载荷（见 `features/home/HomePage.tsx` 的 `navigate`）。
 *
 * 后端创建时只建会话、不落消息，所以「用户那句话」得由前端带过来，等实时通道
 * 连上、会话打开之后再补发 —— 这样初始化过程的帧一条都不会错过。
 */
export interface CreationSeed {
  /**
   * 首页那句需求全文；只在 development 阶段、会话为空时补发一次。
   *
   * 没有它时退回创建时落库的快照（`Agent.initialInput` / `initialAttachments`，
   * 见 `useCreationChat` 的 `stored`），刷新 / 从列表再次进入也还能补发首轮。
   */
  firstPrompt?: string;
  /**
   * 首页创建时后端建好的初始化会话 id。
   *
   * 有它就**直接打开这一场**，不碰运气去取「最近一场」。会话已被删掉时退回原逻辑。
   * 其它入口（列表页点进来、手输地址）没有这个值，行为不变。
   */
  preferredSessionId?: string;
  /**
   * 首页挂在发送框上的附件（**绝对路径**）。
   *
   * `agents/create` 不收附件，所以它们随路由 state 过来，跟首轮一起发出去 ——
   * 端侧形态下没有上传，路径本身就是全部内容，服务端发送时再校验一遍。
   */
  attachments?: string[];
}

export interface CreationChat extends SessionChat {
  link: CreationLink;
  /**
   * 当前打开的真会话（含会话级 `modelId`）。
   * 在连接 / 准备期间是 null，页面据此把模型选择器锁在「加载中」。
   */
  session: Session | null;
  /**
   * 切换当前会话的模型（调 `sessions/:sessionId/update`）。
   * 当前没有会话时是 no-op，返回 false。
   */
  updateModel: (modelId: string) => Promise<boolean>;
  /**
   * 应答对话流里的挂起审批 / 提问。返回值语义见 `useLiveSession.respond`。
   */
  respondApproval: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  respondAnswers: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;
  /**
   * 用当前阶段的最新产出重建沙箱，并新开一场会话。
   *
   * preview 与 evaluation 的 UI 都暴露这个动作（「重新开始预览」/「重新评估」）。
   * 传了 `prompt` 时，新会话打开后立刻把它发出去 —— 仅用于用户的明确动作
   * （「重新评估」= 重建 + 立刻开跑）；不传就是单纯重置，等用户自己开口。
   * `paths` 是随这条消息一起发出去的附件（首页「评估智能体」可能带着文件过来）。
   */
  restart: (prompt?: string, paths?: string[]) => void;
  /**
   * 首轮补发 / 「重开并开跑」没发出去时，交给发送框的一次性回填请求。
   *
   * 这些内容来自路由 state 或页面自己的动作，Composer 从来没拿到过它们；
   * 不还回去就只能让用户回首页重来。`null` = 没有待回填的东西。
   *
   * **只包含当前阶段的那一条**：回填请求在产生时盖上阶段戳（见 `pushReplay`），
   * 切到别的阶段后这里变 null，切回来才重新出现。
   */
  replay: ComposerReplay | null;
  /**
   * 把一段话放进发送框（设计页的 replay 入口），**不自动发**。
   *
   * 与 `replay` 的区别：那个是「补发失败把原话还回来」，由本 Hook 自己产生；
   * 这个是页面收到路由 state（技能库的「优化」）后主动递进来的。共用同一份
   * `ComposerReplay` 管道，`key` 自增保证只应用一次。
   */
  replayInto: (text: string, paths?: string[]) => void;
  /**
   * 把一段话发进**当前阶段最近一场会话**，会话准备好就立刻发（首页「优化智能体」）。
   *
   * 与 `replayInto` 只差「发不发」：内容同样来自路由 state，但那是用户在首页按过
   * 发送的动作，到了设计页不该再让他按一次。会话还在准备就排队，`ready` 后发一次；
   * 准备失败或没发出去时把原文放回发送框 —— 不能让用户回首页重来。
   *
   * 复用最近一场而不是新开：优化的是同一个智能体的产物，上下文要接着上一轮。
   */
  kickoffInto: (text: string, paths?: string[]) => void;
}

/**
 * 创建时落库的首轮快照（契约 5.01 的 `Agent.initialInput` / `Agent.initialAttachments`）。
 *
 * 与 `CreationSeed` 是同一件事的两个来源：路由 state 只活到刷新为止，快照活到智能体被删。
 */
export interface StoredSeed {
  /** 需求原文（`initialInput`），空串 = 创建时没写第一句 */
  prompt: string;
  /** 附件真实绝对路径（`initialAttachments`），空数组 = 创建时没带附件 */
  attachments: string[];
}

export function useCreationChat(
  agentId: string,
  stageId: StageId,
  seed: CreationSeed = {},
  gate: CreationGate = { ready: true },
  /**
   * 创建时落库的首轮快照。路由 state 丢了（刷新 / 从列表再次进入）时用它恢复首轮。
   *
   * 原话与附件要一起来：只恢复文字会悄悄丢掉当时挂的文件，用户看不出少了什么。
   *
   * `undefined` 是「详情还在路上，快照可能就在里面」：此时先别 boot（见下面 gate），
   * 否则会以「没有首轮」开完会话，详情回来后又因为 `bootedKeyRef` 不再补发。
   * 详情取失败时调用方传空快照 —— 恢复不了就算了，页面本来就有取详情的错误提示。
   */
  stored?: StoredSeed,
  /**
   * 智能体所属工作区 id（`Agent.workspaceId`）。只在预览 / 评估首次建会话时用：
   * 服务端要求显式 `modelId`，前端据此找该工作区的默认模型（见 `resolveDefaultModelId`）。
   * 拿不到时退回框架当前工作区；development 阶段忽略它。
   */
  workspaceId?: string,
  /**
   * 生产会话当前的知识检索工作流 id（Composer 工具栏那颗 chip）。
   *
   * 它来自智能体自己的配置（`Agent.knowledgeWorkflowId`，改 / 取消都落库），页面负责
   * 解析成这个值；`null` = 智能体没有启用知识检索。
   *
   * 只有 development 阶段、且消息以 `/agent-genesis:harness-create` 开头时才拼进去 ——
   * 普通消息原样发出。预览 / 评估不生效（那里的消息是任务描述，不是构建参数）。
   */
  knowledgeWorkflowId: string | null = null,
): CreationChat {
  const live = useLiveSession();
  const isLive = isLiveStage(stageId);
  /** 预览 / 评估首次建会话没有现成模型可继承，由前端解析一个默认值 */
  const needsDefaultModel = stageId === 'preview' || stageId === 'evaluation';

  /**
   * 解构成原始值再进 effect 依赖：`gate` 是调用方每次渲染新建的对象。
   * `blocked` 只在预览 / 评估阶段生效（见 `CreationGate`）。
   */
  const gateReady = gate.ready;
  const gateReason = gate.reason ?? '';
  const blocked = stageId !== 'development' && !gateReady;

  /**
   * 解构成原始值再进 effect 依赖：`seed` 是调用方每次渲染新建的对象，
   * 直接依赖它会让 boot 反复被判定为「变了」。
   */
  const seededPrompt = seed.firstPrompt?.trim() ?? '';
  /*
   * 路由 state 优先（它才是这次创建带着的那句话）；没有才退回库里存的原文。
   * 两者允许不一致：用户可能在发送前改过字，`initialInput` 记的是创建时的快照。
   */
  const firstPrompt = seededPrompt !== '' ? seededPrompt : (stored?.prompt.trim() ?? '');

  /**
   * 生产会话的知识检索值由页面持有（智能体配置 + 本页改动），这里只在发送时现取。
   *
   * 读 ref 而不是把它塞进 boot effect 的依赖：改一次 chip 不该把整场 boot 重跑一遍。
   */
  const knowledgeRef = useRef<string | null>(knowledgeWorkflowId);
  knowledgeRef.current = knowledgeWorkflowId;
  /** 只给 development 阶段的 harness-create 消息补参数（预览 / 评估不碰） */
  const applyKnowledge = useCallback(
    (text: string) =>
      stageId === 'development' ? withKnowledgeFlag(text, knowledgeRef.current) : text,
    [stageId],
  );

  const preferredSessionId = seed.preferredSessionId;
  /**
   * 附件同样是调用方每次渲染新建的数组 —— 用拼接出的字符串进依赖，数组引用不进。
   * 路径里不会有 `\u0000`（服务端也会拒），拿它当分隔符不会被内容撞上。
   */
  const attachmentsKey = (seed.attachments ?? []).join('\u0000');
  /** 库里那份附件清单，同样用拼接串进依赖 */
  const storedPathsKey = (stored?.attachments ?? []).join('\u0000');
  /** 快照到没到（`stored` 本身每次渲染都是新对象，不能进依赖） */
  const storedSettled = stored !== undefined;

  const { connect, disconnect, reconnect, closeSession, openSession, notice, lastSendError } = live;
  /** 已经 boot 过的那一场（`${agentId}#${stageId}#${nonce}`）；见文件头第 2 条 */
  const bootedKeyRef = useRef<string | null>(null);
  /** 下一次 boot 是否跳过「复用最近一场」直接新建（restart 用） */
  const forceNewRef = useRef(false);
  /**
   * 「重开」新建会话时带上的模型：沿用当前这场会话的 `modelId`。
   * 不带的话，用户选好的模型会在新一场里丢掉，前端会重新解析默认模型。
   * `undefined` = 当前没有会话，走 `resolveDefaultModelId` 的默认链。
   */
  const carryModelRef = useRef<string | undefined>(undefined);
  /**
   * 「重开并立刻开跑」要发的正文与附件（见 `restart(prompt, paths)`）。
   * 只在**确实新建了一场会话**之后才消费：退回旧会话的分支会把它们还给发送框，
   * 否则等于往一场还有活跃 run 的旧会话里塞消息。
   */
  const pendingSendRef = useRef<{ text: string; paths: string[] } | null>(null);
  const [phase, setPhase] = useState<BootPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  /** 重试 / 重开就是让它换代：effect 的守卫按 key 认，换了 key 才会再 boot 一次 */
  const [nonce, setNonce] = useState(0);
  /**
   * 发送框的「放回去」请求（见 `CreationChat.replay`）；key 递增，同一个请求只应用一次。
   *
   * `stage` 是产生它时所在的阶段：回填请求只该回到那一阶段的发送框。
   * 没有这个戳，首轮补发失败的回填会跟着用户切阶段、在新阶段里再出现一遍。
   */
  const [queuedReplay, setQueuedReplay] = useState<(ComposerReplay & { stage: StageId }) | null>(
    null,
  );
  const replayKeyRef = useRef(0);
  const pushReplay = useCallback(
    (text: string, paths: string[] = []) => {
      replayKeyRef.current += 1;
      setQueuedReplay({ key: replayKeyRef.current, text, paths, stage: stageId });
    },
    [stageId],
  );

  /**
   * 「放进最近一场并立刻发送」的请求（首页「优化智能体」，见 `kickoffInto`）。
   *
   * 与 `queuedReplay` 分开存：那个由 Composer 填进发送框，这个由下面的 effect 直接
   * 交给 `live.send`，Composer 根本不参与。同样盖阶段戳 —— 切走阶段后不该再发。
   */
  const [queuedKickoff, setQueuedKickoff] = useState<(ComposerReplay & { stage: StageId }) | null>(
    null,
  );
  const kickoffKeyRef = useRef(0);
  const kickoffInto = useCallback(
    (text: string, paths: string[] = []) => {
      kickoffKeyRef.current += 1;
      setQueuedKickoff({ key: kickoffKeyRef.current, text, paths, stage: stageId });
    },
    [stageId],
  );

  /**
   * 上电就连接，**与卸载成对**。
   *
   * 「连」和「断」必须写在同一个 effect 里，不能只写 `connect()`：StrictMode 会把每个
   * effect 跑成「挂载 → 卸装 → 再挂载」，而 `useLiveSession` 的卸装清理里有 `disconnect()`
   * ——只连不断的话，第二次挂载时连接已经被那次假卸装掐掉了，页面会停在「断线重连中」
   * 且永远不会自己回来（`disconnect` 是主动断开，不触发重连）。
   *
   * 依赖是空数组：连接是**整页一条**，不随 agentId / stageId 换。换阶段换的是会话。
   */
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  useEffect(() => {
    if (agentId === '' || !isLive) return;

    /*
     * 产物还没生成完：这一阶段**不找会话、也不建会话**，已有的那场也放下。
     * 放在连接判定之前 —— 没连上也不该保留一条上一阶段的会话。
     */
    if (blocked) {
      bootedKeyRef.current = null;
      closeSession();
      setPhase('idle');
      setError(gateReason === '' ? null : gateReason);
      return;
    }

    // 连上之前不碰会话：见文件头第 1 条
    if (live.conn !== 'ready') return;

    /*
     * 首轮快照可能还在智能体详情里（`stored === undefined`）。development 阶段
     * 既没有路由 state 也没有附件时，等详情落定再开会话 —— 早开一场空会话，等详情
     * 回来时 `bootedKeyRef` 已经认过这个 key，恢复首轮的机会就白白错过了。
     * 首页带着原话 / 附件进来、以及预览 / 评估阶段都不需要等：它们不靠快照起跑。
     */
    if (stageId === 'development' && !storedSettled && seededPrompt === '' && attachmentsKey === '') {
      return;
    }

    const key = `${agentId}#${stageId}#${String(nonce)}`;
    if (bootedKeyRef.current === key) return;
    bootedKeyRef.current = key;

    /** 期间换了阶段、或点了重试 / 重开 —— 在途的响应一律丢掉 */
    const stale = () => bootedKeyRef.current !== key;
    const forceNew = forceNewRef.current;
    forceNewRef.current = false;

    setPhase('preparing');
    setError(null);

    /**
     * 这一场是不是**新建**的（restart 才可能为真）。
     * 「重开并开跑」的待发消息只在新建成功后消费，见 `pendingSendRef`。
     */
    let createdNewSession = false;

    /** 复用最近一场；`forceNew` 时新建，409 退回最近一场 */
    async function pickSession(): Promise<string> {
      if (!forceNew) {
        // 首页带过来的初始化会话优先：确认它确实属于这个智能体 / 阶段再打开
        if (preferredSessionId !== undefined) {
          try {
            const preferred = await sessionsApi.detail(preferredSessionId);
            if (preferred.instance.agentId === agentId && preferred.instance.stage === stageId) {
              return preferred.id;
            }
          } catch {
            // 会话被删了 / 后端暂时不可用：退回「最近一场」，后面的失败会给人话
          }
        }
        const found = await sessionsApi.list({ agentId, stage: stageId, page: 1, pageSize: 1 });
        const existing = found.items[0];
        if (existing) return existing.id;
        const created = await sessionsApi.create({
          agentId,
          stage: stageId,
          /*
           * 预览 / 评估没有现成会话可继承模型：建会话前先解析一个默认值。
           * 服务端只收显式 `modelId`，这里不传就只会 400。
           */
          ...(needsDefaultModel ? { modelId: await resolveDefaultModelId(workspaceId) } : {}),
        });
        createdNewSession = true;
        return created.id;
      }

      try {
        // 沿用上一场选中的模型；没有时由前端解析 preview / evaluation 的默认值
        const modelId =
          carryModelRef.current ?? (needsDefaultModel ? await resolveDefaultModelId(workspaceId) : undefined);
        const created = await sessionsApi.create({
          agentId,
          stage: stageId,
          modelId,
          // 重开 = 拿当前产物重建沙箱：服务端先删掉旧沙箱（评估的旧报告也在里面），
          // 下一次 run 前再整体重拷。409 时删不到，退回最近一场
          resetSandbox: true,
        });
        createdNewSession = true;
        return created.id;
      } catch (cause) {
        if (!(cause instanceof ApiError) || cause.code !== 'CONFLICT') throw cause;
        // 用户已经切走了：别把旧阶段的提示写到新阶段头上，交给外层 stale 守卫吞掉
        if (bootedKeyRef.current !== key) throw cause;
        // 同阶段的实例已有活跃 run：重开建不了新会话，退回最近一场让用户先看见它
        notice(msg('create.chat.stageBusy', { stage: stageLabel(stageId) }));
        /*
         * 退回旧会话就不能再自动发「重开并开跑」的那条（run 还在跑，发不进去），
         * 但内容不能丢：交给发送框，等这一轮结束用户自己按发送。
         */
        const unsent = pendingSendRef.current;
        pendingSendRef.current = null;
        if (unsent !== null) pushReplay(unsent.text, unsent.paths);
        const found = await sessionsApi.list({ agentId, stage: stageId, page: 1, pageSize: 1 });
        const latest = found.items[0];
        if (!latest) throw cause;
        return latest.id;
      }
    }

    void (async () => {
      // 换阶段时把上一场会话放下（取消订阅 + 清空消息），不然旧对话会串到新阶段上
      closeSession();
      try {
        const sessionId = await pickSession();
        if (stale()) return;
        await openSession(sessionId);
        if (stale()) return;

        /*
         * 首轮补发只发生在**生成阶段**：首页带过来的需求原话（`seed.firstPrompt`）。
         * 幂等判据是「会话为空」：刷新 / 重进时发过的那场有消息，不会再发。
         *
         * 评估阶段**不再自动开跑**：一轮评估会消耗大量 token 与几分钟时间，
         * 没点「开始评估」就自己跑起来太突兀。kick-off prompt 现在由
         * `EvaluateStage` 的按钮触发（`evalKickoff.ts`）。
         *
         * 排在 `openSession` 之后：订阅已经生效，初始化过程的帧一条都不会错过。
         * 发送本身失败由 `live.send` 自己提示；这里只管「要不要发」。
         */
        const kickoff = stageId === 'development' ? firstPrompt : '';
        /*
         * 附件优先用路由 state 的那份（这次创建带过来的），没有才用库里存的快照。
         * 两份都来自同一次创建，不混用 —— 只恢复文字会悄悄丢掉当时挂的文件。
         *
         * 首页可以只挂文件、不写正文（用户的意思是「就用这些」）：
         * 这种首轮正文为空、附件非空，同样要补发 —— 服务端 `prompt` 与 `attachments`
         * 任一项非空就收（见 4.04 消息）。
         */
        const routePaths = attachmentsKey === '' ? [] : attachmentsKey.split('\u0000');
        const storedPaths = storedPathsKey === '' ? [] : storedPathsKey.split('\u0000');
        const kickoffPaths = stageId === 'development' ? (routePaths.length > 0 ? routePaths : storedPaths) : [];
        if ((kickoff !== '' || kickoffPaths.length > 0) && !forceNew) {
          try {
            const latest = await messagesApi.list({ sessionId, limit: 1 });
            if (stale()) return;
            if (latest.items.length === 0) {
              const accepted = live.send({
                text: applyKnowledge(kickoff),
                // 首页挂上的附件跟首轮一起走：这一轮发出去之后，路由 state 就没人再用了
                attachments: kickoffPaths.map((path, index) => ({
                  id: `seed-${index + 1}`,
                  name: path,
                })),
              });
              /*
               * 没发出去（通道刚断 / 附件已被删 / 服务端拒绝）：把原话和附件放回发送框。
               * 这些内容只存在于路由 state，不回填就彻底丢了 —— 用户只能回首页重来。
               */
              void accepted.then((ok) => {
                if (ok || stale()) return;
                notice(replayNotice('firstPromptReplay', lastSendError()));
                pushReplay(kickoff, kickoffPaths);
              });
            }
          } catch {
            // 判空失败不该把整页判成「准备失败」：会话已经打开，内容放回发送框让用户自己发
            if (!stale()) {
              notice(msg('create.chat.firstPromptReplayAuto'));
              pushReplay(kickoff, kickoffPaths);
            }
          }
        }

        /*
         * 「重开并开跑」：只有真的新建了一场会话才发（见 `pendingSendRef`）。
         * 排在首轮补发之后 —— 两者互斥（`forceNew` 时不会走上面那条）。
         */
        const pendingSend = pendingSendRef.current;
        pendingSendRef.current = null;
        if (pendingSend !== null && createdNewSession && !stale()) {
          void live
            .send({
              text: applyKnowledge(pendingSend.text),
              attachments: pendingSend.paths.map((path, index) => ({
                id: `restart-${index + 1}`,
                name: path,
              })),
            })
            .then((ok) => {
              if (ok || stale()) return;
              notice(replayNotice('promptReplay', lastSendError()));
              pushReplay(pendingSend.text, pendingSend.paths);
            });
        }

        setPhase('ready');
      } catch (cause) {
        if (stale()) return;
        setPhase('failed');
        setError(describeBootError(cause, stageId));
      }
    })();
  }, [
    agentId,
    stageId,
    nonce,
    isLive,
    blocked,
    gateReason,
    live.conn,
    closeSession,
    openSession,
    notice,
    lastSendError,
    firstPrompt,
    seededPrompt,
    storedSettled,
    storedPathsKey,
    preferredSessionId,
    attachmentsKey,
    live.send,
    pushReplay,
    workspaceId,
    applyKnowledge,
  ]);

  const retry = useCallback(() => {
    // 重试不是「重开」：清掉上一次可能没消费掉的 forceNew
    forceNewRef.current = false;
    // 通道本身没连上时顺手立刻重连（不等它自己的退避），否则只是重跑一次准备
    if (live.conn !== 'ready') reconnect();
    setNonce((current) => current + 1);
  }, [live.conn, reconnect]);

  const restart = useCallback(
    (prompt?: string, paths: string[] = []) => {
      // 产物没生成完时「重开」只会白建一场空会话（boot 也会拒绝），直接不做
      if (!isLive || blocked) return;
      // 新一场沿用当前选中的模型（用户刚切过的值也在 `live.session` 里）；
      // 老会话的空串按「没有」处理，交给下面的默认链
      carryModelRef.current = live.session?.modelId || undefined;
      pendingSendRef.current =
        prompt === undefined ? null : { text: prompt, paths };
      forceNewRef.current = true;
      setNonce((current) => current + 1);
    },
    [isLive, blocked, live.session?.modelId],
  );

  /** 只把属于当前阶段的回填请求交给发送框（见 `queuedReplay` 的注释） */
  const replay = queuedReplay !== null && queuedReplay.stage === stageId ? queuedReplay : null;

  /** 只把属于当前阶段的待发请求交给下面的 effect（见 `queuedKickoff` 的注释） */
  const kickoff = queuedKickoff !== null && queuedKickoff.stage === stageId ? queuedKickoff : null;
  /**
   * 已经处理过的那一条 kickoff 的 key。
   *
   * 光靠 `setQueuedKickoff(null)` 不够：StrictMode 会把 effect 跑两遍，
   * 两遍读到的是同一份 state，同一轮会被发两次。ref 在第一遍就落地，第二遍直接跳过。
   */
  const consumedKickoffRef = useRef(0);

  /**
   * 把首页递过来的优化请求真正发出去。
   *
   * 时机只有两个：`ready`（会话已打开）后发一次；`failed`（准备失败）时不再发，
   * 把原文还给发送框。其余状态什么都不做，等 phase 变化再进来。
   */
  useEffect(() => {
    if (kickoff === null || consumedKickoffRef.current === kickoff.key) return;

    if (phase === 'failed') {
      consumedKickoffRef.current = kickoff.key;
      setQueuedKickoff(null);
      pushReplay(kickoff.text, kickoff.paths);
      return;
    }
    if (phase !== 'ready') return;

    consumedKickoffRef.current = kickoff.key;
    setQueuedKickoff(null);
    const accepted = live.send({
      text: applyKnowledge(kickoff.text),
      attachments: kickoff.paths.map((path, index) => ({
        id: `kickoff-${kickoff.key}-${index + 1}`,
        name: path,
      })),
    });
    // 没发出去（通道刚断 / 会话正忙 / 服务端拒绝）：原文回落到发送框，不留一句空提示
    void accepted.then((ok) => {
      if (ok) return;
      notice(replayNotice('promptReplay', lastSendError()));
      pushReplay(kickoff.text, kickoff.paths);
    });
  }, [kickoff, phase, live.send, notice, lastSendError, pushReplay, applyKnowledge]);

  /**
   * 发送成功后清掉待回填请求：用户已经处理过它了。
   *
   * 不清的话，切走再切回来时 Composer 会重新挂载，把同一段内容再填一遍 ——
   * 刚发出去的话看起来又回到了发送框。
   */
  const send = useCallback(
    async (payload: ComposerSubmit): Promise<boolean> => {
      const accepted = await live.send({ ...payload, text: applyKnowledge(payload.text) });
      /*
       * 只清掉**当前阶段**的回填请求：它属于这一场的发送框，内容已经被用户处理掉了。
       * 别的阶段的不能被顺手清掉 —— 典型场景是评估落点被锁时留下的那段要求：
       * 用户在生成阶段发一轮正常的开发消息，不该把评估阶段还没用上的话一起丢掉。
       */
      if (accepted && queuedReplay !== null && queuedReplay.stage === stageId) {
        setQueuedReplay(null);
      }
      return accepted;
    },
    [live.send, queuedReplay, stageId, applyKnowledge],
  );

  return {
    messages: live.conversation,
    // **busy 而不是 running**：点击到 run 落库之间那一段也要锁住发送键
    running: live.busy,
    send,
    stop: live.stop,
    hasOlder: live.hasOlder,
    loadingOlder: live.loadingOlder,
    loadOlder: live.loadOlder,
    session: live.session,
    updateModel: live.updateSessionModel,
    respondApproval: live.respondApproval,
    respondAnswers: live.respondAnswers,
    restart,
    replay,
    replayInto: pushReplay,
    kickoffInto,
    link: {
      conn: live.conn,
      phase,
      error,
      notice: live.lastNotice,
      dismissNotice: live.dismissNotice,
      retry,
    },
  };
}

/**
 * 准备会话失败的人话。三种，都指向一个能动手的下一步：
 * 服务没起（判据只有一处，见 `isBackendDown`）、智能体没了（404）、其余照原话透出。
 */
function describeBootError(cause: unknown, stageId: StageId): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) return backendDownHint();
    if (cause.status === 404) {
      return msg('create.chat.agentMissing');
    }
    if (cause.code === 'CONFLICT') {
      return msg('create.chat.stageConflict', {
        message: cause.message,
        stage: stageLabel(stageId),
      });
    }
    return `${cause.message}（HTTP ${cause.status}）`;
  }
  return cause instanceof Error ? cause.message : msg('create.chat.prepareFailed');
}
