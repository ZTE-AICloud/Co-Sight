/**
 * 设置项声明模型（参考 OpenHands 的 `SettingsFieldSchema`）。
 *
 * 为什么后端要声明字段而不是前端硬编码表单：
 * 设置页的「基础 / 高级 / 全部」三档披露条、逐字段脏标记、以及未来模块自带的
 * 设置片段，都需要一份**数据驱动**的字段清单。前端因此不需要为每个设置项写一遍
 * JSX，新增字段只改后端声明。
 */

import { z } from 'zod';

/** 披露层级：基础档默认可见，进阶档需切到「高级/全部」才出现。 */
export const PROMINENCE_LEVELS = ['basic', 'advanced'] as const;

export type Prominence = (typeof PROMINENCE_LEVELS)[number];

export const SETTINGS_FIELD_TYPES = [
  'string',
  'number',
  'boolean',
  'select',
  'secret',
  'path',
  'url',
  'textarea',
] as const;

export type SettingsFieldType = (typeof SETTINGS_FIELD_TYPES)[number];

export interface SelectOptionSchema {
  value: string;
  /** i18n 键。 */
  labelKey: string;
}

export interface FieldConstraints {
  min?: number;
  max?: number;
  step?: number;
  maxLength?: number;
  pattern?: string;
}

export interface SettingsFieldSchema {
  key: string;
  /** i18n 键，不含前缀；前端拼 `settings.<section>.<key>`。 */
  labelKey: string;
  descriptionKey?: string;
  placeholderKey?: string;
  prominence: Prominence;
  type: SettingsFieldType;
  required: boolean;
  defaultValue?: unknown;
  options?: SelectOptionSchema[];
  constraints?: FieldConstraints;
  /**
   * 只写不读：后端永不返回明文，只回掩码（`**********`）。
   * 用于 apiKey / token 一类字段。
   */
  writeOnly?: boolean;
}

export const settingsFieldSchemaSchema = z.object({
  key: z.string().min(1),
  labelKey: z.string().min(1),
  descriptionKey: z.string().min(1).optional(),
  placeholderKey: z.string().min(1).optional(),
  prominence: z.enum(PROMINENCE_LEVELS),
  type: z.enum(SETTINGS_FIELD_TYPES),
  required: z.boolean(),
  defaultValue: z.unknown().optional(),
  options: z
    .array(z.object({ value: z.string(), labelKey: z.string() }))
    .optional(),
  constraints: z
    .object({
      min: z.number().optional(),
      max: z.number().optional(),
      step: z.number().optional(),
      maxLength: z.number().int().positive().optional(),
      pattern: z.string().optional(),
    })
    .optional(),
  writeOnly: z.boolean().optional(),
});

/** 密钥字段回给前端的固定掩码，前端据此判断"已配置但不可见"。 */
export const SECRET_MASK = '**********';

export function isSecretConfigured(masked: string | null): boolean {
  return masked === SECRET_MASK;
}
