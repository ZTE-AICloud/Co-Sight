/**
 * 模块面门禁专项（`/api/framework/v1/*`）。
 *
 * 这个文件的存在理由是：模块面**是唯一会输出明文密钥的接口**，所以它的门禁不是
 * "加上就完事"的功能，而是需要逐条钉死的性质。三条主线：
 *
 * 1. **fail closed**——任何异常输入（缺头、错方案、令牌不对、文件没了、文件写坏）
 *    都必须落到 401，不能落到 200，也不能落到 500。500 尤其危险：它会把
 *    错误文本里的文件路径带出去，而且会让人误以为"服务坏了"而不是"你没权限"。
 * 2. **不泄漏比对细节**——错令牌无论长度对不对，响应体逐字节相同。
 * 3. **纵深防御**——回环校验（Host + socket 地址）独立于令牌生效。
 */

import fs from 'node:fs';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const BASE_PATH = '/api/framework/v1/models';

let context: TestContext;

function inject(headers: Record<string, string> = {}, options: Record<string, unknown> = {}) {
  return context.app.inject({ method: 'GET', url: BASE_PATH, headers, ...options });
}

function auth(token: string) {
  return { authorization: `Bearer ${token}` };
}

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('令牌校验', () => {
  it('不带 Authorization → 401，且错误码是模块面专用键', async () => {
    const response = await inject();
    expect(response.statusCode).toBe(401);
    const body = response.json();
    expect(body.success).toBe(false);
    expect(body.error.code).toBe('UNAUTHORIZED');
    expect(body.error.messageKey).toBe('error.unauthorized.module_token');
  });

  it('错令牌：等长与不等长的响应体逐字节相同', async () => {
    const real = context.services.moduleToken.read() ?? '';
    expect(real).not.toBe('');

    // 与真令牌等长（只改最后一个字符）——防"长度对不对"被观测出来
    const sameLength = `${real.slice(0, -1)}${real.endsWith('A') ? 'B' : 'A'}`;
    const differentLength = 'short-token';

    const a = await inject(auth(sameLength));
    const b = await inject(auth(differentLength));

    expect(a.statusCode).toBe(401);
    expect(b.statusCode).toBe(401);
    // traceId 每次不同，比正文的 error 部分而不是整串
    expect(a.json().error.message).toBe(b.json().error.message);
    expect(a.json().error.messageKey).toBe(b.json().error.messageKey);
    expect(a.body).not.toContain(sameLength);
  });

  it('令牌放 query 不认——只认 Authorization 头', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const response = await context.app.inject({
      method: 'GET',
      url: `${BASE_PATH}?token=${encodeURIComponent(real)}`,
    });
    expect(response.statusCode).toBe(401);
  });

  it('非 Bearer 方案 → 401', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const basic = await inject({ authorization: `Basic ${real}` });
    expect(basic.statusCode).toBe(401);

    // 少了空格前缀也算方案不对
    const bare = await inject({ authorization: real });
    expect(bare.statusCode).toBe(401);
  });

  it('正确令牌 → 200', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const response = await inject(auth(real));
    expect(response.statusCode).toBe(200);
    expect(response.json().success).toBe(true);
  });
});

describe('fail closed', () => {
  it('令牌文件不存在时是 401，不是 200，也不是 500', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const filePath = context.services.paths.moduleToken;
    const backup = fs.readFileSync(filePath, 'utf8');
    fs.rmSync(filePath);

    try {
      expect(context.services.moduleToken.read()).toBeNull();
      const response = await inject(auth(real));
      expect(response.statusCode).toBe(401);
    } finally {
      fs.writeFileSync(filePath, backup, { mode: 0o600 });
    }
  });

  it('令牌文件内容写坏时是 401，且不把文件内容回显出去', async () => {
    const filePath = context.services.paths.moduleToken;
    const backup = fs.readFileSync(filePath, 'utf8');
    const garbage = 'not a valid token !!!';

    try {
      fs.writeFileSync(filePath, garbage, { mode: 0o600 });
      const response = await inject(auth(backup.trim()));
      expect(response.statusCode).toBe(401);
      expect(response.body).not.toContain(garbage);
    } finally {
      fs.writeFileSync(filePath, backup, { mode: 0o600 });
    }
  });
});

