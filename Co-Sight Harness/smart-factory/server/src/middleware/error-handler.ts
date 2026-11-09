import type { NextFunction, Request, Response } from 'express';
import { AppError } from '../shared/errors.js';

/** 兜底 404：未匹配到任何路由。 */
export function notFoundHandler(req: Request, res: Response): void {
  res.status(404).json({
    error: 'NOT_FOUND',
    message: `无匹配路由：${req.method} ${req.originalUrl}`,
    messageKey: 'error.not_found.route',
    params: null,
  });
}

/**
 * 统一错误出口。
 *
 * Express 5 会把 async handler 的 rejection 直接转到这里，因此各 controller
 * 无需再包 try/catch。
 *
 * 注意：Express 靠入参个数（4 个）识别错误中间件，参数不能删。
 */
export function errorHandler(
  err: unknown,
  _req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof AppError) {
    // message 保留中文兜底；messageKey + params 交给前端按当前语言翻译。
    res.status(err.status).json({
      error: err.code,
      message: err.message,
      messageKey: err.messageKey,
      params: err.params ?? null,
    });
    return;
  }

  // body-parser 的客户端错误（JSON 语法错、超过 2mb 上限）自带 4xx status：属于请求不合法，
  // 统一按 400 回、不进错误日志，否则客户端的笔误会被当成服务端故障
  const parsedStatus = (err as { status?: unknown } | null)?.status;
  if (typeof parsedStatus === 'number' && parsedStatus >= 400 && parsedStatus < 500) {
    res.status(400).json({
      error: 'BAD_REQUEST',
      message: err instanceof Error ? err.message : '请求体不合法',
      messageKey: 'error.bad_request.default',
      params: null,
    });
    return;
  }

  console.error('[smart-factory] unhandled error:', err);
  res.status(500).json({
    error: 'INTERNAL_ERROR',
    message: err instanceof Error ? err.message : '内部错误',
    // 5xx 的原始 message 可能含路径 / 堆栈，**不进**响应体（与 message 的既有口径一致）
    messageKey: 'error.internal',
    params: null,
  });
}
