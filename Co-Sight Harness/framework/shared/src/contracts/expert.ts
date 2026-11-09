/**
 * 专家契约（需求 4.2–4.5；2.2）。
 *
 * 三点直接来自决策：
 * - D13 = A：四个筛选项 `全部 / 最热 / 最新 / 预置`，`预置` 由后端种子标记区分。
 * - D15 = B：`最热` = **纯使用次数**倒序（不加近 30 天加权，不做埋点）。
 * - D19 = A：卡片的 设计/评估/优化 三个动作共用一个目标路由，靠 `mode` 参数区分。
 */

import { z } from 'zod';

import { httpUrlSchema } from './primitives';

export const EXPERT_FILTERS = ['all', 'hot', 'new', 'preset'] as const;

export type ExpertFilter = (typeof EXPERT_FILTERS)[number];

/** 卡片底部的四个动作（需求 4.5）。 */
export const EXPERT_ACTIONS = ['use', 'design', 'evaluate', 'optimize'] as const;

export type ExpertAction = (typeof EXPERT_ACTIONS)[number];

/**
 * `use` 走「使用」路径（跳到会话页），其余三个走 Agent 开发模块并携带 mode。
 * 定义在契约层，因为它同时约束框架的跳转与目标模块对 `mode` 的解读。
 */
export const EXPERT_ACTION_KIND: Record<ExpertAction, 'conversation' | 'agent-dev'> = {
  use: 'conversation',
  design: 'agent-dev',
  evaluate: 'agent-dev',
  optimize: 'agent-dev',
};

export const expertSchema = z.object({
  id: z.uuid(),
  /** 专家名称，也是搜索框的匹配字段（需求 4.4）。 */
  name: z.string().min(1).max(64),
  /** 上传者（需求 4.2）。 */
  author: z.string().min(1).max(64),
  description: z.string().max(500),
  /** 头像地址；null 时前端用名称首字生成占位头像。 */
  avatarUrl: z.string().nullable(),
  /** 多标签（需求 4.2）。 */
  tags: z.array(z.string().min(1).max(24)).max(8),
  /** 使用次数，`最热` 排序依据（D15 = B）。 */
  useCount: z.number().int().nonnegative(),
  /** 是否预置专家，`预置` 页签的筛选依据（D13 = A）。 */
  isPreset: z.boolean(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type Expert = z.infer<typeof expertSchema>;

export const expertListQuerySchema = z.object({
  filter: z.enum(EXPERT_FILTERS).default('all'),
  /**
   * 按名称模糊搜索；空串等价于不搜索（前端清空输入框即传空串）。
   *
   * 顺序是"先 transform 再 optional"，不能反过来：`.optional().transform(...)`
   * 会让**输出**类型里 `q` 变成必填的 `string | undefined`，于是每个直接调用
   * 仓储的地方都得写一句 `q: undefined`。契约里表达的是"可以没有 q，
   * 且 q 不会是空串"，所以 optional 要放在最外层。
   */
  q: z
    .string()
    .trim()
    .max(64)
    .transform((value) => (value === '' ? undefined : value))
    .optional(),
  page: z.coerce.number().int().min(1).default(1),
  /** 网格为 6 列 × 5 行，首页整屏恰好 30 张卡片。 */
  pageSize: z.coerce.number().int().min(1).max(60).default(30),
});

export type ExpertListQuery = z.infer<typeof expertListQuerySchema>;

/** 新建专家。v1 的预置数据由 seed 直接经仓储写入，此契约供模块与测试使用。 */
export const createExpertInputSchema = z.object({
  name: z.string().trim().min(1).max(64),
  author: z.string().trim().min(1).max(64),
  description: z.string().trim().max(500).default(''),
  avatarUrl: httpUrlSchema.nullable().default(null),
  tags: z.array(z.string().trim().min(1).max(24)).max(8).default([]),
  isPreset: z.boolean().default(false),
});

export type CreateExpertInput = z.infer<typeof createExpertInputSchema>;

/** 记录一次「使用」（需求 4.5 `使用` 按钮），驱动 `最热` 排序。 */
export const recordExpertUseInputSchema = z.object({
  /** 使用发生的工作区；未指定表示不在任何工作区内。 */
  workspaceId: z.uuid().nullable().default(null),
});

export type RecordExpertUseInput = z.infer<typeof recordExpertUseInputSchema>;
