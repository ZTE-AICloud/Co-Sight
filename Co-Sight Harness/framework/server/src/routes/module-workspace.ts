/**
 * 模块面：工作区（`/api/framework/v1/workspaces`）。
 *
 * 与浏览器面 `/api/workspaces` 是**同一份数据的两个面**，没有任何字段上的差异
 * （工作区没有密钥，不需要像模型那样分两套投影）。之所以两边都有，是因为它们的
 * 调用者不同：这边是本机其他模块的服务端进程（带令牌），那边是框架自己的页面。
 *
 * 所有业务判断都在 `services/workspaces.ts`，本文件与 `routes/workspace.ts` 一样
 * 只做"校验入参 + 调服务 + 包信封"。**不要在这里补一条**——补了就与浏览器面分叉。
 *
 * 门禁不在本文件里，在 `routes/module-face.ts` 的父上下文钩子上。
 *
 * 关于"建目录"：`POST` 不传 `directory` 时，框架会在工作区根目录下按工作区名
 * 派生一个目录名并创建它（见 `lib/slug.ts`）。这一条与浏览器面完全一致，
 * 因为它们是同一个 service。传了绝对路径则只绑定、不创建。
 */

import {
  AppError,
  createWorkspaceInputSchema,
  updateWorkspaceInputSchema,
  workspaceIdParamsSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 `app.ts` 里声明的 tags 对应（两个子树共用一个分组）。 */
const TAG = 'framework-module';

export const moduleWorkspaceRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.workspaces.overview());
  });

  /*
   * `/active` 在 `/:id` 之前注册，与浏览器面同序（理由见 `routes/workspace.ts`）。
   * 没有生效工作区时 `200` + `data: null`，不是 404。
   */
  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.workspaces.findActive());
  });

  app.post(
    '/',
    { schema: { tags: [TAG], body: createWorkspaceInputSchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.workspaces.create(request.body), 201);
    },
  );

  app.get('/:id', { schema: { tags: [TAG], params: workspaceIdParamsSchema } }, async (request, reply) => {
    const workspace = await app.services.workspaces.findById(request.params.id);
    if (workspace === null) {
      throw AppError.notFound('工作区', request.params.id);
    }
    return sendOk(reply, workspace);
  });

  app.patch(
    '/:id',
    { schema: { tags: [TAG], params: workspaceIdParamsSchema, body: updateWorkspaceInputSchema } },
    async (request, reply) => {
      const updated = await app.services.workspaces.update(request.params.id, request.body);
      if (updated === null) {
        throw AppError.notFound('工作区', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.post('/:id/activate', { schema: { tags: [TAG], params: workspaceIdParamsSchema } }, async (request, reply) => {
    const workspace = await app.services.workspaces.activate(request.params.id);
    if (workspace === null) {
      throw AppError.notFound('工作区', request.params.id);
    }
    return sendOk(reply, workspace);
  });

  app.delete('/:id', { schema: { tags: [TAG], params: workspaceIdParamsSchema } }, async (request, reply) => {
    const { id } = request.params;
    const removed = await app.services.workspaces.deleteById(id);
    if (removed === null) {
      throw AppError.notFound('工作区', id);
    }
    // 目录处置与浏览器面共用同一份服务逻辑（见 `routes/workspace.ts` 里那段注释）。
    // 模块作者最需要知道的边界是：框架创建的目录会删，外部绑定的目录只解绑。
    if (removed.directory !== null) {
      request.log.info(
        {
          workspaceId: id,
          directory: removed.directory,
          directoryDisposition: removed.directoryDisposition,
        },
        '工作区记录已删除（模块面）',
      );
    }
    return sendOk(reply, { id, deleted: true });
  });
};
