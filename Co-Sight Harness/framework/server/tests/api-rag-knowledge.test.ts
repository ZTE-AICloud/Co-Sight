/**
 * RAG 知识库浏览器面（`/api/rag-knowledge/*`）。
 *
 * 除常规 CRUD，这里守三条容易被"顺手改坏"的语义：
 *
 * 1. **没有生效项回 `200 + data: null`**，不是 404——前端据此渲染空态而不是错误态；
 * 2. **激活是"切换"**：新的一条生效后，旧的必须变回 false，列表里不能同时出现两个徽标；
 * 3. **非法路由在边界被拒**（`javascript:` 一类），422 且不落库。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const BASE_PATH = '/api/rag-knowledge';
const MISSING_ID = '00000000-0000-4000-8000-000000000000';

let context: TestContext;

async function createKb(payload: Record<string, unknown> = {}) {
  return context.app.inject({
    method: 'POST',
    url: BASE_PATH,
    payload: {
      name: '产品知识库',
      routeUrl: 'https://kb.example.com/kb/42',
      ...payload,
    },
  });
}

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('RAG 知识库浏览器面', () => {
  it('空列表与空生效项都是 200 + null 语义', async () => {
    const list = await context.app.inject({ method: 'GET', url: BASE_PATH });
    expect(list.statusCode).toBe(200);
    expect(list.json().data).toEqual([]);

    const active = await context.app.inject({ method: 'GET', url: `${BASE_PATH}/active` });
    expect(active.statusCode).toBe(200);
    expect(active.json().data).toBeNull();
  });

  it('/defaults 只说"有没有"默认 API Key，且没被 /:id 吞掉', async () => {
    const response = await context.app.inject({ method: 'GET', url: `${BASE_PATH}/defaults` });
    expect(response.statusCode).toBe(200);
    /*
     * 测试环境没设 CO_KNOWLEDGE_API_KEY。同时这条断言也守住路由顺序：
     * 若 `/defaults` 被 `/:id` 吃掉，uuid 校验会让它变成 422 而不是 200。
     */
    expect(response.json().data).toEqual({ hasDefaultApiKey: false });
  });

  it('新增：补默认值，未生效', async () => {
    const response = await createKb();
    expect(response.statusCode).toBe(201);
    const created = response.json().data as Record<string, unknown>;
    expect(created.isActive).toBe(false);
    expect(created.description).toBeNull();
    expect(created.routeUrl).toBe('https://kb.example.com/kb/42');
    // 账号密码的缺省值是 null，不是空串（见契约里的 `default(null)`）。
    expect(created.username).toBeNull();
    expect(created.hasPassword).toBe(false);
    expect(created.passwordMasked).toBeNull();
    // API Key 与密码同一套缺省：没配就是 false + null。
    expect(created.hasApiKey).toBe(false);
    expect(created.apiKeyMasked).toBeNull();
  });

  it('新增时直接设为可用', async () => {
    const response = await createKb({ name: '直接生效', isActive: true });
    expect(response.statusCode).toBe(201);
    expect(response.json().data.isActive).toBe(true);

    const active = await context.app.inject({ method: 'GET', url: `${BASE_PATH}/active` });
    expect(active.json().data.name).toBe('直接生效');
  });

  it('激活即切换：旧的生效项自动变回 false', async () => {
    const first = (await createKb({ name: '甲', isActive: true })).json().data;
    const second = (await createKb({ name: '乙' })).json().data;

    const activated = await context.app.inject({
      method: 'POST',
      url: `${BASE_PATH}/${String(second.id)}/activate`,
    });
    expect(activated.statusCode).toBe(200);
    expect(activated.json().data.isActive).toBe(true);

    const list = (await context.app.inject({ method: 'GET', url: BASE_PATH })).json()
      .data as Record<string, unknown>[];
    const activeNames = list.filter((item) => item.isActive === true).map((item) => item.name);
    expect(activeNames).toEqual(['乙']);
    expect(list.find((item) => item.id === first.id)?.isActive).toBe(false);
  });

  it('PATCH 部分更新，空补丁被拒', async () => {
    const created = (await createKb({ name: '待改名' })).json().data;

    const patched = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: { name: '改过名', description: '新说明' },
    });
    expect(patched.statusCode).toBe(200);
    expect(patched.json().data.name).toBe('改过名');
    expect(patched.json().data.description).toBe('新说明');

    const empty = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: {},
    });
    expect(empty.statusCode).toBe(422);
  });

  it('非法跳转路由在边界被拒，且不落库', async () => {
    const before = (await context.app.inject({ method: 'GET', url: BASE_PATH })).json().data
      .length;

    for (const routeUrl of [
      'javascript:alert(1)',
      'file:///etc/passwd',
      'https://u:p@kb.example.com/',
    ]) {
      const response = await createKb({ name: '恶意路由', routeUrl });
      expect(response.statusCode).toBe(422);
    }

    const after = (await context.app.inject({ method: 'GET', url: BASE_PATH })).json().data
      .length;
    expect(after).toBe(before);
  });

  it('删除生效项后 /active 回到 null', async () => {
    const created = (await createKb({ name: '将被删除', isActive: true })).json().data;

    const deleted = await context.app.inject({
      method: 'DELETE',
      url: `${BASE_PATH}/${String(created.id)}`,
    });
    expect(deleted.statusCode).toBe(200);
    expect(deleted.json().data).toEqual({ id: created.id, deleted: true });

    const active = await context.app.inject({ method: 'GET', url: `${BASE_PATH}/active` });
    expect(active.json().data).toBeNull();
  });

  it('不存在的 id 一律 404', async () => {
    const cases = [
      { method: 'GET' as const, url: `${BASE_PATH}/${MISSING_ID}` },
      { method: 'PATCH' as const, url: `${BASE_PATH}/${MISSING_ID}`, payload: { name: 'x' } },
      { method: 'DELETE' as const, url: `${BASE_PATH}/${MISSING_ID}` },
      { method: 'POST' as const, url: `${BASE_PATH}/${MISSING_ID}/activate` },
    ];
    for (const request of cases) {
      const response = await context.app.inject(request);
      expect(response.statusCode).toBe(404);
      expect(response.json().error.code).toBe('NOT_FOUND');
    }
  });
});

