/**
 * `src/api/client.ts` 的行为测试。
 *
 * 这个文件值得单独测（而不是只在页面用例里顺带覆盖），因为它是**所有**请求的
 * 唯一出入口：信封解包、错误分类、查询串拼装三件事只要有一处不对，
 * 表现都是远端的某次点击"没反应"或"提示是空白的"，很难反推到这一层。
 */

import { describe, expect, it } from 'vitest';

import { request, requestData } from '../src/api/client';
import { ApiNetworkError, ApiRequestError } from '../src/api/errors';
import { callInit, callUrl, envelope, errorEnvelope, jsonResponse, stubFetch, stubFetchRejected, textResponse } from './helpers/render';

/** 从 init 里取请求头。真实类型是 HeadersInit，客户端只会传普通对象。 */
function headers(init: RequestInit): Record<string, string> {
  return init.headers as Record<string, string>;
}

describe('request：成功路径', () => {
  it('拆开成功信封，返回 data 与 meta', async () => {
    const meta = { page: 1, pageSize: 30, total: 42, totalPages: 2, hasMore: true };
    stubFetch(jsonResponse(envelope({ items: ['a'] }, meta)));

    const result = await request<{ items: string[] }>('/experts');

    expect(result.data).toEqual({ items: ['a'] });
    expect(result.meta).toEqual(meta);
  });

  it('meta 整个缺失时给 null，而不是 undefined', async () => {
    // 客户端契约是 "非分页接口 meta 为 null"，调用方据此判断分页，
    // 返回 undefined 会让 `meta === null` 的判断悄悄失效。
    stubFetch(jsonResponse({ success: true, data: 1 }));

    const result = await request<number>('/ping');

    expect(result.meta).toBeNull();
  });

  it('requestData 只把 data 交出来', async () => {
    stubFetch(jsonResponse(envelope({ status: 'ok' })));

    await expect(requestData<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' });
  });

  it('默认 GET，同源携带 cookie', async () => {
    const mock = stubFetch(jsonResponse(envelope(null)));

    await request('/x');

    const init = callInit(mock);
    expect(init.method).toBe('GET');
    // 桥接会话靠 cookie；写成 'include' 会在跨源场景下多余地发送凭据。
    expect(init.credentials).toBe('same-origin');
  });

  it('带 body 时补 Content-Type 并 JSON 序列化，不带 body 时不出现该头', async () => {
    const mock = stubFetch(jsonResponse(envelope(null)));

    await request('/x', { method: 'POST', body: { workspaceId: null } });
    await request('/y');

    const withBody = callInit(mock, 0);
    expect(withBody.method).toBe('POST');
    expect(headers(withBody)['Content-Type']).toBe('application/json');
    // `null` 必须被序列化出来，不能被省略成 `{}`：
    // 服务端靠这个字段区分"不在任何工作区"与"字段漏传"。
    expect(withBody.body).toBe('{"workspaceId":null}');

    const withoutBody = callInit(mock, 1);
    expect('body' in withoutBody).toBe(false);
    expect(headers(withoutBody)['Content-Type']).toBeUndefined();
  });

  it('把 AbortSignal 透传给 fetch', async () => {
    const mock = stubFetch(jsonResponse(envelope(null)));
    const controller = new AbortController();

    await request('/x', { signal: controller.signal });

    expect(callInit(mock).signal).toBe(controller.signal);
  });
});

describe('request：查询串拼装', () => {
  it('跳过 undefined / null / 空串，保留 0 与 false', async () => {
    const mock = stubFetch(jsonResponse(envelope(null)));

    await request('/experts', {
      query: { filter: 'all', q: undefined, page: 1, archived: null, note: '', zero: 0, flag: false },
    });

    const url = new URL(callUrl(mock), 'http://host');
    expect(url.pathname).toBe('/api/experts');
    expect(url.searchParams.get('filter')).toBe('all');
    expect(url.searchParams.get('page')).toBe('1');
    // 0 和 false 是**有效值**：用 `if (value)` 判断会静默丢掉 `page=0`。
    expect(url.searchParams.get('zero')).toBe('0');
    expect(url.searchParams.get('flag')).toBe('false');
    expect(url.searchParams.has('q')).toBe(false);
    expect(url.searchParams.has('archived')).toBe(false);
    expect(url.searchParams.has('note')).toBe(false);
  });

  it('查询项全部被跳过时不留下孤零零的问号', async () => {
    const mock = stubFetch(jsonResponse(envelope(null)));

    await request('/experts', { query: { q: '', page: undefined } });

    expect(callUrl(mock)).toBe('/api/experts');
  });
});

describe('request：失败路径', () => {
  it('失败信封变成 ApiRequestError，并把服务端字段原样带出来', async () => {
    stubFetch(
      jsonResponse(
        errorEnvelope('not_found.expert', 'error.not_found.expert', {
          message: 'expert missing',
          traceId: 'trace-1',
        }),
        404,
      ),
    );

    const error = await request('/experts/none').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiRequestError);
    const apiError = error as ApiRequestError;
    expect(apiError.status).toBe(404);
    expect(apiError.messageKey).toBe('error.not_found.expert');
    expect(apiError.traceId).toBe('trace-1');
    // 界面文案一律经词表渲染，Error.message 只用于日志。
    expect(apiError.message).toBe('expert missing');
  });

  it('校验类错误把字段明细带出来，供表单逐项标红', async () => {
    stubFetch(
      jsonResponse(
        errorEnvelope('validation_failed', 'error.validation_failed', {
          details: [{ path: 'name', code: 'too_big', message: '名称过长' }],
        }),
        422,
      ),
    );

    const error = (await request('/experts', { method: 'POST' }).catch((caught: unknown) => caught)) as ApiRequestError;

    expect(error.fieldIssues()).toEqual([{ path: 'name', code: 'too_big', message: '名称过长' }]);
  });

  it('非校验类错误没有字段明细时返回空数组', async () => {
    stubFetch(jsonResponse(errorEnvelope('internal', 'error.internal'), 500));

    const error = (await request('/x').catch((caught: unknown) => caught)) as ApiRequestError;

    expect(error.fieldIssues()).toEqual([]);
  });

  it('返回 HTML 而不是信封时算网络层错误，不能当成成功', async () => {
    // 典型成因：代理把 /api 指到了静态站点，404 页面被当成接口响应。
    stubFetch(textResponse('<!doctype html><html>not found</html>', 404));

    const error = await request('/experts').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiNetworkError);
    expect((error as ApiNetworkError).message).toContain('不是合法 JSON');
  });

  it('是合法 JSON 但没有信封结构时也算网络层错误', async () => {
    // 只校验 `success` 存在是不够的：任何恰好带这个字段的响应都会被当成信封，
    // 然后在取 data 时拿到 undefined 一路传到很深的组件里才炸。
    stubFetch(jsonResponse({ success: true }));

    const error = await request('/x').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiNetworkError);
  });

  it('空响应体不能被当成成功', async () => {
    stubFetch(textResponse('', 200));

    const error = await request('/x').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiNetworkError);
    expect((error as ApiNetworkError).message).toContain('不是标准信封');
  });

  it('连接失败时抛 ApiNetworkError，并保留原始异常作为 cause', async () => {
    const cause = new TypeError('Failed to fetch');
    stubFetchRejected(cause);

    const error = await request('/x').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiNetworkError);
    // cause 是排查现场的唯一线索（CORS 被拒、连接被拒、DNS 失败长得一模一样）。
    expect((error as ApiNetworkError).cause).toBe(cause);
  });

  it('AbortError 原样抛出', async () => {
    // 主动取消（切页签、改搜索词）是正常控制流，包成网络错误会让
    // "用户自己取消了"显示成"连不上服务端"。
    const abort = new DOMException('aborted', 'AbortError');
    stubFetchRejected(abort);

    await expect(request('/x')).rejects.toBe(abort);
  });
});
