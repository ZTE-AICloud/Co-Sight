/**
 * 归档条目的可执行位补写。
 *
 * Windows 上 `fs.stat` 一律报 0666，解压后的可执行位断言在那里被跳过——
 * 这个纯函数是"产物拿到 Linux 上还能执行"的唯一本地防线，所以它必须单独有测试。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { withExecutableModes } from '../lib/archive/executable-modes.mjs';

const BASE = 'cosight-harness-1';
const TARGETS = [`${BASE}/start.mjs`, `${BASE}/modules/x/bin/claude`];

const file = (name, mode) => ({ path: `${BASE}/${name}`, kind: 'file', mode });

describe('可执行位补写', () => {
  it('声明的条目由 0644 补成 0755', () => {
    const [entry] = withExecutableModes([file('start.mjs', 0o644)], TARGETS);
    assert.equal(entry.mode, 0o755);
  });

  it('未声明的条目不动', () => {
    const [entry] = withExecutableModes([file('README.md', 0o644)], TARGETS);
    assert.equal(entry.mode, 0o644);
  });

  it('已经有 X 位的条目原样保留（可能比 0755 更严格）', () => {
    const [entry] = withExecutableModes([file('start.mjs', 0o700)], TARGETS);
    assert.equal(entry.mode, 0o700);
  });

  it('符号链接与目录不补：它们没有可执行位可言', () => {
    const entries = [
      { path: `${BASE}/start.mjs`, kind: 'symlink', mode: 0o644 },
      { path: `${BASE}/start.mjs`, kind: 'directory', mode: 0o755 },
    ];
    const [link, dir] = withExecutableModes(entries, TARGETS);
    assert.equal(link.mode, 0o644);
    assert.equal(dir.mode, 0o755);
  });

  it('不改入参', () => {
    const input = [file('start.mjs', 0o644)];
    withExecutableModes(input, TARGETS);
    assert.equal(input[0].mode, 0o644);
  });
});
