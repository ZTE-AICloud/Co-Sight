// SPDX-License-Identifier: Apache-2.0
/**
 * @file chat-socket.test.ts
 * @description 断线后的自动重连行为。
 *
 * 联调时真实出现过：服务端按心跳超时 close(1000) 后，客户端既不重连也不重订阅，
 * 用户只能回观测页点「恢复对话」。这里钉住三点：
 *   1. 非主动断开 → 按退避自动重连；
 *   2. 主动 disconnect → 不再拉起；
 *   3. 浏览器 online / 可见性恢复 → 立即重连，不等退避。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatSocket } from "../chat-socket";

/** 只实现 ChatSocket 用到的成员；所有实例按创建顺序收集。 */
class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState: number = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  readonly sent: string[] = [];
  /** 客户端主动 close 时传入的参数（看门狗测试用）。 */
  readonly closeCalls: Array<{ code?: number; reason?: string }> = [];

  constructor(readonly url: string) {
    instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closeCalls.push({ code, reason });
    this.readyState = FakeWebSocket.CLOSED;
  }

  /** 模拟握手成功。 */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** 模拟服务端主动断开（心跳超时 / 后端重启）。 */
  serverClose(code = 1000, reason = "心跳超时"): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason });
  }
}

const instances: FakeWebSocket[] = [];
let socket: ChatSocket | null = null;

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  socket?.disconnect();
  socket = null;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ChatSocket 自动重连", () => {
  it("服务端心跳超时断开后按退避自动重连，并保留会话标识", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    expect(instances).toHaveLength(1);
    instances[0]!.open();
    await connected;

    socket.sessionId = "sess_1";
    instances[0]!.serverClose(1000, "心跳超时");
    expect(socket.state).toBe("disconnected");

    // 第一次退避是 500ms
    await vi.advanceTimersByTimeAsync(499);
    expect(instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(instances).toHaveLength(2);

    instances[1]!.open();
    await vi.advanceTimersByTimeAsync(0);
    expect(socket.state).toBe("connected");
    // 重连不丢会话标识：上层据此重新订阅
    expect(socket.sessionId).toBe("sess_1");
  });

  it("退避重连失败会继续排下一次（0.5s → 1s）", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    instances[0]!.open();
    await connected;

    instances[0]!.serverClose();
    await vi.advanceTimersByTimeAsync(500);
    expect(instances).toHaveLength(2);
    instances[1]!.serverClose();

    await vi.advanceTimersByTimeAsync(999);
    expect(instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(instances).toHaveLength(3);
  });

  it("主动 disconnect 之后不再重连", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    instances[0]!.open();
    await connected;

    socket.disconnect();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(instances).toHaveLength(1);
  });

  it("浏览器恢复在线时立即重连，不等退避", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    instances[0]!.open();
    await connected;

    instances[0]!.serverClose();
    expect(instances).toHaveLength(1);

    // 退避表还没到点，online 事件应当立即拉起新连接
    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(instances).toHaveLength(2);
  });

  it("连接仍然存活时 online 只补一次心跳，不新建连接", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    instances[0]!.open();
    await connected;

    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);

    expect(instances).toHaveLength(1);
    expect(instances[0]!.sent.some((frame) => JSON.parse(frame).method === "ping")).toBe(true);
  });
});

describe("ChatSocket 半开连接看门狗", () => {
  /** 模拟服务端下行帧（pong 或任意事件）。 */
  function deliver(target: FakeWebSocket, method: string): void {
    target.onmessage?.({
      data: JSON.stringify({ id: "f1", type: "response", method, timestamp: Date.now(), payload: {} }),
    });
  }

  it("连续 3 个心跳周期没有下行帧时主动 close(4001)", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    const first = instances[0]!;
    first.open();
    await connected;

    await vi.advanceTimersByTimeAsync(30_000 * 2);
    expect(first.closeCalls).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(first.closeCalls[first.closeCalls.length - 1]).toEqual({
      code: 4001,
      reason: "pong timeout",
    });
  });

  it("每个周期都能收到下行帧时不会被误杀", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    const first = instances[0]!;
    first.open();
    await connected;

    for (let i = 0; i < 6; i += 1) {
      await vi.advanceTimersByTimeAsync(30_000);
      deliver(first, "pong");
    }

    expect(first.closeCalls).toHaveLength(0);
  });

  it("retryNow 跳过退避等待，立即重新连接并清零次数", async () => {
    socket = new ChatSocket();
    const connected = socket.connect();
    instances[0]!.open();
    await connected;

    instances[0]!.serverClose();
    expect(socket.state).toBe("disconnected");
    expect(socket.reconnectAttempts).toBe(1);

    socket.retryNow();
    await vi.advanceTimersByTimeAsync(0);

    expect(instances).toHaveLength(2);
    expect(socket.reconnectAttempts).toBe(0);
  });
});
