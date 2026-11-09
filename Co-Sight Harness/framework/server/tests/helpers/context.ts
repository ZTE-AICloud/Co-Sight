/**
 * 测试上下文：每个测试用例一套独立的 COSIGHT_HOME 与 sqlite 文件。
 *
 * 不复用固定的临时库，是因为仓储测试会写入数据，共享库会让用例之间产生顺序依赖
 * （先跑的用例留下的记录影响后跑用例的计数与排序）。建目录 + 跑迁移只有几毫秒，
 * 换来用例可以任意顺序执行，值得。
 *
 * vitest.config.ts 里的 `fileParallelism: false` 仍然保留：它防的是跨文件的
 * 全局状态（进程级 cwd、环境变量）相互干扰。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import type { FastifyInstance } from 'fastify';

import { buildApp } from '../../src/app';
import { loadConfig } from '../../src/config/env';
import { closeServices, createServices, type Services } from '../../src/services/container';

export interface TestContext {
  app: FastifyInstance;
  services: Services;
  /** 该用例独占的数据根目录。 */
  home: string;
}

/**
 * `env` 是追加的环境变量，用来测"某个配置项存在时"的行为（比如服务端预置的
 * 默认 API Key）。基础四项放在它**之前**，调用方不能借此换掉数据目录——
 * 那样两个用例会共用同一个 sqlite 文件，顺序依赖就又回来了。
 */
export async function createTestContext(env: NodeJS.ProcessEnv = {}): Promise<TestContext> {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-test-'));

  const config = loadConfig({
    COSIGHT_HOME: home,
    COSIGHT_DATABASE_URL: `file:${path.join(home, 'test.sqlite')}`,
    COSIGHT_HOST_ORIGIN: 'http://127.0.0.1:4310',
    NODE_ENV: 'test',
    ...env,
  });

  const services = await createServices({ config });
  const app = await buildApp({ services, logger: false });
  await app.ready();

  return { app, services, home };
}

export async function destroyTestContext(context: TestContext): Promise<void> {
  await context.app.close();
  await closeServices(context.services);
  fs.rmSync(context.home, { recursive: true, force: true });
}

/** 带独立上下文的用例包装，保证异常路径下也清理干净。 */
export function withContext(
  run: (context: TestContext) => Promise<void>,
  env: NodeJS.ProcessEnv = {},
): () => Promise<void> {
  return async () => {
    const context = await createTestContext(env);
    try {
      await run(context);
    } finally {
      await destroyTestContext(context);
    }
  };
}
