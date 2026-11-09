/**
 * 密钥存储（D26 = A）。
 *
 * 这里测的是**文件权限**与**内容边界**，而不是 CRUD 本身：
 * - 权限错了（0644）等于密钥对同机其他用户可见，是真正的事故；
 * - 内容边界决定了"看不懂的文件"会被拒绝，还是被下一次写入静默覆盖。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CredentialStore, CredentialsError, secretRef } from '../src/credentials/store';

let home: string;
let filePath: string;

beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-cred-'));
  filePath = path.join(home, '.credentials.yaml');
});

afterEach(() => {
  fs.rmSync(home, { recursive: true, force: true });
});

describe('CredentialStore', () => {
  it('文件不存在时读出空集合，而不是报错', () => {
    const store = new CredentialStore(filePath);
    expect(store.read('model:1')).toBeNull();
    expect(store.listRefs()).toEqual([]);
  });

  it('写入后文件权限是 0600', async () => {
    const store = new CredentialStore(filePath);
    await store.set('model:abc', 'sk-secret');
    expect(fs.statSync(filePath).mode & 0o777).toBe(0o600);
  });

  it('目录权限被收紧到 0700', async () => {
    const nested = path.join(home, 'deep', '.credentials.yaml');
    await new CredentialStore(nested).set('model:a', 'v');
    expect(fs.statSync(path.dirname(nested)).mode & 0o777).toBe(0o700);
  });

  it('写入的值可以被新的实例读回（确实落盘）', async () => {
    const store = new CredentialStore(filePath);
    await store.set('model:abc', 'sk-secret');
    expect(store.read('model:abc')).toBe('sk-secret');
    expect(store.has('model:abc')).toBe(true);
    expect(new CredentialStore(filePath).read('model:abc')).toBe('sk-secret');
  });

  it('写入时去掉首尾空白，拒绝空值', async () => {
    const store = new CredentialStore(filePath);
    await store.set('model:abc', '  sk-x  ');
    expect(store.read('model:abc')).toBe('sk-x');
    await expect(store.set('model:empty', '   ')).rejects.toThrow(CredentialsError);
  });

  it('删除是幂等的', async () => {
    const store = new CredentialStore(filePath);
    await store.set('model:abc', 'v');
    await store.delete('model:abc');
    await store.delete('model:abc');
    expect(store.listRefs()).toEqual([]);
  });

  it('并发写入不会互相覆盖（写操作串行）', async () => {
    const store = new CredentialStore(filePath);
    await Promise.all([
      store.set('model:a', '1'),
      store.set('model:b', '2'),
      store.set('agent-proxy:c', '3'),
    ]);
    expect(new CredentialStore(filePath).listRefs()).toEqual([
      'agent-proxy:c',
      'model:a',
      'model:b',
    ]);
  });

  it('一次写入失败不会让后续写入永久失败（链条不断）', async () => {
    const store = new CredentialStore(filePath);
    await expect(store.set('model:bad', '')).rejects.toThrow(CredentialsError);
    await store.set('model:ok', 'fine');
    expect(store.read('model:ok')).toBe('fine');
  });

  it('非字符串的值被丢弃，不会当作密钥使用', async () => {
    fs.writeFileSync(filePath, 'version: 1\nsecrets:\n  model:a: good\n  model:b:\n    nested: x\n');
    const store = new CredentialStore(filePath);
    expect(store.read('model:a')).toBe('good');
    expect(store.read('model:b')).toBeNull();
    expect(store.listRefs()).toEqual(['model:a']);
  });

  it('secrets 段缺失视为空文件（首次使用前的正常状态）', () => {
    fs.writeFileSync(filePath, 'version: 1\n');
    expect(new CredentialStore(filePath).listRefs()).toEqual([]);
  });

  it('顶层不是映射时报错，避免覆盖用户原有内容', () => {
    fs.writeFileSync(filePath, '- 1\n- 2\n');
    expect(() => new CredentialStore(filePath).listRefs()).toThrow(CredentialsError);
    fs.writeFileSync(filePath, 'just a string\n');
    expect(() => new CredentialStore(filePath).listRefs()).toThrow(CredentialsError);
  });

  it('secrets 段不是映射时报错', () => {
    fs.writeFileSync(filePath, 'version: 1\nsecrets: oops\n');
    expect(() => new CredentialStore(filePath).listRefs()).toThrow(CredentialsError);
  });

  it('YAML 语法错误时报错，且不清空文件', () => {
    const broken = 'version: 1\nsecrets: [unclosed\n';
    fs.writeFileSync(filePath, broken);
    expect(() => new CredentialStore(filePath).listRefs()).toThrow(CredentialsError);
    expect(fs.readFileSync(filePath, 'utf8')).toBe(broken);
  });

  it('secretRef 生成稳定且带类别前缀的键', () => {
    expect(secretRef('model', 'id-1')).toBe('model:id-1');
    expect(secretRef('agent-proxy', 'id-2')).toBe('agent-proxy:id-2');
  });
});
