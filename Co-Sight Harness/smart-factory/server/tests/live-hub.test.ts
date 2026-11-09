import { test } from 'node:test';
import assert from 'node:assert/strict';
import { liveHub } from '../src/shared/live/live-hub.js';

const TIMEOUT = Symbol('timeout');

/** 给等待类断言加护栏：预期内的放行应立刻发生，迟迟不来的即判失败。 */
function withTimeout<T>(promise: Promise<T>, ms = 150): Promise<T | typeof TIMEOUT> {
  return Promise.race([promise, new Promise<typeof TIMEOUT>((resolve) => setTimeout(() => resolve(TIMEOUT), ms))]);
}

test('waitFor 先注册：settle 立即放行', async () => {
  const decision = liveHub.waitFor<string>('m1');
  liveHub.settle('m1', 'approved');
  assert.equal(await withTimeout(decision), 'approved');
});

test('settle 先到（广播先于注册的窗口）：暂存后 waitFor 立即取到，不挂死', async () => {
  liveHub.settle('m2', 'approved');
  assert.equal(await withTimeout(liveHub.waitFor<string>('m2')), 'approved');
});

test('暂存只消费一次：取走后再等同一 key 不会再收到旧值', async () => {
  liveHub.settle('m3', 'approved');
  assert.equal(await withTimeout(liveHub.waitFor<string>('m3')), 'approved');
  assert.equal(await withTimeout(liveHub.waitFor<string>('m3')), TIMEOUT);
});
