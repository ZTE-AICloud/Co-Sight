/**
 * 模块面契约的形状测试。
 *
 * 这里断言的不是"字段值对不对"（那是服务端的事），而是**密钥字段在哪张脸上、
 * 不在哪张脸上**。之所以值得单独钉：两面共用 `provider`/`label`/`modelName` 这些
 * 字段，很容易在重构时把两张脸合并成"一张带可选 apiKey 的脸"——那时"这次响应里
 * 到底有没有明文"就变成运行期才知道的事，而这个字段恰恰最不能靠运行期兜。
 */

import { describe, expect, test } from 'vitest';

import { modelConfigSchema } from './model';
import {
  MODEL_PROTOCOLS,
  moduleModelListResponseSchema,
  moduleModelSecretSchema,
  moduleModelSummarySchema,
  protocolFromProvider,
} from './module-model';

const summary = {
  id: '00000000-0000-4000-8000-000000000000',
  provider: 'openai',
  protocol: 'openai',
  label: '主模型',
  modelName: 'gpt-5',
  baseUrl: null,
  hasApiKey: true,
  isActive: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  updatedAt: '2026-01-01T00:00:00.000Z',
} as const;

function keysOf(schema: { shape: Record<string, unknown> }): string[] {
  return Object.keys(schema.shape);
}

describe('模块面契约的密钥字段', () => {
  test('summary 里既没有 apiKey 也没有 apiKeyMasked', () => {
    const keys = keysOf(moduleModelSummarySchema);
    expect(keys).not.toContain('apiKey');
    expect(keys).not.toContain('apiKeyMasked');
  });

  test('secret 里必须有 apiKey，且允许为 null', () => {
    expect(keysOf(moduleModelSecretSchema)).toContain('apiKey');
    expect(moduleModelSecretSchema.parse({ ...summary, apiKey: null, temperature: 0.7, topP: 1, maxOutputTokens: null, contextWindow: null, timeoutSeconds: 120 }).apiKey).toBeNull();
    expect(
      moduleModelSecretSchema.parse({ ...summary, apiKey: 'sk-x', temperature: 0.7, topP: 1, maxOutputTokens: null, contextWindow: null, timeoutSeconds: 120 }).apiKey,
    ).toBe('sk-x');
  });

  test('secret 不是 summary 的"多一个可选字段"版本——apiKey 是必填键', () => {
    expect(
      moduleModelSecretSchema.safeParse({ ...summary, temperature: 0.7, topP: 1, timeoutSeconds: 120 })
        .success,
    ).toBe(false);
  });

  test('浏览器面契约反向：有 apiKeyMasked，没有 apiKey', () => {
    const keys = keysOf(modelConfigSchema);
    expect(keys).toContain('apiKeyMasked');
    expect(keys).not.toContain('apiKey');
  });

  test('列表响应是 items + activeId，不是裸数组', () => {
    const parsed = moduleModelListResponseSchema.parse({ items: [summary], activeId: null });
    expect(parsed.activeId).toBeNull();
    expect(parsed.items).toHaveLength(1);
  });
});

describe('protocol 派生', () => {
  test('只有 anthropic 走 anthropic 协议，其余都走 openai 兼容协议', () => {
    expect(protocolFromProvider('anthropic')).toBe('anthropic');
    for (const provider of ['openai', 'azure-openai', 'ollama', 'openai-compatible'] as const) {
      expect(protocolFromProvider(provider), provider).toBe('openai');
    }
  });

  test('协议枚举就是这两个值', () => {
    expect([...MODEL_PROTOCOLS]).toEqual(['anthropic', 'openai']);
  });
});
