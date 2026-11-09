/**
 * 框架统一错误模型。
 *
 * 设计要点（对应用户规则「API 响应格式」与 D28 双语）：
 * - 错误码是**有限枚举**，前端可穷举 switch，不靠匹配字符串。
 * - 每个错误同时给 `messageKey`（i18n 键）与 `message`（服务端已渲染的中文兜底），
 *   前端优先用 key 翻译，缺键时退化为 message，避免出现空白错误提示。
 * - `traceId` 由服务端注入，用于把用户看到的报错对齐到日志。
 */

export const API_ERROR_CODES = [
  'BAD_REQUEST',
  'VALIDATION_FAILED',
  'NOT_FOUND',
  'CONFLICT',
  'PAYLOAD_TOO_LARGE',
  'UNSUPPORTED_MEDIA_TYPE',
  'RATE_LIMITED',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'NOT_IMPLEMENTED',
  'UPSTREAM_UNAVAILABLE',
  'INTERNAL',
] as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

export const ERROR_HTTP_STATUS: Record<ApiErrorCode, number> = {
  BAD_REQUEST: 400,
  VALIDATION_FAILED: 422,
  NOT_FOUND: 404,
  CONFLICT: 409,
  PAYLOAD_TOO_LARGE: 413,
  UNSUPPORTED_MEDIA_TYPE: 415,
  RATE_LIMITED: 429,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_IMPLEMENTED: 501,
  UPSTREAM_UNAVAILABLE: 503,
  INTERNAL: 500,
};

/** 字段级校验问题，用于表单逐项报错。 */
export interface FieldIssue {
  /** 点分路径，如 `name` 或 `apiKey.baseUrl`。 */
  path: string;
  /** 机器可读的短码，如 `too_small`、`invalid_format`。 */
  code: string;
  /** i18n 键。 */
  messageKey: string;
  message: string;
}

export interface ApiError {
  code: ApiErrorCode;
  /** i18n 键，形如 `error.not_found.workspace`。 */
  messageKey: string;
  /** 服务端渲染的中文兜底文案。 */
  message: string;
  /** 字段级明细；非表单类错误为 null。 */
  details: FieldIssue[] | null;
  /** 关联日志的追踪号；由服务端在响应时补齐。 */
  traceId: string | null;
}

export interface AppErrorOptions {
  details?: FieldIssue[];
  cause?: unknown;
}

/**
 * 领域错误。路由层只抛这个类，由统一的错误处理器翻译成 HTTP 响应。
 * 任何未被捕获的普通 Error 一律按 INTERNAL 处理，且**不外泄**其 message。
 */
export class AppError extends Error {
  readonly code: ApiErrorCode;
  readonly messageKey: string;
  readonly details: FieldIssue[] | null;
  /** 面向用户的文案与 i18n 键由构造参数给出；Error.message 仅用于服务端日志。 */
  constructor(
    code: ApiErrorCode,
    messageKey: string,
    message: string,
    options: AppErrorOptions = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'AppError';
    this.code = code;
    this.messageKey = messageKey;
    this.details = options.details ?? null;
  }

  toApiError(traceId: string | null = null): ApiError {
    return {
      code: this.code,
      messageKey: this.messageKey,
      message: this.message,
      details: this.details,
      traceId,
    };
  }

  static notFound(resource: string, id?: string): AppError {
    return new AppError(
      'NOT_FOUND',
      `error.not_found.${resource}`,
      id === undefined ? `未找到${resource}` : `未找到${resource}：${id}`,
    );
  }

  static conflict(resource: string, reason: string): AppError {
    return new AppError('CONFLICT', `error.conflict.${resource}`, reason);
  }

  static validation(issues: FieldIssue[]): AppError {
    return new AppError('VALIDATION_FAILED', 'error.validation_failed', '请求参数校验未通过', {
      details: issues,
    });
  }

  /**
   * 未认证。v1 的框架自有接口不设认证（D25：本地单用户），
   * 但**模块桥接**需要区分"令牌过期"与"参数写错"——两者对模块的处理完全不同
   * （重新申请令牌 vs 报 bug），所以错误码必须分开。
   */
  static unauthorized(reason = '缺少或已失效的桥接会话'): AppError {
    return new AppError('UNAUTHORIZED', 'error.unauthorized', reason);
  }

  static forbidden(reason: string): AppError {
    return new AppError('FORBIDDEN', 'error.forbidden', reason);
  }

  /**
   * 模块面令牌被拒（缺头 / 方案不对 / 值不匹配 / 令牌文件读不到）。
   *
   * 与 `unauthorized()` 分开是因为 messageKey 不同：桥接那句是"缺少或已失效的
   * 桥接会话"，模块面这句要指向 `$COSIGHT_HOME/.module-token` 这个具体文件，
   * 否则调用方看不出该去修什么。
   *
   * **四种失败原因回同一句文案**，刻意不区分：响应里区分"文件不存在"与"值不对"
   * 等于向调用方泄漏本机文件系统的状态；真实原因只进服务端日志。
   */
  static moduleTokenRejected(reason: string): AppError {
    return new AppError('UNAUTHORIZED', 'error.unauthorized.module_token', reason);
  }

  static notImplemented(feature: string, messageKey = 'error.not_implemented'): AppError {
    return new AppError('NOT_IMPLEMENTED', messageKey, `${feature}尚未实现`);
  }
}

export function toApiError(error: unknown, traceId: string | null = null): ApiError {
  if (error instanceof AppError) {
    return error.toApiError(traceId);
  }
  // 非 AppError 一律按内部错误处理，message 不对外暴露（避免泄漏堆栈/路径/SQL）。
  return {
    code: 'INTERNAL',
    messageKey: 'error.internal',
    message: '服务内部错误',
    details: null,
    traceId,
  };
}
