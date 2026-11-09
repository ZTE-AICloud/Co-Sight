import type { Server } from 'node:http';
import { WebSocket, WebSocketServer } from 'ws';
import { config } from '../../config/index.js';
import { AppError, BadRequestError, NotFoundError } from '../errors.js';
import type {
  ApprovalDecision,
  Message,
  MessageRole,
  MessageType,
  Run,
  Session,
  SessionEffort,
  SessionMode,
  SessionStatus,
} from '../types/index.js';
import { optionalInt, optionalString, requireEnum, requireString } from '../validate.js';
import { errorEnvelope, eventEnvelope, parseEnvelope, responseEnvelope, type Envelope } from './envelope.js';
import { liveHub, type Subscriber } from './live-hub.js';

/** 心跳超时 = 间隔的 2 倍：客户端按间隔发帧，超时没收到任何上行帧即断开（4.06 实时通道 §2）。 */
const HEARTBEAT_TIMEOUT_FACTOR = 2;
const HEARTBEAT_CLOSE_CODE = 1000;

const APPROVAL_DECISIONS: readonly ApprovalDecision[] = ['approved', 'approved_all', 'rejected'];
const SESSION_MODES: readonly SessionMode[] = ['read_only', 'workspace_write', 'full_access'];
const SESSION_EFFORTS: readonly SessionEffort[] = ['low', 'medium', 'high', 'xhigh', 'max'];

/** 订阅握手：会话不存在即 null；挂起兼容帧由网关在响应之后补发。 */
export interface SubscribeInfo {
  status: SessionStatus;
  pending: Array<{ method: string; payload: unknown }>;
}

/** 历史消息项：content 为解析后的 JSON 字符串，与 REST 历史同形。 */
export interface HistoryMessage {
  id: string;
  sessionId: string;
  runId: string | null;
  role: MessageRole;
  type: MessageType;
  content: string;
  createdAt: string;
}

export interface HistoryResult {
  sessionId: string;
  messages: HistoryMessage[];
  total: number;
}

/** send 的产物：新会话按 agentId 现建时 sessionId 由服务端确定。 */
export interface SendResult {
  sessionId: string;
  runId: string;
  instanceId: string;
  /** run 在返回时已进入 running（起跑条件已解析完） */
  status: 'running';
  effort: SessionEffort;
  modelId: string;
  modelName: string;
  /** 本服务不做模型回落，恒为 false；字段与 agent-runtime 对齐 */
  modelFellBack: false;
  message: Message;
  run: Run;
}

export interface SendInput {
  sessionId?: string;
  agentId?: string;
  prompt: string;
  /** 本机文件：`[{ path }]` 或裸路径字符串；校验与落库在 session 服务里 */
  attachments?: unknown;
  /** 新建会话（agentId / 自由对话）绑定的模型 id，必填非空；续聊不接受 */
  modelId?: unknown;
  /** 新建会话的审批模式，缺省 workspace_write；续聊不接受 */
  mode?: unknown;
  /** 新建会话的推理强度，缺省 high；续聊不接受 */
  effort?: unknown;
  /** 新建会话（agentId / 自由对话）时回调，网关据此补订阅 */
  onSessionResolved?: (sessionId: string) => void;
}

/**
 * 网关不认识业务实现：动作由 `index.ts` 注入，避免 `shared/` 反向依赖 `modules/`。
 */
export interface WsHandlers {
  send(input: SendInput): Promise<SendResult>;
  abortRun(input: { runId: string }): Promise<Run>;
  respond(input: { messageId: string; decision?: string; answers?: Record<string, string[]> }): Promise<unknown>;
  respondApproval(input: { approvalId: string; decision: ApprovalDecision }): Promise<Message>;
  /** answers 由服务层归一与校验：对象 `{问: [答]}` 与数组 `[{question, answer}]` 都透传。 */
  respondTool(input: { toolCallId: string; answers: unknown }): Promise<Message>;
  switchModel(input: { sessionId: string; modelId: string }): Promise<Session>;
  switchMode(input: { sessionId: string; mode: SessionMode }): Promise<Session>;
  switchEffort(input: { sessionId: string; effort: SessionEffort }): Promise<Session>;
  history(input: {
    sessionId: string;
    limit?: number;
    offset?: number;
    includeTelemetry?: boolean;
  }): Promise<HistoryResult>;
  subscribeInfo(sessionId: string): Promise<SubscribeInfo | null>;
}

