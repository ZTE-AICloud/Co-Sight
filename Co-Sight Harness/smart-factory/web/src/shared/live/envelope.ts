/**
 * 实时通道的信封：前端侧副本，镜像 `server/src/shared/live/envelope.ts`。
 *
 * 为什么是「副本」而不是共享包：与 `shared/api/agents.ts` 里的 `Agent` 同一个理由 ——
 * 接口稳定后再抽 `packages/shared-types`，现在是两端各持一份、以 4.06 实时通道 §3 为正本
 * （见 `shared/types/index.ts` 文件头的 TODO）。
 *
 * 三条硬规则（写错任何一条都会静默挂死或误判成功）：
 *   1. **每个请求必须带 `id`**。服务端对解析失败的帧回 `id:'unknown'`，那条请求的 Promise
 *      就永远等不到回执 —— 挂在这里，不报错。
 *   2. **响应的 `method` 恒等于请求的 `method`**，没有 `.result` 后缀（`ping` 的响应 `method`
 *      也是 `ping`，`pong` 只是 payload 里的字段）。
 *   3. **错误响应没有 `payload` 字段**，只有 `error:{code,message}`。这与 REST 的顶层
 *      `{error:string, message:string}` 不是一回事 —— 两边不能共用解析器，所以这里另立一个
 *      `WsError`，不要去复用 `shared/api/client.ts` 的 `ApiError`。
 */

export type EnvelopeType = 'request' | 'response' | 'event';

export interface Envelope<T = unknown> {
  id: string;
  type: EnvelopeType;
  method: string;
  timestamp: number;
  payload?: T;
  error?:
    | {
        code: string;
        message: string;
        messageKey?: string;
        params?: Record<string, string | number> | null;
      }
    | null;
}

/**
 * WS 侧的错误。形状与 REST 的 `ApiError` 刻意不同（`code` 是服务端给的字符串码，
 * 如 `BAD_REQUEST` / `NOT_FOUND` / `CONFLICT` / `INTERNAL_ERROR` / `SLOW_CONSUMER`）。
 *
 * `CONFLICT` 在多数写操作上**不是失败**：应答时它表示「别人已经结算了」、中止时表示
 * 「run 已落终态」——调用方该按「事情已经成了」处理，而不是弹红。判据放在调用点，
 * 这里只负责把 code 带出来。
 */
export class WsError extends Error {
  readonly code: string;
  /** 服务端给 i18n 键；`message` 是已经翻译好（或服务端中文兜底）的句子 */
  readonly messageKey: string | null;

  constructor(code: string, message: string, messageKey: string | null = null) {
    super(message);
    this.name = 'WsError';
    this.code = code;
    this.messageKey = messageKey;
  }
}

/** 请求帧的自增号：`Date.now()` 在同一毫秒里连发两条会撞号，撞号就等于把自己那条回执认错 */
let requestSequence = 0;

/** 造一个上行请求帧。`id` 由这里统一盖章，调用方不要自己拼 */
export function requestEnvelope<T>(method: string, payload: T): Envelope<T> {
  requestSequence += 1;
  return { id: `req_${Date.now()}_${requestSequence}`, type: 'request', method, timestamp: Date.now(), payload };
}

/** 解析下行帧；形状不对返回 null（由调用方决定记日志还是丢弃） */
export function parseEnvelope(raw: string): Envelope | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const candidate = parsed as Partial<Envelope>;
    if (typeof candidate.method !== 'string' || typeof candidate.id !== 'string') return null;
    return candidate as Envelope;
  } catch {
    return null;
  }
}
