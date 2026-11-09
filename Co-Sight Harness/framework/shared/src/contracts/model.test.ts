import { describe, expect, test } from 'vitest';

import { createModelConfigInputSchema, updateModelConfigInputSchema } from './model';

const minimal = { provider: 'openai', label: 'GPT-4o', modelName: 'gpt-4o' } as const;

describe('createModelConfigInputSchema', () => {
  test('最小输入补齐合理的默认值', () => {
    const input = createModelConfigInputSchema.parse(minimal);
    expect(input.temperature).toBe(0.7);
    expect(input.topP).toBe(1);
    expect(input.timeoutSeconds).toBe(120);
    expect(input.baseUrl).toBeNull();
    expect(input.apiKey).toBeNull();
    expect(input.isActive).toBe(false);
  });

  test('未知的 provider 被拒', () => {
    expect(
      createModelConfigInputSchema.safeParse({ ...minimal, provider: 'gemini' }).success,
    ).toBe(false);
  });

  test('temperature 越界被拒', () => {
    expect(
      createModelConfigInputSchema.safeParse({ ...minimal, temperature: 5 }).success,
    ).toBe(false);
  });

  test('baseUrl 必须是合法 URL', () => {
    expect(
      createModelConfigInputSchema.safeParse({ ...minimal, baseUrl: 'not-a-url' }).success,
    ).toBe(false);
  });

  test('超时上限 3600 秒，避免挂死的请求永不释放', () => {
    expect(createModelConfigInputSchema.safeParse({ ...minimal, timeoutSeconds: 99999 }).success).toBe(
      false,
    );
  });
});

describe('updateModelConfigInputSchema', () => {
  test('空补丁被拒', () => {
    expect(updateModelConfigInputSchema.safeParse({}).success).toBe(false);
  });

  test('apiKey 传 null 表示清除密钥', () => {
    expect(updateModelConfigInputSchema.parse({ apiKey: null }).apiKey).toBeNull();
  });

  test('apiKey 传 undefined（缺省）表示保持原密钥', () => {
    expect(updateModelConfigInputSchema.parse({ label: '新名字' }).apiKey).toBeUndefined();
  });
});
