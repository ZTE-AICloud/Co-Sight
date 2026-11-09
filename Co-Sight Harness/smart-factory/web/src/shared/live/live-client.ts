/**
 * 实时通道客户端：连接、心跳、请求-应答、事件订阅、断线重连。
 *
 * **不出网、不懂 React、不认识会话**：它只知道「帧」。会话的业务语义（哪些消息算挂起、
 * 流式缓冲怎么覆盖）在 `./useLiveSession.ts` —— 调试页与创建页阶段①共用那一份。
 *
 * 契约正本：`server/docs/04-api/4.06-实时通道.md`（连接 §1 / 心跳 §2 / 信封 §3 /
 * 上行 §4 / 下行 §5 / 时序 §6 / 重连 §7 / 客户端必守规则 §9）。
 *
 * 六条纪律，逐条对着文档，写错任何一条都有确定的坏结果：
 *
 *   1. **每个请求带 `id`**（`requestEnvelope` 统一盖章）。服务端对解析失败的帧回
 *      `id:'unknown'`，那条 Promise 永远等不到回执 —— 静默挂死。所以这里给每个请求加了
 *      `requestTimeoutMs` 兜底，超时**报出来**而不是挂住（调试工具尤其需要这个）。
 *   2. **等到 `connection.ready` 才算可用**，在那之前发任何请求都排进 `queue`。
 *   3. **心跳由客户端驱动**：`heartbeatMs` 发一条 `{method:'ping'}`。不起、或间隔 >60s，
 *      服务端 60s 后按「心跳超时」断开（`close code=1000`）。服务端**不主动**发协议层 ping。
 *      §2.1 还提到网络半开：客户端可能迟迟收不到 `close`，所以这里再叠一层「一个心跳周期
 *      内没收到任何帧就自行判死并重连」。
 *   4. **重连后必须重订阅**：订阅随连接消失，服务端不记得你订过什么（`liveHub.unsubscribeAll`）。
 *      所以订阅关系记在 `subscriptions` 里，`connection.ready` 之后自动补上，再回调
 *      `onReconnected` 让上层重拉 REST。
 *   5. **`error` 事件（`SLOW_CONSUMER`）不是提示，是「马上要断了」** —— 按重连流程处理。
 *   6. **原始帧旁路**（`onFrame`）：进出每一帧都捅出去。这是调试页区别于产品页的那件东西。
 */

import { parseEnvelope, requestEnvelope, WsError } from './envelope';
import { apiErrorText } from '../../i18n/translate';
import { currentLocale, msg } from '../../i18n/useI18n';
import type { Envelope } from './envelope';

export type LiveState = 'idle' | 'connecting' | 'ready' | 'closed';

/** 原始帧日志的一项：方向 + 帧本身。`in` 是下行（服务端→客户端），`out` 是上行 */
export interface Frame {
  dir: 'in' | 'out';
  envelope: Envelope;
}

export interface LiveClientOptions {
  /** 缺省由页面按同源推导，见 buildWsUrl */
  url: string;
  /** 心跳间隔。服务端超时是它的 2 倍，所以这个值要明显小于 60s */
  heartbeatMs?: number;
  /** 请求回执的超时兜底：超时即报错而不挂死。0 表示不设（照文档的「不超时」） */
  requestTimeoutMs?: number;
  /** 断线后自动重连（调试页可以关掉它，好观察手动重连） */
  autoReconnect?: boolean;
  /** 重连退避的起始间隔，逐次翻倍、封顶 `reconnectMaxMs` */
  reconnectDelayMs?: number;
  reconnectMaxMs?: number;

  onState?: (state: LiveState, detail?: string) => void;
  onFrame?: (frame: Frame) => void;
  /** 连接级事件（`connection.ready` / `error`）以外的**业务事件**都走这里 */
  onEvent?: (method: string, payload: unknown, frame: Envelope) => void;
  /** 重连成功、且已重订阅之后回调。上层在这里重拉消息与 runs/session 状态 */
  onReconnected?: () => void;
  /** 连接级的人话提示（心跳超时、慢消费者、握手失败…） */
  onNotice?: (text: string) => void;
  /**
   * 撤回一条**已经不再成立**的提示。
   *
   * 提示条是粘性的（不自动消失，见 `ConversationPane` 的注释），所以像
   * 「1s 后重连（第 1 次）」这种描述的是**待发生的事**：连上之后它就过期了，
   * 必须由发起方撤回，否则会一直挂在页面上。参数是当初发出去的那条原文，
   * 上层据此只在「还是这一条」时才清掉（期间被别的提示顶掉就不动）。
   */
  onNoticeCleared?: (text: string) => void;
}

