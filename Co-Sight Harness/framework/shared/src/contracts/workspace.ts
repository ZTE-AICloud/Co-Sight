/**
 * 工作区契约（需求 2.1；语义见 D16 = A：逻辑容器 + 可选目录绑定）。
 *
 * 关键决定：主键是 uuid，**不是**目录路径。
 * 目录只是可选属性，用户可以「随手新建」一个不绑目录的工作区；
 * 绑定目录时也不要求目录已存在（创建与使用解耦）。
 */

import { z } from 'zod';

import { absolutePathSchema } from './primitives';

export const workspaceSchema = z.object({
  id: z.uuid(),
  name: z.string().min(1).max(64),
  /** 绑定的本地绝对路径；未绑定时为 null。 */
  directory: z.string().nullable(),
  /** 该工作区的默认模型配置 id；null 表示沿用全局当前模型。 */
  defaultModelId: z.uuid().nullable(),
  /** 该工作区的默认 Agent 代理配置 id；null 表示沿用全局默认。 */
  defaultAgentId: z.uuid().nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type Workspace = z.infer<typeof workspaceSchema>;

export const createWorkspaceInputSchema = z.object({
  name: z.string().trim().min(1).max(64),
  directory: absolutePathSchema.nullable().default(null),
  defaultModelId: z.uuid().nullable().default(null),
  defaultAgentId: z.uuid().nullable().default(null),
});

export type CreateWorkspaceInput = z.infer<typeof createWorkspaceInputSchema>;

export const updateWorkspaceInputSchema = z
  .object({
    name: z.string().trim().min(1).max(64).optional(),
    directory: absolutePathSchema.nullable().optional(),
    defaultModelId: z.uuid().nullable().optional(),
    defaultAgentId: z.uuid().nullable().optional(),
  })
  .refine((patch) => Object.values(patch).some((value) => value !== undefined), {
    message: '至少需要一个待更新字段',
  });

export type UpdateWorkspaceInput = z.infer<typeof updateWorkspaceInputSchema>;

export const workspaceIdParamsSchema = z.object({
  id: z.uuid(),
});

export type WorkspaceIdParams = z.infer<typeof workspaceIdParamsSchema>;

/**
 * 「在系统对话框里选一个目录」的入参。
 *
 * `initialPath` 只是对话框的**起点**，不是要保存的值：它可能是一个还不存在的路径
 * （D16 允许先绑定不存在的目录），服务端发现目录不存在时就退回系统默认位置。
 * 仍然按绝对路径校验：这个值会被交给本机的对话框命令，边界上不接受相对路径。
 */
export const pickDirectoryInputSchema = z.object({
  initialPath: absolutePathSchema.nullable().default(null),
});

export type PickDirectoryInput = z.infer<typeof pickDirectoryInputSchema>;

/** 选择结果：`null` 表示用户取消了（不是错误）。 */
export interface PickDirectoryResult {
  path: string | null;
}
