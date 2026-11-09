/**
 * 模块清单接口（C2 嵌入机制）。
 *
 * 这里验的是接口层最重要的一条约定：**坏清单不抛错，而是出现在 `invalid` 里**。
 * 如果某个同事的 module.json 写错就让接口 500，前端拿不到任何模块列表，
 * 表现会是"整个平台空白"，而真实原因只是某个可选模块的清单多了一个逗号。
 */

import fs from 'node:fs';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

/** 与宿主不同源的模块入口（D24 要求模块独立部署）。 */
const MODULE_ORIGIN = 'http://127.0.0.1:5174';

let context: TestContext;

function writeManifest(id: string, content: unknown): void {
  const dir = path.join(context.home, 'modules', id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'module.json'), JSON.stringify(content));
}

function validManifest(id: string): Record<string, unknown> {
  return {
    schemaVersion: 1,
    id,
    name: { 'zh-CN': '任务中心', 'en-US': 'Task Center' },
    description: { 'zh-CN': '任务管理模块', 'en-US': 'Task management' },
    version: '1.2.0',
    entry: `${MODULE_ORIGIN}/${id}/index.html`,
    allowedOrigins: [MODULE_ORIGIN],
    mounts: [{ capability: 'conversation', path: '/conversation' }],
  };
}

beforeEach(async () => {
  context = await createTestContext();
});

afterEach(async () => {
  await destroyTestContext(context);
});

describe('模块清单接口', () => {
  it('尚无模块接入时返回空列表而不是错误', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    // v1 的预期常态：同事的模块还没接进来。空不等于失败。
    expect(body.success).toBe(true);
    expect(body.data.modules).toEqual([]);
    expect(body.data.invalid).toEqual([]);
  });

  it('合法清单出现在 modules 里', async () => {
    writeManifest('task-center', validManifest('task-center'));
    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    const body = response.json();
    expect(body.data.modules).toHaveLength(1);
    expect(body.data.modules[0].id).toBe('task-center');
    expect(body.data.modules[0].icon).toBeNull();
    expect(body.data.invalid).toEqual([]);
  });

  it('清单 JSON 语法错误被收集进 invalid，其余模块照常返回', async () => {
    writeManifest('task-center', validManifest('task-center'));
    const brokenDir = path.join(context.home, 'modules', 'broken');
    fs.mkdirSync(brokenDir, { recursive: true });
    fs.writeFileSync(path.join(brokenDir, 'module.json'), '{ 这不是 JSON');

    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.data.modules).toHaveLength(1);
    expect(body.data.invalid).toHaveLength(1);
    expect(body.data.invalid[0].issues[0].code).toBe('invalid_json');
    // 报错必须带文件路径，否则用户无从下手。
    expect(body.data.invalid[0].file).toContain('broken');
  });

  it('与宿主同源的模块被判为不合法（D24）', async () => {
    writeManifest('sneaky', {
      ...validManifest('sneaky'),
      entry: 'http://127.0.0.1:4310/sneaky/index.html',
      allowedOrigins: ['http://127.0.0.1:4310'],
    });

    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    const body = response.json();
    expect(body.data.modules).toEqual([]);
    const codes = body.data.invalid[0].issues.map((issue: { code: string }) => issue.code);
    expect(codes).toContain('same_origin_as_host');
  });

  it('远端访问时把回环 entry 换成请求方主机名', async () => {
    writeManifest('task-center', validManifest('task-center'));
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/modules',
      headers: { host: '203.0.113.10:4300' },
    });
    const body = response.json();
    expect(body.data.modules[0].entry).toBe('http://203.0.113.10:5174/task-center/index.html');
    // allowedOrigins 跟着换，保持"包含 entry 的源"这条不变式。
    expect(body.data.modules[0].allowedOrigins).toEqual(['http://203.0.113.10:5174']);
  });

  it('本机访问时清单保持原样（localhost 与 127.0.0.1 是不同的源，不能改写）', async () => {
    writeManifest('task-center', validManifest('task-center'));
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/modules',
      headers: { host: '127.0.0.1:4300' },
    });
    const body = response.json();
    expect(body.data.modules[0].entry).toBe(`${MODULE_ORIGIN}/task-center/index.html`);
    expect(body.data.modules[0].allowedOrigins).toEqual([MODULE_ORIGIN]);
  });

  it('本来就部署在非回环地址的 entry 不被改写', async () => {
    writeManifest('remote', {
      ...validManifest('remote'),
      entry: 'http://192.168.1.9:5174/remote/index.html',
      allowedOrigins: ['http://192.168.1.9:5174'],
    });
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/modules',
      headers: { host: '203.0.113.10:4300' },
    });
    const body = response.json();
    expect(body.data.modules[0].entry).toBe('http://192.168.1.9:5174/remote/index.html');
    expect(body.data.modules[0].allowedOrigins).toEqual(['http://192.168.1.9:5174']);
  });

  it('模块目录下有子目录但没有 module.json 时安静跳过', async () => {
    fs.mkdirSync(path.join(context.home, 'modules', 'not-a-module'), { recursive: true });
    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    const body = response.json();
    expect(body.data.modules).toEqual([]);
    expect(body.data.invalid).toEqual([]);
  });

  it('modules 目录整个不存在时也返回空列表', async () => {
    fs.rmSync(path.join(context.home, 'modules'), { recursive: true, force: true });
    const response = await context.app.inject({ method: 'GET', url: '/api/modules' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data.modules).toEqual([]);
  });
});
