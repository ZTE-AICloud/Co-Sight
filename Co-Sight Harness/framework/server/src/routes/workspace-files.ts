/**
 * 工作区文件浏览（**浏览器面**，只读）——会话区右侧边栏的「工作区文件」面板在用。
 *
 * ## 为什么不在模块面
 *
 * 这三个端点吐的是**用户文件的内容**。模块面那枚令牌已经能改平台配置，再把
 * "读任意工作区文件"挂上去，等于给一枚泄漏的令牌多一个能读走用户文件的用法，
 * 而这组接口的消费方是框架自己的界面。所以它只在 `/api/workspaces` 下，
 * `module-facing-api.md` / `workspace-api.md` 的端点表里**没有**它们。
 *
 * ## 门禁：本文件自己的 `onRequest`，比浏览器面其余部分严一档
 *
 * 浏览器面的其他接口没有门禁（D25：本机单用户，只监听 `127.0.0.1`）。这一组
 * **额外**加回环校验（`Host` 与来源 socket 都要是回环），理由很具体：
 *
 * 浏览器面对 **DNS rebinding** 本来没有防线——恶意站点把自己控制的域名解析到
 * `127.0.0.1`，浏览器就当成同源，CORS 完全不介入。在此之前这条攻击面只够
 * 翻一翻工作区**记录**（名字、路径、改模型配置），代价有限；这一组一旦开口，
 * 它够读**文件内容**。所以在这里补上唯一能露馅的那道检查（`Host`）。
 *
 * 代价是明确的：**把 UI 部署到非回环地址时这两个 GET 会 403**，文件面板打不开。
 * 这条写在 `docs/workspace-design.md` 的「只读浏览」一节里，不留给下一个人猜。
 *
 * 不加 `Authorization`：那会让浏览器面也要令牌，而浏览器里本来就拿不到令牌
 * （这正是模块面的设计）。回环校验挡的是浏览器，不是本机进程；同机同用户的
 * 进程本来就能直接读磁盘，加令牌对它们没有任何意义。
 *
 * ## 为什么这里没有 `if (error instanceof ...)` 之类的东西
 *
 * 校验与磁盘访问全在 `services/workspace-files.ts`，路由只做"校验入参（schema）、
 * 调服务、包信封"。文件头里那段包含规则是**唯一**一份，别在这里补第二个判断。
 */

import { AppError, workspaceFilePathQuerySchema, workspaceIdParamsSchema } from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { isLoopbackAddress, isLoopbackHost } from '../http/loopback';
import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'workspace-file';

export const workspaceFileRoutes: FastifyPluginAsyncZod = async (app) => {
  app.addHook('onRequest', async (request) => {
    /*
     * 两道一起判，缺一不可：`Host` 是客户端直接写的头（挡 DNS rebinding），
     * `request.ip` 是 socket 地址（挡真的从别的机器连进来）。只判后者的话，
     * rebinding 场景下 socket 恰恰就是回环，正好漏掉。
     *
     * `request.ip` 的可靠性依赖 `trustProxy: false`，同 `http/loopback.ts` 的文件头。
     */
    if (!isLoopbackHost(request.headers.host) || !isLoopbackAddress(request.ip)) {
      // 刻意不区分"哪个不满足"：说了等于把服务端看到的头回显给一个外部来源。
      throw forbidden();
    }
  });

  /** 列一层目录；`?path=` 是工作区相对路径，省略即根。 */
  app.get(
    '/:id/files',
    { schema: { tags: [TAG], params: workspaceIdParamsSchema, querystring: workspaceFilePathQuerySchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.workspaceFiles.list(request.params.id, request.query.path ?? ''));
    },
  );

  /** 读一个文本文件（前 512 KiB）。 */
  app.get(
    '/:id/files/content',
    { schema: { tags: [TAG], params: workspaceIdParamsSchema, querystring: workspaceFilePathQuerySchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.workspaceFiles.readText(request.params.id, request.query.path ?? ''));
    },
  );

  /** 读一张图片，内联成 data URL。 */
  app.get(
    '/:id/files/image',
    { schema: { tags: [TAG], params: workspaceIdParamsSchema, querystring: workspaceFilePathQuerySchema } },
    async (request, reply) => {
      return sendOk(reply, await app.services.workspaceFiles.readImage(request.params.id, request.query.path ?? ''));
    },
  );
};

/**
 * `AppError.forbidden(reason)` 给的是 `error.forbidden` 这个键，而词表里
 * `forbidden` 已经是带 `default` 的分组——面板上"这台机器之外打不开"与
 * "没有权限"不是同一件事，那句话要能单独取到，所以这里直接构造。
 */
function forbidden(): AppError {
  return new AppError('FORBIDDEN', 'error.forbidden.loopback_only', '工作区文件浏览只对本机开放');
}
