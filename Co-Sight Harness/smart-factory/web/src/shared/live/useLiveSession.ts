/**
 * 真会话：REST 拉历史 + WS 收发实时，合成一份可渲染的会话状态。
 *
 * **发消息也走 WS**（`send` 方法），不另开 `POST /messages/send`：既然会话已经订阅在
 * 通道上，发送没有理由走第二条连接；两条路径服务端是同一段逻辑，形状完全相同。
 *
 * 它对外只承诺 `messages` / `running` / `send` / `stop` 这几个形状 ——
 * 创建页的 `useCreationChat` 再包一层「找或建某个阶段的会话」，`Conversation`
 * 组件只认这几个 prop。所以换会话来源时，换的是 Hook、不是组件。
 *
 * 使用点是创建页的三个阶段（`features/agent-create/useCreationChat.ts` 在这里再包一层
 * 「找或建阶段的会话」）。它只管「一条已选定的会话怎么跑」，**不负责挑会话** ——
 * 挑法是各处的策略。
 *
 * ── 三条铁律（写错任何一条都是经典 bug） ──────────────────────────────────────
 *
 * 1. **消息表按 `id` upsert、按 `seq` 排序。**
 *    `message` 事件是「落库快照」不是增量：同一 id 会来好几次（挂起 → 结算），
 *    每次都整行覆盖。排序只能用 `seq` —— `createdAt` 更新时不刷新，用它排会错位。
 *
 * 2. **`chat.delta` 累加，收到落库的 `message` 时整体覆盖。**
 *    delta 是瞬态的（断线即丢），`message` 才是正文真相。写成 `buffer += content.text`
 *    就会**内容翻倍**。一个 run 里可能有多段正文（工具调用后模型再生成一段），
 *    段的划分**靠到达顺序**：每收到一条 `text`/`thinking` 消息就结束当前段。
 *
 * 3. **不能等 `send` 的响应回来再开始收事件。**
 *    服务端「先广播、后 return」，响应帧排在这一轮事件的后面；`send` 响应里的
 *    `run.status` 恒为 `pending`（落库初值），不代表已开跑 —— 真开跑看 `run.started`。
 *
 * ── 进会话的顺序也是固定的（4.06 §7.1） ──────────────────────────────────────
 *   `subscribe` → （服务端补发当前挂起的审批/交互，就是普通 `message` 事件）
 *   → `GET messages/list` → 按 id 合并 → `GET runs/list` + `sessions/detail` 定忙碌态。
 * 反了会丢掉「拉取完成 ↔ 订阅生效」之间那个窗口里的事件，而 WS **不回放**，丢了就找不回。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ConversationMessage, WaitDecision } from '../components/Conversation/types';
import type { ComposerSubmit } from '../components/Composer';
import { ApiError } from '../api/client';
import { resolveDefaultModelId } from '../api/default-model';
import {
  isBackendDown,
  messagesApi,
  runsApi,
  sessionsApi,
  type InstanceStage,
  type Message,
  type Run,
  type SendResult,
  type Session,
} from '../api/sessions';
import { msg, useI18n } from '../../i18n/useI18n';
import { buildWsUrl, LiveClient } from './live-client';
import type { Frame, LiveState } from './live-client';
import type { WsError } from './envelope';
import { toConversationMessages } from './map-message';
import type { LiveSegment } from './map-message';

/** 时间线上的一条。帧、REST 结果、提示全按发生顺序排在一起，排查时不用对两个列表 */
export type LogEntry =
  | { kind: 'frame'; at: number; frame: Frame }
  | { kind: 'rest'; at: number; label: string; ok: boolean; body: unknown }
  | { kind: 'notice'; at: number; text: string };

/** 日志上限：`chat.delta` 来得极密，不封顶会把内存和渲染都拖垮 */
const LOG_LIMIT = 300;

/**
 * 一次 `messages/list` 的页大小。
 *
 * 打开会话拿的是「最近一页」，向上续页也用同一页大小 —— `hasOlder` 的判定
 * （满页即认为上面还有）依赖这两处一致，所以做成一个常量，别再各写各的 50。
 */
const MESSAGE_PAGE = 50;

/**
 * run 状态的前进方向，用来挡「迟到的旧快照」（见 applyRun）。
 * 三个终态并列 —— 它们之间不会再互相迁移。
 */
const RUN_RANK: Record<Run['status'], number> = {
  pending: 0,
  running: 1,
  succeeded: 2,
  failed: 2,
  aborted: 2,
};

const WS_URL = buildWsUrl();

export interface LiveSession {
  /** 连接态，以及连不上/被踢时的人话原因 */
  conn: LiveState;
  connDetail: string | undefined;
  wsUrl: string;

