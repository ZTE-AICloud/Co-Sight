/**
 * 专家接口（需求 2.2；页面需求 4.3–4.5）。
 *
 * 列表是唯一被前端高频调用的接口：切页签、输入搜索词、滚动加载都会打它。
 * 因此四个页签的排序全部下沉到 SQL（见 expert.repository），路由只透传参数，
 * 不做内存排序或过滤——内存排序没法分页，一页之后顺序就错了。
 */

import {
  AppError,
  createExpertInputSchema,
  expertListQuerySchema,
  idParamsSchema,
  recordExpertUseInputSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk, sendPaged } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'expert';

export const expertRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG], querystring: expertListQuerySchema } }, async (request, reply) => {
    const query = request.query;
    const { items, total } = await app.services.experts.list(query);
    return sendPaged(reply, items, total, query.page, query.pageSize);
  });

  /**
   * 框架侧的专家新建入口。**v1 前端不调用它**：按 D14，顶部「专家智能体创建」
   * 按钮是跳到 Agent 开发模块由那边创建（D20/D21 均为占位）。此接口保留是为了
   * 种子数据、测试与后续模块回写，契约先行。
   */
  app.post('/', { schema: { tags: [TAG], body: createExpertInputSchema } }, async (request, reply) => {
    const created = await app.services.experts.create(request.body);
    return sendOk(reply, created, 201);
  });

  app.get('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const expert = await app.services.experts.findById(request.params.id);
    if (expert === null) {
      throw AppError.notFound('专家', request.params.id);
    }
    return sendOk(reply, expert);
  });

  /**
   * 记录一次「使用」（需求 4.5 的「使用」按钮）。
   *
   * 计数与跳转解耦：跳转由前端直接改路由（D19 = A），这里只负责把热度记下来，
   * 因为 D15 = B 的「最热」完全由这个计数决定，漏记一次排序就不准了。
   */
  app.post(
    '/:id/use',
    { schema: { tags: [TAG], params: idParamsSchema, body: recordExpertUseInputSchema } },
    async (request, reply) => {
      const { id } = request.params;
      const { workspaceId } = request.body;

      // workspaceId 只用于归属留痕；给了就必须存在，否则静默记成 null 会掩盖调用方的 bug。
      if (workspaceId !== null) {
        const workspace = await app.services.workspaces.findById(workspaceId);
        if (workspace === null) {
          throw AppError.notFound('工作区', workspaceId);
        }
      }

      const updated = await app.services.experts.recordUse(id);
      if (updated === null) {
        throw AppError.notFound('专家', id);
      }
      return sendOk(reply, updated);
    },
  );

  app.delete('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const { id } = request.params;
    const deleted = await app.services.experts.deleteById(id);
    if (!deleted) {
      throw AppError.notFound('专家', id);
    }
    return sendOk(reply, { id, deleted: true });
  });
};
