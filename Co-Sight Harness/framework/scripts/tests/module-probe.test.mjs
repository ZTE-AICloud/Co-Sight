/**
 * 模块注册表的探活报告。
 *
 * 两条边界：
 *  - 平台不支持的模块**不探活**：它本来就没被拉起，探活只会报 ECONNREFUSED，
 *    读起来像模块坏了（Windows 上的 smart-factory 就是这种）；
 *  - 真正没起来的模块仍然要报成"不可达"，不能因为上一条而放宽。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { formatProbeReport, probeModules } from '../lib/module-probe.mjs';

/** 一个不会有人监听的回环端口：立刻 ECONNREFUSED，不依赖网络。 */
const DEAD_PORT = 1;

function manifest(id, healthcheck) {
  return {
    dir: id,
    file: `/${id}/module.json`,
    hasFile: true,
    id,
    label: id,
    entry: null,
    healthcheck,
    problem: null,
  };
}

describe('模块探活报告', () => {
  it('平台不支持的模块不探活，报"本平台不适用"', async () => {
    const skipped = new Map([['smart-factory', '本平台不适用（仅支持 linux-x64，当前 win32-x64），本次启动未拉起']]);
    const [result] = await probeModules(
      [manifest('smart-factory', `http://127.0.0.1:${DEAD_PORT}/`)],
      { platformSkipped: skipped },
    );

    assert.equal(result.status, 'skipped');
    assert.match(result.detail, /本平台不适用/);
    assert.doesNotMatch(result.detail, /ECONNREFUSED|不可达/);
  });

  it('未跳过且端口没人监听时仍报不可达', async () => {
    const [result] = await probeModules([manifest('other', `http://127.0.0.1:${DEAD_PORT}/`)]);

    assert.equal(result.status, 'unreachable');
    assert.match(result.detail, /不可达/);
  });

  it('跳过与不可达在报告里用不同记号', async () => {
    const results = await probeModules(
      [manifest('smart-factory', `http://127.0.0.1:${DEAD_PORT}/`), manifest('other', `http://127.0.0.1:${DEAD_PORT}/`)],
      { platformSkipped: new Map([['smart-factory', '本平台不适用（仅支持 linux-x64，当前 win32-x64）']]) },
    );
    const lines = formatProbeReport(results);

    assert.match(lines.join('\n'), /· smart-factory（smart-factory）：本平台不适用/);
    assert.match(lines.join('\n'), /— other（other）：不可达/);
  });
});
