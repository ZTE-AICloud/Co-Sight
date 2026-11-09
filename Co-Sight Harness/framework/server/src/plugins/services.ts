/**
 * 把服务容器挂到 Fastify 实例上。
 *
 * 用 `decorate` + 模块类型增强，而不是每个路由插件重新 `import` 容器：
 * 后者会把装配点散到各处，且测试里没法替换成临时库。
 */

import type { FastifyInstance } from 'fastify';

import type { Services } from '../services/container';

declare module 'fastify' {
  interface FastifyInstance {
    services: Services;
  }
}

export function decorateServices(app: FastifyInstance, services: Services): void {
  app.decorate('services', services);
}
