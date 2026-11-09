/**
 * 响应构造工具。
 *
 * 路由一律经这三个函数返回，保证**每个**响应（含错误、含 404）都是同一套信封。
 * 直接 `reply.send({...})` 会绕过信封，前端就得对两种形状做分支。
 */

import type { FastifyReply } from 'fastify';

import { ERROR_HTTP_STATUS, buildPageMeta, fail, ok, type ApiError, type PageMeta } from 'harness-shared';

export function sendOk<T>(reply: FastifyReply, data: T, statusCode = 200): FastifyReply {
  return reply.status(statusCode).send(ok(data));
}

/** 分页列表：数据装成 `{ items }`，分页信息进 `meta`。 */
export function sendPaged<T>(
  reply: FastifyReply,
  items: T[],
  total: number,
  page: number,
  pageSize: number,
): FastifyReply {
  const meta: PageMeta = buildPageMeta(total, page, pageSize);
  return reply.status(200).send(ok({ items }, meta));
}

/** 错误响应的 HTTP 状态码由错误码映射，路由不自行指定。 */
export function sendError(reply: FastifyReply, error: ApiError): FastifyReply {
  return reply.status(ERROR_HTTP_STATUS[error.code]).send(fail(error));
}
