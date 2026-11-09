/**
 * 模块面工作区接口（`/api/framework/v1/workspaces`）。
 *
 * 这一组与模型那组有一处本质区别：**它会碰磁盘**。`POST` 不传 `directory` 时，
 * 框架会在工作区根下建一个目录并绑定。于是这个文件里除了常规的 CRUD 与 404/409，
 * 还要守住三条与磁盘有关的性质：
 *
 * 1. **建出来的目录一定在根之内**——名字里带 `../../` 也不行（这是安全项）；
 * 2. **改名不动磁盘；删除只删框架自己建的工作区目录**——外部绑定目录是用户的文件；
 * 3. **用户手填的绝对路径不会被创建**——框架只管自己那一亩三分地。
 *
 * 纯函数那一层（slug 的字符集、长度、保留名、碰撞）在 `workspace-directory.test.ts`
 * 里逐条测；这里测的是"经 HTTP 走一遍之后，磁盘上到底是什么样"。
 */

import fs from 'node:fs';
import path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { PUBLIC_WORKSPACE_DIR_NAME } from '../src/config/paths';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const BASE_PATH = '/api/framework/v1/workspaces';
const MISSING_ID = '00000000-0000-4000-8000-000000000000';

let context: TestContext;
let token: string;

/** 带令牌打模块面。默认 `GET`，写操作自己覆盖 `method`。 */
function callModule(pathname: string, init: Record<string, unknown> = {}) {
  return context.app.inject({
    method: 'GET',
    url: `${BASE_PATH}${pathname}`,
    headers: { authorization: `Bearer ${token}` },
    ...init,
  });
}