/** 一次分派的产物：响应载荷 + 「响应之后」动作（订阅补发挂起帧）。 */
interface DispatchResult {
  payload: unknown;
  afterResponse?: () => void;
}

/** 未知方法单独成类：它的错误帧 method 固定为 error，与参数校验错误区分。 */
class UnknownMethodError extends BadRequestError {
  constructor(method: string) {
    super(`未知方法：${method}`, 'error.bad_request.unknown_method', { method });
  }
}

/** WS 只有四种错误码，REST 的细分码在这里收口。 */
const WS_ERROR_CODES: Readonly<Record<string, string>> = {
  BAD_REQUEST: 'VALIDATION',
  INTERNAL_ERROR: 'INTERNAL',
  FRAMEWORK_UNAVAILABLE: 'INTERNAL',
};

function toWsErrorCode(error: unknown): string {
  const code = error instanceof AppError ? error.code : 'INTERNAL_ERROR';
  if (code === 'NOT_FOUND' || code === 'CONFLICT' || code === 'VALIDATION') return code;
  return WS_ERROR_CODES[code] ?? 'INTERNAL';
}

/** 成功响应的 method：ping 为 pong，其余为请求方法加 .result。 */
function responseMethodOf(requestMethod: string): string {
  return requestMethod === 'ping' ? 'pong' : `${requestMethod}.result`;
}

export interface WsGateway {
  close(): void;
  readonly connectionCount: number;
}

interface Client extends Subscriber {
  socket: WebSocket;
  connectionId: string;
}

function sendEnvelope(socket: WebSocket, envelope: Envelope): boolean {
  if (socket.readyState !== WebSocket.OPEN) return false;

  if (socket.bufferedAmount > config.wsMaxBufferedBytes) {
    // 4.06 实时通道 §5：连接级错误走下行事件（method='error'），不是请求响应
    socket.send(JSON.stringify(eventEnvelope('error', { code: 'SLOW_CONSUMER', message: '客户端消费过慢，连接将被断开' })));
    socket.close();
    return false;
  }

  socket.send(JSON.stringify(envelope));
  return true;
}

