/**
 * 模型设置契约（需求 2.3；前端表单见 3.2）。
 *
 * 密钥处理遵循 D26：**只写不读**。后端返回 `apiKeyMasked`（固定掩码或 null），
 * 明文只落 `$COSIGHT_HOME/.credentials.yaml`（0600），库里只存引用。
 * 因此本契约里**没有任何字段会返回明文密钥**。
 */

import { z } from 'zod';

import { httpUrlSchema } from './primitives';

export const MODEL_PROVIDER_KINDS = [
  'openai',
  'anthropic',
  'azure-openai',
  'ollama',
  'openai-compatible',
] as const;

export type ModelProviderKind = (typeof MODEL_PROVIDER_KINDS)[number];

export const modelConfigSchema = z.object({
  id: z.uuid(),
  provider: z.enum(MODEL_PROVIDER_KINDS),
  /** 用户可见名称，如「内部 Qwen3-32B」。 */
  label: z.string().min(1).max(64),
  /** 自定义网关地址；null 表示用 provider 官方地址。 */
  baseUrl: z.string().nullable(),
  modelName: z.string().min(1).max(128),
  /** 密钥掩码；未配置为 null。明文永不返回。 */
  apiKeyMasked: z.string().nullable(),
  hasApiKey: z.boolean(),
  /** 是否为当前生效的模型配置（全局至多一个）。 */
  isActive: z.boolean(),

  temperature: z.number().min(0).max(2),
  topP: z.number().min(0).max(1),
  maxOutputTokens: z.number().int().positive().nullable(),
  contextWindow: z.number().int().positive().nullable(),
  timeoutSeconds: z.number().int().positive(),

  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type ModelConfig = z.infer<typeof modelConfigSchema>;

const sharedFields = {
  provider: z.enum(MODEL_PROVIDER_KINDS),
  label: z.string().trim().min(1).max(64),
  baseUrl: httpUrlSchema.nullable().default(null),
  modelName: z.string().trim().min(1).max(128),
  temperature: z.number().min(0).max(2).default(0.7),
  topP: z.number().min(0).max(1).default(1),
  maxOutputTokens: z.number().int().positive().nullable().default(null),
  contextWindow: z.number().int().positive().nullable().default(null),
  timeoutSeconds: z.number().int().positive().max(3600).default(120),
};

export const createModelConfigInputSchema = z.object({
  ...sharedFields,
  /** 明文密钥，仅入不出。 */
  apiKey: z.string().min(1).max(2048).nullable().default(null),
  isActive: z.boolean().default(false),
});

export type CreateModelConfigInput = z.infer<typeof createModelConfigInputSchema>;

export const updateModelConfigInputSchema = z
  .object({
    provider: sharedFields.provider.optional(),
    label: z.string().trim().min(1).max(64).optional(),
    baseUrl: httpUrlSchema.nullable().optional(),
    modelName: z.string().trim().min(1).max(128).optional(),
    /** `undefined` = 保持原密钥；`null` = 清除；字符串 = 覆盖。 */
    apiKey: z.string().min(1).max(2048).nullable().optional(),
    isActive: z.boolean().optional(),
    temperature: z.number().min(0).max(2).optional(),
    topP: z.number().min(0).max(1).optional(),
    maxOutputTokens: z.number().int().positive().nullable().optional(),
    contextWindow: z.number().int().positive().nullable().optional(),
    timeoutSeconds: z.number().int().positive().max(3600).optional(),
  })
  .refine((patch) => Object.values(patch).some((value) => value !== undefined), {
    message: '至少需要一个待更新字段',
  });

export type UpdateModelConfigInput = z.infer<typeof updateModelConfigInputSchema>;

/**
 * 连通性自检的结果（设置页的「测试连接」）。
 *
 * 只有结果契约，没有入参契约：入参就是路径上的模型 id（`idParamsSchema`）。
 * 曾经这里有一份 `modelProbeInputSchema = { id }`，被当成请求体用在路由上，
 * 导致传空体直接被校验拦成 422，探测逻辑根本执行不到——已删除，避免重复定义
 * 出两种形状。
 *
 * v1 不实现探测（D21 = C），但结果契约先定下来，前端可以直接照着写展示逻辑。
 */
export interface ModelProbeResult {
  ok: boolean;
  latencyMs: number | null;
  modelKey: string;
  errorKey: string | null;
  errorMessage: string | null;
}
