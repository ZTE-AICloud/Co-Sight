/**
 * 工坊的会话来源（`docs/capability-routing.md` §3）。
 *
 * 与创建页的 `useCreationChat` 差别只有一条：**工坊不在进页面时建会话**。
 *
 *  - 没有 `?session=`、也没有从首页带过来的正文 → 只连通道、什么都不建；
 *    用户第一次点发送时才 `POST sessions/create { cwd }`（§3.2）。这样历史列表里
 *    不会出现一串空场，会话名也能按首条正文取。
 *  - 从首页按下发送跳过来（带 `location.state`）→ 这是「第一次发送」，
 *    连上并拿到 cwd 之后自动建会话、发出去。首页负责「用户已经点了发送」，
 *    工坊不能把那句话再塞回输入框让他点第二次。**正文可以是空的**：优化场只选了
 *    技能、没写要求时，首条就是命令 + 技能路径，照样发。
 *  - 带 `?session=` → 打开那一场；`instance.cwd` 对不上就按无效参数处理
 *    （不猜、不跨目录打开）。
 *
 * 首条消息的拼装在 `compose-prompt.ts`；这里只决定「什么时候拼」：只有**新建**的
 * 那一场才拼，打开的历史会话原样发送。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { msg } from '../../i18n/useI18n';
import { ApiError } from '../../shared/api/client';
import { resolveDefaultModelId } from '../../shared/api/default-model';
import { sessionsApi } from '../../shared/api/sessions';
import type { Session } from '../../shared/api/sessions';
import type { Skill } from '../../shared/api/skills';
import { modelBlockReason, sessionModelBlockReason, useModels } from '../../shared/api/useModels';
import type { ComposerModel, ComposerReplay, ComposerSubmit } from '../../shared/components/Composer';
import type {
  ConversationMessage,
  WaitDecision,
} from '../../shared/components/Conversation/types';
import type { LiveState } from '../../shared/live/live-client';
import { useLiveSession } from '../../shared/live/useLiveSession';
import { composeFirstMessage, sessionNameFor } from './compose-prompt';
import type { WorkshopMode } from './compose-prompt';

/** 会话准备到哪一步。`connecting` 与 `preparing` 期间发送键不可用，但正文仍可编辑 */
export type WorkshopPhase = 'connecting' | 'preparing' | 'ready' | 'failed';

/** 首页按下发送时带过来的首轮内容（`location.state`） */
export interface WorkshopSeed {
  /** 用户写的正文（可能为空串：只挂了附件 / 优化场只点了技能） */
  firstPrompt: string;
  /** 附件绝对路径 */
  attachments: string[];
}

export interface UseWorkshopSessionInput {
  /** 工坊会话的 cwd（`GET /skills` 的 `cwd`）；null = 还没拿到 */
  cwd: string | null;
  /** 首页带过来的首轮内容；null = 用户自己在这个页面开始 */
  seed: WorkshopSeed | null;
  /** 地址里的 `?session=`；null = 新会话 */
  preferredSessionId: string | null;
  /** 当前入口是创建还是优化（只影响首条消息与会话名） */
  mode: WorkshopMode;
  /** 优化目标；创建场为 null */
  target: Skill | null;
  /** 解析默认模型用的工作区 id */
  workspaceId: string | undefined;
  /**
   * 工作区是否已经落定（加载中 → false）。首页带首轮过来时要等它：
   * 早判会把「正在读工作区」当成「不能开始」，把用户那句话退回发送框。
   */
  startSettled?: boolean;
  /** 工作区层面的阻塞原因（没有生效工作区 / 读取失败）；非空时首页首轮不自动发 */
  startBlockedReason?: string | null;
  /** 新建会话成功（页面据此把 `?session=` 写进地址） */
  onSessionOpened: (sessionId: string) => void;
  /** 地址里的 `?session=` 无效（页面据此把它删掉） */
  onSessionInvalid: () => void;
}

export interface WorkshopChat {
  messages: ConversationMessage[];
  running: boolean;
  /** 发一轮；false = 没出去，正文与附件由 Composer 还回输入框（首页首轮则由 `replay` 还） */
  send: (payload: ComposerSubmit) => Promise<boolean>;
  stop: () => void;
  hasOlder: boolean;
  loadingOlder: boolean;
  loadOlder: () => void;
  respondApproval: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  respondAnswers: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;

  session: Session | null;
  phase: WorkshopPhase;
  /** 准备失败的人话原因（只有 `phase === 'failed'` 时有值） */
  error: string | null;
  conn: LiveState;
  connDetail: string | undefined;
  notice: string | null;
  dismissNotice: () => void;
  /** 准备失败的出口：重来一次（通道没连上时顺带立刻重连） */
  retry: () => void;
  /** 右下角模型选择器；会话存在时值就是会话自己的 `modelId` */
  model: ComposerModel;
  /** 模型清单不可用时挡住发送的人话原因（加载中 / 拉失败 / 空都挡） */
  modelBlockedReason: string | null;
  /** 首页首轮没发出去时，把原话放回发送框的一次性请求 */
  replay: ComposerReplay | null;

