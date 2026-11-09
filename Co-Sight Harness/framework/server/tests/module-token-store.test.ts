/**
 * `ModuleTokenStore` 单元测试。
 *
 * 重点在两条容易被"顺手优化"掉的性质上：
 * **重启不轮换**（每次启动换令牌等于把文件退化成启动期随机数）与
 * **看不懂的文件必须抛错**（静默覆盖 = 静默数据丢失，与 `CredentialStore` 同一原则）。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { MODULE_TOKEN_FILE_NAME } from '../src/config/paths';
import { ModuleTokenError, ModuleTokenStore } from '../src/credentials/module-token';

let dir: string;
let filePath: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-token-'));
  filePath = path.join(dir, MODULE_TOKEN_FILE_NAME);
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('ModuleTokenStore', () => {
  it('ensure() 首次生成，再次调用返回同一个值（重启不轮换）', () => {
    const store = new ModuleTokenStore(filePath);
    const first = store.ensure();
    const second = new ModuleTokenStore(filePath).ensure();
    expect(second).toBe(first);
  });

  it('生成的令牌是 43 字符 base64url，解码 32 字节', () => {
    const token = new ModuleTokenStore(filePath).ensure();
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(Buffer.from(token, 'base64url')).toHaveLength(32);
  });

  it('文件权限 0600，且内容只有一行', () => {
    const store = new ModuleTokenStore(filePath);
    store.ensure();
    expect(store.fileMode()).toBe(0o600);
    expect(fs.readFileSync(filePath, 'utf8').trim().split('\n')).toHaveLength(1);
  });

  it('不留 .tmp 残留', () => {
    new ModuleTokenStore(filePath).ensure();
    expect(fs.readdirSync(dir).filter((name) => name.endsWith('.tmp'))).toEqual([]);
  });

  it('read() 在文件不存在时返回 null', () => {
    expect(new ModuleTokenStore(filePath).read()).toBeNull();
  });

  it('内容非法时 read() 抛 ModuleTokenError，而不是当作合法令牌', () => {
    const store = new ModuleTokenStore(filePath);
    for (const bad of ['', '   \n', 'has space here', 'short', 'a'.repeat(15)]) {
      fs.writeFileSync(filePath, bad, { mode: 0o600 });
      expect(() => store.read(), JSON.stringify(bad)).toThrow(ModuleTokenError);
    }
  });

  it('内容非法时 verify() 返回 false 而不是抛异常', () => {
    fs.writeFileSync(filePath, 'has space here', { mode: 0o600 });
    const store = new ModuleTokenStore(filePath);
    expect(store.verify('anything')).toBe(false);
  });

  it('verify() 对错令牌返回 false，对正确令牌返回 true', () => {
    const store = new ModuleTokenStore(filePath);
    const token = store.ensure();
    expect(store.verify(token)).toBe(true);
    expect(store.verify(`${token}x`)).toBe(false);
    expect(store.verify('')).toBe(false);
  });

  it('rotate() 换新值，revoke() 幂等且此后 read() 为 null', () => {
    const store = new ModuleTokenStore(filePath);
    const first = store.ensure();
    const second = store.rotate();
    expect(second).not.toBe(first);
    expect(store.read()).toBe(second);

    store.revoke();
    store.revoke();
    expect(store.read()).toBeNull();
    expect(store.fileMode()).toBeNull();
  });

  it('父目录不存在时会自己建出来', () => {
    const nested = path.join(dir, 'a', 'b', MODULE_TOKEN_FILE_NAME);
    const store = new ModuleTokenStore(nested);
    expect(store.ensure()).toHaveLength(43);
    expect(store.verify(store.read() ?? '')).toBe(true);
  });
});