  session: Session | null;
  /** 当前 run（最近一次发起的那条）；`status` 为 pending/running 时算「在跑」 */
  run: Run | null;
  running: boolean;
  /** 界面上「此刻发不出去」：在跑、或 send 请求还在路上（防连点） */
  busy: boolean;

  /** 权威消息表，已按 seq 升序 */
  messages: Message[];
  /** 派生：此刻挂起、等应答的审批与交互 */
  pending: Message[];
  /** 喂给 Conversation 组件的投影 */
  conversation: ConversationMessage[];

  /**
   * 已加载的最早一条之前还有没有消息。
   *
   * 打开会话只拿最近一页，满页即认为上面还有；向上续页时按「本页是否满」更新。
   * 只由这两处判定 —— 重连 / 收尾那种重拉最近一页的请求不碰它，否则会把翻到底的会话
   * 又标成「还有更早」。
   */
  hasOlder: boolean;
  /** 更早一页正在路上（滚动回调据此不重复发请求，界面据此显示加载提示） */
  loadingOlder: boolean;

  log: LogEntry[];
  lastNotice: string | null;
  /** 页面自己报一条提示（会同时进时间线）。用于「随手可发生的输入错误」这类本地校验 */
  notice: (text: string) => void;
  dismissNotice: () => void;

  connect: () => void;
  disconnect: () => void;
  reconnect: () => void;
  /** 强制断线，演练自动重连 */
  forceClose: () => void;

  /** 新建并打开一个会话；成功返回新 sessionId（失败回 null，原因进 lastNotice） */
  /** 新建会话；会先按默认链解析模型（`workspaceId` 用于找该工作区的默认模型） */
  createSession: (agentId: string, stage: InstanceStage, name?: string, workspaceId?: string) => Promise<string | null>;
  /** 换会话：重订阅 + 重拉历史 */
  openSession: (sessionId: string) => Promise<void>;
  closeSession: () => void;

  /**
   * 发一轮。`false` = 没发出去（没会话 / 通道没连上 / 服务端拒绝），
   * 原因进 `lastNotice`；发送框据此把正文与附件还回来。
   */
  send: (payload: ComposerSubmit) => Promise<boolean>;
  /**
   * 最近一次 `send` 没发出去的人话原因（成功 / 还没发过时为 `null`）。
   *
   * 是**读 ref 的普通函数**，不是 state：调用方通常在 `send().then()` 里紧接着读，
   * 那一刻 React 还没重新渲染，读 state 只会拿到上一次的旧值。
   * 用途是把 `send` 已经报过的原因拼进自己那条提示里，别用一句通用文案把它盖掉。
   */
  lastSendError: () => string | null;
  stop: () => void;
  /**
   * 切换当前会话的模型（`sessions/:sessionId/update`）。
   *
   * 成功时把服务端返回的整条 Session 落进状态，选择器的值直接跟着 `session.modelId` 走；
   * false = 没切成功（原因进 lastNotice，`CONFLICT` 表示这一轮还在跑）。
   */
  updateSessionModel: (modelId: string) => Promise<boolean>;
  /** true = 已结算 / 已被别处结算；false = 可恢复失败（提示见 lastNotice） */
  respondApproval: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  respondAnswers: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;

  /** 手发一条原始上行（绕过 UI）：调试用 */
  rawRequest: (method: string, payload: unknown) => Promise<unknown>;
  /** 手拉一次 REST 并记进时间线 */
  refetch: (kind: 'messages' | 'pending' | 'runs' | 'session') => Promise<void>;
  /** 重拉当前会话的「全部」：消息 + run + session（重连后走它） */
  refetchAll: () => Promise<void>;

  /**
   * 向上续一页更早的消息（`beforeSeq = 已加载的最小 seq`）。
   *
   * 没有更早的、已经在加载、或还没开会话时是 no-op。合并进同一张消息表后由 seq 排序，
   * 调用方不必关心插入位置。
   */
  loadOlder: () => void;

  clearLog: () => void;
}