/** 同源推导 WS 地址：开发态经 vite proxy（配了 `ws: true`）打到后端，部署态由反代承担同一职责 */
export function buildWsUrl(path = '/api/smart-factory/v1/ws'): string {
  const override = import.meta.env.VITE_WS_BASE_URL;
  if (override) return `${override.replace(/\/$/, '')}${path}`;
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}${path}`;
}

interface PendingRequest {
  method: string;
  resolve: (payload: unknown) => void;
  reject: (error: WsError) => void;
  timer: number | null;
}

/** 补齐缺省值之后的那份选项：这几个字段在类里是确定有值的 */
interface ResolvedOptions extends LiveClientOptions {
  heartbeatMs: number;
  requestTimeoutMs: number;
  autoReconnect: boolean;
  reconnectDelayMs: number;
  reconnectMaxMs: number;
}

export class LiveClient {
  private readonly options: ResolvedOptions;

  /** 自己记状态，不从 socket.readyState 现推：拆连接后 socket 是 null，推出来的值会跟报出去的打架 */
  private currentState: LiveState = 'idle';

  private socket: WebSocket | null = null;
  /** 主动断开：不触发重连，也不报「异常断开」 */
  private closing = false;
  /** 已建立过的连接数：>0 时的 ready 才算「重连」 */
  private readyCount = 0;

  private heartbeatTimer: number | null = null;
  /**
   * 上一次因排期重连而发出的提示原文（`Xs 后重连（第 N 次）`）。
   * 连上之后这条提示就过期了，由 `onReady` / `disconnect` 撤回；`null` = 没有待撤回的。
   */
  private reconnectNotice: string | null = null;
  /** 上一次收到任何下行帧的时刻，用于半开连接的自行判死（§2.1） */
  private lastInboundAt = 0;

  /** 未拿到回执的请求，按 id 对号。拿到 `connection.ready` 之前发出的排在 queue 里 */
  private readonly requests = new Map<string, PendingRequest>();
  private readonly queue: Envelope[] = [];

  /** 当前应当持有的订阅。重连后照它补订阅 */
  private readonly subscriptions = new Set<string>();

  private reconnectTimer: number | null = null;
  private reconnectAttempts = 0;

  constructor(options: LiveClientOptions) {
    this.options = {
      ...options,
      heartbeatMs: options.heartbeatMs ?? 30_000,
      requestTimeoutMs: options.requestTimeoutMs ?? 15_000,
      autoReconnect: options.autoReconnect ?? true,
      reconnectDelayMs: options.reconnectDelayMs ?? 1_000,
      reconnectMaxMs: options.reconnectMaxMs ?? 15_000,
    };
  }

  get state(): LiveState {
    return this.currentState;
  }

  get isReady(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }

  /** 打开连接。重入是安全的：已连着的连接会被顶掉 */
  connect(): void {
    this.closing = false;
    this.clearReconnect();
    this.teardownSocket();

    this.setState('connecting');
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.options.url);
    } catch (error) {
      // 地址非法（协议写错之类）在构造时就抛，这里要接住，否则是一个未捕获异常
      this.options.onNotice?.(
        msg('live.invalidUrl', {
          error: error instanceof Error ? error.message : String(error),
        }),
      );
      this.setState('closed');
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;
    // 不在这里 flush：文档要求「先等到 connection.ready 再发任何请求」，见 onReady
    socket.onmessage = (event) => this.handleFrame(String(event.data));
    socket.onerror = () => {
      // 浏览器不给 onerror 任何细节（安全限制），只说「握手/传输失败」——
      // 开发态最常见的原因就是 vite 代理没开 `ws: true`，所以把这句写进提示里
      this.options.onNotice?.(msg('live.connectError'));
    };
    socket.onclose = (event) => this.handleClose(event);
  }

  /** 主动断开：不重连、不报错。订阅关系保留（下次 connect 会自动补） */
  disconnect(): void {
    // closing + teardownSocket 已经足够压住重连：teardown 摘掉 onclose，不会走到 scheduleReconnect。
    // 刻意**不**去翻 autoReconnect 开关 —— 那会让「断开一次」变成永久性的设置改动
    this.closing = true;
    this.clearReconnect();
    // 主动断开后不会再有那次重连，排期提示同样过期
    this.clearReconnectNotice();
    this.stopHeartbeat();
    this.rejectAll(new WsError('CLOSED', msg('live.disconnected')));
    this.teardownSocket();
    this.setState('closed', msg('live.closedByUser'));
  }

  /**
   * 强制断线，用于演练重连。
   *
   * 与 `disconnect` 的区别就是**保留自动重连**：这是「模拟网络抖动」，不是「用户关掉了」。
   */
  forceClose(): void {
    this.closing = false;
    // 上一次排期整体作废（提示与定时器）：下面会重新排一次，
    // 留着旧定时器会让 scheduleReconnect 直接早退，页面上的提示就再也对不上号了
    this.clearReconnectNotice();
    this.clearReconnect();
    this.options.onNotice?.(msg('live.forceClosed'));
    this.teardownSocket();
    this.setState('closed');
    this.scheduleReconnect();
  }

  /** 手动重连：把退避清零，立刻连 */
  reconnect(): void {
    this.options.autoReconnect = true;
    this.reconnectAttempts = 0;
    this.connect();
  }

  /**
   * 发一条请求，等它的回执。
   *
   * 失败（错误响应）抛 `WsError`；超时抛 `WsError('TIMEOUT')`；连接不可用抛
   * `WsError('CLOSED')`。**拿 `CONFLICT` 之前请先看 envelope.ts 里那段说明** ——
   * 多数写操作上它不是失败。
   */
  request<T = unknown>(method: string, payload: unknown = {}): Promise<T> {
    const envelope = requestEnvelope(method, payload);
    return new Promise<T>((resolve, reject) => {
      const pending: PendingRequest = {
        method,
        resolve: (value) => resolve(value as T),
        reject,
        timer: null,
      };

      if (this.options.requestTimeoutMs > 0) {
        pending.timer = window.setTimeout(() => {
          this.requests.delete(envelope.id);
          reject(
            new WsError(
              'TIMEOUT',
              msg('live.requestTimeout', {
                method,
                ms: this.options.requestTimeoutMs,
              }),
            ),
          );
        }, this.options.requestTimeoutMs);
      }

      this.requests.set(envelope.id, pending);

      if (this.isReady) this.send(envelope);
      else this.queue.push(envelope);
    });
  }

  /** 订阅一个会话，并把订阅关系记住（重连后自动补） */
  subscribe(sessionId: string): Promise<unknown> {
    this.subscriptions.add(sessionId);
    return this.request('subscribe', { sessionId });
  }

  /** 取消订阅，同时把它从「重连后要补」的集合里摘掉 */
  async unsubscribe(sessionId: string): Promise<void> {
    this.subscriptions.delete(sessionId);
    if (!this.isReady) return;
    await this.request('unsubscribe', { sessionId }).catch(() => undefined);
  }

  /** 当前记住的订阅（供调试面板展示） */
  get subscribedSessions(): string[] {
    return [...this.subscriptions];
  }

  // ── 内部 ────────────────────────────────────────────────────────────────

  private setState(state: LiveState, detail?: string): void {
    this.currentState = state;
    this.options.onState?.(state, detail);
  }

  private send(envelope: Envelope): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
    this.options.onFrame?.({ dir: 'out', envelope });
    this.socket.send(JSON.stringify(envelope));
  }

  private flushQueue(): void {
    const queued = this.queue.splice(0, this.queue.length);
    for (const envelope of queued) this.send(envelope);
  }

  private handleFrame(raw: string): void {
    this.lastInboundAt = Date.now();

    const frame = parseEnvelope(raw);
    if (!frame) {
      // 解析不出来的帧也要留痕：它可能是「代理把 HTML 塞进来了」这类问题的唯一线索
      this.options.onFrame?.({
        dir: 'in',
        envelope: { id: 'unknown', type: 'event', method: 'unparsable', timestamp: Date.now(), payload: raw },
      });
      return;
    }

    this.options.onFrame?.({ dir: 'in', envelope: frame });

    if (frame.type === 'response') {
      this.settle(frame);
      return;
    }
    if (frame.method === 'connection.ready') {
      this.onReady();
      return;
    }
    if (frame.method === 'error') {
      // §5.7 / §8：这是「马上要断」，不是普通提示
      const payload = frame.payload as { code?: string; message?: string } | undefined;
      this.options.onNotice?.(
        msg('live.connectionError', {
          code: payload?.code ?? '',
          message: payload?.message ?? '',
        }),
      );
      if (payload?.code === 'SLOW_CONSUMER') {
        this.teardownSocket();
        this.setState('closed');
        this.scheduleReconnect();
      }
      return;
    }

    this.options.onEvent?.(frame.method, frame.payload, frame);
  }

  private settle(frame: Envelope): void {
    const pending = this.requests.get(frame.id);
    if (!pending) {
      // 没有对号入座的请求：多半是错号响应（重复 id）。日志里已经能看到这一帧
      this.options.onNotice?.(
        msg('live.unclaimedResponse', { method: frame.method, id: frame.id }),
      );
      return;
    }
    this.requests.delete(frame.id);
    if (pending.timer !== null) window.clearTimeout(pending.timer);

    if (frame.error) {
      // 与 HTTP 侧同一条规则（见 apiErrorText）：精确登记的键才本地化，
      // 未登记的具体原因用服务端原话，别被分组 default 吞成「请求格式不正确」。
      pending.reject(
        new WsError(
          frame.error.code,
          apiErrorText(
            currentLocale(),
            frame.error.messageKey,
            frame.error.message,
            frame.error.params ?? undefined,
          ),
          frame.error.messageKey ?? null,
        ),
      );
    } else {
      pending.resolve(frame.payload);
    }
  }

  private onReady(): void {
    this.readyCount += 1;
    const isReconnect = this.readyCount > 1;
    this.setState(
      'ready',
      isReconnect ? msg('live.reconnectCount', { count: this.readyCount }) : undefined,
    );
    this.reconnectAttempts = 0;
    // 连上了：「Xs 后重连」已经兑现，那条提示必须撤回（否则会一直挂着）
    this.clearReconnectNotice();
    this.startHeartbeat();
    // §2/§3：现在才算连接可用，之前排队的请求从这里开始发
    this.flushQueue();

    if (!isReconnect) return;

    // §7.2：重连 = 新连接 + 重订阅 + 重拉。重拉是上层的事，这里只负责重订阅，然后回调
    void this.resubscribeAll().then(() => this.options.onReconnected?.());
  }

  private async resubscribeAll(): Promise<void> {
    for (const sessionId of this.subscriptions) {
      try {
        await this.request('subscribe', { sessionId });
      } catch (error) {
        this.options.onNotice?.(
          msg('live.resubscribeFailed', {
            sessionId,
            error: error instanceof Error ? error.message : String(error),
          }),
        );
      }
    }
  }

  private handleClose(event: CloseEvent): void {
    this.stopHeartbeat();
    this.rejectAll(new WsError('CLOSED', msg('live.disconnected')));
    this.socket = null;

    if (this.closing) {
      this.setState('closed', msg('live.closedByUser'));
      return;
    }

    // 服务端两种主动断开：心跳超时（1000 + reason）与慢消费者（无 code，且先发过 error 事件）
    const detail =
      event.reason ||
      (event.code === 1000 ? msg('live.serverClosed') : msg('live.closeCode', { code: event.code }));
    this.setState('closed', detail);
    if (event.reason === '心跳超时') this.options.onNotice?.(msg('live.heartbeatTimeout'));

    this.scheduleReconnect();
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.lastInboundAt = Date.now();
    this.heartbeatTimer = window.setInterval(() => {
      // §2.1：网络半开时可能迟迟收不到 close，所以自己判死
      if (Date.now() - this.lastInboundAt > this.options.heartbeatMs * 2) {
        this.options.onNotice?.(msg('live.halfOpen'));
        this.teardownSocket();
        this.setState('closed');
        this.scheduleReconnect();
        return;
      }
      void this.request('ping', {}).catch(() => undefined);
    }, this.options.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (!this.options.autoReconnect || this.reconnectTimer !== null) return;
    const delay = Math.min(this.options.reconnectDelayMs * 2 ** this.reconnectAttempts, this.options.reconnectMaxMs);
    this.reconnectAttempts += 1;
    const text = msg('live.reconnectIn', {
      seconds: Math.round(delay / 1000),
      count: this.reconnectAttempts,
    });
    this.reconnectNotice = text;
    this.options.onNotice?.(text);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** 撤回「Xs 后重连」这条提示：连上了，或用户主动断开了，它都不再成立 */
  private clearReconnectNotice(): void {
    const text = this.reconnectNotice;
    if (text === null) return;
    this.reconnectNotice = null;
    this.options.onNoticeCleared?.(text);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /** 摘掉 socket 且**不**触发重连逻辑（由调用方决定要不要重连） */
  private teardownSocket(): void {
    this.stopHeartbeat();
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    // 先摘回调再关：否则 onclose 会把「我们自己关的」当成断线，叠一轮重连
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try {
      socket.close();
    } catch {
      /* 已经关了 */
    }
  }

  private rejectAll(error: WsError): void {
    for (const [id, pending] of this.requests) {
      if (pending.timer !== null) window.clearTimeout(pending.timer);
      pending.reject(error);
      this.requests.delete(id);
    }
    this.queue.length = 0;
  }
}
