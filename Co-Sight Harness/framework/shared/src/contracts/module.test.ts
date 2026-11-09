import { describe, expect, test } from 'vitest';

import {
  type ModuleManifest,
  moduleManifestSchema,
  pickModuleForCapability,
  validateModuleManifest,
} from './module';

const HOST_ORIGIN = 'http://localhost:4310';

function manifest(overrides: Partial<ModuleManifest> = {}): ModuleManifest {
  return {
    ...moduleManifestSchema.parse({
      schemaVersion: 1,
      id: 'conversation-module',
      name: { 'zh-CN': '会话模块', 'en-US': 'Conversation' },
      description: { 'zh-CN': '会话对话', 'en-US': 'Chat' },
      version: '1.0.0',
      entry: 'http://localhost:4100/index.html',
      allowedOrigins: ['http://localhost:4100'],
      mounts: [{ capability: 'conversation', path: '/conversation' }],
    }),
    ...overrides,
  };
}

describe('validateModuleManifest', () => {
  test('合规清单无问题', () => {
    expect(validateModuleManifest(manifest(), HOST_ORIGIN)).toEqual([]);
  });

  test('entry 的源不在白名单内会被拒（D24）', () => {
    const issues = validateModuleManifest(
      manifest({ entry: 'http://evil.example/index.html' }),
      HOST_ORIGIN,
    );
    expect(issues.map((issue) => issue.code)).toContain('origin_not_allowed');
  });

  test('与宿主同源会被拒，因为 sandbox 将失去隔离意义（D24 = A）', () => {
    const issues = validateModuleManifest(
      manifest({
        entry: `${HOST_ORIGIN}/modules/conversation/index.html`,
        allowedOrigins: [HOST_ORIGIN],
      }),
      HOST_ORIGIN,
    );
    expect(issues.map((issue) => issue.code)).toContain('same_origin_as_host');
  });

  test('白名单项带路径会被拒，要求写成纯源', () => {
    const issues = validateModuleManifest(
      manifest({ allowedOrigins: ['http://localhost:4100/app'] }),
      HOST_ORIGIN,
    );
    expect(issues.map((issue) => issue.code)).toContain('not_a_bare_origin');
  });

  test('重复的 capability 挂载会被拒', () => {
    const issues = validateModuleManifest(
      manifest({
        mounts: [
          { capability: 'conversation', path: '/conversation' },
          { capability: 'conversation', path: '/chat' },
        ],
      }),
      HOST_ORIGIN,
    );
    expect(issues.map((issue) => issue.code)).toContain('duplicate');
  });
});

describe('moduleManifestSchema', () => {
  test('缺少任一语言的名称会被拒（D28 双语）', () => {
    const result = moduleManifestSchema.safeParse({
      schemaVersion: 1,
      id: 'x-module',
      name: { 'zh-CN': '只有中文' },
      description: { 'zh-CN': '描述', 'en-US': 'desc' },
      version: '1.0.0',
      entry: 'http://localhost:4100/',
      allowedOrigins: ['http://localhost:4100'],
      mounts: [{ capability: 'history', path: '/history' }],
    });
    expect(result.success).toBe(false);
  });

  test('非法 id（大写）会被拒', () => {
    const result = moduleManifestSchema.safeParse({
      schemaVersion: 1,
      id: 'BadId',
      name: { 'zh-CN': '名', 'en-US': 'n' },
      description: { 'zh-CN': '描', 'en-US': 'd' },
      version: '1.0.0',
      entry: 'http://localhost:4100/',
      allowedOrigins: ['http://localhost:4100'],
      mounts: [{ capability: 'history', path: '/history' }],
    });
    expect(result.success).toBe(false);
  });
});

describe('pickModuleForCapability', () => {
  test('同 capability 多模块时取版本更高者', () => {
    const picked = pickModuleForCapability(
      [manifest({ id: 'a-module', version: '1.2.0' }), manifest({ id: 'b-module', version: '1.10.0' })],
      'conversation',
    );
    expect(picked?.id).toBe('b-module');
  });

  test('没有模块声明该 capability 时返回 null', () => {
    expect(pickModuleForCapability([manifest()], 'observability')).toBeNull();
  });
});
