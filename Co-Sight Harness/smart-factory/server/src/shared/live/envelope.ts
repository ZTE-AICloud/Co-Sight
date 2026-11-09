/**
 * WebSocket 信封：请求 / 响应 / 事件三种，形状见 4.06 实时通道 §3。
 */
export interface Envelope<T = unknown> {
  id: string;
  type: 'request' | 'response' | 'event';
  method: string;
  timestamp: number;
  payload?: T;
  /** `messageKey` 给前端翻译；`message` 是中文兜底（与 REST 错误同一口径）。 */
  error?: { code: string; message: string; messageKey?: string; params?: Record<string, string | number> | null } | null;
}

let eventSequence = 0;

/** 服务端事件：id 形如 evt_<ts>_<n> */
export function eventEnvelope<T>(method: string, payload: T): Envelope<T> {
  eventSequence += 1;
  return { id: `evt_${Date.now()}_${eventSequence}`, type: 'event', method, timestamp: Date.now(), payload };
}

export function responseEnvelope<T>(id: string, method: string, payload: T): Envelope<T> {
  return { id, type: 'response', method, timestamp: Date.now(), payload, error: null };
}

export function errorEnvelope(
  id: string,
  method: string,
  code: string,
  message: string,
  messageKey?: string,
  params?: Record<string, string | number> | null,
): Envelope<null> {
  return {
    id,
    type: 'response',
    method,
    timestamp: Date.now(),
    error: {
      code,
      message,
      ...(messageKey === undefined ? {} : { messageKey }),
      ...(params === undefined || params === null ? {} : { params }),
    },
  };
}

/** 解析上行帧；形状不对返回 null，由网关回错误响应。type 必填，只认 request / response / event。 */
export function parseEnvelope(raw: string): Envelope | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const candidate = parsed as Partial<Envelope>;
    if (typeof candidate.method !== 'string' || typeof candidate.id !== 'string') return null;
    if (candidate.type !== 'request' && candidate.type !== 'response' && candidate.type !== 'event') return null;
    return candidate as Envelope;
  } catch {
    return null;
  }
}
