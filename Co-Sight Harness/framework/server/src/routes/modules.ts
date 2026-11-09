/**
 * 模块清单接口（C2 嵌入机制）。
 *
 * 前端启动时拉一次，据此决定每个插槽该 iframe 哪个源。同时**把不合法的清单
 * 一并返回**：框架不能默默忽略一个写错的模块，否则同事只会看到"页面空白"，
 * 却无从知道是自己的 module.json 有问题。
 */

import type { FastifyPluginAsyncZod } from 'fastify-type-provider-zod';

import { hostnameFromHostHeader, isLoopbackHost } from '../http/loopback';
import { sendOk } from '../http/reply';
import { rebaseLoopbackManifests, scanModules } from '../modules/registry';

export const moduleRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get('/', { schema: { tags: ['module'] } }, async (request, reply) => {
    const { config, paths } = app.services;
    const result = scanModules(paths.modules, config.hostOrigin);

    /*
     * 远端访问时，清单里写死的 `localhost` 指向的是**访问者自己的机器**。
     * 把回环入口换成请求方用的主机名，iframe 才能落到宿主这台机器上；
     * 本机访问时保持原样（见 registry.ts 的 rebaseLoopbackManifests）。
     */
    const hostname = hostnameFromHostHeader(request.headers.host);
    const visible =
      hostname === null || isLoopbackHost(hostname)
        ? result
        : rebaseLoopbackManifests(result, hostname);

    return sendOk(reply, visible);
  });
};
