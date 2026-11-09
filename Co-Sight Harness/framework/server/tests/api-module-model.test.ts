/**
 * 模块面模型接口（`/api/framework/v1/models`）。
 *
 * 这是**唯一**会输出明文密钥的接口面，所以这个文件里成对写断言：
 * 明文出现在它该出现的地方（详情、active），**且不出现在它不该出现的地方**（列表、
 * 浏览器面）。只断言"详情里有密钥"是不够的——某天有人把详情映射复制到列表映射上，
 * 那种测试照样全绿。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { ModuleModelSecret } from 'harness-shared/module-models';

import { secretRef } from '../src/credentials/store';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const API_KEY = 'sk-live-do-not-leak-0123456789';
const BASE_PATH = '/api/framework/v1/models';

let context: TestContext;
let token: string;

/** 带令牌打模块面。默认成功，失败用例自己走 `inject`。 */
function callModule(path: string, init: Record<string, unknown> = {}) {
  return context.app.inject({
    method: 'GET',
    url: `${BASE_PATH}${path}`,
    headers: { authorization: `Bearer ${token}` },
    ...init,
  });
}

async function createModel(payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const response = await context.app.inject({
    method: 'POST',
    url: '/api/models',
    payload: {
      provider: 'openai',
      label: '模块面用例',
      modelName: 'gpt-5',
      apiKey: API_KEY,
      ...payload,
    },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data as Record<string, unknown>;
}

beforeAll(async () => {
  context = await createTestContext();
  token = context.services.moduleToken.read() ?? '';
  expect(token).not.toBe('');
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('模块面：详情接口', () => {
  it('详情逐字段等于写入值，且带明文密钥与推理参数', async () => {
    const created = await createModel({
      label: '逐字段',
      modelName: 'claude-sonnet-5-5',
      baseUrl: 'https://api.example.com/v1',
      temperature: 0.3,
      topP: 0.9,
      maxOutputTokens: 4096,
      contextWindow: 200000,
      timeoutSeconds: 300,
    });

    const response = await callModule(`/${String(created.id)}`);
    expect(response.statusCode).toBe(200);

    const data = response.json().data as ModuleModelSecret;
    expect(data).toEqual({
      id: created.id,
      provider: 'openai',
      protocol: 'openai',
      label: '逐字段',
      modelName: 'claude-sonnet-5-5',
      baseUrl: 'https://api.example.com/v1',
      hasApiKey: true,
      isActive: false,
      createdAt: created.createdAt,
      updatedAt: created.updatedAt,
      apiKey: API_KEY,
      temperature: 0.3,
      topP: 0.9,
      maxOutputTokens: 4096,
      contextWindow: 200000,
      timeoutSeconds: 300,
    });
  });

  it('未配密钥时 apiKey 为 null，而不是空串或掩码', async () => {
    const created = await createModel({ label: '无密钥', apiKey: null });
    const data = (await callModule(`/${String(created.id)}`)).json().data as ModuleModelSecret;
    expect(data.apiKey).toBeNull();
    expect(data.hasApiKey).toBe(false);
  });

  it('详情里没有 apiKeyMasked 字段', async () => {
    const created = await createModel({ label: '无掩码' });
    const data = (await callModule(`/${String(created.id)}`)).json().data as Record<string, unknown>;
    expect('apiKeyMasked' in data).toBe(false);
  });

  it('不存在的 id → 404', async () => {
    const response = await callModule('/00000000-0000-4000-8000-000000000000');
    expect(response.statusCode).toBe(404);
    expect(response.json().success).toBe(false);
    expect(response.json().error.code).toBe('NOT_FOUND');
  });

  it('五个 provider 的 protocol 派生全覆盖', async () => {
    const cases: [string, string][] = [
      ['anthropic', 'anthropic'],
      ['openai', 'openai'],
      ['azure-openai', 'openai'],
      ['ollama', 'openai'],
      ['openai-compatible', 'openai'],
    ];
    for (const [provider, expected] of cases) {
      const created = await createModel({ label: `协议-${provider}`, provider });
      const data = (await callModule(`/${String(created.id)}`)).json().data as ModuleModelSecret;
      expect(data.protocol).toBe(expected);
    }
  });

  it('baseUrl 为 null 时原样返回 null，不做默认值推导', async () => {
    const created = await createModel({ label: '无地址', baseUrl: null });
    const data = (await callModule(`/${String(created.id)}`)).json().data as ModuleModelSecret;
    expect(data.baseUrl).toBeNull();
  });
});

describe('模块面：/active', () => {
  it('没有生效模型时返回 200 且 data 为 null（不是 404）', async () => {
    const response = await callModule('/active');
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toBeNull();
  });

  it('激活后返回该模型，带明文密钥', async () => {
    const created = await createModel({ label: '激活项' });
    const activate = await context.app.inject({
      method: 'POST',
      url: `/api/models/${String(created.id)}/activate`,
    });
    expect(activate.statusCode).toBe(200);

    const response = await callModule('/active');
    expect(response.statusCode).toBe(200);
    const data = response.json().data as ModuleModelSecret;
    expect(data.id).toBe(created.id);
    expect(data.isActive).toBe(true);
    expect(data.apiKey).toBe(API_KEY);
  });
});

describe('模块面：列表接口', () => {
  it('列表不含明文密钥，也不含 apiKeyMasked', async () => {
    await createModel({ label: '列表泄漏检查' });
    const response = await callModule('');
    expect(response.statusCode).toBe(200);
    expect(response.body).not.toContain(API_KEY);

    const items = response.json().data.items as Record<string, unknown>[];
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect('apiKey' in item).toBe(false);
      expect('apiKeyMasked' in item).toBe(false);
    }
  });

  it('activeId 与生效项一致；未激活时为 null', async () => {
    const body = (await callModule('')).json().data as {
      items: { id: string; isActive: boolean }[];
      activeId: string | null;
    };
    const active = body.items.filter((item) => item.isActive);
    expect(active.length).toBeLessThanOrEqual(1);
    expect(body.activeId).toBe(active[0]?.id ?? null);
  });
});

describe('模块面：写接口（D33）', () => {
  /*
   * 写接口的破坏力比读大：一枚泄漏的令牌原来只能读走密钥，现在还能把平台配置改成
   * 攻击者想要的样子。所以这里除了成功路径，还要钉住三件事：
   *
   * 1. **不传的字段不能被改**——`PATCH` 是"部分更新"，退化成"整体覆盖"会把用户没碰过的
   *    字段静默清空（最典型的是密钥被一次改名请求抹掉）；
   * 2. **写响应的明文形状与详情一致**（含 `apiKey`）——这是刻意的取舍，得有人守着；
   * 3. **DELETE 连带删掉 `.credentials.yaml` 里的那条密钥**——只删库行会留下孤儿密钥。
   */

  it('POST 建模型：201，响应是含明文的详情形状，且真的落库', async () => {
    const response = await callModule('', {
      method: 'POST',
      payload: {
        provider: 'anthropic',
        label: '模块面新建',
        modelName: 'claude-sonnet-5-5',
        apiKey: API_KEY,
      },
    });

    expect(response.statusCode).toBe(201);
    const data = response.json().data as ModuleModelSecret;
    expect(data.apiKey).toBe(API_KEY);
    expect(data.label).toBe('模块面新建');
    expect(data.protocol).toBe('anthropic');
    expect(data.isActive).toBe(false);

    // "落库了"要另外确认一次：响应可能是拼出来的假象。
    const reread = await callModule(`/${String(data.id)}`);
    expect(reread.statusCode).toBe(200);
    expect((reread.json().data as ModuleModelSecret).modelName).toBe('claude-sonnet-5-5');
  });

  it('POST 的 provider 非法 → 422', async () => {
    const response = await callModule('', {
      method: 'POST',
      payload: { provider: 'not-a-provider', label: 'x', modelName: 'x' },
    });
    expect(response.statusCode).toBe(422);
  });

  it('PATCH 只改传进来的字段，密钥与其余字段一概不动', async () => {
    const created = await createModel({
      label: '部分更新前',
      baseUrl: 'https://api.example.com/v1',
      temperature: 0.25,
    });
    const id = String(created.id);

    const response = await callModule(`/${id}`, {
      method: 'PATCH',
      payload: { label: '部分更新后' },
    });
    expect(response.statusCode).toBe(200);

    const data = response.json().data as ModuleModelSecret;
    expect(data.label).toBe('部分更新后');
    // 一次改名请求不该顺手动到这三样——这正是"部分更新"与"整体覆盖"的分界。
    expect(data.apiKey).toBe(API_KEY);
    expect(data.baseUrl).toBe('https://api.example.com/v1');
    expect(data.temperature).toBe(0.25);
  });

  it('PATCH 的 apiKey 三态：不传=保持、null=清除、字符串=覆盖', async () => {
    const created = await createModel({ label: '密钥三态' });
    const id = String(created.id);
    const ref = secretRef('model', id);

    const kept = await callModule(`/${id}`, { method: 'PATCH', payload: { temperature: 0.4 } });
    expect((kept.json().data as ModuleModelSecret).apiKey).toBe(API_KEY);
    expect(context.services.credentials.read(ref)).toBe(API_KEY);

    const cleared = await callModule(`/${id}`, { method: 'PATCH', payload: { apiKey: null } });
    const clearedData = cleared.json().data as ModuleModelSecret;
    expect(clearedData.apiKey).toBeNull();
    expect(clearedData.hasApiKey).toBe(false);
    // 库里的字段变了不算数，凭据文件里的那条也得真的没了。
    expect(context.services.credentials.read(ref)).toBeNull();

    const overwritten = await callModule(`/${id}`, {
      method: 'PATCH',
      payload: { apiKey: 'sk-rotated-9999' },
    });
    expect((overwritten.json().data as ModuleModelSecret).apiKey).toBe('sk-rotated-9999');
    expect(context.services.credentials.read(ref)).toBe('sk-rotated-9999');
  });

  it('PATCH isActive 顶掉原来的生效项（模块面没有单独的 /activate）', async () => {
    const first = await createModel({ label: '生效-1' });
    const second = await createModel({ label: '生效-2' });

    expect(
      (await callModule(`/${String(first.id)}`, { method: 'PATCH', payload: { isActive: true } }))
        .statusCode,
    ).toBe(200);
    expect((await callModule('/active')).json().data.id).toBe(first.id);

    expect(
      (await callModule(`/${String(second.id)}`, { method: 'PATCH', payload: { isActive: true } }))
        .statusCode,
    ).toBe(200);
    const activeNow = (await callModule('/active')).json().data;
    expect(activeNow.id).toBe(second.id);

    // 全局至多一个生效项：置新的之后，旧的必须不再是生效项。
    const firstNow = (await callModule(`/${String(first.id)}`)).json().data as ModuleModelSecret;
    expect(firstNow.isActive).toBe(false);
  });

  it('PATCH 空对象 → 422；不存在的 id → 404', async () => {
    const created = await createModel({ label: '空 PATCH' });
    const empty = await callModule(`/${String(created.id)}`, { method: 'PATCH', payload: {} });
    expect(empty.statusCode).toBe(422);

    const missing = await callModule('/00000000-0000-4000-8000-000000000000', {
      method: 'PATCH',
      payload: { label: 'x' },
    });
    expect(missing.statusCode).toBe(404);
  });

  it('DELETE 返回 { id, deleted: true }，之后详情 404，密钥也一并删掉', async () => {
    const created = await createModel({ label: '待删除' });
    const id = String(created.id);
    const ref = secretRef('model', id);
    expect(context.services.credentials.read(ref)).toBe(API_KEY);

    const response = await callModule(`/${id}`, { method: 'DELETE' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data).toEqual({ id, deleted: true });

    expect((await callModule(`/${id}`)).statusCode).toBe(404);
    // 只删库行会留下孤儿密钥：清单里还有它，但没有任何模型指向它，谁也删不掉。
    expect(context.services.credentials.read(ref)).toBeNull();
  });

  it('DELETE 不存在的 id → 404', async () => {
    const response = await callModule('/00000000-0000-4000-8000-000000000000', {
      method: 'DELETE',
    });
    expect(response.statusCode).toBe(404);
  });
});

describe('跨面回归：同一份数据，两个面', () => {
  it('模块面拿得到明文，浏览器面同时仍拿不到', async () => {
    const created = await createModel({ label: '跨面' });
    const id = String(created.id);

    const moduleDetail = await callModule(`/${id}`);
    expect((moduleDetail.json().data as ModuleModelSecret).apiKey).toBe(API_KEY);

    const browserDetail = await context.app.inject({ method: 'GET', url: `/api/models/${id}` });
    expect(browserDetail.statusCode).toBe(200);
    expect(browserDetail.body).not.toContain(API_KEY);
    expect(browserDetail.json().data.apiKeyMasked).toBe('**********');

    const browserList = await context.app.inject({ method: 'GET', url: '/api/models' });
    expect(browserList.body).not.toContain(API_KEY);
  });

  it('模块面**写**出来的模型，浏览器面同样拿不到明文', async () => {
    /*
     * 写接口最值得担心的一种回归：为了让写响应带上明文，有人把模块面的投影逻辑
     * 下沉/复用到共用的地方，于是浏览器面也开始回传明文。上面那条测的是
     * "库里的数据拿不到明文"，这条测的是"**经模块面写进去的**数据也拿不到"——
     * 两条路径不同（一条走 repository 的 create，一条走 update），得分别覆盖。
     */
    const created = await callModule('', {
      method: 'POST',
      payload: {
        provider: 'openai',
        label: '模块面写入的跨面检查',
        modelName: 'gpt-5',
        apiKey: API_KEY,
      },
    });
    const id = String((created.json().data as ModuleModelSecret).id);

    const patched = await callModule(`/${id}`, {
      method: 'PATCH',
      payload: { apiKey: `${API_KEY}-rotated` },
    });
    expect(patched.statusCode).toBe(200);

    for (const url of ['/api/models', `/api/models/${id}`]) {
      const browser = await context.app.inject({ method: 'GET', url });
      expect(browser.statusCode).toBe(200);
      expect(browser.body, `${url} 泄漏了明文密钥`).not.toContain(API_KEY);
    }
  });
});
