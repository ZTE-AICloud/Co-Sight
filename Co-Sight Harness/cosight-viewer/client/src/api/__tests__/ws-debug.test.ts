// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * 诊断日志开关的行为约定。
 *
 * 最重要的两条:
 *   1. 关闭时**一次 console 都不许调** —— 这才是"关掉即零成本"。
 *   2. HashRouter 下查询串在 `#` 后面,`?wsDebug=1` 必须能在 hash 里被读到。
 */

const STORAGE_KEY = "cosight:wsDebug";

/** 每个用例都重新 import,绕开模块级缓存 */
async function load() {
  vi.resetModules();
  return import("../ws-debug");
}

function setLocation(search: string, hash: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { search, hash, href: `http://localhost:4830/${hash}` },
  });
}

let logSpy: ReturnType<typeof vi.spyOn>;

/** 第 n 次 console.log 的参数表(先断言过次数再用)。 */
function callOf(n: number): unknown[] {
  const call = logSpy.mock.calls[n];
  if (!call) throw new Error(`console.log 没有被第 ${n + 1} 次调用`);
  return call;
}

beforeEach(() => {
  window.localStorage.clear();
  logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
});

afterEach(() => {
  logSpy.mockRestore();
  window.localStorage.clear();
});

describe("isWsDebugEnabled", () => {
  it("is off by default", async () => {
    setLocation("", "");
    const { isWsDebugEnabled } = await load();
    expect(isWsDebugEnabled()).toBe(false);
  });

  it("reads ?wsDebug=1 from the hash — HashRouter puts the query after #", async () => {
    setLocation("", "#/chat?wsDebug=1");
    const { isWsDebugEnabled } = await load();
    expect(isWsDebugEnabled()).toBe(true);
  });

  it("reads ?wsDebug=1 from a plain search string too", async () => {
    setLocation("?wsDebug=1", "");
    const { isWsDebugEnabled } = await load();
    expect(isWsDebugEnabled()).toBe(true);
  });

  it("remembers the choice so later navigations keep it", async () => {
    setLocation("", "#/chat?wsDebug=1");
    const first = await load();
    expect(first.isWsDebugEnabled()).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");

    // 换页后 URL 上不再带参数,应沿用上次设置
    setLocation("", "#/sessions");
    const second = await load();
    expect(second.isWsDebugEnabled()).toBe(true);
  });

  it("turns off and clears the stored value with ?wsDebug=0", async () => {
    window.localStorage.setItem(STORAGE_KEY, "1");
    setLocation("", "#/chat?wsDebug=0");
    const { isWsDebugEnabled } = await load();
    expect(isWsDebugEnabled()).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("logging output", () => {
  it("writes nothing at all while off", async () => {
    setLocation("", "");
    const { wsLogLifecycle, wsLogFrame } = await load();

    wsLogLifecycle("connected", "ws://x");
    wsLogFrame("←", "chat.delta", 42, { payload: { big: "x".repeat(1000) } });

    expect(logSpy).not.toHaveBeenCalled();
  });

  it("prints lifecycle plus每一帧 的方向/方法/体积/完整 payload", async () => {
    setLocation("", "#/chat?wsDebug=1");
    const { wsLogLifecycle, wsLogFrame } = await load();

    const payload = { payload: { prompt: "hi" } };
    wsLogLifecycle("connected", "ws://x");
    wsLogLifecycle("disconnected", "code=1006");
    wsLogFrame("→", "send", 7, payload);
    wsLogFrame("←", "chat.delta", 42, { payload: { delta: "hel" } });

    expect(logSpy).toHaveBeenCalledTimes(4);
    expect(callOf(0)[0]).toContain("connected");
    expect(callOf(1)[0]).toContain("code=1006");
    expect(callOf(2)[0]).toBe("[ChatSocket] → send 7B");
    expect(callOf(2)[1]).toBe(payload);
    expect(callOf(3)[0]).toBe("[ChatSocket] ← chat.delta 42B");
  });

  it("never logs heartbeats — a ping/pong pair every 30s is pure noise", async () => {
    setLocation("", "#/chat?wsDebug=1");
    const { wsLogFrame } = await load();

    wsLogFrame("→", "ping", 10, {});
    wsLogFrame("←", "pong", 10, {});

    expect(logSpy).not.toHaveBeenCalled();
  });

  it("can be flipped at runtime via setWsDebugEnabled", async () => {
    setLocation("", "");
    const { setWsDebugEnabled, wsLogFrame } = await load();

    wsLogFrame("←", "chat.delta", 1);
    expect(logSpy).not.toHaveBeenCalled();

    setWsDebugEnabled(true);
    wsLogFrame("←", "chat.delta", 1);
    expect(logSpy).toHaveBeenCalledTimes(1);
  });
});
