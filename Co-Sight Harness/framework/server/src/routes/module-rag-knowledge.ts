/**
 * 模块面：RAG 知识库跳转路由（`/api/framework/v1/rag-knowledge`）。
 *
 * **只有两个只读端点，没有写接口。** 这不是遗漏：知识库的写入者是「设置里的用户」，
 * 模块只需要知道当前该用哪条路由。少一个写入口，一枚泄漏的模块令牌就少一分杀伤面
 * （`docs/module-facing-api.md` 的权限面一节）。
 *
 * ## 门禁不在本文件里
 *
 * 它在 `routes/module-face.ts` 的插件级 `onRequest` 钩子上（回环 + 拒绝 `Origin` +
 * 令牌），本文件是被那个父上下文注册进来的。**不要在本文件里补门禁**，也不要在
 * `app.ts` 里单独注册本插件——那会让它绕开这两道，而"没门禁"的接口不会报错，
 * 只会安静地对全世界开放。
 *
 * ## 没有生效项时 `data: null`
 *
 * HTTP 仍是 200。模块必须把「用户还没配置」当正常态，不要按失败重试——
 * 这条口径写在 `docs/rag-knowledge-api.md` 里，给模块作者看。
 *
 * ## 明文密码只从 `/active` 出去
 *
 * 与模型面同一套投影分工：列表返回 `ModuleRagKnowledgeSummary`（只有 `hasPassword`），
 * `/active` 返回 `ModuleRagKnowledgeSecret`（含明文 `password`）。走
 * `app.services.moduleRagKnowledge`，**不要**在这里自己读 `ragKnowledge` 仓储——
 * 那是浏览器面的投影，里面根本没有明文字段可读。
 */

import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应（三个子树共用一个分组）。 */
const TAG = 'framework-module';

export const moduleRagKnowledgeRoutes: FastifyPluginAsyncZod = async (app) => {
  /** 全量列表：给需要"让用户选一条"的模块用。**不含**明文密码。 */
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.moduleRagKnowledge.list());
  });

  /** 当前生效的一条，或 `null`。这是绝大多数模块唯一需要的端点，**含**明文密码。 */
  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.moduleRagKnowledge.findActive());
  });
};
