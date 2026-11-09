/**
 * 桥接会话服务（D25 = A）。
 *
 * 三条必须成立的性质：
 * 1. 令牌**一次性**——重放必须失败，否则"一次性"就只是文档里的说法；
 * 2. 令牌**会过期**；
 * 3. 令牌与来源**绑定**——被别的页面拾取也换不出会话。
 */

import { describe, expect, it } from 'vitest';

import { BridgeSessionService } from '../src/bridge/session';

/** 可控时钟，用来测过期而不真的等待。 */
function clock(start = 1_000_000): { now: () => number; advance: (ms: number) => void } {
  let current = start;
  return {
    now: () => current,
    advance: (ms: number) => {
      current += ms;
    },
  };
}

describe('BridgeSessionService', () => {
  it('令牌可兑换为会话', () => {
    const service = new BridgeSessionService();
    const { token } = service.mintToken();
    const session = service.exchange(token);
    expect(session).not.toBeNull();
    expect(service.verify(session?.sessionId ?? '')).not.toBeNull();
  });

  it('令牌只能兑换一次', () => {
    const service = new BridgeSessionService();
    const { token } = service.mintToken();
    expect(service.exchange(token)).not.toBeNull();
    expect(service.exchange(token)).toBeNull();
  });

  it('未签发的令牌兑换失败', () => {
    const service = new BridgeSessionService();
    expect(service.exchange('not-a-real-token')).toBeNull();
  });

  it('令牌过期后无法兑换', () => {
    const time = clock();
    const service = new BridgeSessionService({ now: time.now });
    const { token } = service.mintToken();
    time.advance(61_000);
    expect(service.exchange(token)).toBeNull();
  });

  it('令牌与来源绑定：来源不符时不兑换', () => {
    const service = new BridgeSessionService();
    const { token } = service.mintToken('http://module.test');
    expect(service.exchange(token, 'http://evil.test')).toBeNull();
  });

  it('令牌与来源绑定：令牌因来源不符作废后不可重试', () => {
    const service = new BridgeSessionService();
    const { token } = service.mintToken('http://module.test');
    expect(service.exchange(token, 'http://evil.test')).toBeNull();
    // 来源不符也要消费掉令牌，否则攻击者可以反复试来源。
    expect(service.exchange(token, 'http://module.test')).toBeNull();
  });

  it('未绑定来源的令牌不校验来源', () => {
    const service = new BridgeSessionService();
    const { token } = service.mintToken(null);
    expect(service.exchange(token, 'http://any.test')).not.toBeNull();
  });

  it('会话过期后失效', () => {
    const time = clock();
    const service = new BridgeSessionService({ now: time.now });
    const session = service.exchange(service.mintToken().token);
    const id = session?.sessionId ?? '';
    expect(service.verify(id)).not.toBeNull();
    time.advance(13 * 60 * 60 * 1000);
    expect(service.verify(id)).toBeNull();
  });

  it('主动登出后会话立即失效', () => {
    const service = new BridgeSessionService();
    const session = service.exchange(service.mintToken().token);
    const id = session?.sessionId ?? '';
    service.revoke(id);
    expect(service.verify(id)).toBeNull();
  });

  it('每次签发的令牌都不同', () => {
    const service = new BridgeSessionService();
    const tokens = new Set(Array.from({ length: 20 }, () => service.mintToken().token));
    expect(tokens.size).toBe(20);
  });
});
