import type { Envelope } from './envelope.js';

/** 订阅者：一个连接就是一个订阅者；`send` 返回 false 表示没能送达。 */
export interface Subscriber {
  send(envelope: Envelope): boolean;
}

const subscribers = new Map<string, Set<Subscriber>>();

/** 被阻塞的引擎：message id → 放行回调。真相在库里，这里只存句柄。 */
const waiters = new Map<string, (value: unknown) => void>();

/**
 * 决策先于等待者到达时的暂存：message id → 决策值。
 *
 * 兜住"广播先于注册"的窗口——客户端可能在引擎注册等待句柄之前就完成应答；
 * waitFor 注册时先取暂存，取走即删。message id 不复用，不会串线。
 */
const pendingSettlements = new Map<string, unknown>();

/**
 * 进程内实时扇出：会话 → 订阅者集合。
 *
 * 无回放：只投递给当前在线订阅者，服务端不缓冲历史事件。
 */
export const liveHub = {
  subscribe(sessionId: string, subscriber: Subscriber): void {
    const set = subscribers.get(sessionId) ?? new Set<Subscriber>();
    set.add(subscriber);
    subscribers.set(sessionId, set);
  },

  unsubscribe(sessionId: string, subscriber: Subscriber): void {
    const set = subscribers.get(sessionId);
    if (!set) return;
    set.delete(subscriber);
    if (set.size === 0) subscribers.delete(sessionId);
  },

  /** 连接断开时调用：从所有会话的订阅集合里摘掉它。 */
  unsubscribeAll(subscriber: Subscriber): void {
    for (const [sessionId, set] of subscribers) {
      set.delete(subscriber);
      if (set.size === 0) subscribers.delete(sessionId);
    }
  },

  broadcast(sessionId: string, envelope: Envelope): void {
    const set = subscribers.get(sessionId);
    if (!set) return;
    for (const subscriber of [...set]) subscriber.send(envelope);
  },

  subscriberCount(sessionId: string): number {
    return subscribers.get(sessionId)?.size ?? 0;
  },

  /**
   * 挂起等待一次决策（审批 / 交互）。
   *
   * 不设超时——出口只有应答、中止、服务重启、进程被杀。
   */
  waitFor<T>(key: string): Promise<T> {
    const stashed = pendingSettlements.get(key);
    if (stashed !== undefined) {
      pendingSettlements.delete(key);
      return Promise.resolve(stashed as T);
    }
    return new Promise<T>((resolve) => {
      waiters.set(key, resolve as (value: unknown) => void);
    });
  },

  /** 交付一次决策：有等待者即放行；没有则暂存，等 waitFor 注册时取走。 */
  settle<T>(key: string, value: T): void {
    const resolve = waiters.get(key);
    if (!resolve) {
      pendingSettlements.set(key, value);
      return;
    }
    waiters.delete(key);
    resolve(value);
  },

  hasWaiter(key: string): boolean {
    return waiters.has(key);
  },
};
