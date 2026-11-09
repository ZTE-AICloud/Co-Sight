/**
 * 工作区接口（需求 2.1：新建 / 切换 / 删除）——**浏览器面**。
 *
 * "切换"是服务端状态（见 app_state 表注释）：工作区决定默认模型与默认 Agent，
 * 这份上下文必须全局唯一，否则两个标签页会各自以为自己在不同工作区。
 *
 * ## 这个文件为什么这么薄
 *
 * 重名检查、建目录、"删当前工作区要清指针"三件事都在 `services/workspaces.ts`，
 * 与模块面（`routes/module-workspace.ts`）共用同一份。这里只做三件事：
 * 校验入参（schema）、调服务、把领域结果包成信封。**不要在路由里补业务判断**——
 * 补一条就意味着模块面少了同一条，而两者的差异没有任何测试能发现。
 *
 * 本文件里唯一"多余"的东西是 DELETE 成功后那一行 info 日志：它需要 request 上下文
 * 才知道是谁删的，服务层拿不到，所以必须留在这里。
 */

import {
  AppError,
  createWorkspaceInputSchema,
  updateWorkspaceInputSchema,
  workspaceIdParamsSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'workspace';

export const workspaceRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.workspaces.list());
  });

  app.post(
    '/',
    { schema: { tags: [TAG], body: createWorkspaceInputSchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.workspaces.create(request.body), 201);
    },
  );

  /**
   * 当前工作区。必须声明在 `/:id` 之前语义上才清晰——虽然 find-my-way 对静态段
   * 优先于参数段，不依赖注册顺序，但读代码的人不该被迫知道这一点。
   */
  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.workspaces.findActive());
  });

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
    /*
     * 只有框架自己创建的工作区目录会被删；外部绑定目录保留（见
     * `docs/workspace-design.md`）。日志必须把处置结果写清楚：用户看到目录还在时，
     * 能一眼判断是 `external` 的预期行为，还是删除失败。
     */
    if (removed.directory !== null) {
      request.log.info(
        {
          workspaceId: id,
          directory: removed.directory,
          directoryDisposition: removed.directoryDisposition,
        },
        '工作区记录已删除',
      );
    }
    return sendOk(reply, { id, deleted: true });
  });
};
