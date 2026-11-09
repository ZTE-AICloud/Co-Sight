/**
 * 权限位的两条判断：Windows、以及"这个文件系统没有 chmod"。
 *
 * 这两种情形**本机一个都复现不了**——Linux 上 `statSync` 不会给你 `0o666`，
 * `chmod` 也不会抛 `ENOSYS`。所以判定写成纯函数，测试直接喂参数；
 * 这是这批"只在别人机器上发作"的问题唯一的守卫方式（见 `lib/file-mode.ts`）。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { writeFileAtomicSync } from '../src/lib/atomic-file';
import { checkSecretFileMode, chmodBestEffort, posixModeIsMeaningful } from '../src/lib/file-mode';

let scratch: string;

beforeEach(() => {
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-file-mode-'));
});

afterEach(() => {
  vi.restoreAllMocks();
  fs.rmSync(scratch, { recursive: true, force: true });
});

function errno(code: string): NodeJS.ErrnoException {
  const error = new Error(code) as NodeJS.ErrnoException;
  error.code = code;
  return error;
}

/** 只看权限位，不看文件类型位。 */
function modeBits(target: string): number {
  return fs.statSync(target).mode & 0o777;
}

describe('posixModeIsMeaningful', () => {
  it('只把 Windows 排除在外', () => {
    expect(posixModeIsMeaningful('win32')).toBe(false);
    expect(posixModeIsMeaningful('linux')).toBe(true);
    expect(posixModeIsMeaningful('darwin')).toBe(true);
  });
});

describe('checkSecretFileMode', () => {
  it('Windows 上 0o666 是"这里不用 POSIX 权限位"，不是"权限太宽"', () => {
    // 这条是那类"每次启动都刷一条假告警"的根因：Windows 上 Node 对普通文件
    // 一律报 0o666，拿它跟 0600 比永远不等。
    expect(checkSecretFileMode(0o666, 'win32')).toEqual({ status: 'not-applicable' });
    expect(checkSecretFileMode(0o444, 'win32')).toEqual({ status: 'not-applicable' });
  });

  it('POSIX 上同样一个 0o666 就是真的告警，并且带上实际权限', () => {
    expect(checkSecretFileMode(0o666, 'linux')).toEqual({ status: 'permissive', mode: 0o666 });
    expect(checkSecretFileMode(0o640, 'linux')).toEqual({ status: 'permissive', mode: 0o640 });
  });

  it('0600 通过，0600 之外的任何一位都拦', () => {
    expect(checkSecretFileMode(0o600, 'linux')).toEqual({ status: 'ok' });
    expect(checkSecretFileMode(0o700, 'linux')).toEqual({ status: 'permissive', mode: 0o700 });
    expect(checkSecretFileMode(0o500, 'linux')).toEqual({ status: 'permissive', mode: 0o500 });
  });

  it('文件不存在时报 absent——包括在 Windows 上（没文件就没有权限可谈）', () => {
    expect(checkSecretFileMode(null, 'linux')).toEqual({ status: 'absent' });
    expect(checkSecretFileMode(null, 'win32')).toEqual({ status: 'absent' });
  });
});

describe('chmodBestEffort', () => {
  it('正常文件系统上真的把权限设成给定值', () => {
    const file = path.join(scratch, 'token');
    fs.writeFileSync(file, 'x');
    chmodBestEffort(file, 0o600);
    expect(modeBits(file)).toBe(0o600);
  });

  it('ENOSYS（没有 chmod 这个概念的挂载）被吞掉', () => {
    vi.spyOn(fs, 'chmodSync').mockImplementation(() => {
      throw errno('ENOSYS');
    });
    expect(() => chmodBestEffort(path.join(scratch, 'x'), 0o600)).not.toThrow();
  });

  it('其他错误照抛：POSIX 上 chmod 失败是真问题，静默放过会让人以为权限收紧了', () => {
    vi.spyOn(fs, 'chmodSync').mockImplementation(() => {
      throw errno('EPERM');
    });
    expect(() => chmodBestEffort(path.join(scratch, 'x'), 0o600)).toThrow(/EPERM/);
  });
});

describe('原子写在 chmod 不可用时仍然完成', () => {
  it('令牌/密钥照样落盘，内容正确——收紧权限失败不该升级成"写不进去"', () => {
    // 修复前的真实故障路径：writeFileAtomicSync 最后一步 chmodSync 无保护地抛，
    // 于是"文件系统不支持 chmod"表现成"服务启动失败"。
    vi.spyOn(fs, 'chmodSync').mockImplementation(() => {
      throw errno('ENOSYS');
    });

    const file = path.join(scratch, 'nested', '.module-token');
    expect(() => writeFileAtomicSync(file, 'secret-token-value\n', 0o600)).not.toThrow();
    expect(fs.readFileSync(file, 'utf8')).toBe('secret-token-value\n');
    // 不留半成品：临时文件命名是 `${file}.${pid}.${时间戳}.tmp`。
    expect(fs.readdirSync(path.dirname(file))).toEqual(['.module-token']);
  });
});
