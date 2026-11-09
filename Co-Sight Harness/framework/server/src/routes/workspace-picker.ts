/**
 * 系统目录选择（**浏览器面**，只挂 `/api/workspaces`）。
 *
 * ## 为什么由服务端弹窗
 *
 * 浏览器拿不到绝对路径（见 `services/directory-picker.ts` 的文件头）。工作区表单里的
 * 「绑定目录」要的正是这台机器上的绝对路径，所以对话框只能由服务端在本机桌面拉起。
 *
 * ## 为什么要回环门禁
 *
 * 这是浏览器面里**第二个能在用户机器上产生副作用**的接口：它不读写数据，
 * 但会在桌面上弹出模态窗口，并把用户选中的路径回给调用方。浏览器面对 DNS rebinding
 * 本来没有防线（恶意站点把自己的域名解析到 127.0.0.1，就成了"同源"），
 * 一旦放开，外部页面能反复弹窗，还能读到用户选中的目录。所以与 `workspace-files`
 * 用同一条门禁（见 http/loopback.ts），而不是沿用浏览器面其它接口"本机单用户、
 * 不加门禁"的口径。
 *
 * 代价照旧写明：**把 UI 部署到非回环地址时这个接口会 403**，此时只能手输路径。
 *
 * ## 为什么不在模块面
 *
 * 模块没有"替用户在桌面上选目录"的正当理由，而这枚令牌能改平台配置——
 * 给它多一个能弹窗、能探本机目录的能力没有任何收益。`module-facing-api.md`
 * 的端点表里没有它。
 */

import { AppError, pickDirectoryInputSchema } from 'harness-shared';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { isLoopbackAddress, isLoopbackHost } from '../http/loopback';
import { sendOk } from '../http/reply';

/** OpenAPI 分组名；与 app.ts 里声明的 tags 对应。 */
const TAG = 'workspace-picker';

export const workspacePickerRoutes: FastifyPluginAsyncZod = async (app) => {
  app.addHook('onRequest', async (request) => {
    /*
     * 两道一起判，缺一不可：`Host` 是客户端直接写的头（挡 DNS rebinding），
     * `request.ip` 是 socket 地址（挡真的从别的机器连进来）。理由与
     * `routes/workspace-files.ts` 完全相同。
     */
    if (!isLoopbackHost(request.headers.host) || !isLoopbackAddress(request.ip)) {
      throw forbidden();
    }
  });

  app.post(
    '/pick-directory',
    { schema: { tags: [TAG], body: pickDirectoryInputSchema } },
    async (request, reply) => {
      const path = await app.services.directoryPicker.pick(request.body.initialPath);
      return sendOk(reply, { path });
    },
  );
};

/**
 * 独立构造而不是 `AppError.forbidden()`：词表里 `forbidden` 是带 `default` 的分组，
 * 而"目录选择只对本机开放"与"工作区文件浏览只对本机开放"是两句不同的话，
 * 共用同一个键会让其中一边说不清自己为什么被拒。
 */
function forbidden(): AppError {
  return new AppError('FORBIDDEN', 'error.forbidden.directory_picker', '目录选择只对本机开放，请从本机访问');
}
