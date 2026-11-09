import { describe, expect, test } from 'vitest';

import { createAgentProxyInputSchema, updateAgentProxyInputSchema } from './agent-proxy';

const minimal = { name: '默认代理', agentType: 'code-agent' } as const;

describe('createAgentProxyInputSchema', () => {
  test('最小输入补齐默认额度', () => {
    const input = createAgentProxyInputSchema.parse(minimal);
    expect(input.maxIterations).toBe(50);
    expect(input.parallelism).toBe(4);
    expect(input.timeoutSeconds).toBe(600);
    expect(input.memoryEnabled).toBe(true);
    expect(input.condensationEnabled).toBe(true);
    expect(input.securityAnalyzer).toBe('none');
    expect(input.enabled).toBe(true);
    expect(input.isDefault).toBe(false);
    expect(input.token).toBeNull();
    expect(input.extra).toEqual({});
  });

  test('extra 接受任意模块私有配置（框架只透传）', () => {
    const input = createAgentProxyInputSchema.parse({
      ...minimal,
      extra: { customField: 'x', nested: { deep: [1, 2] } },
    });
    expect(input.extra['customField']).toBe('x');
  });

  test('未知的 securityAnalyzer 被拒', () => {
    expect(
      createAgentProxyInputSchema.safeParse({ ...minimal, securityAnalyzer: 'magic' }).success,
    ).toBe(false);
  });

  test('并行度上限 64', () => {
    expect(createAgentProxyInputSchema.safeParse({ ...minimal, parallelism: 999 }).success).toBe(
      false,
    );
  });

  test('endpoint 必须是合法 URL', () => {
    expect(
      createAgentProxyInputSchema.safeParse({ ...minimal, endpoint: 'localhost:8080' }).success,
    ).toBe(false);
  });
});

describe('updateAgentProxyInputSchema', () => {
  test('空补丁被拒', () => {
    expect(updateAgentProxyInputSchema.safeParse({}).success).toBe(false);
  });

  test('token 传 null 表示清除', () => {
    expect(updateAgentProxyInputSchema.parse({ token: null }).token).toBeNull();
  });

  test('可单独覆盖 extra', () => {
    expect(updateAgentProxyInputSchema.parse({ extra: { a: 1 } }).extra).toEqual({ a: 1 });
  });
});
