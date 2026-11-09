/**
 * 模块面知识库路由契约（对外接口 `/api/framework/v1/rag-knowledge`）。
 *
 * ⚠️ **本文件与 `rag-knowledge.ts` 是刻意相反的两面。改动前请把下面这段读完。**
 *
 * - `rag-knowledge.ts` = **浏览器面**。它的密码只有 `hasPassword` 与固定掩码
 *   `passwordMasked`，**永不含明文**——这条硬契约由 `server/tests/api-rag-knowledge.test.ts`
 *   钉住。
 * - 本文件 = **模块面**。它**有**明文 `password`——代价是调用方必须带一枚本机令牌，
 *   那枚令牌只存在于 `$COSIGHT_HOME/.module-token`（文件 0600）。浏览器读不到本机文件，
 *   所以 XSS 与跨源页面拿不到密码。这与模型两面（`model.ts` / `module-model.ts`）
 *   是同一条论证，不多一个字。
 *
 * 隔离靠的还是那三条**结构性**保证（与 `module-model.ts` 完全相同）：
 *
 * 1. **本文件不写进 `contracts/index.ts`**（那是个 `export *` barrel），服务端经
 *    subpath `harness-shared/module-rag-knowledge` 导入；
 * 2. **服务端的投影函数物理分离**：浏览器面是 `RagKnowledgeRepository` 的私有
 *    `toRecord()`，模块面是 `services/module-rag-knowledge.ts`；
 * 3. **守卫测试** `server/tests/module-contract-isolation.test.ts` 断言前端源码与两个
 *    barrel 里都不出现本文件。
 */

import { z } from 'zod';

import { ragKnowledgeBaseSchema } from './rag-knowledge';

/**
 * 列表项：只放"选中一条路由"所需的字段。
 *
 * 刻意**没有** `password` / `apiKey`，也刻意**没有**两个掩码——掩码在模块面没有语义。
 * 明文只从 `/active` 一条路由出去，泄漏面因此是固定的一条。
 * `username` 保留：它不是秘密，且"这条用的是哪个账号"在模块侧同样有意义。
 */
export const moduleRagKnowledgeSummarySchema = ragKnowledgeBaseSchema.omit({
  passwordMasked: true,
  apiKeyMasked: true,
});

export type ModuleRagKnowledgeSummary = z.infer<typeof moduleRagKnowledgeSummarySchema>;

/**
 * 详情：summary + **明文密码** + **明文 Agent API Key**。
 *
 * `password` 为 null 表示这条路由没有配密码（`hasPassword === false`）。
 * 消费方必须自己处理这一支（例如"直接用地址打开"），不要把 null 当空串塞进表单。
 *
 * `apiKey` 为 null 表示"这条路由没有自己的 Key，且服务端也没配默认"。
 * 服务端配了 `COSIGHT_KNOWLEDGE_API_KEY`（或 `CO_KNOWLEDGE_API_KEY`）时，
 * 这里回的就是那枚默认值——消费方拿到的始终是**生效**的那一枚，不需要再判断
 * 自己该用哪一层。
 */
export const moduleRagKnowledgeSecretSchema = moduleRagKnowledgeSummarySchema.extend({
  password: z.string().nullable(),
  apiKey: z.string().nullable(),
});

export type ModuleRagKnowledgeSecret = z.infer<typeof moduleRagKnowledgeSecretSchema>;

/** 列表响应：与其它模块面接口同一套 `sendOk` 信封，`data` 直接是数组。 */
export type ModuleRagKnowledgeListResponse = ModuleRagKnowledgeSummary[];
