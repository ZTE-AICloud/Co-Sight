/**
 * 模块面：模型配置（`/api/framework/v1/models`）。
 *
 * 与浏览器面 `/api/models/*` **刻意不同**：这里的详情**带明文密钥**。
 * 浏览器面那句「没有任何字段会返回明文密钥」依然成立，一个字都没松
 * （`tests/api-model.test.ts` 钉着它）；两面能共存，是因为这边的门禁要求调用方
 * 出示一枚只存在于 `$COSIGHT_HOME/.module-token`（0600）的令牌——浏览器读不到本机文件。
 *
 * ## 门禁不在本文件里
 *
 * 它在 `routes/module-face.ts` 的插件级 `onRequest` 钩子上，本文件是被那个父上下文
 * 注册进来的。**不要在本文件里补一道 `preHandler`**——那会变成"有的路由查了两次、
 * 有的路由一次都没查"，而漏查的那条不报错，只是安静地对全世界开放。
 *
 * ## 关于写接口（D33）
 *
 * 需求里有"设置、修改、删除"，所以这里有 POST/PATCH/DELETE。曾经有一版刻意只做只读，
 * 理由是 `credentials/store.ts` 明写跨进程并发**未做文件锁**，一旦模块面可写就会
 * 「两个进程同时对 `.credentials.yaml` read-modify-write 丢更新」。那条顾虑现在不成立了，
 * 原因是它假设错了写者的身份：**模块面的写全部经 HTTP 打到这一个框架进程**，
 * `.credentials.yaml` 始终只有这一个进程写，进程内 `CredentialStore.#writeChain`
 * 的串行链就是全序。跨进程风险只存在于"有人绕过 HTTP 直接改那个文件"，
 * 而那与浏览器面今天的情况没有区别。
 *
 * 于是**写操作没有引入新的竞态**，但它放大了一件事，必须写在文档里（§残余风险）：
 * 同一个 `$COSIGHT_HOME` 起两个框架实例仍然是不支持的，只是这一次的后果从
 * "丢一次密钥更新"变成"两个进程都认为自己该管这份配置"。
 *
 * 另一条要说清的：模块面**没有** `POST /:id/activate`。不是漏了——`PATCH` 的 body 里
 * 就是 `isActive`（`updateModelConfigInputSchema`），要切生效项就 `PATCH { "isActive": true }`。
 * 浏览器面那条 `/activate` 是给「列表行上的一个按钮」用的便利路由，模块面不需要。
 */

import {
  AppError,
  createModelConfigInputSchema,
  idParamsSchema,
  updateModelConfigInputSchema,
} from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 `app.ts` 里声明的 tags 对应（两个子树共用一个分组）。 */
const TAG = 'framework-module';

export const moduleModelRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.moduleModels.list());
  });

  /*
   * `/active` 必须注册在 `/:id` **之前**。Fastify 的路由本就优先匹配静态段，
   * 所以顺序其实不影响结果；保持同序是为了与 `routes/model.ts` 一致，
   * 免得后人改了路由实现时踩到。
   *
   * 没有生效模型时返回 `200` + `data: null`，**不是 404**——与浏览器面
   * `GET /api/models/active` 同语义。
   */
  app.get('/active', { schema: { tags: [TAG] } }, async (_request, reply) => {
    return sendOk(reply, await app.services.moduleModels.findActive());
  });

  /*
   * 写入走 `moduleModels`（模块面服务）而不是直接调 `models`（仓储）：
   * 响应必须按**模块面的投影**回（带明文密钥、不带 apiKeyMasked），
   * 而那个投影函数住在 `services/module-models.ts`。
   *
   * 投影在模块面服务里、写入在仓储里，是刻意的分工：仓储的 `create/update/delete`
   * 是浏览器面在用的同一份实现（包括"先落密钥再落库"的顺序），模块面不该有第二套；
   * 而"回什么形状"两面必须不同，所以那一层在服务上。
   */
  app.post(
    '/',
    { schema: { tags: [TAG], body: createModelConfigInputSchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.moduleModels.create(request.body), 201);
    },
  );

  app.patch(
    '/:id',
    { schema: { tags: [TAG], params: idParamsSchema, body: updateModelConfigInputSchema } },
    async (request, reply) => {
      const updated = await app.services.moduleModels.update(request.params.id, request.body);
      if (updated === null) {
        throw AppError.notFound('模型配置', request.params.id);
      }
      return sendOk(reply, updated);
    },
  );

  app.get('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const model = await app.services.moduleModels.findById(request.params.id);
    if (model === null) {
      throw AppError.notFound('模型配置', request.params.id);
    }
    return sendOk(reply, model);
  });

  app.delete('/:id', { schema: { tags: [TAG], params: idParamsSchema } }, async (request, reply) => {
    const { id } = request.params;
    const deleted = await app.services.moduleModels.deleteById(id);
    if (!deleted) {
      throw AppError.notFound('模型配置', id);
    }
    return sendOk(reply, { id, deleted: true });
  });
};
