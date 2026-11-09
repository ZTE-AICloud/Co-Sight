/**
 * 模块注册表扫描。
 *
 * 关键行为是"坏清单不阻断扫描"：一个同事写错 module.json，不能连带让
 * 其他人已写好的模块也加载不出来。因此合法与非法要能并存于一次扫描结果里。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { scanModules } from '../src/modules/registry';

const HOST_ORIGIN = 'http://127.0.0.1:4310';

let modulesDir: string;

beforeEach(() => {
  modulesDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-modules-'));
});

afterEach(() => {
  fs.rmSync(modulesDir, { recursive: true, force: true });
});

function writeModule(id: string, manifest: unknown): void {
  const dir = path.join(modulesDir, id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, 'module.json'),
    typeof manifest === 'string' ? manifest : JSON.stringify(manifest, null, 2),
  );
}

function validManifest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schemaVersion: 1,
    id: 'agent-dev',
    name: { 'zh-CN': 'Agent 开发', 'en-US': 'Agent Dev' },
    description: { 'zh-CN': '开发与评估 Agent', 'en-US': 'Develop and evaluate agents' },
    version: '1.0.0',
    entry: 'http://127.0.0.1:5174/',
    allowedOrigins: ['http://127.0.0.1:5174'],
    mounts: [{ capability: 'agent-dev', path: '/agent-dev' }],
    ...overrides,
  };
}

describe('scanModules', () => {
  it('目录不存在时返回空结果，不报错', () => {
    const result = scanModules(path.join(modulesDir, 'missing'), HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid).toEqual([]);
  });

  it('空目录返回空结果', () => {
    expect(scanModules(modulesDir, HOST_ORIGIN).modules).toEqual([]);
  });

  it('接受合法清单', () => {
    writeModule('agent-dev', validManifest());
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.invalid).toEqual([]);
    expect(result.modules.map((m) => m.id)).toEqual(['agent-dev']);
  });

  it('JSON 语法错误被收集而不是抛出', () => {
    writeModule('broken', '{ not json');
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid).toHaveLength(1);
    expect(result.invalid[0]?.issues[0]?.code).toBe('invalid_json');
  });

  it('带 UTF-8 BOM 的清单照常接受（Windows 记事本存出来的就是这个）', () => {
    // 没有这一条时，BOM 会让 JSON.parse 抛错，一个写得好好的模块被收进 invalid、
    // 静默不注册——用户看到的是"功能没接上"，而错在一个看不见的字节上。
    writeModule('agent-dev', `\uFEFF${JSON.stringify(validManifest(), null, 2)}`);
    // 断言写的是"文件里真的有 BOM 字节"，而不是相信上面那个转义——
    // 否则这条测试会在 BOM 写丢的时候照样绿。
    expect(fs.readFileSync(path.join(modulesDir, 'agent-dev', 'module.json')).subarray(0, 3)).toEqual(
      Buffer.from([0xef, 0xbb, 0xbf]),
    );

    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.invalid).toEqual([]);
    expect(result.modules.map((m) => m.id)).toEqual(['agent-dev']);
  });

  it('契约不满足（缺 en-US 文案、id 含大写）被拒绝', () => {
    writeModule('bad-id', validManifest({ id: 'Bad_Id' }));
    writeModule('no-en', validManifest({ name: { 'zh-CN': '只有中文' } }));
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid).toHaveLength(2);
  });

  it('与宿主同源的模块被拒绝（D24 = A）', () => {
    writeModule(
      'same-origin',
      validManifest({
        entry: `${HOST_ORIGIN}/embed`,
        allowedOrigins: [HOST_ORIGIN],
      }),
    );
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid[0]?.issues.map((i) => i.code)).toContain('same_origin_as_host');
  });

  it('entry 不在白名单内时被拒绝', () => {
    writeModule('off-list', validManifest({ entry: 'http://other.test/' }));
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid[0]?.issues.map((i) => i.code)).toContain('origin_not_allowed');
  });

  it('合法与非法清单可以在同一次扫描中并存', () => {
    writeModule('agent-dev', validManifest());
    writeModule('broken', '{ not json');
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules.map((m) => m.id)).toEqual(['agent-dev']);
    expect(result.invalid).toHaveLength(1);
  });

  it('没有 module.json 的目录被忽略', () => {
    fs.mkdirSync(path.join(modulesDir, 'stray'), { recursive: true });
    const result = scanModules(modulesDir, HOST_ORIGIN);
    expect(result.modules).toEqual([]);
    expect(result.invalid).toEqual([]);
  });
});
