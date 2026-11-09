/**
 * Agent 代理配置契约（需求 2.3-1；前端表单见 3.3）。
 *
 * 框架**不实现** Agent 运行本身——那是 agent-genesis / 各模块的事。
 * 框架只负责：把「用哪个代理、连哪个地址、给什么额度、开哪些能力」配置下来，
 * 并在设置页显示出来。因此除了少量框架关心的额度字段，其余一律走 `extra` 透传。
 *
 * 这个透传通道是刻意的：新增模块时不需要改框架 schema，模块自己在 manifest 里
 * 声明它需要的设置字段（见 settings-schema.ts），框架负责渲染与存储。
 */

import { z } from 'zod';

import { httpUrlSchema } from './primitives';

export const SECURITY_ANALYZERS = ['none', 'invariant', 'llm'] as const;

export type SecurityAnalyzer = (typeof SECURITY_ANALYZERS)[number];

export const agentProxyConfigSchema = z.object({
  id: z.uuid(),
  name: z.string().min(1).max(64),
  description: z.string().max(500).nullable(),
  /** 代理类型标识，由目标模块定义（框架只透传，不枚举）。 */
  agentType: z.string().min(1).max(64),
  /** 代理服务地址；null 表示由模块自行决定。 */
  endpoint: z.string().nullable(),
  enabled: z.boolean(),
  /** 全局默认代理；至多一个。 */
  isDefault: z.boolean(),

  /** 单轮任务的最大迭代步数。 */
  maxIterations: z.number().int().positive(),
  /** 并行度。 */
  parallelism: z.number().int().positive(),
  timeoutSeconds: z.number().int().positive(),
  memoryEnabled: z.boolean(),
  condensationEnabled: z.boolean(),
  securityAnalyzer: z.enum(SECURITY_ANALYZERS),

  /** 访问令牌掩码；明文永不返回（D26）。 */
  tokenMasked: z.string().nullable(),
  hasToken: z.boolean(),

  /** 模块私有配置透传；框架不解读其内容。 */
  extra: z.record(z.string(), z.unknown()),

  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type AgentProxyConfig = z.infer<typeof agentProxyConfigSchema>;

export const createAgentProxyInputSchema = z.object({
  name: z.string().trim().min(1).max(64),
  description: z.string().trim().max(500).nullable().default(null),
  agentType: z.string().trim().min(1).max(64),
  endpoint: httpUrlSchema.nullable().default(null),
  enabled: z.boolean().default(true),
  isDefault: z.boolean().default(false),
  maxIterations: z.number().int().positive().max(1000).default(50),
  parallelism: z.number().int().positive().max(64).default(4),
  timeoutSeconds: z.number().int().positive().max(86400).default(600),
  memoryEnabled: z.boolean().default(true),
  condensationEnabled: z.boolean().default(true),
  securityAnalyzer: z.enum(SECURITY_ANALYZERS).default('none'),
  token: z.string().min(1).max(2048).nullable().default(null),
  extra: z.record(z.string(), z.unknown()).default({}),
});

export type CreateAgentProxyInput = z.infer<typeof createAgentProxyInputSchema>;

export const updateAgentProxyInputSchema = z
  .object({
    name: z.string().trim().min(1).max(64).optional(),
    description: z.string().trim().max(500).nullable().optional(),
    agentType: z.string().trim().min(1).max(64).optional(),
    endpoint: httpUrlSchema.nullable().optional(),
    enabled: z.boolean().optional(),
    isDefault: z.boolean().optional(),
    maxIterations: z.number().int().positive().max(1000).optional(),
    parallelism: z.number().int().positive().max(64).optional(),
    timeoutSeconds: z.number().int().positive().max(86400).optional(),
    memoryEnabled: z.boolean().optional(),
    condensationEnabled: z.boolean().optional(),
    securityAnalyzer: z.enum(SECURITY_ANALYZERS).optional(),
    /** `undefined` = 保持；`null` = 清除；字符串 = 覆盖。 */
    token: z.string().min(1).max(2048).nullable().optional(),
    extra: z.record(z.string(), z.unknown()).optional(),
  })
  .refine((patch) => Object.values(patch).some((value) => value !== undefined), {
    message: '至少需要一个待更新字段',
  });

export type UpdateAgentProxyInput = z.infer<typeof updateAgentProxyInputSchema>;
