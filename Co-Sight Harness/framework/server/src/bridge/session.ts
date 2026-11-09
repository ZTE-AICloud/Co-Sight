/**
 * 桥接会话（D25 = A）。
 *
 * 场景：模块跑在**另一个源**的 iframe 里（D24 = A）。它要调框架 API，
 * 而 v1 是本地单用户、没有登录体系，所以身份靠一次性令牌换取：
 *
 *   宿主 POST /api/bridge/token          → 拿到 { token, exchangeUrl }
 *   宿主 postMessage(host:init, token)   → 令牌走消息通道，**不进 URL**
 *   模块 POST exchangeUrl { token }       → 令牌作废，换回会话 cookie
 *   模块后续请求带 cookie                 → 即可访问 API
 *
 * 为什么令牌不能放 URL 查询串：查询串会被 Referer 头带出去、进浏览器历史、
 * 进反代访问日志。postMessage 是本进程内的点对点通道，不落任何一处。
 *
 * 两点实现约束：
 * - 令牌**一次性**：exchange 命中后立即从表里删除，重放必然失败。
 * - 会话只存内存：重启即失效。本地单用户下这是特性而非缺陷——进程一停，
 *   没有悬空凭据留在磁盘上。
 */

import { randomBytes, randomUUID } from 'node:crypto';

/** 一次性令牌有效期：足够宿主完成一次 postMessage 往返，又不留长窗口。 */
const TOKEN_TTL_MS = 60_000;
/** 会话有效期；v1 是本地长驻会话，取 12 小时。 */
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
/** 桥接 cookie 名。 */
export const BRIDGE_COOKIE_NAME = 'cosight_bridge';

interface TokenRecord {
  /** 只允许被兑换到声明的这个源，避免令牌被第三方页面拾取后复用。 */
  origin: string | null;
  expiresAt: number;
}

export interface BridgeSession {
  /** 会话 id；仅用于日志与前端展示，不是凭据本身。 */
  sessionId: string;
  expiresAt: number;
}

interface SessionRecord extends BridgeSession {
  origin: string | null;
}

export interface BridgeSessionServiceOptions {
  /** 注入时钟，便于测试过期路径而不必真的等待。 */
  now?: () => number;
}

export class BridgeSessionService {
  readonly #tokens = new Map<string, TokenRecord>();
  readonly #sessions = new Map<string, SessionRecord>();
  readonly #now: () => number;

  constructor(options: BridgeSessionServiceOptions = {}) {
    this.#now = options.now ?? Date.now;
  }

  /** 令牌熵取 32 字节（256 位），远超可暴力枚举的量级。 */
  mintToken(origin: string | null = null): { token: string; expiresAt: number } {
    this.#sweep();
    const token = randomBytes(32).toString('base64url');
    const expiresAt = this.#now() + TOKEN_TTL_MS;
    this.#tokens.set(token, { origin, expiresAt });
    return { token, expiresAt };
  }

  /**
   * 兑换令牌。令牌不存在、已过期、已用过、或来源不匹配时返回 null。
   * 无论成功与否，命中的令牌都会被消费掉——失败重试必须重新申请。
   */
  exchange(token: string, origin: string | null = null): BridgeSession | null {
    const record = this.#tokens.get(token);
    if (record === undefined) {
      return null;
    }
    this.#tokens.delete(token);

    if (record.expiresAt <= this.#now()) {
      return null;
    }
    if (record.origin !== null && origin !== record.origin) {
      return null;
    }

    const sessionId = randomUUID();
    const expiresAt = this.#now() + SESSION_TTL_MS;
    this.#sessions.set(sessionId, { sessionId, expiresAt, origin });
    return { sessionId, expiresAt };
  }

  /** 校验会话；不存在或已过期返回 null。 */
  verify(sessionId: string): BridgeSession | null {
    const record = this.#sessions.get(sessionId);
    if (record === undefined) {
      return null;
    }
    if (record.expiresAt <= this.#now()) {
      this.#sessions.delete(sessionId);
      return null;
    }
    return { sessionId: record.sessionId, expiresAt: record.expiresAt };
  }

  /** 主动登出。 */
  revoke(sessionId: string): void {
    this.#sessions.delete(sessionId);
  }

  /** 清理过期条目。每次签发令牌时顺带扫一遍，不额外起定时器。 */
  #sweep(): void {
    const now = this.#now();
    for (const [token, record] of this.#tokens) {
      if (record.expiresAt <= now) {
        this.#tokens.delete(token);
      }
    }
    for (const [id, record] of this.#sessions) {
      if (record.expiresAt <= now) {
        this.#sessions.delete(id);
      }
    }
  }
}
