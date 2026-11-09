// SPDX-License-Identifier: Apache-2.0
/**
 * @file chat-socket.ts
 * @description Agent Runtime WebSocket 连接封装
 */

import { AGENT_RUNTIME_WS_URL } from "../config/api-config";
import type { AttachmentWire } from "../attachments/types";
import { wsLogFrame, wsLogLifecycle } from "./ws-debug";

// WebSocket 消息基础结构
interface BaseMessage {
  id: string;
  type: "request" | "response" | "event";
  method: string;
  timestamp: number;
  payload?: Record<string, unknown>;
  error?: {
    /** 服务端错误码：VALIDATION / NOT_FOUND / CONFLICT / INTERNAL 等字符串。 */
    code: string;
    message: string;
    /** 供前端按当前语言翻译的键；调用方据此区分具体冲突（如 error.conflict.active_run）。 */
    messageKey?: string;
    params?: Record<string, string | number> | null;
    details?: unknown;
  } | null;
}

/** 服务端错误响应转成的 Error：保留 code / messageKey / params，调用方可按 key 分支处理。 */
export class ChatSocketError extends Error {
  readonly code: string;
  readonly messageKey?: string;
  readonly params?: Record<string, string | number> | null;

  constructor(error: NonNullable<BaseMessage["error"]>) {
    super(error.message);
    this.name = "ChatSocketError";
    this.code = error.code;
    this.messageKey = error.messageKey;
    this.params = error.params;
  }
}

// 请求消息
export interface RequestMessage extends BaseMessage {
  type: "request";
}

// 响应消息
export interface ResponseMessage extends BaseMessage {
  type: "response";
}

// 事件消息
export interface EventMessage extends BaseMessage {
  type: "event";
}

// 所有消息类型
export type SocketMessage = RequestMessage | ResponseMessage | EventMessage;

// 事件处理器类型
type EventHandler = (message: EventMessage) => void;

// 连接状态
export type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

/** 心跳间隔；服务端对 ping 回 pong，半开连接靠它发现。 */
const HEARTBEAT_INTERVAL_MS = 30_000;
/** 连续多少个心跳周期没有任何下行帧就判定连接已死。 */
const HEARTBEAT_MISS_LIMIT = 3;
/** 看门狗主动收线时使用的业务关闭码。 */
const PONG_TIMEOUT_CLOSE_CODE = 4001;

/**
 * 生成唯一 ID
 */
