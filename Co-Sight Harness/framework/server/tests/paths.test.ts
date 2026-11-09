/**
 * 数据目录布局与权限（D26 = A）。
 *
 * 权限这几条是安全要求而不是风格偏好：`.credentials.yaml` 存的是模型与代理的
 * 明文密钥，文件必须 0600、所在目录必须 0700，否则同机其他用户可读。
 * 断言用 `stat` 的实际 mode 位，而不是"调用了 chmod"——后者证明不了结果。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  credentialsFileMode,
  ensureDataPaths,
  ensureDirectory,
  resolveDataPaths,
} from '../src/config/paths';

let home: string;

beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-paths-'));
});

afterEach(() => {
  vi.restoreAllMocks();
  fs.rmSync(home, { recursive: true, force: true });
});

/** 只看权限位，不看文件类型位。 */
function modeBits(target: string): number {
  return fs.statSync(target).mode & 0o777;
}

describe('resolveDataPaths', () => {
  it('密钥与业务数据分文件存放，备份 sqlite 不会连带泄漏密钥', () => {
    const paths = resolveDataPaths('/tmp/cosight');
    expect(paths.home).toBe('/tmp/cosight');
    expect(paths.database).toBe(path.join('/tmp/cosight', 'sqlite.db'));
    expect(paths.credentials).toBe(path.join('/tmp/cosight', '.credentials.yaml'));
    expect(paths.modules).toBe(path.join('/tmp/cosight', 'modules'));
  });

  it('密钥文件模式是 0600', () => {
    expect(credentialsFileMode()).toBe(0o600);
  });
});

describe('ensureDirectory', () => {
  it('建目录并收紧到 0700（不被进程 umask 削弱）', () => {
    const dir = path.join(home, 'nested', 'data');
    ensureDirectory(dir);
    expect(fs.existsSync(dir)).toBe(true);
    expect(modeBits(dir)).toBe(0o700);
  });

  it('已存在的目录权限被纠正回 0700', () => {
    const dir = path.join(home, 'loose');
    fs.mkdirSync(dir, { recursive: true, mode: 0o755 });
    fs.chmodSync(dir, 0o755);
    ensureDirectory(dir);
    expect(modeBits(dir)).toBe(0o700);
  });

  it('幂等：重复调用不报错', () => {
    const dir = path.join(home, 'again');
    ensureDirectory(dir);
    ensureDirectory(dir);
    expect(modeBits(dir)).toBe(0o700);
  });

  it('文件系统不支持 chmod（ENOSYS）时不阻断启动', () => {
    // 非 POSIX 挂载点上的真实情况：收紧权限失败，但这不该让整个平台起不来。
    const error = new Error('not implemented') as NodeJS.ErrnoException;
    error.code = 'ENOSYS';
    vi.spyOn(fs, 'chmodSync').mockImplementation(() => {
      throw error;
    });

    expect(() => ensureDirectory(path.join(home, 'nochmod'))).not.toThrow();
  });

  it('其他 chmod 错误照常抛出（不吞异常）', () => {
    const error = new Error('permission denied') as NodeJS.ErrnoException;
    error.code = 'EPERM';
    vi.spyOn(fs, 'chmodSync').mockImplementation(() => {
      throw error;
    });

    expect(() => ensureDirectory(path.join(home, 'denied'))).toThrow('permission denied');
  });
});

describe('ensureDataPaths', () => {
  it('一次性建好 home 与 modules，且都是 0700', () => {
    const paths = resolveDataPaths(home);
    ensureDataPaths(paths);
    expect(modeBits(paths.home)).toBe(0o700);
    expect(modeBits(paths.modules)).toBe(0o700);
  });
});
