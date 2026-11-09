/**
 * 模块面（对外接口 `/api/framework/v1/*`）的**唯一**入口插件。
 *
 * 面下有三个子树，由本文件统一注册：
 *
 *   /api/framework/v1/models          模型配置（含明文密钥）
 *   /api/framework/v1/workspaces      工作区（读写的都是本机平台的配置与目录）
 *   /api/framework/v1/rag-knowledge   RAG 知识库跳转路由（**只读**）
 *
 * ## 门禁为什么上提到这里
 *
 * 上一版只有一个 `/models` 子树，门禁是它自己的插件级 `onRequest` 钩子，理由写在
 * 当时的文件头里：「将来有人往这个插件里加第四条路由时，门禁会自动继承——结构上
 * 无法忘记」。加第二个子树时，那条理由正好失效了：子插件是**并列**注册的，
 * 门禁挂在 `/models` 上不会管到 `/workspaces`，而"新面忘了挂门禁"的表现是——
 * 一个不需要任何令牌就能读写的接口，且它**不会报错**，只会安静地工作。
 *
 * 所以钩子再上提一层，挂在 `/api/framework/v1` 这个父上下文上。Fastify 的插件
 * 封装保证父上下文的 `onRequest` 对**此后注册的所有子路由**生效，于是
 * 「往模块面加东西」与「被门禁保护」仍然是同一件事，与面的数量无关。
 *
 * ## 令牌的权限面（D33）
 *
 * `.module-token` 最初的存在理由是「让本机进程拿到模型配置（含明文密钥）」，
 * 现在它同时能改模型、能建/删工作区。**它仍然不是访问控制边界**——
 * 同 UID 的进程可以直接读 `$COSIGHT_HOME/.credentials.yaml`，根本不需要走 HTTP
 * （见 `credentials/module-token.ts` 文件头）。权限面扩大的真实后果不是"多了个入口"，
 * 而是"一枚泄漏的令牌炸得更大"，因此这里加了一行写操作的审计日志，
 * 并把这句口径写进 `docs/module-facing-api.md`。
 */

import { AppError } from 'harness-shared';
import { MODULE_TOKEN_HEADER, MODULE_TOKEN_SCHEME } from 'harness-shared/module-models';
import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { isLoopbackAddress, isLoopbackHost } from '../http/loopback';
import { moduleModelRoutes } from './module-model';
import { moduleRagKnowledgeRoutes } from './module-rag-knowledge';
import { moduleWorkspaceRoutes } from './module-workspace';

export const moduleFaceRoutes: FastifyPluginAsyncZod = async (app) => {
  app.addHook('onRequest', async (request) => {
    /*
     * 第一道：回环校验。挡的是 DNS rebinding——恶意站点把域名解析到 127.0.0.1，
     * 浏览器便认为在跟同源通信，此时 Host 头露出的是攻击者的域名。
     * 这一道依赖 `app.ts` 的 `trustProxy: false`（否则 request.ip 可被
     * X-Forwarded-For 伪造）——改那行之前先读 `http/loopback.ts` 的文件头。
     */
    if (!isLoopbackHost(request.headers.host) || !isLoopbackAddress(request.ip)) {
      throw AppError.forbidden('模块面只接受来自本机回环地址的请求');
    }

    /*
     * 第二道：显式拒绝浏览器。浏览器发的请求会带 Origin，本机进程不会。
     *
     * 这条**不是**主力防线（同源 GET 浏览器根本不发 Origin），主力是下面第三道的
     * 令牌。它在这里的价值是一句可执行的声明：密钥只留给模块的服务端进程，
     * 任何前端页面——**包括模块自己的前端**——都不该拿到它。
     */
    if (request.headers.origin !== undefined) {
      throw AppError.forbidden('模块面不接受来自浏览器页面的请求');
    }

    // 第三道：令牌。这才是真正的门。
    const header = request.headers[MODULE_TOKEN_HEADER];
    if (typeof header !== 'string' || !header.startsWith(MODULE_TOKEN_SCHEME)) {
      throw AppError.moduleTokenRejected('缺少模块面令牌');
    }

    if (!app.services.moduleToken.verify(header.slice(MODULE_TOKEN_SCHEME.length))) {
      /*
       * 真实原因（文件不存在 / 内容非法 / 不匹配）不外泄，响应一律同一句——
       * 区分它们等于向外报出本机文件系统的状态。
       *
       * 这里**不额外打日志**：`installErrorHandler` 已经会记一条 warn（含 code 与
       * messageKey），足以定位。再加一条就是每个被拒请求两行，而这是攻击者能随手
       * 刷满的路径。要让运维知道去哪拿令牌，靠启动时那条指明路径的日志。
       */
      throw AppError.moduleTokenRejected('模块面令牌无效');
    }

    /*
     * 门已过：**到这里才记写操作的审计**。
     *
     * 放在令牌校验之后而不是之前，是因为之前记的话，每个被拒的探测请求都会留一行，
     * 把日志变成攻击者可控的噪声，真正需要回溯的那几条反而被埋掉。
     *
     * 记什么：方法 + 路径 + 对端地址 + 令牌是哪一个（只记文件名，永远不记值）。
     * 记的用途很具体——模块面没有操作者身份，出了"谁把生效模型改到了坏 baseUrl"
     * 这种问题，这行日志是唯一能回答"哪台机器、什么时候"的东西。
     */
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      request.log.warn(
        { method: request.method, url: request.url, ip: request.ip },
        '模块面写操作（令牌已通过校验）',
      );
    }
  });

  await app.register(moduleModelRoutes, { prefix: '/models' });
  await app.register(moduleWorkspaceRoutes, { prefix: '/workspaces' });
  await app.register(moduleRagKnowledgeRoutes, { prefix: '/rag-knowledge' });
};
