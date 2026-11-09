/**
 * 数据库 schema（D7：SQLite + Drizzle）。
 *
 * 两条贯穿全表的约定：
 * 1. **列名显式写出 snake_case**，不依赖 drizzle 的 casing 推断——契约层用
 *    camelCase，落库用 snake_case，映射只在这一层发生。
 * 2. **密钥永不入库**。凡是密钥字段一律存 `*_ref`（指向 .credentials.yaml 的键），
 *    库文件可以随便备份/分享而不会泄漏密钥（D26 = A）。
 */

import { sql } from 'drizzle-orm';
import { index, integer, real, sqliteTable, text, uniqueIndex } from 'drizzle-orm/sqlite-core';

export const workspaces = sqliteTable('workspaces', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  /** 绑定的本地绝对路径；未绑定为 null（D16 = A）。 */
  directory: text('directory'),
  defaultModelId: text('default_model_id'),
  defaultAgentId: text('default_agent_id'),
  createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
  updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
});

export const experts = sqliteTable(
  'experts',
  {
    id: text('id').primaryKey(),
    name: text('name').notNull(),
    author: text('author').notNull(),
    description: text('description').notNull(),
    avatarUrl: text('avatar_url'),
    /** 多标签，以 JSON 数组存；标签是展示与筛选素材，不做独立表。 */
    tags: text('tags', { mode: 'json' }).$type<string[]>().notNull(),
    /** `最热` 排序依据（D15 = B：纯使用次数）。 */
    useCount: integer('use_count').notNull(),
    /** `预置` 页签筛选依据（D13 = A）。 */
    isPreset: integer('is_preset', { mode: 'boolean' }).notNull(),
    createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
    updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
  },
  (table) => [
    // 三个页签各一条排序路径：热度、时间、预置筛选。
    index('experts_use_count_idx').on(table.useCount),
    index('experts_created_at_idx').on(table.createdAt),
    index('experts_is_preset_idx').on(table.isPreset),
    index('experts_name_idx').on(table.name),
  ],
);

export const modelConfigs = sqliteTable('model_configs', {
  id: text('id').primaryKey(),
  provider: text('provider').notNull(),
  label: text('label').notNull(),
  baseUrl: text('base_url'),
  modelName: text('model_name').notNull(),
  /** 指向 .credentials.yaml 的键；null 表示未配置密钥。 */
  apiKeyRef: text('api_key_ref'),
  isActive: integer('is_active', { mode: 'boolean' }).notNull(),
  temperature: real('temperature').notNull(),
  topP: real('top_p').notNull(),
  maxOutputTokens: integer('max_output_tokens'),
  contextWindow: integer('context_window'),
  timeoutSeconds: integer('timeout_seconds').notNull(),
  createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
  updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
});

export const agentProxyConfigs = sqliteTable('agent_proxy_configs', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  description: text('description'),
  agentType: text('agent_type').notNull(),
  endpoint: text('endpoint'),
  enabled: integer('enabled', { mode: 'boolean' }).notNull(),
  isDefault: integer('is_default', { mode: 'boolean' }).notNull(),
  maxIterations: integer('max_iterations').notNull(),
  parallelism: integer('parallelism').notNull(),
  timeoutSeconds: integer('timeout_seconds').notNull(),
  memoryEnabled: integer('memory_enabled', { mode: 'boolean' }).notNull(),
  condensationEnabled: integer('condensation_enabled', { mode: 'boolean' }).notNull(),
  securityAnalyzer: text('security_analyzer').notNull(),
  /** 指向 .credentials.yaml 的键；null 表示未配置。 */
  tokenRef: text('token_ref'),
  /** 模块私有配置透传，框架不解读。 */
  extra: text('extra', { mode: 'json' }).$type<Record<string, unknown>>().notNull(),
  createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
  updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
});

/**
 * 单例应用状态键值表。
 *
 * v1 只有一处用途：记录"当前工作区"（需求 2.1 的**切换**）。切换是服务端状态而不是
 * 前端 local storage——否则每个浏览器各自记一份，多标签页之间就会互相矛盾，
 * 而工作区同时决定默认模型/默认 Agent，属于该由服务端说了算的东西。
 * 做成 kv 表而不是给 workspaces 加 `is_active` 列，是因为将来还会有别的单例状态
 * （默认语言、上次打开的路由），加列会让语义混进工作区自身的数据里。
 */
export const appState = sqliteTable('app_state', {
  key: text('key').primaryKey(),
  value: text('value').notNull(),
  updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
});

/**
 * RAG 知识库跳转路由（设置 → 知识库路由设置）。
 *
 * 「可用」= 当前生效，**全局至多一条**。用部分唯一索引兜底而不是靠应用层自觉：
 * 即使是并发写或有人手工改库，也不可能出现两行 `is_active = 1`，模块侧读到的
 * 永远是唯一确定的一条。没有「至少一条」的约束——删掉生效项后就该是「当前没有」。
 *
 * 这张表没有密钥：`route_url` 只接受 http/https 绝对地址（校验在 shared 契约层），
 * 且服务端从不去请求它（不做连通性探测，避免 SSRF）。
 */
export const ragKnowledgeBases = sqliteTable(
  'rag_knowledge_bases',
  {
    id: text('id').primaryKey(),
    name: text('name').notNull(),
    routeUrl: text('route_url').notNull(),
    /** 登录知识库用的账号；null 表示不需要登录。 */
    username: text('username'),
    /** 指向 .credentials.yaml 的键；null 表示未配置密码（D26，与模型的 api_key_ref 同形）。 */
    passwordRef: text('password_ref'),
    /**
     * 模块访问知识服务用的 Agent API Key 引用（`CO_KNOWLEDGE_API_KEY`）。
     * null 表示这条路由没有自己的 Key——模块面会回落到服务端默认（若有）。
     */
    apiKeyRef: text('api_key_ref'),
    description: text('description'),
    isActive: integer('is_active', { mode: 'boolean' }).notNull().default(false),
    createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
    updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
  },
  (table) => [
    // 部分唯一索引：只约束 is_active = 1 的行，0 可以有任意多行。
    uniqueIndex('rag_knowledge_bases_active_uidx')
      .on(table.isActive)
      .where(sql`${table.isActive} = 1`),
  ],
);

export const schema = {
  workspaces,
  experts,
  modelConfigs,
  agentProxyConfigs,
  ragKnowledgeBases,
  appState,
};

export type WorkspaceRow = typeof workspaces.$inferSelect;
export type ExpertRow = typeof experts.$inferSelect;
export type ModelConfigRow = typeof modelConfigs.$inferSelect;
export type AgentProxyConfigRow = typeof agentProxyConfigs.$inferSelect;
export type RagKnowledgeRow = typeof ragKnowledgeBases.$inferSelect;
export type AppStateRow = typeof appState.$inferSelect;
