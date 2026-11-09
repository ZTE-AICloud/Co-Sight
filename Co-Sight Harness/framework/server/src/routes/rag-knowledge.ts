/**
 * RAG 知识库跳转路由接口（设置 → 知识库路由设置）。
 *
 * 浏览器面：给设置面板用的完整增删改查 + 切换生效项。响应一律 `sendOk`、
 * 错误一律 `AppError`，与其它配置类接口同一套信封，前端不需要为它写分支。
 *
 * 三个刻意的选择：
 *
 * - `GET /active` 在"没有生效项"时回 `200` + `data: null`，**不是 404**。
 *   没有生效知识库是正常状态（用户一条都没配，或刚删掉），404 会诱导前端
 *   把它当错误弹提示。
 * - `POST /:id/activate` 是便利路由，等价于 `PATCH { isActive: true }`，
 *   与模型配置保持一致：列表行上的一个按钮不必自己拼 PATCH body。
 * - **不做连通性探测**（与模型 probe 同理）：服务端拿着用户填的地址去请求就是一条
 *   SSRF 路径。要确认地址能不能打开，由用户点侧栏「知识库」让浏览器加载它。
 */

import {
  AppError,
  createRagKnowledgeBaseInputSchema,
  idParamsSchema,
  updateRagKnowledgeBaseInputSchema,
  type RagKnowledgeDefaults,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'rag-knowledge';

export const ragKnowledgeRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.ragKnowledge.list());
  });

  /*
   * `/active` 注册在 `/:id` 之前：Fastify 本身优先匹配静态段，顺序不影响结果，
   * 保持同序是为了与 `routes/model.ts` 一致。
   */
  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.ragKnowledge.findActive());
  });

  /*
   * 面板需要知道"留空会怎样"：服务端有没有预置默认 API Key。
   *
   * 只回布尔，**不回值**——默认值来自 `COSIGHT_KNOWLEDGE_API_KEY`，属于服务端配置，
   * 一旦回传到浏览器就等于把它写进了前端可读的网络响应，D26 那条线也就破了。
   * 静态段 `/defaults` 必须与 `/:id` 并存而不被吞掉：Fastify 优先静态段。
   */
  app.get('/defaults', { schema: { tags: [TAG] } }, async (_request, reply) => {
    const defaults: RagKnowledgeDefaults = {
      hasDefaultApiKey: app.services.config.ragKnowledgeApiKey !== null,
    };
    return sendOk(reply, defaults);
  });

  app.post(
    '/',
    { schema: { tags: [TAG], body: createRagKnowledgeBaseInputSchema } },
    async (request, reply) => {
      const created = await app.services.ragKnowledge.create(request.body);
      return sendOk(reply, created, 201);
    },
  );

  app.get('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const record = await app.services.ragKnowledge.findById(request.params.id);
    if (record === null) {
      throw AppError.notFound('知识库', request.params.id);
    }
    return sendOk(reply, record);
  });

  app.patch(
    '/:id',
    { schema: { tags: [TAG], params: idParamsSchema, body: updateRagKnowledgeBaseInputSchema } },
    async (request, reply) => {
      const updated = await app.services.ragKnowledge.update(request.params.id, request.body);
      if (updated === null) {
        throw AppError.notFound('知识库', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.post(
    '/:id/activate',
    { schema: { tags: [TAG], params: idParamsSchema } },
    async (request, reply) => {
      const updated = await app.services.ragKnowledge.update(request.params.id, { isActive: true });
      if (updated === null) {
        throw AppError.notFound('知识库', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.delete(
    '/:id',
    { schema: { tags: [TAG], params: idParamsSchema } },
    async (request, reply) => {
      const { id } = request.params;
      const deleted = await app.services.ragKnowledge.deleteById(id);
      if (!deleted) {
        throw AppError.notFound('知识库', id);
      }
      return sendOk(reply, { id, deleted: true });
    },
  );
};