function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Agent Runtime WebSocket 客户端
 */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  /** 正在建立的连接：并发 connect() 复用同一个 Promise，避免开两条 socket。 */
  private connectPromise: Promise<void> | null = null;
  /** 断线后的重连定时器。 */
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttemptCount = 0;
  /** 自上个心跳周期以来是否收到过任何下行帧（pong / chat.delta / message…）。 */
  private framesSinceTick = false;
  /** 连续多少个心跳周期没有收到任何下行帧。 */
  private missedHeartbeats = 0;
  /**
   * 是否应保持连接：connect() 置 true，disconnect() 置 false。
   *
   * 只有它为 true 时 onclose 才会安排重连 —— 用户主动断开（切页/卸载）不能再拉起。
   */
  private shouldReconnect = false;
  /** 浏览器侧的重连触发器（online / focus / visibilitychange），显式断开时卸载。 */
  private removeReconnectTriggers: (() => void) | null = null;
  private pendingRequests: Map<
    string,
    {
      resolve: (value: ResponseMessage) => void;
      reject: (error: Error) => void;
    }
  > = new Map();
  private eventHandlers: Map<string, EventHandler[]> = new Map();
  private _state: ConnectionState = "disconnected";
  private _sessionId: string | null = null;
  private _instanceId: string | null = null;
  private _runId: string | null = null;

  // 公共状态（只读）
  get state(): ConnectionState {
    return this._state;
  }

  /** 已连续安排的重连次数（连接成功后归零）；上层据此展示"重连中/无法连接"。 */
  get reconnectAttempts(): number {
    return this.reconnectAttemptCount;
  }

  get sessionId(): string | null {
    return this._sessionId;
  }

  set sessionId(value: string | null) {
    this._sessionId = value;
  }

  get instanceId(): string | null {
    return this._instanceId;
  }

  get runId(): string | null {
    return this._runId;
  }

  set runId(value: string | null) {
    this._runId = value;
  }

  /**
   * 建立 WebSocket 连接。
   *
   * 幂等：已连接直接返回；正在连接复用同一个 Promise（并发调用不会开出两条 socket）。
   * 连接期间及断线后由本类自行保活/重连，直到显式 `disconnect()`。
   */
  connect(): Promise<void> {
    this.shouldReconnect = true;
    this.installReconnectTriggers();

    if (this.ws?.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }

    this.connectPromise = this.openSocket().finally(() => {
      this.connectPromise = null;
    });
    return this.connectPromise;
  }

  /** 真正建立一条新连接。旧连接（CLOSING / CLOSED）只解绑丢弃，不影响会话标识。 */
  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws) {
        this.detachSocket(this.ws);
        this.ws = null;
      }

      this._state = "connecting";
      this.emitStateChange();

      // 构造 WebSocket URL
      //   - 绝对地址（单机模式：浏览器直连 agent-runtime）→ 直接用
      //   - 相对路径（容器模式：走页面 origin，由网关分流）→ 拼页面 origin
      // 使用 userId 参数进行身份注入（文档要求，鉴权暂缓阶段用 dev 身份）
      let wsUrl: string;
      if (/^wss?:\/\//.test(AGENT_RUNTIME_WS_URL)) {
        wsUrl = `${AGENT_RUNTIME_WS_URL}?userId=dev`;
      } else {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        wsUrl = `${protocol}//${window.location.host}${AGENT_RUNTIME_WS_URL}?userId=dev`;
      }

      let socket: WebSocket;
      try {
        socket = new WebSocket(wsUrl);
      } catch (error) {
        this._state = "error";
        this.emitStateChange();
        reject(new Error(`Failed to create WebSocket: ${error}`));
        // URL 本身有问题时先等一下再试，避免瞬时死循环
        this.scheduleReconnect();
        return;
      }

      this.ws = socket;

      socket.onopen = () => {
        // 旧 socket 的迟到事件不能覆盖新连接的状态
        if (this.ws !== socket) return;
        wsLogLifecycle("connected", wsUrl);
        this._state = "connected";
        this.reconnectAttemptCount = 0;
        this.emitStateChange();
        this.startHeartbeat();
        resolve();
      };

      socket.onmessage = (event) => {
        if (this.ws !== socket) return;
        // 任何下行帧（pong / chat.delta / message…）都证明连接还活着
        this.framesSinceTick = true;
        try {
          const message: SocketMessage = JSON.parse(event.data);
          // 原始帧长度在解析前顺手取,避免为了打印再 stringify 一次
          this.handleMessage(message, typeof event.data === "string" ? event.data.length : 0);
        } catch (error) {
          console.error("[ChatSocket] Failed to parse message:", error);
        }
      };

      socket.onerror = (error) => {
        if (this.ws !== socket) return;
        console.error("[ChatSocket] Error:", error);
        this._state = "error";
        this.emitStateChange();
        reject(new Error("WebSocket error"));
      };

      socket.onclose = (event) => {
        if (this.ws !== socket) return;
        wsLogLifecycle(
          "disconnected",
          `code=${event.code}${event.reason ? ` ${event.reason}` : ""}`,
        );
        this.ws = null;
        // 握手阶段就断开时浏览器未必先触发 onerror：这里必须显式结算 connect()，
        // 否则 connectPromise 永远悬着，后续重连会一直复用它、开不出新连接。
        reject(new Error(`WebSocket closed before open: ${event.code}`));
        this._state = "disconnected";
        this.emitStateChange();
        this.stopHeartbeat();
        this.rejectAllPending("Connection closed");
        // 服务端空闲超时（1000 心跳超时）、网络抖动、后端重启都会走到这里：
        // 只要用户没主动断开，就自动重连；重连成功由上层重新订阅并补历史。
        this.scheduleReconnect();
      };
    });
  }

  /**
   * 断开连接（用户主动）。
   *
   * 与 onclose 的区别：这里置 `shouldReconnect = false` 并卸载浏览器触发器，
   * 不会再被自动拉起。
   */
  disconnect(): void {
    this.shouldReconnect = false;
    this.clearReconnectTimer();
    this.removeReconnectTriggers?.();
    this.removeReconnectTriggers = null;

    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }

    if (this.ws) {
      this.detachSocket(this.ws);
      this.ws.close();
      this.ws = null;
    }

    this._state = "disconnected";
    this._sessionId = null;
    this._instanceId = null;
    this._runId = null;
    this.emitStateChange();
    this.rejectAllPending("Disconnected");
  }

  /** 解绑一条 socket 的全部处理器，避免旧连接在关闭后再发出状态事件。 */
  private detachSocket(socket: WebSocket): void {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /** 指数退避重连（0.5s → 1s → 2s → 5s 封顶）。 */
  private scheduleReconnect(): void {
    if (!this.shouldReconnect || this.reconnectTimer !== null) return;
    const delay = Math.min(500 * 2 ** this.reconnectAttemptCount, 5000);
    this.reconnectAttemptCount += 1;
    // 每次安排重连都广播一次（state 仍是 disconnected）：上层据此显示"第 N 次"
    // 并判断是否已到"无法连接"的降级阈值。
    this.emitStateChange();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.shouldReconnect) return;
      void this.connect().catch(() => {
        // onerror/onclose 已安排下一次；这里只吞掉 Promise，避免未处理拒绝
      });
    }, delay);
  }

  /**
   * 浏览器恢复前台 / 网络恢复时立即重连（不走退避）。
   *
   * 后台标签页的定时器会被节流，靠退避定时器可能等很久；这三个事件是可靠的
   * "用户回来了"信号。连接仍然活着时顺手补一次 ping，刷新服务端的 lastSeen。
   */
  private reconnectNow(): void {
    if (!this.shouldReconnect) return;
    const ws = this.ws;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      this.pingNow();
      return;
    }
    this.clearReconnectTimer();
    // 不清零重连次数：切标签页 / 网络恢复不代表服务可用，否则离线计数永远到不了阈值。
    void this.connect().catch(() => {
      // 失败由 onclose 继续退避
    });
  }

  /**
   * 用户手动重连：跳过退避等待，立即尝试一次。
   *
   * 这是用户明确表达"现在再试一次"，所以重置计数；成功后 onopen 也会归零。
   * 正在连接时只补一次心跳，避免并发开连接。
   */
  retryNow(): void {
    this.shouldReconnect = true;
    const ws = this.ws;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      this.pingNow();
      return;
    }
    this.clearReconnectTimer();
    this.reconnectAttemptCount = 0;
    this.emitStateChange();
    void this.connect().catch(() => {
      // 失败由 onclose 继续退避
    });
  }

  /** 立即发一次心跳，不等待 30s 周期。 */
  private pingNow(): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.send({
      id: generateId(),
      type: "request",
      method: "ping",
      timestamp: Date.now(),
      payload: {},
      error: null,
    });
  }

  /** 安装 online / focus / visibilitychange 触发器；只装一次，显式断开时卸载。 */
  private installReconnectTriggers(): void {
    if (
      this.removeReconnectTriggers ||
      typeof window === "undefined" ||
      typeof document === "undefined"
    ) {
      return;
    }

    const onOnline = () => this.reconnectNow();
    const onFocus = () => this.reconnectNow();
    const onVisibility = () => {
      if (document.visibilityState === "visible") this.reconnectNow();
    };

    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);

    this.removeReconnectTriggers = () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }

  /**
   * 发送请求并等待响应
   */
  sendRequest(method: string, payload: Record<string, unknown>): Promise<ResponseMessage> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error("Not connected"));
        return;
      }

      const id = generateId();
      const message: RequestMessage = {
        id,
        type: "request",
        method,
        timestamp: Date.now(),
        payload,
        error: null,
      };

      // 保存 pending request
      this.pendingRequests.set(id, { resolve, reject });

      // 发送消息
      const frame = JSON.stringify(message);
      // 发送方向也要能看到:排查"send 到底带了哪些参数"(如协议要求不带 modelId)靠它
      wsLogFrame("→", method, frame.length, message);
      this.ws.send(frame);

      // 超时处理（30秒）
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Request timeout: ${method}`));
        }
      }, 30000);
    });
  }

  /**
   * 发送消息（不需要响应）
   */
  private send(message: RequestMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const frame = JSON.stringify(message);
      // 心跳(ping)会被 wsLogFrame 内部跳过,这里统一收口便于审计
      wsLogFrame("→", message.method, frame.length, message);
      this.ws.send(frame);
    }
  }

  /**
   * 订阅会话（接收会话事件）
   *
   * 返回服务端的订阅快照：`payload.status` 是会话当前状态（`in_progress` 表示有活跃 run），
   * 恢复会话时据此还原"运行中"状态，不能只看本地是否在流式输出。
   */
  async subscribe(sessionId: string): Promise<ResponseMessage> {
    const response = await this.sendRequest("subscribe", { sessionId });
    this._sessionId = sessionId;
    return response;
  }

  /**
   * 拉取会话历史消息（协议 8.5 获取历史）
   *
   * 响应 method 为 `history.result`，消息按 createdAt 升序返回（最早在前），
   * offset=0 取最近一批，前端直接渲染即可、无需 reverse。
   * 服务端对发送方隐式订阅，调用前不需要先 subscribe。
   */
  async history(params: {
    sessionId: string;
    limit?: number;
    offset?: number;
    includeTelemetry?: boolean;
  }): Promise<ResponseMessage> {
    return this.sendRequest("history", {
      sessionId: params.sessionId,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      includeTelemetry: params.includeTelemetry ?? false,
    });
  }

  /**
   * 发送聊天消息
   *
   * 首帧用 `agentId`（+ 可选 `modelId`）建会话；不传 `agentId` 时是自由对话。
   * 续聊只用 `sessionId`。
   * 开源版已去掉 `versionId`；已有会话改模型走 `switchModel`（`model.switch`），
   * 不能把 `modelId` 塞进续聊帧；`mode/effort.switch` 仍未支持。
   */
  async sendMessage(params: {
    prompt: string;
    sessionId?: string;
    instanceId?: string;
    agentId?: string;
    modelId?: string;
    /** 本机文件路径（local-path 模式为 `{ path }`；云版由 provider 映射） */
    attachments?: AttachmentWire[];
  }): Promise<ResponseMessage> {
    const payload: Record<string, unknown> = {
      prompt: params.prompt,
    };

    if (params.sessionId) payload.sessionId = params.sessionId;
    if (params.instanceId) payload.instanceId = params.instanceId;
    if (params.agentId) payload.agentId = params.agentId;
    if (params.modelId) payload.modelId = params.modelId;
    if (params.attachments !== undefined && params.attachments.length > 0) {
      payload.attachments = params.attachments;
    }

    return this.sendRequest("send", payload);
  }

  /**
   * 切换已有会话的模型（`model.switch`）。
   *
   * 服务端在 run 间隙生效（`appliesTo: 'nextRun'`），成功后还会广播
   * `settings.changed`，其他窗口据此同步。续聊帧不接受 `modelId`，改模型只能走这里。
   */
  async switchModel(sessionId: string, modelId: string): Promise<ResponseMessage> {
    return this.sendRequest("model.switch", { sessionId, modelId });
  }

  /**
   * 首帧：建会话并发送第一条消息
   */
  async createInstanceAndSend(params: {
    /** 不传 = 自由对话（服务端建目录会话，不需要智能体） */
    agentId?: string;
    modelId?: string;
    prompt: string;
    attachments?: AttachmentWire[];
  }): Promise<ResponseMessage> {
    const response = await this.sendMessage(params);

    // 从响应中提取 instanceId
    if (response.payload?.instanceId) {
      this._instanceId = response.payload.instanceId as string;
    }

    return response;
  }

  /**
   * 注册事件处理器
   */
  on(event: string, handler: EventHandler): void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, []);
    }
    this.eventHandlers.get(event)!.push(handler);
  }

  /**
   * 移除事件处理器
   */
  off(event: string, handler: EventHandler): void {
    const handlers = this.eventHandlers.get(event);
    if (handlers) {
      const index = handlers.indexOf(handler);
      if (index !== -1) {
        handlers.splice(index, 1);
      }
    }
  }

  /**
   * 处理收到的消息
   *
   * @param frameSize 原始帧字节数,仅用于诊断输出
   */
  private handleMessage(message: SocketMessage, frameSize = 0): void {
    wsLogFrame("←", message.method, frameSize, message);
    switch (message.type) {
      case "response":
        this.handleResponse(message);
        break;
      case "event":
        this.handleEvent(message);
        break;
    }
  }

  /**
   * 处理响应消息
   */
  private handleResponse(message: ResponseMessage): void {
    const pending = this.pendingRequests.get(message.id);
    if (pending) {
      this.pendingRequests.delete(message.id);
      if (message.error) {
        pending.reject(new ChatSocketError(message.error));
      } else {
        pending.resolve(message);
      }
    }
  }

  /**
   * 处理事件消息
   */
  private handleEvent(message: EventMessage): void {
    const handlers = this.eventHandlers.get(message.method);
    if (handlers) {
      handlers.forEach((handler) => handler(message));
    }

    // 同时触发通配符事件
    const wildcardHandlers = this.eventHandlers.get("*");
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => handler(message));
    }
  }

  /**
   * 开始心跳 + 半开连接看门狗。
   *
   * 每个周期检查自上个周期以来是否收到过任何下行帧：
   * 连续 `HEARTBEAT_MISS_LIMIT` 个周期都没有，说明连接已经死了（常见于休眠、
   * 代理静默丢包），主动 `close()` 让 `onclose` 走正常重连流程。
   * 正在流式输出的连接每帧都会重置计数，不会被误杀。
   */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.framesSinceTick = false;
    this.missedHeartbeats = 0;
    this.heartbeatInterval = setInterval(() => {
      if (this.framesSinceTick) {
        this.framesSinceTick = false;
        this.missedHeartbeats = 0;
      } else {
        this.missedHeartbeats += 1;
      }

      if (this.missedHeartbeats >= HEARTBEAT_MISS_LIMIT) {
        this.ws?.close(PONG_TIMEOUT_CLOSE_CODE, "pong timeout");
        return;
      }

      this.pingNow();
    }, HEARTBEAT_INTERVAL_MS);
  }

  /**
   * 停止心跳
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  /**
   * 拒绝所有 pending 请求
   */
  private rejectAllPending(reason: string): void {
    this.pendingRequests.forEach(({ reject }) => {
      reject(new Error(reason));
    });
    this.pendingRequests.clear();
  }

  /**
   * 发送状态变化事件（供外部监听）
   */
  private emitStateChange(): void {
    const handlers = this.eventHandlers.get("stateChange");
    if (handlers) {
      const event: EventMessage = {
        id: generateId(),
        type: "event",
        method: "stateChange",
        timestamp: Date.now(),
        payload: { state: this._state },
      };
      handlers.forEach((handler) => handler(event));
    }
  }
}

// 单例实例
let socketInstance: ChatSocket | null = null;

/**
 * 获取 WebSocket 客户端单例
 */
export function getChatSocket(): ChatSocket {
  if (!socketInstance) {
    socketInstance = new ChatSocket();
  }
  return socketInstance;
}

/**
 * 重置 WebSocket 客户端（用于测试或重新连接）
 */
export function resetChatSocket(): void {
  if (socketInstance) {
    socketInstance.disconnect();
    socketInstance = null;
  }
}
