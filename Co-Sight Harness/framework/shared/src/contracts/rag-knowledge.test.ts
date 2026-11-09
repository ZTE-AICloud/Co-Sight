import { describe, expect, test } from 'vitest';

import {
  RAG_KB_DESCRIPTION_MAX_LENGTH,
  RAG_KB_NAME_MAX_LENGTH,
  RAG_KB_PASSWORD_MAX_LENGTH,
  RAG_KB_ROUTE_MAX_LENGTH,
  createRagKnowledgeBaseInputSchema,
  ragKnowledgeRouteUrlSchema,
  updateRagKnowledgeBaseInputSchema,
} from './rag-knowledge';

const minimal = { name: '产品知识库', routeUrl: 'https://kb.example.com/kb/42' } as const;

describe('ragKnowledgeRouteUrlSchema', () => {
  test.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'file:///etc/passwd',
    '//evil.example/x',
    '/\\evil.example/x',
    'ftp://a.example/',
    'not-a-url',
    '/relative/path',
    'https://user:pass@kb.example.com/',
    'https://user@kb.example.com/',
  ])('拒绝 %s', (value) => {
    expect(ragKnowledgeRouteUrlSchema.safeParse(value).success).toBe(false);
  });

  test.each([
    'http://127.0.0.1:4830/kb/1',
    'https://kb.example.com/kb/42',
    'http://kb.example.com/a?b=c#d',
  ])('接受 %s', (value) => {
    expect(ragKnowledgeRouteUrlSchema.safeParse(value).success).toBe(true);
  });

  test('去掉两侧空白后再判断', () => {
    expect(ragKnowledgeRouteUrlSchema.parse('  https://kb.example.com/  ')).toBe(
      'https://kb.example.com/',
    );
  });

  test('超过长度上限被拒', () => {
    const tooLong = `https://kb.example.com/${'a'.repeat(RAG_KB_ROUTE_MAX_LENGTH)}`;
    expect(ragKnowledgeRouteUrlSchema.safeParse(tooLong).success).toBe(false);
  });
});

describe('createRagKnowledgeBaseInputSchema', () => {
  test('最小输入补齐默认值：不生效、无说明', () => {
    const input = createRagKnowledgeBaseInputSchema.parse(minimal);
    expect(input.isActive).toBe(false);
    expect(input.description).toBeNull();
    expect(input.name).toBe('产品知识库');
  });

  test('名称两侧空白被裁掉', () => {
    expect(createRagKnowledgeBaseInputSchema.parse({ ...minimal, name: '  生产  ' }).name).toBe(
      '生产',
    );
  });

  test('空名称被拒', () => {
    expect(createRagKnowledgeBaseInputSchema.safeParse({ ...minimal, name: '   ' }).success).toBe(
      false,
    );
  });

  test('名称超长被拒', () => {
    expect(
      createRagKnowledgeBaseInputSchema.safeParse({
        ...minimal,
        name: 'a'.repeat(RAG_KB_NAME_MAX_LENGTH + 1),
      }).success,
    ).toBe(false);
  });

  test('说明超长被拒', () => {
    expect(
      createRagKnowledgeBaseInputSchema.safeParse({
        ...minimal,
        description: 'a'.repeat(RAG_KB_DESCRIPTION_MAX_LENGTH + 1),
      }).success,
    ).toBe(false);
  });

  test('缺少跳转路由被拒', () => {
    expect(createRagKnowledgeBaseInputSchema.safeParse({ name: '知识库' }).success).toBe(false);
  });

  test('账号密码缺省为 null（不设置），不是空串', () => {
    const parsed = createRagKnowledgeBaseInputSchema.parse(minimal);
    expect(parsed.username).toBeNull();
    expect(parsed.password).toBeNull();
  });

  test('账号两侧空白被去掉；密码原样保留', () => {
    const parsed = createRagKnowledgeBaseInputSchema.parse({
      ...minimal,
      username: '  admin  ',
      password: ' pass with spaces ',
    });
    expect(parsed.username).toBe('admin');
    // 密码不做 trim：尾部空格可能是密码的一部分（与模型密钥同理）。
    expect(parsed.password).toBe(' pass with spaces ');
  });

  test('空密码串被拒（min(1)），"不设置"要用 null', () => {
    expect(createRagKnowledgeBaseInputSchema.safeParse({ ...minimal, password: '' }).success).toBe(
      false,
    );
  });

  test('超过密码长度上限被拒', () => {
    expect(
      createRagKnowledgeBaseInputSchema.safeParse({
        ...minimal,
        password: 'a'.repeat(RAG_KB_PASSWORD_MAX_LENGTH + 1),
      }).success,
    ).toBe(false);
  });
});

describe('updateRagKnowledgeBaseInputSchema', () => {
  test('空补丁被拒', () => {
    expect(updateRagKnowledgeBaseInputSchema.safeParse({}).success).toBe(false);
  });

  test('只传一个字段也合法', () => {
    expect(updateRagKnowledgeBaseInputSchema.parse({ isActive: true }).isActive).toBe(true);
  });

  test('description 传 null 表示清空，缺省表示不改', () => {
    expect(updateRagKnowledgeBaseInputSchema.parse({ description: null }).description).toBeNull();
    expect(updateRagKnowledgeBaseInputSchema.parse({ name: '新名字' }).description).toBeUndefined();
  });

  test('更新时同样拒绝非 http/https 路由', () => {
    expect(
      updateRagKnowledgeBaseInputSchema.safeParse({ routeUrl: 'javascript:alert(1)' }).success,
    ).toBe(false);
  });
});
