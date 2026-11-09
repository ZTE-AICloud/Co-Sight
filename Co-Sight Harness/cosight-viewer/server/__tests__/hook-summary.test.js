// SPDX-License-Identifier: Apache-2.0
/**
 * @file Unit tests for server/lib/hook-summary.js — 低频 hook 接收汇总计数器。
 */

const { describe, it, mock, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const {
  createHookSummary,
  resolveSummaryMs,
  DEFAULT_SUMMARY_MS,
} = require("../lib/hook-summary");

describe("createHookSummary", () => {
  afterEach(() => {
    mock.timers.reset();
  });

  it("increment/reset/getCount 基本计数", () => {
    const s = createHookSummary(() => {});
    assert.equal(s.getCount(), 0);
    s.increment();
    s.increment();
    s.increment();
    assert.equal(s.getCount(), 3);
    s.reset();
    assert.equal(s.getCount(), 0);
  });

  it("窗口到期时输出收到的条数并清零,重复 start 复用同一定时器", () => {
    mock.timers.enable({ apis: ["setInterval"] });
    const lines = [];
    const s = createHookSummary((msg) => lines.push(msg), 60000);
    const t1 = s.start();
    const t2 = s.start();
    assert.equal(t1, t2, "重复 start 应返回同一定时器");

    s.increment();
    s.increment();
    mock.timers.tick(60000);
    assert.equal(lines.length, 1);
    assert.match(lines[0], /\[HOOK_SUMMARY\] received 2 hooks in last 1min/);
    assert.equal(s.getCount(), 0, "汇总后应清零");

    s.increment();
    mock.timers.tick(60000);
    assert.equal(lines.length, 2);
    assert.match(lines[1], /received 1 hooks/);
    s.stop();
  });

  it("窗口内无 hook 也输出 0 条(链路存活心跳)", () => {
    mock.timers.enable({ apis: ["setInterval"] });
    const lines = [];
    const s = createHookSummary((msg) => lines.push(msg), 60000);
    s.start();
    mock.timers.tick(60000);
    assert.equal(lines.length, 1);
    assert.match(lines[0], /received 0 hooks/);
    s.stop();
  });

  it("logFn 抛异常不影响后续汇总", () => {
    mock.timers.enable({ apis: ["setInterval"] });
    let calls = 0;
    const s = createHookSummary(() => {
      calls++;
      throw new Error("log fail");
    }, 60000);
    s.start();
    s.increment();
    mock.timers.tick(60000); // 第一次抛异常被内部捕获
    mock.timers.tick(60000); // 第二次照常触发
    assert.equal(calls, 2);
    s.stop();
  });
});

describe("resolveSummaryMs", () => {
  it("解析环境变量,非法输入回退默认 5 分钟", () => {
    assert.equal(resolveSummaryMs("300000"), 300000);
    assert.equal(resolveSummaryMs("abc"), DEFAULT_SUMMARY_MS);
    assert.equal(resolveSummaryMs("0"), DEFAULT_SUMMARY_MS);
    assert.equal(resolveSummaryMs("-1"), DEFAULT_SUMMARY_MS);
    assert.equal(resolveSummaryMs(""), DEFAULT_SUMMARY_MS);
    assert.equal(resolveSummaryMs(undefined), DEFAULT_SUMMARY_MS);
    assert.equal(DEFAULT_SUMMARY_MS, 5 * 60 * 1000);
  });
});
