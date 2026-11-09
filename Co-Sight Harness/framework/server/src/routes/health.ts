/**
 * 健康检查。
 *
 * 除了给编排脚本探活，它还承担一个前端需求：设置页要展示"数据目录在哪"。
 * 与其让前端去猜，不如由服务端把实际生效的路径报出来——用户配错 COSIGHT_HOME
 * 时能立刻看出来。
 *
 * 关于 `schema.tags`：本文件里每个路由都带一个 `schema` 对象，即便没有需要校验
 * 的输入。原因是"是否有 schema"决定了该路由是否进入 OpenAPI 文档——只写
 * `tags` 既能出现在文档里，又顺带归到正确的分组。没有 tag 的接口会全部堆在
 * default 分组下，接口一多，文档就等于没法看。
 *
 * （这里刻意不写具体接口数量：写死的数字会随着新增接口过期，而没人会想起来改它。）
 */

import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { sendOk } from '../http/reply';
import { SERVER_VERSION } from '../version';

export const healthRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/health', { schema: { tags: ['health'] } }, async (_request, reply) => {
    const { config } = app.services;
    return sendOk(reply, {
      status: 'ok' as const,
      version: SERVER_VERSION,
      uptimeSeconds: Math.round(process.uptime()),
      cosightHome: config.cosightHome,
      database: 'sqlite',
    });
  });
};
