/**
 * Agent 代理配置接口（需求 2.3-1：配置与显示）。
 *
 * "显示"是这里的关键约束：配置项要能原样回给前端渲染成表单，
 * 所以出参包含全部可编辑字段；唯独 token 与模型密钥同规则——只回掩码。
 */

import {
  AppError,
  createAgentProxyInputSchema,
  idParamsSchema,
  updateAgentProxyInputSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'agent-proxy';

export const agentProxyRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.agentProxies.list());
  });

  app.get('/default', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.agentProxies.findDefault());
  });

  app.post('/', { schema: { tags: [TAG], body: createAgentProxyInputSchema } }, async (request, reply) => {
    const created = await app.services.agentProxies.create(request.body);
    return sendOk(reply, created, 201);
  });

  app.get('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const config = await app.services.agentProxies.findById(request.params.id);
    if (config === null) {
      throw AppError.notFound('Agent 代理配置', request.params.id);
    }
    return sendOk(reply, config);
  });

  app.patch(
    '/:id',
    { schema: { tags: [TAG], params: idParamsSchema, body: updateAgentProxyInputSchema } },
    async (request, reply) => {
      const updated = await app.services.agentProxies.update(request.params.id, request.body);
      if (updated === null) {
        throw AppError.notFound('Agent 代理配置', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.post('/:id/default', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const updated = await app.services.agentProxies.update(request.params.id, { isDefault: true });
    if (updated === null) {
      throw AppError.notFound('Agent 代理配置', request.params.id);
    }
    return sendOk(reply, updated);
  });

  app.delete('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const { id } = request.params;
    const deleted = await app.services.agentProxies.deleteById(id);
    if (!deleted) {
      throw AppError.notFound('Agent 代理配置', id);
    }
    return sendOk(reply, { id, deleted: true });
  });
};
