/**
 * 工作区接口（需求 2.1）。
 *
 * 重点在两条容易漏的边界：
 * - 改名时的重名冲突（只测创建时的冲突会漏掉 PATCH 这条绕过路径）；
 * - 删除当前工作区后，`/active` 不能继续指向一个不存在的记录。
 */

import fs from 'node:fs';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

async function createWorkspace(name: string, directory: string | null = null): Promise<string> {
  const response = await context.app.inject({
    method: 'POST',
    url: '/api/workspaces',
    payload: { name, directory },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data.id as string;
}

describe('工作区接口', () => {
  it('初始列表为空', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/workspaces' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toEqual([]);
  });

  it('新建后可在列表中查到', async () => {
    const id = await createWorkspace('默认工作区', '/srv/cosight');
    const list = await context.app.inject({ method: 'GET', url: '/api/workspaces' });
    const items = list.json().data as { id: string; directory: string }[];
    const created = items.find((item) => item.id === id);
    expect(created?.directory).toBe('/srv/cosight');
  });

  it('重名新建返回 409', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces',
      payload: { name: '默认工作区' },
    });
    expect(response.statusCode).toBe(409);
    expect(response.json().error.code).toBe('CONFLICT');
  });

  it('目录必须是绝对路径', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces',
      payload: { name: '相对路径', directory: 'relative/path' },
    });
    expect(response.statusCode).toBe(422);
    expect(response.json().error.details[0].path).toBe('directory');
  });

  it('切换：激活后再读 /active 拿到同一条', async () => {
    const id = await createWorkspace('切换目标');
    const activate = await context.app.inject({
      method: 'POST',
      url: `/api/workspaces/${id}/activate`,
    });
    expect(activate.statusCode).toBe(200);

    const active = await context.app.inject({ method: 'GET', url: '/api/workspaces/active' });
    expect(active.json().data.id).toBe(id);
  });

  it('切换：切换到第二条后第一条不再活跃', async () => {
    const first = await createWorkspace('切换 A');
    const second = await createWorkspace('切换 B');
    await context.app.inject({ method: 'POST', url: `/api/workspaces/${first}/activate` });
    await context.app.inject({ method: 'POST', url: `/api/workspaces/${second}/activate` });

    const active = await context.app.inject({ method: 'GET', url: '/api/workspaces/active' });
    expect(active.json().data.id).toBe(second);
  });

  it('切换不存在的工作区返回 404', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/00000000-0000-4000-8000-000000000000/activate',
    });
    expect(response.statusCode).toBe(404);
  });

  it('重命名可以改目录，也能显式解绑目录', async () => {
    const id = await createWorkspace('待改名', '/srv/old');
    const renamed = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: { name: '已改名' },
    });
    expect(renamed.json().data.name).toBe('已改名');
    // 只传 name 时 directory 不受影响。
    expect(renamed.json().data.directory).toBe('/srv/old');

    const unbound = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: { directory: null },
    });
    expect(unbound.json().data.directory).toBeNull();
  });

  it('可以绑定与解绑默认模型/默认 Agent（工作区决定默认配置）', async () => {
    const id = await createWorkspace('带默认配置');
    const modelId = '00000000-0000-4000-8000-000000000001';
    const agentId = '00000000-0000-4000-8000-000000000002';

    const bound = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: { defaultModelId: modelId, defaultAgentId: agentId },
    });
    expect(bound.statusCode).toBe(200);
    expect(bound.json().data.defaultModelId).toBe(modelId);
    expect(bound.json().data.defaultAgentId).toBe(agentId);

    // 解绑时另一个字段不动：两个引用是独立的，清一个不该顺手清另一个。
    const unbound = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: { defaultModelId: null },
    });
    expect(unbound.json().data.defaultModelId).toBeNull();
    expect(unbound.json().data.defaultAgentId).toBe(agentId);
  });

  it('新建时可以直接带上默认模型/默认 Agent 与目录', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces',
      payload: {
        name: '一次建好',
        directory: '/srv/bound',
        defaultModelId: '00000000-0000-4000-8000-000000000003',
      },
    });
    expect(response.statusCode).toBe(201);
    expect(response.json().data.directory).toBe('/srv/bound');
    expect(response.json().data.defaultModelId).toBe('00000000-0000-4000-8000-000000000003');
    // 没给的字段落成 null，而不是 undefined 缺键——前端可以直接当"未设置"渲染。
    expect(response.json().data.defaultAgentId).toBeNull();
  });

  it('改名撞上已有名字返回 409', async () => {
    await createWorkspace('占位名');
    const id = await createWorkspace('将被改名');
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: { name: '占位名' },
    });
    expect(response.statusCode).toBe(409);
  });

  it('空补丁被拒绝（避免无意义的写入）', async () => {
    const id = await createWorkspace('空补丁');
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/workspaces/${id}`,
      payload: {},
    });
    expect(response.statusCode).toBe(422);
  });

  it('删除当前工作区后 /active 返回 null', async () => {
    const id = await createWorkspace('将被删除');
    await context.app.inject({ method: 'POST', url: `/api/workspaces/${id}/activate` });

    const removed = await context.app.inject({ method: 'DELETE', url: `/api/workspaces/${id}` });
    expect(removed.statusCode).toBe(200);
    expect(removed.json().data.deleted).toBe(true);

    const active = await context.app.inject({ method: 'GET', url: '/api/workspaces/active' });
    expect(active.json().data).toBeNull();
  });

  it('删除工作区时同步删除框架创建的目录', async () => {
    const id = await createWorkspace('删除目录');
    const detail = await context.app.inject({ method: 'GET', url: `/api/workspaces/${id}` });
    const directory = detail.json().data.directory as string;
    expect(fs.existsSync(directory)).toBe(true);

    const removed = await context.app.inject({ method: 'DELETE', url: `/api/workspaces/${id}` });

    expect(removed.statusCode).toBe(200);
    expect(fs.existsSync(directory)).toBe(false);
  });

  it('删除不存在的工作区返回 404', async () => {
    const response = await context.app.inject({
      method: 'DELETE',
      url: '/api/workspaces/00000000-0000-4000-8000-000000000001',
    });
    expect(response.statusCode).toBe(404);
  });

  it('库里残留悬空的活动指针时 /active 自愈为 null', async () => {
    // 直接写一个不存在的 id，模拟工作区被外部删除后指针未清理的情况。
    await context.services.appState.set('active_workspace_id', '00000000-0000-4000-8000-0000000000ff');
    const response = await context.app.inject({ method: 'GET', url: '/api/workspaces/active' });
    expect(response.json().data).toBeNull();
    // 并且指针被清掉了，不是每次都重新算一遍。
    expect(await context.services.appState.get('active_workspace_id')).toBeNull();
  });
});
