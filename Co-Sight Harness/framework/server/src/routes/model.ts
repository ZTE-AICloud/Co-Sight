/**
 * 模型配置接口（需求 2.3）。
 *
 * 密钥的进出规则（D26 = A）：
 * - 入参收明文，但只写进 `.credentials.yaml`；
 * - 出参**只回掩码**，明文永不出现在任何响应里。
 * 因此把同一条配置读两次看到的都是 `**********`，这正是"密钥不可回读"该有的样子。
 */

import {
  AppError,
  createModelConfigInputSchema,
  idParamsSchema,
  updateModelConfigInputSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'model';

export const modelRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.models.list());
  });

  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.models.findActive());
  });

  app.post('/', { schema: { tags: [TAG], body: createModelConfigInputSchema } }, async (request, reply) => {
    const created = await app.services.models.create(request.body);
    return sendOk(reply, created, 201);
  });

  app.get('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const model = await app.services.models.findById(request.params.id);
    if (model === null) {
      throw AppError.notFound('模型配置', request.params.id);
    }
    return sendOk(reply, model);
  });

  app.patch(
    '/:id',
    { schema: { tags: [TAG], params: idParamsSchema, body: updateModelConfigInputSchema } },
    async (request, reply) => {
      const updated = await app.services.models.update(request.params.id, request.body);
      if (updated === null) {
        throw AppError.notFound('模型配置', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.post('/:id/activate', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const updated = await app.services.models.update(request.params.id, { isActive: true });
    if (updated === null) {
      throw AppError.notFound('模型配置', request.params.id);
    }
    return sendOk(reply, updated);
  });

  /**
   * 连通性探测：**v1 明确不实现**（D21 = C，待定）。
   *
   * 除了"要不要做"尚未决策，它还牵涉一个安全问题：baseUrl 由用户填写，
   * 服务端拿着它去发请求就是一条 SSRF 路径（可打内网、可打云元数据端点）。
   * 真要做，必须先过地址白名单与内网段黑名单——那是独立一个批次的工作量，
   * 不该顺手塞进模型 CRUD 里。所以这里如实返回 NOT_IMPLEMENTED，而不是
   * 做一个看似能用、实则不设防的探测。
   */
  app.post('/:id/probe', { schema: { tags: [TAG], params: idParamsSchema } }, async () => {
    throw AppError.notImplemented('模型连通性探测', 'error.not_implemented.model_probe');
  });

  app.delete('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const { id } = request.params;
    const deleted = await app.services.models.deleteById(id);
    if (!deleted) {
      throw AppError.notFound('模型配置', id);
    }
    return sendOk(reply, { id, deleted: true });
  });
};