export function useLiveSession(): LiveSession {
  const { locale } = useI18n();
  const [conn, setConn] = useState<LiveState>('idle');
  const [connDetail, setConnDetail] = useState<string | undefined>(undefined);
  const [session, setSession] = useState<Session | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [messagesById, setMessagesById] = useState<Record<string, Message>>({});
  const [live, setLive] = useState<LiveSegment | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [lastNotice, setLastNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  /** 上面还有没有更早的消息；见 `LiveSession.hasOlder` */
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);

  /** 当前会话。放 ref：WS 回调与 REST 回调都要读它，但不该进依赖数组（否则回调每次重建） */
  const sessionIdRef = useRef<string | null>(null);
  /**
   * `hasOlder` 的 ref 副本。滚动回调会在同一帧里连问几次，读 state 拿到的是上一次渲染的值，
   * 这里要的是「这一刻还该不该发请求」。
   */
  const hasOlderRef = useRef(false);
  /** 续页请求在路上的闸，作用同 `sendingRef`：挡住同一 tick 的重复触发 */
  const loadingOlderRef = useRef(false);
  /** 向上续页的游标：已加载消息里最小的 seq（见 `loadOlder`） */
  const oldestSeqRef = useRef<number | null>(null);
  /** 流式缓冲，键是 `${runId}:${messageType}`。见铁律 2 */
  const buffersRef = useRef(new Map<string, string>());
  const clientRef = useRef<LiveClient | null>(null);
  /**
   * 「send 还在路上」的防连点闸。
   *
   * 用 ref 而不是上面那个 `sending` state：state 更新是异步的，同一次渲染里连点两下会双双放行
   * （两份都读到 `sending === false`）。而这里要挡的正是「同一 tick 连点」。
   */
  const sendingRef = useRef(false);
  /**
   * 最近一次 `send` 失败的原因。放 ref 的理由同 `sendingRef`：调用方在
   * `send().then()` 里同步读取，State 那一刻还没更新（见 `lastSendError`）。
   */
  const lastSendErrorRef = useRef<string | null>(null);

  const appendLog = useCallback((entry: LogEntry) => {
    setLog((current) => {
      const next = [...current, entry];
      return next.length > LOG_LIMIT ? next.slice(next.length - LOG_LIMIT) : next;
    });
  }, []);

  /** state 与 ref 一起写：渲染读 state，回调读 ref（理由见 `hasOlderRef`） */
  const markHasOlder = useCallback((next: boolean) => {
    hasOlderRef.current = next;
    setHasOlder(next);
  }, []);

  const notice = useCallback(
    (text: string) => {
      setLastNotice(text);
      appendLog({ kind: 'notice', at: Date.now(), text });
    },
    [appendLog],
  );

  /** 整行覆盖。**不动 `createdAt`、不改顺序** —— 排序在渲染前按 seq 做 */
  const upsert = useCallback((message: Message) => {
    setMessagesById((current) => ({ ...current, [message.id]: message }));
  }, []);

  /**
   * 收一条 run 快照，**迟到的旧快照不许回退**。
   *
   * 为什么需要这个闸：`send` 的响应里那条 run 的 `status` 恒为 `pending`（落库初值），
   * 而服务端是「先广播、后 return」—— 所以 `run.started`（`running`）**可能先到**，
   * 紧接着那条 `pending` 的响应才回来，一盖就把界面按回「还没开跑」。
   * 这不是理论问题：第一次就撞上了，表现是 run 卡在 pending、取消键出不来。
   *
   * 判定按状态前进方向：同一条 run 上，排名更靠后的不收；换了 run id 一律接受（新的一轮）。
   */
  const applyRun = useCallback((next: Run) => {
    setRun((current) => {
      if (current && current.id === next.id && RUN_RANK[next.status] < RUN_RANK[current.status]) {
        return current;
      }
      return next;
    });
  }, []);

  /** REST 重拉回来的「最近一条 run」。没有 run 就是真的没有（换会话后清空走这条） */
  const applyRunOrNull = useCallback(
    (next: Run | null) => {
      if (next === null) setRun(null);
      else applyRun(next);
    },
    [applyRun],
  );

  /*
   * 客户端懒建一次就够：下面的回调**只用 setState 更新器与 ref**，闭包不会过期。
   *
   * 它引用了后面才声明的 `refetchPending` / `refetchAll`。这是安全的：这里只是**定义**闭包，
   * 真正执行要等到挂载后有人调 `getClient()`，那时那几个 const 早就初始化完了。
   * 反过来不能把它们写进依赖数组 —— 数组字面量在 render 期就被求值，那一处才是真的 TDZ。
   */
  const getClient = useCallback((): LiveClient => {
    if (clientRef.current) return clientRef.current;

    const instance = new LiveClient({
      url: WS_URL,
      onState: (state, detail) => {
        setConn(state);
        setConnDetail(detail);
      },
      onFrame: (frame) => appendLog({ kind: 'frame', at: Date.now(), frame }),
      onNotice: (text) => notice(text),
      /*
       * 撤回过期提示（如「1s 后重连」）：只清**还是那一条**的时候。
       * 期间若被别的提示顶掉，说明用户已经该看新的了，别动它。
       * 用 setState 更新器是为了守住「这里的闭包不会过期」那条约定（见下方注释）。
       */
      onNoticeCleared: (text) =>
        setLastNotice((current) => (current === text ? null : current)),
      onEvent: (method, payload) => {
        /*
         * 只认当前打开的那一场会话。
         *
         * 切走之后旧会话的帧仍可能到：`openSession` 撤订阅是异步的，重连补订阅也有一帧
         * 在路上。这些帧不带「属于哪场会话」的判断就会盖到新会话上 —— 正文增量画进新对话、
         * `applyRun` 把旧 run 当成当前的（停止键会去停旧会话）。事件载荷都带 `sessionId`，
         * 在这里一句话挡掉，页面层就不必用「运行中禁止切换」来回避。
         */
        const eventSessionId = (payload as { sessionId?: unknown }).sessionId;
        if (typeof eventSessionId === 'string' && eventSessionId !== sessionIdRef.current) return;

        switch (method) {
          case 'session.status': {
            const { status } = payload as { status: Session['status'] };
            // 只更新状态字段：事件里只有 sessionId 与 status，整条会话另由 REST 拿
            setSession((current) => (current ? { ...current, status } : current));
            break;
          }
          case 'session.named': {
            const { name } = payload as { name: string };
            // 服务端只在会话名为空时补，事件里只有 sessionId 与 name
            setSession((current) => (current ? { ...current, name } : current));
            break;
          }
          case 'run.started':
          case 'run.status': {
            const incoming = payload as Run;
            applyRun(incoming);
            if (method === 'run.status') {
              // 终态：这一轮结束，流式占位也一起收回（真内容已经落库成 message 了）
              setLive(null);
              buffersRef.current.clear();
              // §5.4：收尾后重拉一次消息，把结算结果对齐（挂起会在这期间变成 approved/aborted）
              void refetchPending();
            }
            break;
          }
          case 'message': {
            const message = payload as Message;
            upsert(message);
            // 铁律 2：落库消息到达 = 这一段结束，缓冲清掉；正文以这条消息为准（覆盖，不是追加）
            if ((message.type === 'text' || message.type === 'thinking') && message.runId) {
              buffersRef.current.delete(`${message.runId}:${message.type}`);
              if (message.type === 'text') setLive(null);
            }
            break;
          }
          case 'chat.delta': {
            // chat.delta 只带正文增量；thinking 已改走 chat.thinking.delta
            const { runId, delta } = payload as { runId: string; delta: string };
            const key = `${runId}:text`;
            const text = (buffersRef.current.get(key) ?? '') + delta;
            buffersRef.current.set(key, text);
            setLive({ runId, text });
            break;
          }
          case 'chat.thinking.delta': {
            // thinking 不进对话流（只在时间线上看），所以只缓冲、不推给渲染
            const { runId, delta } = payload as { runId: string; delta: string };
            const key = `${runId}:thinking`;
            buffersRef.current.set(key, (buffersRef.current.get(key) ?? '') + delta);
            break;
          }
          default:
            break;
        }
      },
      onReconnected: () => {
        // §7.2 第 3、4 步：重订阅由客户端自己做完了，重拉是这里的事
        void refetchAll();
      },
    });

    clientRef.current = instance;
    return instance;
  }, [appendLog, notice, upsert, applyRun]);

  // ── REST 取数 ────────────────────────────────────────────────────────────

  /** 把一批消息并进表里。**后到的覆盖先到的**（4.06 §7.3） */
  const mergeMessages = useCallback(
    (items: Message[]) => {
      /*
       * 续页游标在这里**同步**推进，不能只等下面那个 passive effect。
       *
       * 「内容撑不满一屏 / 停在顶部」时的补页链是在 layout 阶段紧接着发下一枪的
       * （见 Conversation 的 useLayoutEffect）；那一刻 passive effect 还没跑，
       * 读到的还是上一页的 seq —— 同一页会被重拉一遍，合并后首条 id 没变，
       * 补页链就断在半路（实测停在 52 步不动）。
       */
      for (const item of items) {
        if (oldestSeqRef.current === null || item.seq < oldestSeqRef.current) {
          oldestSeqRef.current = item.seq;
        }
      }
      setMessagesById((current) => {
        const next = { ...current };
        for (const item of items) next[item.id] = item;
        return next;
      });
    },
    [],
  );

  /**
   * 错误 → 给人看的一句话。
   *
   * 服务端 / 网关的内部码（`VALIDATION` / `INTERNAL` …）**不进提示**：它不是用户能动手的
   * 东西，还会把「引用的模型被删了」这种可修复状态说成「请求不合法」。需要看码的场合
   * （调试日志）传 `withCode`。
   */
  const describeError = useCallback(
    (error: unknown, withCode = false): string => {
      if (error instanceof ApiError) {
        if (isBackendDown(error)) return msg('live.localServerDown', { url: WS_URL });
        if (error.code === 'CONFLICT')
          return msg('live.conflictRunning', { message: error.message });
        return withCode ? `${error.code}：${error.message}` : error.message;
      }
      const ws = error as WsError;
      if (ws && typeof ws.code === 'string') {
        return withCode ? `${ws.code}：${ws.message}` : ws.message;
      }
      return error instanceof Error ? error.message : String(error);
    },
    [],
  );

  const refetchPending = useCallback(async () => {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    try {
      const page = await messagesApi.list({ sessionId, status: 'pending', limit: 200 });
      mergeMessages(page.items);
    } catch (error) {
      notice(msg('live.reloadPendingFailed', { error: describeError(error) }));
    }
  }, [mergeMessages, notice, describeError]);

  const refetchAll = useCallback(async () => {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    try {
      // 先消息、再 run 与会话：拉完这几样，界面就是服务端的真相
      const page = await messagesApi.list({ sessionId, limit: MESSAGE_PAGE });
      mergeMessages(page.items);
      const runs = await runsApi.list(sessionId, 1, 1);
      applyRunOrNull(runs.items[0] ?? null);
      setSession(await sessionsApi.detail(sessionId));
      appendLog({ kind: 'rest', at: Date.now(), label: `重拉会话 ${sessionId}`, ok: true, body: { messages: page.items.length, total: runs.total } });
    } catch (error) {
      notice(msg('live.reloadFailed', { error: describeError(error) }));
      appendLog({ kind: 'rest', at: Date.now(), label: `重拉会话 ${sessionId}`, ok: false, body: describeError(error, true) });
    }
  }, [mergeMessages, appendLog, notice, describeError, applyRunOrNull]);

  const refetch = useCallback(
    async (kind: 'messages' | 'pending' | 'runs' | 'session') => {
      const sessionId = sessionIdRef.current;
      if (!sessionId) {
        notice(msg('live.noSession'));
        return;
      }
      try {
        if (kind === 'messages') {
          const page = await messagesApi.list({ sessionId, limit: MESSAGE_PAGE });
          mergeMessages(page.items);
          appendLog({ kind: 'rest', at: Date.now(), label: `messages/list（最近 ${MESSAGE_PAGE} 条，nextAfterSeq=${String(page.nextAfterSeq)}）`, ok: true, body: page.items });
        } else if (kind === 'pending') {
          const page = await messagesApi.list({ sessionId, status: 'pending', limit: 200 });
          mergeMessages(page.items);
          appendLog({ kind: 'rest', at: Date.now(), label: 'messages/list?status=pending', ok: true, body: page.items });
        } else if (kind === 'runs') {
          const result = await runsApi.list(sessionId, 1, 10);
          applyRunOrNull(result.items[0] ?? null);
          appendLog({ kind: 'rest', at: Date.now(), label: 'runs/list', ok: true, body: result.items });
        } else {
          const detail = await sessionsApi.detail(sessionId);
          setSession(detail);
          appendLog({ kind: 'rest', at: Date.now(), label: 'sessions/detail', ok: true, body: detail });
        }
      } catch (error) {
        notice(describeError(error));
        appendLog({ kind: 'rest', at: Date.now(), label: `REST ${kind}`, ok: false, body: describeError(error, true) });
      }
    },
    [mergeMessages, appendLog, notice, describeError],
  );

  /**
   * 向上续一页更早的消息。
   *
   * 游标是「已加载的最小 seq」（4.04 §4），不是 `nextAfterSeq` —— 那个只负责向下续拉。
   * 不按 `afterSeq` 增量续拉的那条告诫（见 `messagesApi.list`）在这里不成立：
   * `beforeSeq` 取的是**更早**的一段，那些行早已是终态，不会再从「等审批」变成「已结算」。
   */
  const loadOlder = useCallback(() => {
    const sessionId = sessionIdRef.current;
    const beforeSeq = oldestSeqRef.current;
    if (!sessionId || beforeSeq === null || loadingOlderRef.current || !hasOlderRef.current) return;

    loadingOlderRef.current = true;
    setLoadingOlder(true);

    void (async () => {
      try {
        const page = await messagesApi.list({ sessionId, beforeSeq, limit: MESSAGE_PAGE });
        // 换会话期间回来的页不许并进来（同 openSession 的那道 guard）
        if (sessionIdRef.current !== sessionId) return;
        mergeMessages(page.items);
        // 本页不满 = 到头了；满页也允许再翻（下一页可能刚好为空，翻完自然变 false）
        markHasOlder(page.items.length >= MESSAGE_PAGE);
        appendLog({
          kind: 'rest',
          at: Date.now(),
          label: `messages/list（更早 ${page.items.length} 条，beforeSeq=${beforeSeq}）`,
          ok: true,
          body: page.items,
        });
      } catch (error) {
        if (sessionIdRef.current !== sessionId) return;
        notice(describeError(error));
        appendLog({ kind: 'rest', at: Date.now(), label: `messages/list（更早，beforeSeq=${beforeSeq}）`, ok: false, body: describeError(error, true) });
      } finally {
        loadingOlderRef.current = false;
        setLoadingOlder(false);
      }
    })();
  }, [mergeMessages, markHasOlder, appendLog, notice, describeError]);

  // ── 会话动作 ─────────────────────────────────────────────────────────────

  /** 清空本地消息表与流式状态：换会话必须清，否则上一条会话的消息会串进来 */
  const resetMessages = useCallback(() => {
    setMessagesById({});
    setLive(null);
    buffersRef.current.clear();
    // 续页状态属于「上一场会话」：不清的话新会话会带着旧游标/旧结论
    oldestSeqRef.current = null;
    loadingOlderRef.current = false;
    setLoadingOlder(false);
    markHasOlder(false);
  }, [markHasOlder]);

  const openSession = useCallback(
    async (sessionId: string) => {
      const previous = sessionIdRef.current;
      sessionIdRef.current = sessionId;
      resetMessages();
      setRun(null);

      const live = getClient();
      // 一条连接只跟一场会话：旧订阅不撤的话，切走后它的帧还会继续进来（见 onEvent）
      if (previous !== null && previous !== sessionId) void live.unsubscribe(previous);
      if (!live.isReady) notice(msg('live.historyOnly'));

      try {
        // §7.1：**先订阅再拉历史**。反了这个窗口里的事件回不来（WS 不回放）
        if (live.isReady) await live.subscribe(sessionId);
        const page = await messagesApi.list({ sessionId, limit: MESSAGE_PAGE });

        // 换会话期间用户可能已经切走：**先判再合并**。反过来的话，旧会话的历史会
        // 并进新会话的状态里 —— 后面那处 guard 拦得住 setSession，拦不住已经写进去的消息。
        if (sessionIdRef.current !== sessionId) return;
        mergeMessages(page.items);
        // 满页即认为上面还有更早的；不满说明整场会话就这一页
        markHasOlder(page.items.length >= MESSAGE_PAGE);

        const detail = await sessionsApi.detail(sessionId);
        if (sessionIdRef.current !== sessionId) return;

        setSession(detail);
        const runs = await runsApi.list(sessionId, 1, 1);
        if (sessionIdRef.current !== sessionId) return;
        applyRunOrNull(runs.items[0] ?? null);
        appendLog({
          kind: 'rest',
          at: Date.now(),
          label: `打开会话 ${sessionId}`,
          ok: true,
          body: { messages: page.items.length, run: runs.items[0]?.status ?? null },
        });
      } catch (error) {
        // 旧会话的失败也别提示到新会话头上
        if (sessionIdRef.current !== sessionId) return;
        notice(describeError(error));
        appendLog({ kind: 'rest', at: Date.now(), label: `打开会话 ${sessionId}`, ok: false, body: describeError(error, true) });
      }
    },
    [getClient, resetMessages, mergeMessages, appendLog, notice, describeError],
  );

  const createSession = useCallback(
    async (agentId: string, stage: InstanceStage, name?: string, workspaceId?: string): Promise<string | null> => {
      try {
        // 会话是每次新建一行（get-or-create 只发生在实例上）
        // 服务端只收显式 modelId：调试页没有模型选择器，先按默认链解析一个
        const modelId = await resolveDefaultModelId(workspaceId);
        const created = await sessionsApi.create({ agentId, stage, name, modelId });
        appendLog({ kind: 'rest', at: Date.now(), label: `新建会话（${agentId} / ${stage}）`, ok: true, body: created });
        await openSession(created.id);
        return created.id;
      } catch (error) {
        notice(describeError(error));
        appendLog({ kind: 'rest', at: Date.now(), label: `新建会话（${agentId} / ${stage}）`, ok: false, body: describeError(error, true) });
        return null;
      }
    },
    [openSession, appendLog, notice, describeError],
  );

  const closeSession = useCallback(() => {
    const sessionId = sessionIdRef.current;
    sessionIdRef.current = null;
    if (sessionId && clientRef.current?.isReady) void clientRef.current.unsubscribe(sessionId);
    setSession(null);
    setRun(null);
    resetMessages();
  }, [resetMessages]);

  const send = useCallback(
    (payload: ComposerSubmit): Promise<boolean> => {
      const sessionId = sessionIdRef.current;
      // 每次尝试先清掉上一次的原因：调用方读到的必须属于这一次，不能是旧账
      lastSendErrorRef.current = null;
      if (!sessionId) {
        const reason = msg('live.noSession');
        lastSendErrorRef.current = reason;
        notice(reason);
        return Promise.resolve(false);
      }
      const text = payload.text.trim();
      // 与 Composer 的可用条件一致：只有附件、没有正文也发得出去
      if (text === '' && payload.attachments.length === 0) return Promise.resolve(false);
      // 防连点：send 一返回就禁用发送是契约要求（4.06 §4.3），但 UI 上的禁用有延迟，这里硬挡
      if (sendingRef.current) return Promise.resolve(false);

      /*
       * 发消息走实时通道，不另开 HTTP 请求。
       *
       * WS 的 `send` 与 REST 的 `messages/send` 是同一条服务路径（4.04 §5），
       * 但会话已经挂在通道上，发送也走同一条，省掉一条与订阅无关的连接。
       * 通道没连上时排队等 `connection.ready` 不是好体验 —— 直接说清楚，让用户先连。
       */
      const client = getClient();
      if (!client.isReady) {
        const reason = msg('live.sendNotConnected');
        lastSendErrorRef.current = reason;
        notice(reason);
        return Promise.resolve(false);
      }

      // 附件只带路径：端侧形态下没有上传，服务端校验后拼进引擎 prompt，并落进消息的 content.files
      const attachments = payload.attachments.map((file) => ({ path: file.name }));

      sendingRef.current = true;
      setSending(true);
      /*
       * 返回 true / false 而不是 void：Composer 靠它决定要不要把这一轮还回来。
       * 所有失败都在这里收口（含「通道没连上」之外的请求错误），返回的 Promise 不会 reject。
       */
      return client
        .request<SendResult>('send', {
          sessionId,
          prompt: text,
          ...(attachments.length > 0 ? { attachments } : {}),
        })
        .then((result) => {
          // 铁律 3：事件可能已经先到了，这里 upsert 同一 id 不会出问题（幂等）
          // 附件已经写在这条消息的 content.files 里，投影时自然带出来，不必本地另存
          upsert(result.message);
          // 用 applyRun 而不是裸 setRun：这条 run 的 status 恒为 pending，若 run.started 已经先到，
          // 直接盖会把界面按回「还没开跑」（见 applyRun 的说明）
          applyRun(result.run);
          return true;
        })
        .catch((error: unknown) => {
          const reason = describeError(error);
          lastSendErrorRef.current = reason;
          notice(reason);
          return false;
        })
        .finally(() => {
          sendingRef.current = false;
          setSending(false);
        });
    },
    [getClient, upsert, notice, describeError],
  );

  const stop = useCallback(() => {
    const runId = run?.id;
    if (!runId) {
      notice(msg('live.noRunningRun'));
      return;
    }
    // 走 WS 而不是 REST runs/abort：两端都已经连着通道，没有理由为「停」再开一条 REST 路
    void getClient()
      .request('run.abort', { runId })
      .catch((error: unknown) => {
        const ws = error as WsError;
        if (ws?.code === 'CONFLICT') {
          notice(msg('live.runTerminal'));
          void refetch('runs');
          return;
        }
        notice(describeError(error));
      });
  }, [run, getClient, notice, describeError, refetch]);

  /**
   * 切换模型走 REST（`sessions/:sessionId/update`），不走 WS：4.06 的上行只有
   * 发送 / 结算 / 中止这几个实时动作，会话字段的修改是普通写接口。
   */
  const updateSessionModel = useCallback(
    async (modelId: string): Promise<boolean> => {
      const sessionId = sessionIdRef.current;
      if (!sessionId) {
        notice(msg('live.noSession'));
        return false;
      }
      try {
        const updated = await sessionsApi.update(sessionId, { modelId });
        // 期间切走了：旧会话的结果别盖到新会话上
        if (sessionIdRef.current !== sessionId) return false;
        setSession(updated);
        appendLog({
          kind: 'rest',
          at: Date.now(),
          label: `切换会话模型 ${sessionId}`,
          ok: true,
          body: updated,
        });
        return true;
      } catch (error) {
        if (sessionIdRef.current !== sessionId) return false;
        // 409 不是故障：run 启动时就把模型读定了，服务端拒绝中途改值
        notice(
          error instanceof ApiError && error.code === 'CONFLICT'
            ? msg('live.switchModelRunning')
            : describeError(error),
        );
        appendLog({
          kind: 'rest',
          at: Date.now(),
          label: `切换会话模型 ${sessionId}`,
          ok: false,
          body: describeError(error, true),
        });
        return false;
      }
    },
    [appendLog, notice, describeError],
  );

  /**
   * 结算一条挂起消息，返回「还要不要再试」。
   *
   *   true  = 已结算，或已被别处结算（409）—— 卡片应当保持禁用，等同 id 的快照替换它；
   *   false = 传输 / 服务端错误 —— 提示已经通过 notice 弹出，卡片把按钮放开让用户重试。
   *
   * 成功时直接把响应里的 `message` 落进本地表：服务端是「先广播、后 return」，
   * 广播在路上时卡片就能立刻变结算行，不必等事件到达。
   */
  const respond = useCallback(
    async (
      messageId: string,
      payload: { decision?: WaitDecision; answers?: Record<string, string[]> },
    ): Promise<boolean> => {
      try {
        const result = await getClient().request<{ message: Message }>('message.respond', {
          messageId,
          ...payload,
        });
        upsert(result.message);
        return true;
      } catch (error) {
        const ws = error as WsError;
        if (ws?.code === 'CONFLICT') {
          // 不是失败：别的路径已经结算了。重拉消息把那条已结算的整行拿回来；
          // 不能用 status=pending 的重拉 —— 它恰好查不到已经结算的那条。
          notice(msg('live.alreadySettled'));
          void refetch('messages');
          return true;
        }
        notice(describeError(error));
        return false;
      }
    },
    [getClient, upsert, notice, describeError, refetch],
  );

  const respondApproval = useCallback(
    (messageId: string, decision: WaitDecision) => respond(messageId, { decision }),
    [respond],
  );

  const respondAnswers = useCallback(
    (messageId: string, answers: Record<string, string[]>) => respond(messageId, { answers }),
    [respond],
  );

  const rawRequest = useCallback(
    async (method: string, payload: unknown) => {
      try {
        // 成功时不另记一条：↑ 请求与 ↓ 回执两帧本来就都在时间线上，回执的载荷也在那一行里。
        // （早先这里记的是 `rest` 类目，于是发出的 WS 帧被标成「REST」，读起来是错的）
        return await getClient().request(method, payload);
      } catch (error) {
        // 失败要留痕：超时/`id` 丢失这类情况压根没有 ↓ 帧可看
        notice(`${method}：${describeError(error)}`);
        throw error;
      }
    },
    [getClient, notice, describeError],
  );

  const connect = useCallback(() => getClient().connect(), [getClient]);
  const disconnect = useCallback(() => getClient().disconnect(), [getClient]);
  const reconnect = useCallback(() => getClient().reconnect(), [getClient]);
  const forceClose = useCallback(() => getClient().forceClose(), [getClient]);

  // 卸载时收干净：留着一条连接会让服务端空转到心跳超时
  useEffect(() => {
    return () => {
      clientRef.current?.disconnect();
    };
  }, []);

  // ── 派生 ─────────────────────────────────────────────────────────────────

  // 按 seq 排序在这里做，且只在这里做（铁律 1）。快照本来就是「按 (sessionId, seq) 排的一张表」
  const messages = useMemo(
    () => Object.values(messagesById).sort((a, b) => a.seq - b.seq),
    [messagesById],
  );

  /*
   * 向上续页的游标跟着消息表走。放 ref 而不是让 `loadOlder` 依赖 `messages`：
   * 后者在每个 `chat.delta` 都换新数组，滚动回调会跟着重建成百上千次。
   */
  useEffect(() => {
    oldestSeqRef.current = messages[0]?.seq ?? null;
  }, [messages]);

  const pending = useMemo(
    () => messages.filter((message) => message.status === 'pending'),
    [messages],
  );

  const running = run !== null && (run.status === 'pending' || run.status === 'running');

  const conversation = useMemo(
    () =>
      toConversationMessages(messages, {
        locale,
        live,
        // 只有这个 run 里的工具条目允许保持「正在执行」；其余 run 的在途调用已经不可能有结果了
        activeRunId: running ? (run?.id ?? null) : null,
      }),
    [messages, live, running, run, locale],
  );

  const clearLog = useCallback(() => setLog([]), []);
  const dismissNotice = useCallback(() => setLastNotice(null), []);

  const lastSendError = useCallback(() => lastSendErrorRef.current, []);

  return {
    conn,
    connDetail,
    wsUrl: WS_URL,
    session,
    run,
    running,
    busy: running || sending,
    messages,
    pending,
    conversation,
    hasOlder,
    loadingOlder,
    loadOlder,
    log,
    lastNotice,
    notice,
    dismissNotice,
    connect,
    disconnect,
    reconnect,
    forceClose,
    createSession,
    openSession,
    closeSession,
    send,
    lastSendError,
    stop,
    updateSessionModel,
    respondApproval,
    respondAnswers,
    rawRequest,
    refetch,
    refetchAll,
    clearLog,
  };
}
