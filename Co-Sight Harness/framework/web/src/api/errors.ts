/**
 * 前端侧的 API 错误类型。
 *
 * 为什么不在 api 客户端里直接 `throw new Error(body.error.message)`：
 *
 * 1. **错误码要能穷举**。UI 需要区分"没找到"（显示空态）与"服务端崩了"
 *    （显示重试按钮），靠匹配文案字符串会在改一次文案时静默失效。
 * 2. **要能拿到 traceId**。用户报错时把 traceId 贴出来，才能对齐服务端日志。
 * 3. **网络失败与服务端错误必须分开**。请求压根没到服务端（后端没启动）时，
 *    `body.error` 是拿不到的；把它硬塞进同一个类里会让"后端没启动"显示成
 *    "服务内部错误"，把排查方向引到完全错误的地方。
 */

import type { ApiError, ApiErrorCode, FieldIssue, PageMeta } from 'harness-shared';

/** 服务端返回的结构化错误（HTTP 状态码非 2xx，且响应体是标准信封）。 */
export class ApiRequestError extends Error {
  override readonly name = 'ApiRequestError';
  readonly code: ApiErrorCode;
  /** 服务端给的 i18n 键；前端优先翻它。 */
  readonly messageKey: string;
  readonly details: FieldIssue[] | null;
  readonly traceId: string | null;
  readonly status: number;

  constructor(status: number, error: ApiError) {
    // Error.message 只用于日志；界面文案一律经 useI18n 渲染，不走这里。
    super(error.message);
    this.status = status;
    this.code = error.code;
    this.messageKey = error.messageKey;
    this.details = error.details;
    this.traceId = error.traceId;
  }

  /** 字段级校验明细，供表单逐项标红。非校验类错误返回空数组。 */
  fieldIssues(): FieldIssue[] {
    return this.details ?? [];
  }
}

/** 请求未能到达服务端，或响应不是合法信封。 */
export class ApiNetworkError extends Error {
  override readonly name = 'ApiNetworkError';
  /** 保留原始异常，便于在控制台看到真实原因（CORS、连接被拒、解析失败）。 */
  override readonly cause: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.cause = cause;
  }
}

export function isApiRequestError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError;
}

export function isApiNetworkError(error: unknown): error is ApiNetworkError {
  return error instanceof ApiNetworkError;
}

/** 成功信封。`meta` 在运行期可能整个缺失，所以类型里带上 `undefined`。 */
export interface SuccessEnvelope {
  success: true;
  data: unknown;
  meta: PageMeta | null | undefined;
}

/** 失败信封。 */
export interface FailureEnvelope {
  success: false;
  error: ApiError;
}

export type Envelope = SuccessEnvelope | FailureEnvelope;

/**
 * 判断一个值是不是标准信封（用于识别"返回了 HTML 而不是 JSON"这类情况）。
 *
 * 判据不止"有 success 布尔字段"：成功信封必须**带 data 键**，失败信封必须有
 * 对象型的 error。只看 `success` 的话，任何一个恰好带 `{"success":true}`
 * 的响应都会被当成信封，然后在取 `data` 时拿到 undefined 并一路传下去——
 * 到很深的组件里才炸，且看不出根因。
 */
export function looksLikeEnvelope(value: unknown): value is Envelope {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.success !== 'boolean') {
    return false;
  }
  return record.success
    ? 'data' in record
    : typeof record.error === 'object' && record.error !== null;
}
