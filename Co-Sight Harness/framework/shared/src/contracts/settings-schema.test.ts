import { describe, expect, test } from 'vitest';

import { SECRET_MASK, isSecretConfigured, settingsFieldSchemaSchema } from './settings-schema';

describe('isSecretConfigured', () => {
  test('掩码表示已配置', () => {
    expect(isSecretConfigured(SECRET_MASK)).toBe(true);
  });

  test('null 表示未配置', () => {
    expect(isSecretConfigured(null)).toBe(false);
  });

  test('任何非掩码字符串都不算已配置，避免误判', () => {
    expect(isSecretConfigured('')).toBe(false);
    expect(isSecretConfigured('sk-real-key')).toBe(false);
  });
});

describe('settingsFieldSchemaSchema', () => {
  const field = {
    key: 'apiKey',
    labelKey: 'settings.model.apiKey',
    prominence: 'basic',
    type: 'secret',
    required: false,
  } as const;

  test('接受合法的字段声明', () => {
    expect(settingsFieldSchemaSchema.safeParse({ ...field, writeOnly: true }).success).toBe(true);
  });

  test('未知的 prominence 被拒', () => {
    expect(
      settingsFieldSchemaSchema.safeParse({ ...field, prominence: 'expert' }).success,
    ).toBe(false);
  });

  test('未知的字段类型被拒', () => {
    expect(settingsFieldSchemaSchema.safeParse({ ...field, type: 'color' }).success).toBe(false);
  });

  test('select 需要选项与之配套', () => {
    const parsed = settingsFieldSchemaSchema.parse({
      ...field,
      type: 'select',
      options: [{ value: 'a', labelKey: 'settings.opt.a' }],
    });
    expect(parsed.options).toHaveLength(1);
  });

  test('约束里的数值范围可表达', () => {
    const parsed = settingsFieldSchemaSchema.parse({
      ...field,
      type: 'number',
      constraints: { min: 0, max: 2, step: 0.1 },
    });
    expect(parsed.constraints?.max).toBe(2);
  });
});