  /** 打开一场历史会话；cwd 对不上或请求失败返回 false（原因进 notice） */
  open: (sessionId: string) => Promise<boolean>;
  /** 「新会话」/ 当前会话被删：放下它，下一次发送再建 */
  reset: () => void;
}

export function useWorkshopSession(input: UseWorkshopSessionInput): WorkshopChat {
  const {
    cwd,
    seed,
    preferredSessionId,
    mode,
    target,
    workspaceId,
    startSettled = true,
    startBlockedReason = null,
    onSessionOpened,
    onSessionInvalid,
  } = input;

  const live = useLiveSession();
  const { models, loading: modelsLoading, error: modelsError } = useModels();

  /** 首场会话建立之前先解析一个默认模型：服务端只收显式 `modelId`，不猜 */
  const [draftModelId, setDraftModelId] = useState<string | null>(null);
  const [phase, setPhase] = useState<WorkshopPhase>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ComposerReplay | null>(null);
  const replayKeyRef = useRef(0);
  const [nonce, setNonce] = useState(0);
  /** boot 只跑一次（StrictMode 会把 effect 跑两遍，而「建会话」不幂等） */
  const bootedRef = useRef(false);

  const pushReplay = useCallback((text: string, paths: string[]) => {
    replayKeyRef.current += 1;
    setReplay({ key: replayKeyRef.current, text, paths });
  }, []);

  const { connect, disconnect, openSession, closeSession, send: liveSend } = live;

  /**
   * 连 / 断必须成对：`useLiveSession` 的卸装清理里有 `disconnect()`，只连不断的话
   * StrictMode 的假卸装会把连接掐掉，第二次挂载永远回不来（真踩过）。
   */
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  /** 没有会话时解析一次默认模型，供选择器显示；失败就交给 modelBlockReason 挡发送 */
  useEffect(() => {
    if (draftModelId !== null || live.session !== null) return;
    let cancelled = false;
    void resolveDefaultModelId(workspaceId)
      .then((id) => {
        if (!cancelled) setDraftModelId(id);
      })
      .catch(() => {
        // 原因已经由 models 的 error / 发送键的阻止文案表达，这里不重复报
      });
    return () => {
      cancelled = true;
    };
  }, [draftModelId, live.session, workspaceId]);

  /** 打开一场会话，并校验它确实属于这个目录 */
  const open = useCallback(
    async (sessionId: string): Promise<boolean> => {
      if (cwd === null) return false;
      try {
        const detail = await sessionsApi.detail(sessionId);
        if (detail.instance.cwd !== cwd) {
          live.notice(msg('workshop.notice.sessionOtherCwd'));
          return false;
        }
        await openSession(sessionId);
        return true;
      } catch (cause) {
        live.notice(describeError(cause));
        return false;
      }
    },
    [cwd, live, openSession],
  );

  /**
   * 新建一场会话并把这一轮发出去。
   *
   * `restore` 只在「首页首轮」时为非空：那种发送的正文来自 `location.state`，
   * Composer 里本来就没有内容，失败后得由页面放回去（普通发送由 Composer 自己还）。
   */
  const createAndSend = useCallback(
    async (
      text: string,
      attachments: ComposerSubmit['attachments'],
      /** 会话名取的是**用户写的正文**，不是拼好命令的整条 */
      nameBody: string,
      restore: { body: string; paths: string[] } | null,
    ): Promise<boolean> => {
      if (cwd === null) return false;
      setPhase('preparing');
      try {
        const modelId = draftModelId ?? (await resolveDefaultModelId(workspaceId));
        const created = await sessionsApi.create({
          cwd,
          modelId,
          name: sessionNameFor(mode, nameBody, target),
        });
        await openSession(created.id);
        onSessionOpened(created.id);

        const accepted = await liveSend({ text, attachments });
        setPhase('ready');
        if (!accepted && restore !== null) pushReplay(restore.body, restore.paths);
        return accepted;
      } catch (cause) {
        setPhase('ready');
        live.notice(describeError(cause));
        if (restore !== null) pushReplay(restore.body, restore.paths);
        return false;
      }
    },
    [cwd, draftModelId, live, liveSend, mode, onSessionOpened, openSession, pushReplay, target, workspaceId],
  );

  const send = useCallback(
    async (payload: ComposerSubmit): Promise<boolean> => {
      if (cwd === null) {
        live.notice(msg('workshop.blocked.skillsLoading'));
        return false;
      }

      /*
       * 首条还没落地：命令与目标由页面拼（§3.3）；之后的轮次原样发送。
       *
       * 判据不能只看「还没有会话」：`createAndSend` 先建会话、再发送，发送失败时
       * 会话已经在了，而 Composer 交回来的仍是不带前缀的原文。下一次发送若直接
       * `liveSend(payload)`，创建场丢掉 skill-foundry 命令、优化场丢掉技能路径
       * （成了一条普通聊天，甚至改错对象）。刷新后用 `?session=` 恢复一场空会话同理。
       *
       * 「首条已落地」以服务端会话状态为准：状态离开 `not_started`、或本地已有消息，
       * 就说明至少一条消息被接受了，之后不再拼前缀。
       */
      const firstMessagePending =
        live.session === null ||
        (live.session.status === 'not_started' && live.messages.length === 0);

      if (firstMessagePending) {
        const text = composeFirstMessage(mode, payload.text, target);
        // 还没有会话：建一场再发；已经有会话（上次发送失败）：直接重发，不建第二场
        if (live.session === null) {
          return createAndSend(text, payload.attachments, payload.text, null);
        }
        return liveSend({ text, attachments: payload.attachments });
      }

      return liveSend(payload);
    },
    [createAndSend, cwd, live, liveSend, mode, target],
  );

  const reset = useCallback(() => {
    closeSession();
    setReplay(null);
    setPhase('ready');
  }, [closeSession]);

  const retry = useCallback(() => {
    bootedRef.current = false;
    setError(null);
    setPhase('connecting');
    if (live.conn !== 'ready') live.reconnect();
    setNonce((value) => value + 1);
  }, [live]);

  /*
   * 上电序列：等通道 ready + 拿到 cwd，然后按地址 / 首页载荷决定开哪一场。
   * 依赖只放原始值；`seed` 等是这一页 mount 时定下的，不需要跟着对象引用重跑。
   */
  useEffect(() => {
    if (cwd === null) {
      if (phase !== 'preparing') setPhase('connecting');
      return;
    }
    if (live.conn !== 'ready') {
      if (phase !== 'connecting') setPhase('connecting');
      return;
    }
    // 首页首轮要等工作区落定再判「能不能开始」；加载中不消费掉这句话
    if (seed !== null && !startSettled) return;
    if (bootedRef.current) return;
    bootedRef.current = true;

    void (async () => {
      setPhase('preparing');
      setError(null);
      try {
        let restored = false;
        if (preferredSessionId !== null) {
          restored = await open(preferredSessionId);
          if (!restored) onSessionInvalid();
        }

        /*
         * 首页已经把「发送」这个动作做完了：建会话 + 发首轮。
         * 带 ?session= 恢复进来时不补发 —— 那是用户回来继续聊，不是一次新的发送。
         */
        if (!restored && seed !== null) {
          /*
           * 首页「技能优化」只选技能、不写要求也是一次完整的发送：命令与技能路径
           * 都由 `composeFirstMessage` 拼，正文为空照样发得出去。创建场必须有正文或
           * 附件才算发送；优化目标已经失效时也没什么可发（页面会提示「技能不存在」），
           * 用户写的正文原样放回发送框，别静默丢掉。
           */
          const hasBody = seed.firstPrompt !== '' || seed.attachments.length > 0;
          const sendable = mode === 'optimize' ? target !== null : hasBody;
          if (!sendable) {
            if (hasBody) pushReplay(seed.firstPrompt, seed.attachments);
          } else if (startBlockedReason !== null) {
            // 首页已经点过发送，但这一页现在开不了会话：把话放回框里，并说清为什么
            live.notice(startBlockedReason);
            pushReplay(seed.firstPrompt, seed.attachments);
          } else {
            const text = composeFirstMessage(mode, seed.firstPrompt, target);
            const attachments = seed.attachments.map((path, index) => ({
              id: `seed-${index + 1}`,
              name: path,
            }));
            await createAndSend(text, attachments, seed.firstPrompt, {
              body: seed.firstPrompt,
              paths: seed.attachments,
            });
          }
        }

        setPhase('ready');
      } catch (cause) {
        setError(describeError(cause));
        setPhase('failed');
      }
    })();
    // `phase` 故意不进依赖：它只用来避免同一态重复 set
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cwd, live.conn, nonce, startSettled]);

  const model = useMemo<ComposerModel>(
    () => ({
      value: live.session?.modelId ?? draftModelId ?? '',
      options: models.map((item) => ({ value: item.id, label: item.label })),
      onChange: (value) => {
        if (live.session !== null) {
          void live.updateSessionModel(value);
          return;
        }
        // 会话还没建：先把选择记下来，建会话时用它
        setDraftModelId(value);
      },
      loading: modelsLoading || (live.session === null && draftModelId === null),
      error: modelsError,
    }),
    [draftModelId, live, models, modelsError, modelsLoading],
  );

  return {
    messages: live.conversation,
    running: live.running,
    send,
    stop: live.stop,
    hasOlder: live.hasOlder,
    loadingOlder: live.loadingOlder,
    loadOlder: live.loadOlder,
    respondApproval: live.respondApproval,
    respondAnswers: live.respondAnswers,

    session: live.session,
    phase,
    error,
    conn: live.conn,
    connDetail: live.connDetail,
    notice: live.lastNotice,
    dismissNotice: live.dismissNotice,
    retry,
    model,
    modelBlockedReason:
      modelBlockReason({ models, loading: modelsLoading, error: modelsError }, msg('workshop.action.start')) ??
      sessionModelBlockReason({ models, loading: modelsLoading, error: modelsError }, live.session?.modelId),
    replay,

    open,
    reset,
  };
}

/** 与创建页 `describeError` 同口径：服务端已经把人话放在 `message` 里了 */
function describeError(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message;
  if (cause instanceof Error) return cause.message;
  return msg('common.unknownError');
}
