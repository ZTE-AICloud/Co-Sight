/**
 * RAG 知识库仓储：「全局至多一条生效」这条不变量的四处入口。
 *
 * 四条路径各自都要守住它：直接激活、新建即生效、部分更新里带 `isActive: true`、
 * 以及**绕过仓储直接写库**（模拟手工改库或并发写）时由唯一索引兜底。
 * 最后一条尤其重要——仓储的顺序只是应用层的自觉，索引才是真正的不变量。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { ragKnowledgeBases } from '../src/db/schema';
import { newId } from '../src/lib/id';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

function repo() {
  return context.services.ragKnowledge;
}

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('RagKnowledgeRepository', () => {
  it('新建默认不生效，字段原样返回', async () => {
    const created = await repo().create({
      name: '默认知识库',
      routeUrl: 'https://kb.example.com/default',
      description: null,
      isActive: false,
    });
    expect(created.isActive).toBe(false);
    expect(created.description).toBeNull();
    expect(created.routeUrl).toBe('https://kb.example.com/default');
    expect(await repo().findActive()).toBeNull();
  });

  it('连续激活两条后，只有最后那条生效', async () => {
    const first = await repo().create({
      name: '第一条',
      routeUrl: 'https://kb.example.com/1',
      description: null,
      isActive: true,
    });
    expect((await repo().findActive())?.id).toBe(first.id);

    const second = await repo().create({
      name: '第二条',
      routeUrl: 'https://kb.example.com/2',
      description: null,
      isActive: false,
    });
    await repo().update(second.id, { isActive: true });

    const active = await repo().findActive();
    expect(active?.id).toBe(second.id);
    expect((await repo().findById(first.id))?.isActive).toBe(false);
  });

  it('新建时直接生效会清掉旧的生效项', async () => {
    const old = await repo().create({
      name: '旧生效项',
      routeUrl: 'https://kb.example.com/old',
      description: null,
      isActive: true,
    });
    const fresh = await repo().create({
      name: '新生效项',
      routeUrl: 'https://kb.example.com/new',
      description: null,
      isActive: true,
    });

    expect((await repo().findById(old.id))?.isActive).toBe(false);
    expect((await repo().findActive())?.id).toBe(fresh.id);
  });

  it('部分是更新：undefined 不改，null 清空说明', async () => {
    const created = await repo().create({
      name: '待更新',
      routeUrl: 'https://kb.example.com/edit',
      description: '原说明',
      isActive: false,
    });

    const renamed = await repo().update(created.id, { name: '改过名' });
    expect(renamed?.name).toBe('改过名');
    expect(renamed?.description).toBe('原说明');

    const cleared = await repo().update(created.id, { description: null });
    expect(cleared?.description).toBeNull();
    expect(cleared?.routeUrl).toBe('https://kb.example.com/edit');
  });

  it('取消生效只是关掉本条，不会顺带激活别人', async () => {
    const active = await repo().create({
      name: '将被取消',
      routeUrl: 'https://kb.example.com/off',
      description: null,
      isActive: true,
    });
    await repo().update(active.id, { isActive: false });
    expect(await repo().findActive()).toBeNull();
  });

  it('删除生效项后没有生效项，不自动补位', async () => {
    const active = await repo().create({
      name: '将被删除',
      routeUrl: 'https://kb.example.com/delete',
      description: null,
      isActive: true,
    });
    await repo().create({
      name: '旁边的一条',
      routeUrl: 'https://kb.example.com/other',
      description: null,
      isActive: false,
    });

    await expect(repo().deleteById(active.id)).resolves.toBe(true);
    expect(await repo().findActive()).toBeNull();
  });

  it('删除 / 更新不存在的 id 分别返回 false 与 null', async () => {
    const missing = newId();
    await expect(repo().deleteById(missing)).resolves.toBe(false);
    await expect(repo().update(missing, { name: '无主' })).resolves.toBeNull();
  });

  it('部分唯一索引兜底：绕过仓储也插不进第二条生效项', async () => {
    const now = new Date();
    const base = {
      name: '手工插入',
      routeUrl: 'https://kb.example.com/raw',
      description: null,
      createdAt: now,
      updatedAt: now,
    };

    await context.services.handle.db
      .insert(ragKnowledgeBases)
      .values({ ...base, id: newId(), isActive: true });

    // drizzle 把驱动错误包了一层（`Failed query: ...`），真正的 SQLITE_CONSTRAINT
    // 在 `cause` 里，所以要顺着 cause 看，不能只看外层消息。
    const error = await context.services.handle.db
      .insert(ragKnowledgeBases)
      .values({ ...base, id: newId(), isActive: true })
      .then(() => null)
      .catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(Error);
    expect(String((error as Error & { cause?: unknown }).cause)).toMatch(/UNIQUE/i);
  });
});
