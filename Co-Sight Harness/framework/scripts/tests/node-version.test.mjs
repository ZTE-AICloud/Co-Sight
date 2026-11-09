/**
 * Node 版本区间判定。
 *
 * 这是产物启动的第一道闸门，它的坏失败模式只有一个：**它以为自己通过了**。
 * 所以测试分两半——一半是"该放行/该拦住的版本"，另一半是"不认识的写法必须抛错"。
 * 后者比前者重要：一个静默返回 true 的校验，等于没有校验。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  UnsupportedRangeError,
  compareVersions,
  parseVersion,
  satisfies,
} from '../lib/node-version.mjs';

/** 与 server/package.json 的 engines.node 同形，改那边这里会立刻红。 */
const RANGE = '^22.19.0 || >=24.0.0';

describe('版本区间判定：放行与拦截', () => {
  it('接受区间内的版本', () => {
    for (const version of ['22.19.0', '22.19.1', '22.20.0', '24.0.0', '24.13.1', '30.1.2']) {
      assert.equal(satisfies(version, RANGE), true, `${version} 应该被接受`);
    }
  });

  it('拦住区间外的版本（含"太老"与 23.x 这段空档）', () => {
    for (const version of ['18.20.0', '20.11.0', '22.18.9', '23.0.0', '23.11.1']) {
      assert.equal(satisfies(version, RANGE), false, `${version} 应该被拦住`);
    }
  });

  it('带 v 前缀与预发布后缀都能解析（预发布不改变比较结果）', () => {
    assert.equal(satisfies('v22.19.0', RANGE), true);
    assert.equal(satisfies('24.13.1-nightly20250101', '>=24.0.0'), true);
    assert.equal(satisfies('22.18.0-rc.1', RANGE), false);
  });
});

describe('版本区间判定：不认识的写法必须抛错', () => {
  it('抛 UnsupportedRangeError，调用方能与技术故障区分开', () => {
    for (const range of ['latest', 'next', '22.x', '*', '>=22 <25 || *', '']) {
      assert.throws(() => satisfies('22.19.0', range), UnsupportedRangeError, `「${range}」应该被拒绝`);
    }
  });

  it('省略次/修订号是**支持**的写法（`>=22` 等价 `>=22.0.0`），不是"看不懂"', () => {
    assert.equal(satisfies('22.19.0', '>=22'), true);
    assert.equal(satisfies('21.7.0', '>=22'), false);
  });

  it('看不懂的版本号也抛，而不是当 0.0.0 处理', () => {
    assert.throws(() => parseVersion('twenty-two'), UnsupportedRangeError);
  });
});

describe('比较与解析', () => {
  it('逐段比较，缺省段补 0', () => {
    assert.equal(compareVersions(parseVersion('22'), parseVersion('22.0.0')), 0);
    assert.equal(compareVersions(parseVersion('22.0.1'), parseVersion('22.0.0')), 1);
    assert.equal(compareVersions(parseVersion('21.99.99'), parseVersion('22.0.0')), -1);
  });

  it('^ 与 ~ 的边界（不实现 semver 的 0.x 特殊规则，这一点写在实现里）', () => {
    assert.equal(satisfies('22.99.0', '^22.19.0'), true);
    assert.equal(satisfies('23.0.0', '^22.19.0'), false);
    assert.equal(satisfies('22.19.5', '~22.19.0'), true);
    assert.equal(satisfies('22.20.0', '~22.19.0'), false);
  });

  it('同一组里的多个比较符是"且"', () => {
    assert.equal(satisfies('24.5.0', '>=24.0.0 <25.0.0'), true);
    assert.equal(satisfies('25.0.0', '>=24.0.0 <25.0.0'), false);
  });
});
