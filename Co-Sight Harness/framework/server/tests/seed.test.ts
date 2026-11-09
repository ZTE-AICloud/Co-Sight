/**
 * 种子写入（D13 = A）。
 *
 * 核心性质是**幂等**：服务每次启动都会调用它，如果重复插入，用户重启几次
 * `预置` 页签就会出现几倍的重复卡片——这是最容易发生、又最容易被忽略的问题。
 */

import fs from 'node:fs';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { PRESET_EXPERTS } from '../src/seed/data';
import {
  DEFAULT_RAG_KNOWLEDGE,
  DEFAULT_WORKSPACE_NAME,
  seedDefaultRagKnowledge,
  seedDefaultWorkspace,
  seedPresetExperts,
} from '../src/seed/seed';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

beforeEach(async () => {
  context = await createTestContext();
});

afterEach(async () => {
  await destroyTestContext(context);
});

describe('预置专家种子', () => {
  it('首次写入全部预置项，且全部标记为预置', async () => {
    const result = await seedPresetExperts(context.services);
    expect(result.inserted).toBe(PRESET_EXPERTS.length);
    expect(result.skipped).toBe(false);

    const { items } = await context.services.experts.list({
      filter: 'preset',
      page: 1,
      pageSize: 60,
    });
    expect(items).toHaveLength(PRESET_EXPERTS.length);
    expect(items.every((item) => item.isPreset)).toBe(true);
  });

  it('重复调用不产生重复数据', async () => {
    await seedPresetExperts(context.services);
    const second = await seedPresetExperts(context.services);
    expect(second.skipped).toBe(true);
    expect(second.inserted).toBe(0);
    expect(await context.services.experts.count()).toBe(PRESET_EXPERTS.length);
  });

  it('表非空时跳过，即使里面只有用户自己建的专家', async () => {
    const { createExpertInputSchema } = await import('harness-shared');
    await context.services.experts.create(
      createExpertInputSchema.parse({ name: '用户自建', author: '某人' }),
    );
    const result = await seedPresetExperts(context.services);
    expect(result.skipped).toBe(true);
  });

  it('force 会无条件再写一遍（用于恢复预置内容）', async () => {
    await seedPresetExperts(context.services);
    const forced = await seedPresetExperts(context.services, { force: true });
    expect(forced.inserted).toBe(PRESET_EXPERTS.length);
    expect(await context.services.experts.count()).toBe(PRESET_EXPERTS.length * 2);
  });

  it('预置项带有初始使用次数，让「最热」页签有可辨的顺序', async () => {
    await seedPresetExperts(context.services);
    const { items } = await context.services.experts.list({
      filter: 'hot',
      page: 1,
      pageSize: 60,
    });
    expect(items.every((item) => item.useCount > 0)).toBe(true);
    // 倒序：第一条不比第二条少。
    expect((items[0]?.useCount ?? 0) >= (items[1]?.useCount ?? 0)).toBe(true);
  });

  it('预置项的创建时间各不相同（避免「最新」退化成 id 序）', async () => {
    await seedPresetExperts(context.services);
    const { items } = await context.services.experts.list({
      filter: 'preset',
      page: 1,
      pageSize: 60,
    });
    const times = new Set(items.map((item) => item.createdAt));
    expect(times.size).toBe(PRESET_EXPERTS.length);
  });

  it('种子数据本身自洽：名称唯一、标签非空、署名统一', async () => {
    const names = PRESET_EXPERTS.map((item) => item.name);
    expect(new Set(names).size).toBe(names.length);
    for (const item of PRESET_EXPERTS) {
      expect(item.name.length).toBeGreaterThan(0);
      expect(item.description.length).toBeGreaterThan(0);
      expect(item.tags.length).toBeGreaterThan(0);
      expect(item.isPreset).toBe(true);
    }
  });
});

/**
 * 默认工作区：让"没有任何工作区"这个出厂状态不再出现。
 *
 * 为什么它重要：没有 active 工作区时，smart-factory 的前端连 `/agents` 都不请求，
 * 预置智能体即使已经登记在库里也一条都看不到（`AgentListPage.tsx` 的
 * `workspaceId === undefined` 提前返回）。所以"建出来"和"设为当前"两件事缺一不可。
 */
describe('默认工作区种子', () => {
  it('没有工作区时建一个并设为当前，目录落在工作区根下', async () => {
    const result = await seedDefaultWorkspace(context.services);

    expect(result.created).toBe(true);
    expect(result.skipped).toBe(false);
    expect(result.workspace?.name).toBe(DEFAULT_WORKSPACE_NAME);

    const { items, activeId } = await context.services.workspaces.overview();
    expect(items).toHaveLength(1);
    expect(activeId).toBe(items[0]?.id);

    const directory = items[0]?.directory;
    expect(directory).not.toBeNull();
    expect(directory?.startsWith(context.services.paths.workspaces)).toBe(true);
    expect(fs.statSync(directory! as string).isDirectory()).toBe(true);
  });

  it('已有工作区时完全不动，也不改当前工作区', async () => {
    const userWorkspace = await context.services.workspaces.create({
      name: '我自己的工作区',
      directory: null,
      defaultModelId: null,
      defaultAgentId: null,
    });
    await context.services.workspaces.activate(userWorkspace.id);

    const result = await seedDefaultWorkspace(context.services);

    expect(result.skipped).toBe(true);
    expect(result.created).toBe(false);
    const { items, activeId } = await context.services.workspaces.overview();
    expect(items).toHaveLength(1);
    expect(items[0]?.name).toBe('我自己的工作区');
    expect(activeId).toBe(userWorkspace.id);
  });

  it('用户把工作区删光后再启动会重建（与预置专家同一套语义）', async () => {
    const first = await seedDefaultWorkspace(context.services);
    await context.services.workspaces.deleteById(first.workspace!.id);

    const second = await seedDefaultWorkspace(context.services);

    expect(second.created).toBe(true);
    expect(second.workspace?.id).not.toBe(first.workspace?.id);
    expect((await context.services.workspaces.overview()).activeId).toBe(second.workspace?.id);
  });
});

describe('默认知识库路由种子', () => {
  it('首次写入出厂那条，并设为当前可用', async () => {
    const result = await seedDefaultRagKnowledge(context.services);
    expect(result.created).toBe(true);
    expect(result.base?.name).toBe(DEFAULT_RAG_KNOWLEDGE.name);

    const active = await context.services.ragKnowledge.findActive();
    expect(active?.routeUrl).toBe(DEFAULT_RAG_KNOWLEDGE.routeUrl);
    expect(active?.username).toBe(DEFAULT_RAG_KNOWLEDGE.username);
    // 密码进了 `.credentials.yaml`，读模型里只有掩码。
    expect(active?.hasPassword).toBe(true);
    expect(active?.passwordMasked).toBe('**********');
  });

  it('重复调用不产生重复数据', async () => {
    await seedDefaultRagKnowledge(context.services);
    const second = await seedDefaultRagKnowledge(context.services);

    expect(second.skipped).toBe(true);
    expect(second.created).toBe(false);
    expect(await context.services.ragKnowledge.list()).toHaveLength(1);
  });

  it('表非空时跳过，即使里面只有用户自己建的一条', async () => {
    await context.services.ragKnowledge.create({
      name: '用户自建',
      routeUrl: 'https://kb.example.com/mine',
      description: null,
      isActive: false,
    });

    expect((await seedDefaultRagKnowledge(context.services)).skipped).toBe(true);
    expect(await context.services.ragKnowledge.list()).toHaveLength(1);
  });
});
