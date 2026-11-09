/**
 * 统一错误处理。
 *
 * 三条不可退让的规则：
 * 1. **任何响应都走信封**，包括 404 与校验失败——前端因此只需处理一种形状。
 * 2. **5xx 不外泄原始 message**。异常文本里会带文件路径、SQL 片段、甚至密钥，
 *    这些只进日志，不进响应体（对应用户规则「错误消息不泄露敏感数据」）。
 * 3. **404 的行为由注册时机决定**，只设一次。因此"是否回退到 SPA 首页"通过参数
 *    传进来，而不是先设一个再覆盖——Fastify 不保证重复设置 404 处理器的语义。
 */

import path from 'node:path';

import type { FastifyError, FastifyInstance, FastifyRequest } from 'fastify';
import { hasZodFastifySchemaValidationErrors } from 'fastify-type-provider-zod';
import { AppError, type ApiError, type ApiErrorCode } from 'harness-shared';

import { sendError } from '../http/reply';
import { pointerToPath, toFieldIssues } from '../http/validation';

/** API 路由前缀；非此后缀的 GET 才允许回退到前端首页。 */
const API_PREFIX = '/api';

/**
 * 路径像不像一个静态资源（`/assets/index-<hash>.js`、`/fonts/x.woff2`）。
 *
 * SPA 路由没有扩展名。带扩展名的路径缺文件时必须如实返回 404：如果也回退到
 * `index.html`，浏览器拿到的是 `text/html`，按严格 MIME 检查会拒收模块脚本，
 * 用户看到的就是一屏白（升级后浏览器还开着重装前的旧页面时最容易撞上）。
 * 判定与模块侧 `module-web-server.mjs` 保持一致。
 */
function looksLikeAsset(request: FastifyRequest): boolean {
  const pathname = request.url.split('?')[0] ?? '';
  return path.posix.extname(pathname) !== '';
}

interface FallbackText {
  key: string;
  text: string;
}

/** Fastify 内建错误的状态码到契约错误码/文案的映射。 */
const STATUS_FALLBACK: Record<number, { code: ApiErrorCode } & FallbackText> = {
  400: { code: 'BAD_REQUEST', key: 'error.bad_request', text: '请求格式不正确' },
  404: { code: 'NOT_FOUND', key: 'error.not_found.route', text: '接口不存在' },
  413: { code: 'PAYLOAD_TOO_LARGE', key: 'error.payload_too_large', text: '请求体过大' },
  415: { code: 'UNSUPPORTED_MEDIA_TYPE', key: 'error.unsupported_media_type', text: '不支持的内容类型' },
  429: { code: 'RATE_LIMITED', key: 'error.rate_limited', text: '请求过于频繁' },
};

const INTERNAL_FALLBACK: { code: ApiErrorCode } & FallbackText = {
  code: 'INTERNAL',
  key: 'error.internal',
  text: '服务内部错误',
};

export interface InstallErrorHandlerOptions {
  /**
   * 404 时是否把 GET 请求回退到前端首页（生产态托管 dist 时为 true）。
   * 前端是单页应用，`/experts` 这类路由在服务端并不存在文件，必须回退，
   * 否则刷新页面就会看到 404。
   */
  serveSpa?: boolean;
}

export function installErrorHandler(
  app: FastifyInstance,
  options: InstallErrorHandlerOptions = {},
): void {
  app.setErrorHandler((error: FastifyError, request, reply) => {
    const traceId = String(request.id);

    if (error instanceof AppError) {
      // 领域错误是"预期内"的，用 warn；原始 message 只进日志。
      request.log.warn({ traceId, code: error.code, key: error.messageKey }, error.message);
      return sendError(reply, error.toApiError(traceId));
    }

    if (hasZodFastifySchemaValidationErrors(error)) {
      const issues = toFieldIssues(
        error.validation.map((item) => ({
          path: pointerToPath(item.instancePath),
          code: item.keyword,
          message: item.message ?? '校验未通过',
        })),
      );
      request.log.warn({ traceId, issueCount: issues.length }, '请求参数校验失败');
      return sendError(reply, AppError.validation(issues).toApiError(traceId));
    }

    const statusCode = error.statusCode ?? 500;
    // 4xx 是调用方的问题，记 info；5xx 是我们的问题，记 error（含原始 message 与堆栈）。
    if (statusCode >= 500) {
      request.log.error({ traceId, statusCode, code: error.code, err: error }, error.message);
    } else {
      request.log.info({ traceId, statusCode, code: error.code }, error.message);
    }

    const fallback = STATUS_FALLBACK[statusCode] ?? INTERNAL_FALLBACK;
    const payload: ApiError = {
      code: fallback.code,
      messageKey: fallback.key,
      message: fallback.text,
      details: null,
      traceId,
    };
    return sendError(reply, payload);
  });

  app.setNotFoundHandler((request, reply) => {
    if (
      options.serveSpa === true &&
      request.method === 'GET' &&
      !request.url.startsWith(API_PREFIX) &&
      !looksLikeAsset(request)
    ) {
      return reply.sendFile('index.html');
    }

    const error = new AppError(
      'NOT_FOUND',
      'error.not_found.route',
      `接口不存在：${request.method} ${request.url}`,
    );
    return sendError(reply, error.toApiError(String(request.id)));
  });
}
