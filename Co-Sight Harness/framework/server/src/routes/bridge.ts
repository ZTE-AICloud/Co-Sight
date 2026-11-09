/**
 * 桥接接口（D25 = A）。
 *
 * 令牌换会话的三步见 `bridge/session.ts` 的文件头。这里只补三点说明：
 *
 * 1. **这不是访问控制边界。** v1 无登录，谁都能直连本机 API；令牌解决的是
 *    *跨源模块如何拿到一个可验证身份*，不是"挡住未授权访问"。真正的边界是
 *    D25 选定的"只监听 127.0.0.1"——信任范围 = 本机进程。写清楚这一点，
 *    免得后来者误以为有令牌就安全。
 * 2. **`/token` 不校验来源，但把来源记进令牌。** 兑换时会比对，令牌被第三方
 *    页面拾取也无法换出会话。
 * 3. **会话 id 同时以 cookie 和响应体两种形式给出。** 跨源 iframe 发起的请求
 *    属于跨站，浏览器不会带上 `SameSite=Lax` 的 cookie；这种情况下模块改用
 *    `Authorization: Bearer <sessionId>`。同源场景用 cookie 更省事。
 */

import { AppError } from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';
import { z } from 'zod';

import { BRIDGE_COOKIE_NAME } from '../bridge/session';
import { sendOk } from '../http/reply';

/** 令牌是 32 字节 base64url（43 字符）；这里只做长度护栏，格式不额外约束。 */
const exchangeBodySchema = z.object({
  token: z.string().min(16).max(128),
});

/** 会话 cookie 只作用于 API 路径，前端静态资源与文档不受影响。 */
const COOKIE_PATH = '/api';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'bridge';

export const bridgeRoutes: FastifyPluginAsyncZod = async (app) => {
  app.post('/token', { schema: { tags: [TAG] } }, async (request, reply) => {
    const origin = request.headers.origin ?? null;
    const { token, expiresAt } = app.services.bridge.mintToken(origin);
    return sendOk(reply, {
      token,
      expiresAt,
      /** 相对路径：模块拿到的 exchangeUrl 不依赖它自己知道 API 的绝对地址。 */
      exchangeUrl: '/api/bridge/exchange',
    });
  });

  app.post('/exchange', { schema: { tags: [TAG], body: exchangeBodySchema } }, async (request, reply) => {
    const origin = request.headers.origin ?? null;
    const session = app.services.bridge.exchange(request.body.token, origin);
    if (session === null) {
      throw AppError.unauthorized('桥接令牌无效、已过期或已被使用');
    }

    reply.setCookie(BRIDGE_COOKIE_NAME, session.sessionId, {
      path: COOKIE_PATH,
      httpOnly: true,
      // 跨站请求不会带上 Lax cookie，跨源模块请改用响应体里的 sessionId。
      sameSite: 'lax',
      // v1 是 http://localhost 本地访问，没有 TLS 可依托；开启 Secure 会导致
      // cookie 根本不下发。这是 D25 已知并接受的取舍。
      secure: false,
      maxAge: Math.max(0, Math.floor((session.expiresAt - Date.now()) / 1000)),
    });

    return sendOk(reply, session);
  });

  app.get('/session', { schema: { tags: [TAG] } }, async (request, reply) => {
    const cookieValue = request.cookies[BRIDGE_COOKIE_NAME];
    const header = request.headers.authorization;
    const bearer =
      header !== undefined && header.startsWith('Bearer ') ? header.slice('Bearer '.length) : undefined;
    const candidate = cookieValue ?? bearer;

    const session = candidate === undefined ? null : app.services.bridge.verify(candidate);
    if (session === null) {
      throw AppError.unauthorized();
    }
    return sendOk(reply, session);
  });

  app.post('/logout', { schema: { tags: [TAG] } }, async (request, reply) => {
    const cookieValue = request.cookies[BRIDGE_COOKIE_NAME];
    if (cookieValue !== undefined) {
      app.services.bridge.revoke(cookieValue);
    }
    reply.clearCookie(BRIDGE_COOKIE_NAME, { path: COOKIE_PATH });
    return sendOk(reply, { revoked: true });
  });
};
