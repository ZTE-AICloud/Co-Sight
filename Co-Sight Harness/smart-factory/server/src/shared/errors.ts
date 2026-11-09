/**
 * 领域错误基类：带 HTTP status，由 error-handler 中间件统一转换成响应体。
 * 各模块只负责抛出语义化错误，不关心响应格式。
 *
 * 每个错误除了给 `message`（中文兜底），还给 `messageKey` + `params`；
 * 前端按当前语言翻译 key，服务端不出词典。
 */

export type ErrorParams = Record<string, string | number>;

function defaultKey(code: string): string {
  return `error.${code.toLowerCase()}`;
}

export class AppError extends Error {
  readonly status: number;
  readonly code: string;
  /** i18n 键（运行期字符串，前端不在编译期校验） */
  readonly messageKey: string;
  /** 插值参数；没有就是 undefined */
  readonly params: ErrorParams | undefined;

  constructor(
    status: number,
    code: string,
    message: string,
    messageKey: string = defaultKey(code),
    params?: ErrorParams,
  ) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.code = code;
    this.messageKey = messageKey;
    this.params = params;
  }
}

export class NotFoundError extends AppError {
  constructor(what: string, messageKey = 'error.not_found.default', params?: ErrorParams) {
    super(404, 'NOT_FOUND', `${what} 不存在`, messageKey, params);
  }
}

export class BadRequestError extends AppError {
  constructor(message: string, messageKey = 'error.bad_request.default', params?: ErrorParams) {
    super(400, 'BAD_REQUEST', message, messageKey, params);
  }
}

export class ConflictError extends AppError {
  constructor(message: string, messageKey = 'error.conflict.default', params?: ErrorParams) {
    super(409, 'CONFLICT', message, messageKey, params);
  }
}

export class PayloadTooLargeError extends AppError {
  constructor(
    message: string,
    messageKey = 'error.payload_too_large.default',
    params?: ErrorParams,
  ) {
    super(413, 'PAYLOAD_TOO_LARGE', message, messageKey, params);
  }
}

/** 415：请求的形态合法，但内容类型没法按请求的方式解释（预览端点用它表示二进制文件）。 */
export class UnsupportedMediaTypeError extends AppError {
  constructor(
    message: string,
    messageKey = 'error.unsupported_media_type.default',
    params?: ErrorParams,
  ) {
    super(415, 'UNSUPPORTED_MEDIA_TYPE', message, messageKey, params);
  }
}

export class BadGatewayError extends AppError {
  constructor(message: string, messageKey = 'error.bad_gateway.default', params?: ErrorParams) {
    super(502, 'BAD_GATEWAY', message, messageKey, params);
  }
}