/**
 * 密码遵循 D26（只写不读），与模型密钥完全同一条路。
 *
 * 这三条是那个决定的**可执行版本**：浏览器面永远拿不到明文（第一、二条），
 * 而删除必须连带清掉 `.credentials.yaml` 里的键（第三条），否则数据目录里会堆
 * 一批没人引用的密码。
 */
describe('RAG 知识库账号密码（浏览器面只写不读）', () => {
  it('新增带账号密码时只回 hasPassword 与固定掩码', async () => {
    const response = await createKb({ name: '带密码', username: ' admin ', password: 'kb-s3cret' });
    expect(response.statusCode).toBe(201);
    const created = response.json().data as Record<string, unknown>;
    expect(created.username).toBe('admin');
    expect(created.hasPassword).toBe(true);
    expect(created.passwordMasked).toBe('**********');
    // 整个响应体里都不能出现明文。
    expect(JSON.stringify(created)).not.toContain('kb-s3cret');
  });

  it('PATCH 不带 password = 保持；送 null = 清除', async () => {
    const created = (await createKb({ name: '改密码', username: 'u', password: 'first-pass' }))
      .json().data as Record<string, unknown>;

    const kept = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: { name: '改过名' },
    });
    expect(kept.json().data.hasPassword).toBe(true);

    const cleared = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: { password: null },
    });
    expect(cleared.json().data.hasPassword).toBe(false);
    expect(cleared.json().data.passwordMasked).toBeNull();
  });

  it('删除后密钥文件里不留孤儿', async () => {
    const created = (await createKb({ name: '删密钥', password: 'orphan-check' })).json()
      .data as Record<string, unknown>;
    const ref = `rag-knowledge:${String(created.id)}`;
    expect(context.services.credentials.read(ref)).toBe('orphan-check');

    await context.app.inject({ method: 'DELETE', url: `${BASE_PATH}/${String(created.id)}` });
    expect(context.services.credentials.read(ref)).toBeNull();
  });
});

/**
 * API Key 与密码走同一条 D26 路（只写不读、三态 PATCH、删除清孤儿），
 * 但它的**用途不同**：密码是给浏览器登录知识库用的，API Key 是给模块
 * （smart-factory）调知识服务的 Agent API 用的。这里守浏览器面这一侧。
 */
describe('RAG 知识库 API Key（浏览器面只写不读）', () => {
  it('新增带 API Key 时只回 hasApiKey 与固定掩码', async () => {
    const response = await createKb({ name: '带密钥', apiKey: 'ragk_s3cret_key' });
    expect(response.statusCode).toBe(201);
    const created = response.json().data as Record<string, unknown>;
    expect(created.hasApiKey).toBe(true);
    expect(created.apiKeyMasked).toBe('**********');
    // 整个响应体里都不能出现明文。
    expect(JSON.stringify(created)).not.toContain('ragk_s3cret_key');
  });

  it('PATCH 不带 apiKey = 保持；送 null = 清除', async () => {
    const created = (await createKb({ name: '改密钥', apiKey: 'first-key' })).json()
      .data as Record<string, unknown>;

    const kept = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: { name: '改过名' },
    });
    expect(kept.json().data.hasApiKey).toBe(true);

    const cleared = await context.app.inject({
      method: 'PATCH',
      url: `${BASE_PATH}/${String(created.id)}`,
      payload: { apiKey: null },
    });
    expect(cleared.json().data.hasApiKey).toBe(false);
    expect(cleared.json().data.apiKeyMasked).toBeNull();
    // 清除必须连密钥文件一起清掉，否则 `hasApiKey` 与文件会互相说谎。
    expect(
      context.services.credentials.read(`rag-knowledge-api-key:${String(created.id)}`),
    ).toBeNull();
  });

  it('删除后密钥文件里不留孤儿（与密码是两枚独立的键）', async () => {
    const created = (await createKb({ name: '删密钥', password: 'p', apiKey: 'orphan-key' }))
      .json().data as Record<string, unknown>;
    const apiKeyRef = `rag-knowledge-api-key:${String(created.id)}`;
    expect(context.services.credentials.read(apiKeyRef)).toBe('orphan-key');

    await context.app.inject({ method: 'DELETE', url: `${BASE_PATH}/${String(created.id)}` });
    expect(context.services.credentials.read(apiKeyRef)).toBeNull();
  });
});