/** 挂载 WS 网关：与 REST 同端口，路径来自 config。 */
export function attachWsGateway(server: Server, handlers: WsHandlers): WsGateway {
  const wss = new WebSocketServer({ server, path: config.wsPath });
  const clients = new Map<WebSocket, Client>();
  const lastSeen = new Map<WebSocket, number>();
  let connectionSequence = 0;

  async function dispatch(client: Client, envelope: Envelope): Promise<DispatchResult> {
    const payload = (envelope.payload ?? {}) as Record<string, unknown>;

    switch (envelope.method) {
      case 'subscribe': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        // 先订阅再取快照：取快照期间新落的挂起要么进 pending，要么作为实时事件到达，不会两头落空
        liveHub.subscribe(sessionId, client);
        let info: SubscribeInfo | null;
        try {
          info = await handlers.subscribeInfo(sessionId);
        } catch (error) {
          liveHub.unsubscribe(sessionId, client);
          throw error;
        }
        if (!info) {
          liveHub.unsubscribe(sessionId, client);
          throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
        }
        // 补发排在响应之后：前端按 approvalId / toolCallId upsert，重复订阅重复补发是允许的
        return {
          payload: { subscribed: true, sessionId, status: info.status },
          afterResponse: () => {
            for (const frame of info.pending) client.send(eventEnvelope(frame.method, frame.payload));
          },
        };
      }
      case 'unsubscribe': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        liveHub.unsubscribe(sessionId, client);
        return { payload: { sessionId, unsubscribed: true } };
      }
      case 'send': {
        // 正文可以为空**当且仅当**带了附件 —— 形状判定留在网关，路径校验交给服务层
        const prompt = typeof payload.prompt === 'string' ? payload.prompt : '';
        const attachments = payload.attachments;
        if (prompt.trim() === '' && !(Array.isArray(attachments) && attachments.length > 0)) {
          throw new BadRequestError('prompt 必填', 'error.bad_request.prompt_required');
        }
        const sessionId = optionalString(payload.sessionId);
        const agentId = optionalString(payload.agentId);
        // 会话定位至多给一个：两个都给是调用方错误；都不给是自由对话（无智能体，落当前工作区目录）
        if (sessionId !== undefined && agentId !== undefined) {
          throw new BadRequestError('sessionId 与 agentId 不能同时给', 'error.bad_request.session_or_agent');
        }
        // 非字符串 modelId 在网关层直接拒绝；空串原样下发，由服务层按定位分支处理
        if (payload.modelId !== undefined && typeof payload.modelId !== 'string') {
          throw new BadRequestError('modelId 必须是字符串', 'error.bad_request.model_id_string');
        }
        // 已知会话先订阅：发起 send 的连接不得漏掉本轮事件
        if (sessionId !== undefined) liveHub.subscribe(sessionId, client);
        return {
          payload: await handlers.send({
            ...(sessionId !== undefined ? { sessionId } : {}),
            ...(agentId !== undefined ? { agentId } : {}),
            prompt,
            ...(attachments !== undefined ? { attachments } : {}),
            ...(payload.modelId !== undefined ? { modelId: payload.modelId } : {}),
            ...(payload.mode !== undefined ? { mode: payload.mode } : {}),
            ...(payload.effort !== undefined ? { effort: payload.effort } : {}),
            // 新建会话（agentId / 自由对话）的 sessionId 在响应前才确定，回调里补订阅
            ...(sessionId === undefined
              ? { onSessionResolved: (resolved: string) => liveHub.subscribe(resolved, client) }
              : {}),
          }),
        };
      }
      case 'history': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        const limit = optionalInt(payload.limit);
        const offset = optionalInt(payload.offset);
        const includeTelemetry = typeof payload.includeTelemetry === 'boolean' ? payload.includeTelemetry : undefined;
        // 恢复会话只发 history：成功即订阅，后续实时事件才能到达
        liveHub.subscribe(sessionId, client);
        try {
          return {
            payload: await handlers.history({
              sessionId,
              ...(limit !== undefined ? { limit } : {}),
              ...(offset !== undefined ? { offset } : {}),
              ...(includeTelemetry !== undefined ? { includeTelemetry } : {}),
            }),
          };
        } catch (error) {
          liveHub.unsubscribe(sessionId, client);
          throw error;
        }
      }
      case 'approval.respond': {
        const approvalId = requireString(payload.approvalId, 'approvalId');
        const decision = requireEnum(payload.decision, APPROVAL_DECISIONS, 'decision');
        await handlers.respondApproval({ approvalId, decision });
        return { payload: { approvalId, decision, resolved: true } };
      }
      case 'tool.respond': {
        if (payload.answers === undefined) throw new BadRequestError('answers 必填', 'error.bad_request.answers_required');
        const toolCallId = requireString(payload.toolCallId, 'toolCallId');
        await handlers.respondTool({ toolCallId, answers: payload.answers });
        return { payload: { toolCallId, received: true } };
      }
      case 'model.switch': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        const modelId = requireString(payload.modelId, 'modelId');
        await handlers.switchModel({ sessionId, modelId });
        return { payload: { sessionId, modelId, appliesTo: 'nextRun' } };
      }
      case 'mode.switch': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        const mode = requireEnum(payload.mode, SESSION_MODES, 'mode');
        await handlers.switchMode({ sessionId, mode });
        return { payload: { sessionId, mode } };
      }
      case 'effort.switch': {
        const sessionId = requireString(payload.sessionId, 'sessionId');
        const effort = requireEnum(payload.effort, SESSION_EFFORTS, 'effort');
        await handlers.switchEffort({ sessionId, effort });
        return { payload: { sessionId, effort } };
      }
      case 'run.abort': {
        const run = await handlers.abortRun({ runId: requireString(payload.runId, 'runId') });
        return { payload: { runId: run.id, aborted: true } };
      }
      case 'message.respond':
        return {
          payload: {
            message: await handlers.respond({
              messageId: requireString(payload.messageId, 'messageId'),
              ...(typeof payload.decision === 'string' ? { decision: payload.decision } : {}),
              ...(payload.answers && typeof payload.answers === 'object'
                ? { answers: payload.answers as Record<string, string[]> }
                : {}),
            }),
          },
        };
      case 'ping':
        return { payload: { serverTime: Date.now() } };
      default:
        throw new UnknownMethodError(envelope.method);
    }
  }

  async function handleMessage(client: Client, raw: string): Promise<void> {
    lastSeen.set(client.socket, Date.now());
    const envelope = parseEnvelope(raw);
    if (!envelope) {
      client.send(
        errorEnvelope('', 'error', 'VALIDATION', '信封格式非法', 'error.validation_failed'),
      );
      return;
    }

    try {
      const result = await dispatch(client, envelope);
      client.send(responseEnvelope(envelope.id, responseMethodOf(envelope.method), result.payload));
      result.afterResponse?.();
    } catch (error) {
      const unknownMethod = error instanceof UnknownMethodError;
      const method = unknownMethod ? 'error' : responseMethodOf(envelope.method);
      const code = unknownMethod ? 'VALIDATION' : toWsErrorCode(error);
      client.send(
        errorEnvelope(
          envelope.id,
          method,
          code,
          error instanceof Error ? error.message : '内部错误',
          error instanceof AppError ? error.messageKey : 'error.internal',
          error instanceof AppError ? (error.params ?? null) : null,
        ),
      );
    }
  }

  /** 摘掉一个连接：先退订再清表，重复调用幂等。 */
  function release(socket: WebSocket): void {
    const client = clients.get(socket);
    if (client) liveHub.unsubscribeAll(client);
    clients.delete(socket);
    lastSeen.delete(socket);
  }

  wss.on('connection', (socket) => {
    connectionSequence += 1;
    const client: Client = {
      socket,
      connectionId: `conn_${connectionSequence}`,
      send: (envelope) => sendEnvelope(socket, envelope),
    };
    clients.set(socket, client);
    lastSeen.set(socket, Date.now());

    socket.send(
      JSON.stringify(
        eventEnvelope('connection.ready', { connectionId: client.connectionId, restored: false, sessionId: null }),
      ),
    );

    socket.on('message', (raw) => {
      void handleMessage(client, raw.toString());
    });
    socket.on('close', () => release(socket));
    socket.on('error', () => socket.terminate());
  });

  // 空闲扫描：服务端不发 ping，只在超过 2 倍间隔没收到任何上行帧时收线
  const heartbeat = setInterval(() => {
    const now = Date.now();
    for (const [socket, seen] of [...lastSeen]) {
      if (now - seen <= config.wsHeartbeatMs * HEARTBEAT_TIMEOUT_FACTOR) continue;
      release(socket);
      socket.close(HEARTBEAT_CLOSE_CODE, '心跳超时');
    }
  }, config.wsHeartbeatMs);
  heartbeat.unref();

  return {
    get connectionCount(): number {
      return clients.size;
    },
    close(): void {
      clearInterval(heartbeat);
      for (const socket of clients.keys()) {
        try {
          socket.close();
        } catch {
          /* 已经断开 */
        }
        socket.terminate();
      }
      clients.clear();
      lastSeen.clear();
      wss.close();
    },
  };
}