async function createWorkspace(payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const response = await callModule('', {
    method: 'POST',
    payload: { name: `工作区-${String(Math.trunc(Math.random() * 1e9))}`, ...payload },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data as Record<string, unknown>;
}

/**
 * 工作区根下"真正属于某个工作区"的目录名。
 *
 * 排除 `_public`：它是框架自用的公共空间，由 `ensureDataPaths` 在启动时建好，
 * 与工作区记录无关。不过滤的话每个断言都要为它让路，最后就是没人看得懂的 `-1`。
 */
function workspaceDirs(): string[] {
  return fs
    .readdirSync(context.services.paths.workspaces)
    .filter((entry) => entry !== PUBLIC_WORKSPACE_DIR_NAME)
    .toSorted();
}

beforeAll(async () => {
  context = await createTestContext();
  token = context.services.moduleToken.read() ?? '';
  expect(token).not.toBe('');
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('模块面工作区：读', () => {
  it('列表初始为空，activeId 为 null', async () => {
    const response = await callModule('');
    expect(response.statusCode).toBe(200);
    const data = response.json().data as { items: unknown[]; activeId: string | null };
    expect(data.items).toEqual([]);
    expect(data.activeId).toBeNull();
  });

  it('没有生效工作区时 /active 是 200 + null，不是 404', async () => {
    const response = await callModule('/active');
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toBeNull();
  });

  it('列表里的 activeId 与 /active 返回的是同一条', async () => {
    const first = await createWorkspace({ name: '读-甲' });
    const second = await createWorkspace({ name: '读-乙' });

    await callModule(`/${String(second.id)}/activate`, { method: 'POST' });

    const list = (await callModule('')).json().data as { items: { id: string }[]; activeId: string };
    const active = (await callModule('/active')).json().data as { id: string };

    expect(list.activeId).toBe(second.id);
    expect(active.id).toBe(second.id);
    expect(list.items.map((item) => item.id)).toContain(first.id);
  });

  it('不存在的 id → 404', async () => {
    const response = await callModule(`/${MISSING_ID}`);
    expect(response.statusCode).toBe(404);
    expect(response.json().error.code).toBe('NOT_FOUND');
  });
});

describe('模块面工作区：建（会碰磁盘的那一步）', () => {
  it('不传 directory：框架在工作区根下建目录并绑定它的 realpath', async () => {
    const created = await createWorkspace({ name: '建目录用例' });

    const directory = String(created.directory);
    expect(path.isAbsolute(directory)).toBe(true);
    expect(fs.statSync(directory).isDirectory()).toBe(true);

    // 存的是规范化后的路径，不是拼出来的字符串——否则"两条记录指向同一个目录"
    // 在字符串比较下就不成立（macOS 上 `/Users/x` 与 `/users/x` 是同一个目录）。
    expect(directory).toBe(fs.realpathSync(directory));
    // 而且它必须真的在根之下（而不是被指到别处）。
    expect(path.dirname(directory)).toBe(fs.realpathSync(context.services.paths.workspaces));
  });

  it('directory 传 null 与不传等价（都走"框架建目录"那条路）', async () => {
    const created = await createWorkspace({ name: '传 null', directory: null });
    expect(String(created.directory)).not.toBe('null');
    expect(fs.statSync(String(created.directory)).isDirectory()).toBe(true);
  });

  it('名字里带 `../../` 也建不出根目录之外', async () => {
    /*
     * 工作区的 `name` 契约只 trim + 限长，**不限制字符**——它是显示名，
     * 凭什么不让人叫「周报助手 / 2026 Q1」。但它要变成一个路径段，
     * 而 `../../etc` 完全是一个合法的显示名。这条断言就是 slug 化存在的理由，
     * 所以它必须是端到端的（经 HTTP 打进来），而不是只测纯函数。
     */
    const before = workspaceDirs();
    const created = await createWorkspace({ name: '../../逃逸测试' });

    const directory = String(created.directory);
    const root = fs.realpathSync(context.services.paths.workspaces);

    // 目录名的**字符集合**里不可能出现 `/` 或 `.`——这条比"父目录对不对"更强：
    // 只要这个不变量成立，`..` 就永远构不成一个路径段，穿不出去。
    expect(path.basename(directory)).toBe('逃逸测试');
    expect(directory).toBe(path.join(root, '逃逸测试'));
    // 而它必须真的在根之下。`..` 若生效，这里会是 `/tmp/逃逸测试` 之类。
    expect(directory.startsWith(`${root}${path.sep}`)).toBe(true);
    // 根里正好多了它一个：没有在别处偷偷多建（重复建会在这里露馅）。
    expect(workspaceDirs()).toEqual([...before, '逃逸测试'].toSorted());
  });

  it('手填的绝对路径只绑定、不创建、也不要求存在', async () => {
    const target = path.join(context.home, '不存在的目录', '更深一层');
    expect(fs.existsSync(target)).toBe(false);

    const created = await createWorkspace({ name: '绑定手填路径', directory: target });
    expect(created.directory).toBe(target);
    // 对任意绝对路径 `mkdir -p` 等于把一个写原语交给调用方去碰用户整台机器，
    // 而且它会静默造出多层父目录。所以这里必须是 false。
    expect(fs.existsSync(target)).toBe(false);
  });

  it('重名 → 409（重名检查是唯一一道，没有唯一索引兜底）', async () => {
    await createWorkspace({ name: '重名检查' });
    const response = await callModule('', {
      method: 'POST',
      payload: { name: '重名检查' },
    });
    expect(response.statusCode).toBe(409);
    expect(response.json().error.code).toBe('CONFLICT');
  });

  it('相对路径 → 422（契约层挡住，不进业务）', async () => {
    const response = await callModule('', {
      method: 'POST',
      payload: { name: '相对路径', directory: 'relative/path' },
    });
    expect(response.statusCode).toBe(422);
  });
});

describe('模块面工作区：改（不动磁盘）', () => {
  it('改名字：记录变了，绑定的目录一个字没变，磁盘上也没多也没少', async () => {
    const created = await createWorkspace({ name: '改名前' });
    const directory = String(created.directory);

    const response = await callModule(`/${String(created.id)}`, {
      method: 'PATCH',
      payload: { name: '改名后' },
    });
    expect(response.statusCode).toBe(200);

    const updated = response.json().data as Record<string, unknown>;
    expect(updated.name).toBe('改名后');
    // 目录名是创建那一刻派生的一次性快照。跟着改名走意味着"用户改个显示名，
    // 磁盘上少了一个目录、多了一个目录"，而任何指向旧路径的东西会当场失效。
    expect(updated.directory).toBe(directory);
    expect(fs.existsSync(directory)).toBe(true);
  });

  it('改成自己的名字不算冲突', async () => {
    const created = await createWorkspace({ name: '自己改自己' });
    const response = await callModule(`/${String(created.id)}`, {
      method: 'PATCH',
      payload: { name: '自己改自己' },
    });
    expect(response.statusCode).toBe(200);
  });

  it('改成别人的名字 → 409', async () => {
    await createWorkspace({ name: '被占用的名字' });
    const created = await createWorkspace({ name: '想抢名字的' });

    const response = await callModule(`/${String(created.id)}`, {
      method: 'PATCH',
      payload: { name: '被占用的名字' },
    });
    expect(response.statusCode).toBe(409);
  });

  it('directory 传 null 只解绑，不删目录', async () => {
    const created = await createWorkspace({ name: '解绑用例' });
    const directory = String(created.directory);

    const response = await callModule(`/${String(created.id)}`, {
      method: 'PATCH',
      payload: { directory: null },
    });
    expect((response.json().data as Record<string, unknown>).directory).toBeNull();
    expect(fs.existsSync(directory)).toBe(true);
  });

  it('空 PATCH → 422；不存在的 id → 404', async () => {
    const created = await createWorkspace({ name: '空 PATCH 用例' });
    expect((await callModule(`/${String(created.id)}`, { method: 'PATCH', payload: {} })).statusCode)
      .toBe(422);
    expect(
      (await callModule(`/${MISSING_ID}`, { method: 'PATCH', payload: { name: 'x' } })).statusCode,
    ).toBe(404);
  });
});

describe('模块面工作区：切换与删除', () => {
  it('activate 不存在的 id → 404；存在的 → 200 且成为当前', async () => {
    expect((await callModule(`/${MISSING_ID}/activate`, { method: 'POST' })).statusCode).toBe(404);

    const created = await createWorkspace({ name: '激活用例' });
    const response = await callModule(`/${String(created.id)}/activate`, { method: 'POST' });
    expect(response.statusCode).toBe(200);
    expect((await callModule('/active')).json().data.id).toBe(created.id);
  });

  it('DELETE 返回 { id, deleted: true }，之后 404，并删掉框架创建的目录', async () => {
    const created = await createWorkspace({ name: '删除用例' });
    const id = String(created.id);
    const directory = String(created.directory);

    const response = await callModule(`/${id}`, { method: 'DELETE' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toEqual({ id, deleted: true });

    expect((await callModule(`/${id}`)).statusCode).toBe(404);
    // 只有框架自己按工作区名建的目录会被删除；外部绑定目录仍保留（服务层用例覆盖）。
    expect(fs.existsSync(directory)).toBe(false);
    expect(workspaceDirs()).not.toContain(path.basename(directory));
  });

  it('删掉当前工作区 → /active 变 null（指针不会悬空）', async () => {
    const created = await createWorkspace({ name: '删当前' });
    await callModule(`/${String(created.id)}/activate`, { method: 'POST' });
    expect((await callModule('/active')).json().data.id).toBe(created.id);

    await callModule(`/${String(created.id)}`, { method: 'DELETE' });
    const response = await callModule('/active');
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toBeNull();
  });

  it('DELETE 不存在的 id → 404', async () => {
    expect((await callModule(`/${MISSING_ID}`, { method: 'DELETE' })).statusCode).toBe(404);
  });
});

describe('跨面回归：工作区两个面形状一致', () => {
  it('模块面建的工作区，浏览器面看得见、字段一致', async () => {
    /*
     * 工作区**没有密钥**，所以两个面共用同一个 service 与同一份契约，实体形状没有任何差异。
     * 这条断言守的是"以后有人给模块面单独写一套投影"——那会立刻让两个面分叉，
     * 而分叉的表现是"某个字段只在一边更新"。
     */
    const created = await createWorkspace({ name: '跨面工作区' });

    const browser = await context.app.inject({ method: 'GET', url: `/api/workspaces/${String(created.id)}` });
    expect(browser.statusCode).toBe(200);
    expect(browser.json().data).toEqual(created);
  });

  it('列表的信封**刻意不同**：模块面多给一个 activeId', async () => {
    /*
     * 上面那条说的是实体（`Workspace`）一致；列表这一层两边**故意不一样**，
     * 而且这条差异是对的，所以要用断言把它固定下来，免得被"统一一下"改掉：
     *
     * - 浏览器面是纯列表（页面自己另外调 `/active`，它本来就要渲染两处）；
     * - 模块面是 `{items, activeId}`——消费方几乎总是"拿到列表 + 知道当前是哪个"，
     *   分开两次调用会引入一个竞态（两次之间有人切了工作区）。
     */
    const created = await createWorkspace({ name: '信封差异用例' });

    const moduleList = (await callModule('')).json().data as { items: { id: string }[]; activeId: string | null };
    const browserList = await context.app.inject({ method: 'GET', url: '/api/workspaces' });

    expect(Array.isArray(browserList.json().data)).toBe(true);
    expect(browserList.json().data.map((item: { id: string }) => item.id)).toContain(created.id);
    expect(Object.keys(moduleList).toSorted()).toEqual(['activeId', 'items']);
    expect(moduleList.items.map((item) => item.id)).toContain(created.id);
  });
});
