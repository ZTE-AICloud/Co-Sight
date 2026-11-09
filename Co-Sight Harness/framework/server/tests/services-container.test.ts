/**
 * 服务容器。
 *
 * 这里验的不是"装配成功"，而是**装配开关真的生效**：`preparePaths: false`
 * 必须真的不建目录，`migrate: false` 必须真的不建表。这两个开关如果没有被
 * 正确短路，测试环境会悄悄写进真实的 `~/.cosight-harness/`，而这件事在
 * 断言层面完全看不出来——所以这里用"目录不存在""查询直接报错"来反向证明。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { loadConfig, type ServerConfig } from '../src/config/env';
import { resolveDataPaths } from '../src/config/paths';
import { closeServices, createServices, type Services } from '../src/services/container';

const opened: Array<{ home: string; services: Services }> = [];

function makeHome(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-container-'));
}

function configFor(home: string): ServerConfig {
  return loadConfig({
    COSIGHT_HOME: home,
    COSIGHT_DATABASE_URL: `file:${path.join(home, 'test.sqlite')}`,
    NODE_ENV: 'test',
  });
}

async function open(
  home: string,
  options: { preparePaths?: boolean; migrate?: boolean } = {},
): Promise<Services> {
  const services = await createServices({ config: configFor(home), ...options });
  opened.push({ home, services });
  return services;
}

afterEach(async () => {
  for (const entry of opened.splice(0)) {
    await closeServices(entry.services);
    fs.rmSync(entry.home, { recursive: true, force: true });
  }
});

describe('createServices', () => {
  it('默认建好目录、跑完迁移、装配全部仓储', async () => {
    const home = makeHome();
    const services = await open(home);

    expect(fs.existsSync(resolveDataPaths(home).modules)).toBe(true);
    // 迁移跑过的证据是"表真的能查"，而不是"迁移函数被调用过"。
    expect(await services.workspaces.list()).toEqual([]);
    expect(services.experts).toBeDefined();
    expect(services.models).toBeDefined();
    expect(services.agentProxies).toBeDefined();
    expect(services.appState).toBeDefined();
    expect(services.credentials).toBeDefined();
    expect(services.bridge).toBeDefined();
  });

  it('preparePaths: false 时不创建目录结构', async () => {
    const home = makeHome();
    const services = await open(home, { preparePaths: false });

    expect(services.paths.home).toBe(home);
    // 开关没生效的话这里会是 true —— 测试内容会被写进用户的真实数据目录。
    expect(fs.existsSync(resolveDataPaths(home).modules)).toBe(false);
  });

  it('migrate: false 时不建表，查询如实报错而不是静默返回空', async () => {
    const home = makeHome();
    const services = await open(home, { migrate: false });

    // 静默返回 [] 会把"忘了迁移"伪装成"还没有数据"，这是最难查的一类问题。
    await expect(services.experts.list({ filter: 'all', page: 1, pageSize: 30 })).rejects.toThrow();
  });

  it('同一个 home 上重新装配能读到上一次的数据（重启场景）', async () => {
    const home = makeHome();
    const first = await open(home);
    await first.workspaces.create({
      name: '工作区 A',
      directory: null,
      defaultModelId: null,
      defaultAgentId: null,
    });

    const second = await open(home);
    const list = await second.workspaces.list();
    expect(list.map((item) => item.name)).toEqual(['工作区 A']);
  });
});