describe('回环纵深防御', () => {
  it('Host 不是回环名 → 403（DNS rebinding 形态）', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const response = await inject({ ...auth(real), host: 'evil.example.com' });
    expect(response.statusCode).toBe(403);
    // 403 先于令牌判定；即便令牌是错的也仍是 403，证明这道检查独立生效
    const wrong = await inject({ authorization: 'Bearer nope-nope-nope', host: 'evil.example.com' });
    expect(wrong.statusCode).toBe(403);
  });

  it('socket 地址不是回环 → 403', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const response = await inject(auth(real), { remoteAddress: '203.0.113.10' });
    expect(response.statusCode).toBe(403);
  });

  it('三种回环地址写法都放行', async () => {
    const real = context.services.moduleToken.read() ?? '';
    for (const remoteAddress of ['127.0.0.1', '::1', '::ffff:127.0.0.1']) {
      const response = await inject(auth(real), { remoteAddress });
      expect(response.statusCode, `remoteAddress=${remoteAddress}`).toBe(200);
    }
  });

  it('带 Origin 的请求被拒（浏览器形态）', async () => {
    const real = context.services.moduleToken.read() ?? '';
    const response = await inject({ ...auth(real), origin: 'http://127.0.0.1:4310' });
    expect(response.statusCode).toBe(403);
  });
});

describe('令牌文件本身', () => {
  it('落盘权限是 0600', () => {
    expect(context.services.moduleToken.fileMode()).toBe(0o600);
  });

  it('rotate() 后旧令牌立即 401、新令牌 200', async () => {
    const old = context.services.moduleToken.read() ?? '';
    const fresh = context.services.moduleToken.rotate();
    expect(fresh).not.toBe(old);

    expect((await inject(auth(old))).statusCode).toBe(401);
    expect((await inject(auth(fresh))).statusCode).toBe(200);

    // 复原，避免影响同文件里后续用例的假设
    context.services.moduleToken.rotate();
  });
});

describe('门禁是继承来的，不是每个路由文件各挂一次', () => {
  /*
   * 这一组测的是**结构**，不是行为。
   *
   * 门禁挂在 `routes/module-face.ts` 的 `onRequest` 上，`/models` 与 `/workspaces`
   * 是它内部注册的两个子树——于是"往模块面加一条新路由"这件事天然带着门禁。
   *
   * 为什么值得单独立一组：漏挂门禁的失败形态是**静默的**。它不报错、不 500，
   * 只是多出一个不需要认证的接口；如果那条接口恰好会返回明文密钥，
   * 泄漏会一直持续到有人偶然发现。所以这里不测"某一条路径要 401"，
   * 而是**遍历 spec 里模块面的每一条路径**，一条不落地要求 401。
   *
   * 遍历而不是逐个写死：写死的话，将来新增一条路径时这组用例会照样全绿。
   */

  /** 占位 id。校验器在门禁之后才跑，所以随便给个合法 uuid 就行。 */
  const ANY_ID = '00000000-0000-4000-8000-000000000000';

  it('spec 里每一条模块面路径，不带令牌都是 401', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/docs/json' });
    expect(response.statusCode).toBe(200);

    const operations = Object.entries(
      response.json().paths as Record<string, Record<string, unknown>>,
    ).filter(([pathname]) => pathname.startsWith('/api/framework/v1'));
    // 没有这一条，模块面被整个摘掉时下面那个循环会空转通过。
    expect(operations.length).toBeGreaterThan(0);

    for (const [pathname, spec] of operations) {
      const url = pathname.replace(/\{[^}]+\}/g, ANY_ID);
      /*
       * 必须用**该路径真实注册的方法**去请求。
       *
       * Fastify 的门禁是挂在路由上的：请求一个没有注册的方法（比如对
       * 只认 `POST` 的 `.../activate` 发 `GET`）会直接落到路由层的 404，
       * 钩子根本没有机会跑。那条 404 说明的是"这个方法不存在"，
       * 不是"门禁漏了"——用错方法去测，得到的结论会是假的。
       */
      const methods = Object.keys(spec);
      expect(methods.length, `${pathname} 上没有方法`).toBeGreaterThan(0);

      for (const method of methods) {
        const guarded = await context.app.inject({
          method: method.toUpperCase() as 'GET',
          url,
        });

        expect(guarded.statusCode, `${method.toUpperCase()} ${url} 没有门禁`).toBe(401);
        expect(
          guarded.json().error.messageKey,
          `${method.toUpperCase()} ${url} 的错误码不是模块面专用键`,
        ).toBe('error.unauthorized.module_token');
      }
    }
  });

  it('正确令牌下，两个子树都可达（证明 401 来自门禁而不是路径不存在）', async () => {
    // 缺了这条，上面两条会被"路径根本不存在（404 之外的某条错路）"蒙混过去。
    const real = context.services.moduleToken.read() ?? '';
    for (const url of ['/api/framework/v1/models', '/api/framework/v1/workspaces']) {
      const response = await context.app.inject({ method: 'GET', url, headers: auth(real) });
      expect(response.statusCode, url).toBe(200);
    }
  });
});
