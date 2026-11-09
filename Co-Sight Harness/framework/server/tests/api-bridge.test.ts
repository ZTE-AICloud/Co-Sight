/**
 * 桥接 HTTP 流程（D25 = A）。
 *
 * 端到端走一遍：签发令牌 → 兑换 → 拿到会话 → 用会话访问 → 登出后失效。
 * 过期与来源绑定的边界在 bridge-session.test.ts 里用可控时钟测。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { BRIDGE_COOKIE_NAME } from '../src/bridge/session';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const MODULE_ORIGIN = 'http://127.0.0.1:5174';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('桥接接口', () => {
  it('签发令牌：返回令牌、过期时间与兑换地址', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/token',
      headers: { origin: MODULE_ORIGIN },
    });
    expect(response.statusCode).toBe(200);
    const data = response.json().data;
    expect(typeof data.token).toBe('string');
    expect(data.token.length).toBeGreaterThanOrEqual(32);
    expect(data.expiresAt).toBeGreaterThan(Date.now());
    expect(data.exchangeUrl).toBe('/api/bridge/exchange');
  });

  it('令牌不出现在 URL 上（只能从响应体取）', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/token',
    });
    const token = response.json().data.token as string;
    // 这是 D25 的核心约束：URL 会被 Referer、历史记录与反代日志带走。
    expect(response.rawPayload.toString()).toContain('exchangeUrl');
    expect(response.headers['location']).toBeUndefined();
    expect(token).not.toContain('?');
  });

  it('完整流程：兑换 → 用 cookie 访问 → 登出', async () => {
    const minted = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/token',
      headers: { origin: MODULE_ORIGIN },
    });
    const token = minted.json().data.token as string;

    const exchanged = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      headers: { origin: MODULE_ORIGIN },
      payload: { token },
    });
    expect(exchanged.statusCode).toBe(200);
    const session = exchanged.json().data;
    expect(typeof session.sessionId).toBe('string');

    const cookie = exchanged.cookies.find((item) => item.name === BRIDGE_COOKIE_NAME);
    expect(cookie).toBeDefined();
    // HttpOnly 是必须的：会话 id 不该被模块里的脚本读到（防 XSS 窃取）。
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.path).toBe('/api');

    const verified = await context.app.inject({
      method: 'GET',
      url: '/api/bridge/session',
      cookies: { [BRIDGE_COOKIE_NAME]: session.sessionId as string },
    });
    expect(verified.statusCode).toBe(200);
    expect(verified.json().data.sessionId).toBe(session.sessionId);

    const loggedOut = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/logout',
      cookies: { [BRIDGE_COOKIE_NAME]: session.sessionId as string },
    });
    expect(loggedOut.json().data.revoked).toBe(true);

    const afterLogout = await context.app.inject({
      method: 'GET',
      url: '/api/bridge/session',
      cookies: { [BRIDGE_COOKIE_NAME]: session.sessionId as string },
    });
    expect(afterLogout.statusCode).toBe(401);
  });

  it('令牌只能兑换一次，重放返回 401', async () => {
    const minted = await context.app.inject({ method: 'POST', url: '/api/bridge/token' });
    const token = minted.json().data.token as string;

    expect(
      (await context.app.inject({ method: 'POST', url: '/api/bridge/exchange', payload: { token } }))
        .statusCode,
    ).toBe(200);
    const replay = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      payload: { token },
    });
    expect(replay.statusCode).toBe(401);
    expect(replay.json().error.code).toBe('UNAUTHORIZED');
  });

  it('来源不符时拒绝兑换', async () => {
    const minted = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/token',
      headers: { origin: MODULE_ORIGIN },
    });
    const token = minted.json().data.token as string;

    const stolen = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      headers: { origin: 'http://evil.test' },
      payload: { token },
    });
    expect(stolen.statusCode).toBe(401);
  });

  it('伪造令牌被拒绝', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      payload: { token: 'a'.repeat(43) },
    });
    expect(response.statusCode).toBe(401);
  });

  it('过短的令牌被参数校验挡下', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      payload: { token: 'short' },
    });
    expect(response.statusCode).toBe(422);
  });

  it('无会话时访问 /session 返回 401 信封', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/bridge/session' });
    expect(response.statusCode).toBe(401);
    const body = response.json();
    expect(body.success).toBe(false);
    expect(body.error.code).toBe('UNAUTHORIZED');
  });

  it('也支持 Bearer 头（跨站请求带不上 cookie 时的通路）', async () => {
    const minted = await context.app.inject({ method: 'POST', url: '/api/bridge/token' });
    const token = minted.json().data.token as string;
    const exchanged = await context.app.inject({
      method: 'POST',
      url: '/api/bridge/exchange',
      payload: { token },
    });
    const sessionId = exchanged.json().data.sessionId as string;

    const verified = await context.app.inject({
      method: 'GET',
      url: '/api/bridge/session',
      headers: { authorization: `Bearer ${sessionId}` },
    });
    expect(verified.statusCode).toBe(200);
  });
});
