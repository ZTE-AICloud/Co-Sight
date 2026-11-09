/**
 * 查询层的三块"非组件"逻辑：错误类型、Query 客户端默认值与重试策略、错误文案降级。
 *
 * 为什么这三块要单测：
 * - `looksLikeEnvelope` 是"响应体是不是标准信封"的**唯一**判据。判错一次，
 *   后面整条链会把代理返回的 HTML 当 JSON 往下传，报错出现在离根因很远的地方；
 * - 重试策略决定用户等多久才看到错误（4xx 立刻、5xx 多等一次），而它只写在
 *   `defaultOptions` 里，页面级用例看不到；
 * - 文案降级顺序决定"后端没启动"会不会被说成"服务内部错误"——这两句话把用户
 *   指向完全不同的排查方向，混了比没有提示更糟。
 */

import type { ApiError, ApiErrorCode, FieldIssue } from 'harness-shared';
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { request } from '../src/api/client';
import {
  ApiNetworkError,
  ApiRequestError,
  isApiNetworkError,
  isApiRequestError,
  looksLikeEnvelope,
} from '../src/api/errors';
import { createQueryClient } from '../src/api/queryClient';
import { useApiErrorMessage } from '../src/api/useApiErrorMessage';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { errorEnvelope, jsonResponse, stubFetch, stubFetchRejected } from './helpers/render';

/** 造一个服务端错误体。字段名与 framework/shared/src/errors.ts 的 `ApiError` 一致。 */
function makeApiError(
  code: ApiErrorCode,
  messageKey: string,
  extra: { details?: FieldIssue[] | null; traceId?: string | null; message?: string } = {},
): ApiError {
  return {
    code,
    messageKey,
    message: extra.message ?? '服务端兜底文案',
    details: extra.details ?? null,
    traceId: extra.traceId ?? null,
  };
}

const FIELD_ISSUE: FieldIssue = {
  path: 'name',
  code: 'too_small',
  messageKey: 'error.validation_failed',
  message: '不能为空',
};

describe('looksLikeEnvelope', () => {
  it('成功信封必须带 data 键：光有 {"success":true} 不算信封', () => {
    expect(looksLikeEnvelope({ success: true, data: { items: [] }, meta: null })).toBe(true);
    // 这是这个函数存在的全部理由：只看 `success` 的话，`{"success":true}` 会被当信封，
    // 然后在取 data 时拿到 undefined 一路传到很深的组件里才炸。
    expect(looksLikeEnvelope({ success: true })).toBe(false);
    expect(looksLikeEnvelope({ success: true, meta: null })).toBe(false);
  });

  it('失败信封要求 error 是对象', () => {
    expect(looksLikeEnvelope({ success: false, error: makeApiError('NOT_FOUND', 'error.not_found') })).toBe(true);
    expect(looksLikeEnvelope({ success: false, error: '未找到' })).toBe(false);
    expect(looksLikeEnvelope({ success: false, error: null })).toBe(false);
    expect(looksLikeEnvelope({ success: false })).toBe(false);
  });

  it('缺 success、success 非布尔、非对象一律不算信封', () => {
    expect(looksLikeEnvelope({ data: {} })).toBe(false);
    expect(looksLikeEnvelope({ success: 'true', data: {} })).toBe(false);
    expect(looksLikeEnvelope({})).toBe(false);
    expect(looksLikeEnvelope(null)).toBe(false);
    expect(looksLikeEnvelope(undefined)).toBe(false);
    expect(looksLikeEnvelope('[{"success":true}]')).toBe(false);
    // 数组也过 typeof === 'object' 这一关，但它身上没有 success，不能算信封。
    expect(looksLikeEnvelope([{ success: true, data: {} }])).toBe(false);
  });
});

describe('ApiRequestError', () => {
  it('把信封里的 status / code / messageKey / details / traceId 都带出来', () => {
    const error = new ApiRequestError(
      422,
      makeApiError('VALIDATION_FAILED', 'error.validation_failed', {
        details: [FIELD_ISSUE],
        traceId: 'trace-1',
        message: '请求参数校验未通过',
      }),
    );

    expect(error.status).toBe(422);
    expect(error.code).toBe('VALIDATION_FAILED');
    expect(error.messageKey).toBe('error.validation_failed');
    expect(error.traceId).toBe('trace-1');
    // message 只用于日志；界面文案一律经 useI18n 渲染（见 useApiErrorMessage 的用例）。
    expect(error.message).toBe('请求参数校验未通过');
  });

  it('fieldIssues 在无明细时返回空数组而不是 null', () => {
    const error = new ApiRequestError(404, makeApiError('NOT_FOUND', 'error.not_found.expert'));
    // 调用方（表单逐项标红）直接 `for (const issue of error.fieldIssues())`，
    // 返回 null 会让"非校验类错误"这条最常见的路径多一个判空分支。
    expect(error.fieldIssues()).toEqual([]);
    expect(error.details).toBeNull();
  });

  it('fieldIssues 有明细时原样返回', () => {
    const error = new ApiRequestError(
      422,
      makeApiError('VALIDATION_FAILED', 'error.validation_failed', { details: [FIELD_ISSUE] }),
    );
    expect(error.fieldIssues()).toEqual([FIELD_ISSUE]);
  });

  it('name 固定为 ApiRequestError，且能被 instanceof Error 捕获', () => {
    const error = new ApiRequestError(500, makeApiError('INTERNAL', 'error.internal'));
    // name 参与日志与错误上报的分组，继承来的 'Error' 会让两类失败在日志里无法区分。
    expect(error.name).toBe('ApiRequestError');
    expect(error).toBeInstanceOf(Error);
  });
});

describe('ApiNetworkError', () => {
  it('保留原始 cause，便于在控制台看到连接被拒 / JSON 解析失败的真实原因', () => {
    const cause = new TypeError('Failed to fetch');
    const error = new ApiNetworkError('请求未能到达服务端', cause);

    expect(error.cause).toBe(cause);
    expect(error.name).toBe('ApiNetworkError');
    expect(error).toBeInstanceOf(Error);
  });

  it('没有 cause 时不会伪造一个', () => {
    expect(new ApiNetworkError('请求未能到达服务端').cause).toBeUndefined();
  });
});

describe('isApiRequestError / isApiNetworkError', () => {
  it('两类错误互相排斥，普通 Error 两者皆非', () => {
    const requestError = new ApiRequestError(500, makeApiError('INTERNAL', 'error.internal'));
    const networkError = new ApiNetworkError('请求未能到达服务端');

    // 这两个判别的**互斥**比各自为真更重要：若网络错误被判成请求错误，
    // useApiErrorMessage 会去翻 messageKey 然后显示"服务内部错误"，
    // 让用户去查一个根本没启动的服务端。
    expect(isApiRequestError(requestError)).toBe(true);
    expect(isApiNetworkError(requestError)).toBe(false);
    expect(isApiNetworkError(networkError)).toBe(true);
    expect(isApiRequestError(networkError)).toBe(false);

    expect(isApiRequestError(new Error('x'))).toBe(false);
    expect(isApiNetworkError(new Error('x'))).toBe(false);
    expect(isApiRequestError(null)).toBe(false);
    expect(isApiNetworkError('boom')).toBe(false);
  });
});

describe('createQueryClient 的默认值与重试策略', () => {
  it('默认值：staleTime 30s、窗口聚焦刷新、mutation 不重试', () => {
    const defaults = createQueryClient().getDefaultOptions();

    expect(defaults.queries?.staleTime).toBe(30_000);
    expect(defaults.queries?.refetchOnWindowFocus).toBe(true);
    // 写操作（创建/删除）重试有可能产生重复记录，这条不能改。
    expect(defaults.mutations?.retry).toBe(false);
  });

  /*
   * 下面三条用真实的 `request` 驱动，而不是手抛一个 ApiRequestError：
   * `shouldRetry` 的入参就来自客户端对 HTTP 结果的分类，手造错误等于把
   * "500 会被映射成 ApiRequestError" 这一步从被测路径里挖掉。
   *
   * `retryDelay: 0` 是**单次查询**的覆盖项（客户端默认是"指数退避，首试 1s"），
   * 不推进定时器就能让重试立刻发生，用例不会为了等退避而慢 1s+。
   * 重试策略本身仍来自客户端的 `defaultOptions`，没有被这次覆盖动过。
   */
  it('4xx 不重试：404 / 422 都只发一次请求', async () => {
    const notFound = await countsUntilFailure(404, 'NOT_FOUND');
    expect(notFound.calls).toBe(1);
    expect(notFound.error).toBeInstanceOf(ApiRequestError);
    expect((notFound.error as ApiRequestError).status).toBe(404);

    const unprocessable = await countsUntilFailure(422, 'VALIDATION_FAILED');
    expect(unprocessable.calls).toBe(1);
    expect((unprocessable.error as ApiRequestError).status).toBe(422);
  });

  it('5xx 重试一次后放弃', async () => {
    const internal = await countsUntilFailure(500, 'INTERNAL');
    // 第一次失败时 failureCount 为 0 → 值得重试；第二次失败时 failureCount 为 1
    // → 不再重试。所以总数恰好是 2，而不是 3。
    expect(internal.calls).toBe(2);
    expect(internal.error).toBeInstanceOf(ApiRequestError);
  });

  it('网络失败重试一次后放弃', async () => {
    const mock = stubFetchRejected();
    const client = createQueryClient();

    const error = await client
      .fetchQuery({
        queryKey: ['retry-policy', 'network'],
        queryFn: ({ signal }) => request('/experts', { signal }),
        retryDelay: 0,
      })
      .catch((thrown: unknown) => thrown);

    // 本机服务刚启动的一瞬确实可能连接被拒，这一次重试是有意义的。
    expect(mock).toHaveBeenCalledTimes(2);
    expect(error).toBeInstanceOf(ApiNetworkError);
  });
});

/**
 * 让一次真实请求走完客户端的重试策略，返回 fetch 的调用次数与最终抛出的错误。
 *
 * 用返回次数而不是把 `mock` 交给用例：`vi.stubGlobal` 每次都会换掉全局 fetch，
 * 把 mock 留在用例里会诱导写出"跨用例复用一个打桩"的写法。
 */
async function countsUntilFailure(
  status: number,
  code: ApiErrorCode,
): Promise<{ calls: number; error: unknown }> {
  const mock = stubFetch(jsonResponse(errorEnvelope(code, 'error.internal'), status));
  const client = createQueryClient();

  const error = await client
    .fetchQuery({
      queryKey: ['retry-policy', status],
      queryFn: ({ signal }) => request('/experts', { signal }),
      retryDelay: 0,
    })
    .catch((thrown: unknown) => thrown);

  return { calls: mock.mock.calls.length, error };
}

describe('useApiErrorMessage 的三档降级', () => {
  it('服务端错误且 messageKey 在词表里：译成句子', () => {
    const { result } = renderHook(() => useApiErrorMessage());

    const text = result.current(
      new ApiRequestError(404, makeApiError('NOT_FOUND', 'error.not_found.expert')),
    );

    // 期望值直接取自词表：改文案时这里跟着变，不会碎成"文案过时"的假失败。
    expect(text).toBe(zhCN.error.not_found.expert);
  });

  it('服务端错误、具体子键没收录：退到该分组的兜底文案，绝不把键名糊到界面上', () => {
    const { result } = renderHook(() => useApiErrorMessage());

    const text = result.current(
      new ApiRequestError(404, makeApiError('NOT_FOUND', 'error.not_found.dinosaur')),
    );

    /*
     * 「未找到」而不是「服务内部错误」。后者会把一个 404 说成服务端故障——
     * 用户和排查的人都会往错的方向走。分组兜底见 translate.ts 的分组 `default`。
     */
    expect(text).toBe(zhCN.error.not_found.default);
    expect(text).not.toBe(zhCN.error.internal);
    // 界面上出现 `error.not_found.dinosaur` 等于把内部命名暴露给用户，
    // 而且用户拿着这个词什么也做不了。
    expect(text).not.toContain('dinosaur');
  });

  it('服务端给了连分组都对不上的键：才退到通用文案', () => {
    const { result } = renderHook(() => useApiErrorMessage());

    const text = result.current(
      new ApiRequestError(500, makeApiError('INTERNAL', 'some.unmapped.key')),
    );

    expect(text).toBe(zhCN.error.internal);
    expect(text).not.toContain('unmapped');
  });

  it('网络层错误说的是"连不上后端"，而不是"服务内部错误"', () => {
    const { result } = renderHook(() => useApiErrorMessage());

    const text = result.current(new ApiNetworkError('请求未能到达服务端'));

    expect(text).toBe(zhCN.error.network);
    expect(text).not.toBe(zhCN.error.internal);
  });

  it('其余任何抛出物统一说"出错了"，细节留给控制台', () => {
    const { result } = renderHook(() => useApiErrorMessage());

    expect(result.current(new Error('渲染期崩了'))).toBe(zhCN.error.internal);
    expect(result.current('一个字符串')).toBe(zhCN.error.internal);
    expect(result.current(null)).toBe(zhCN.error.internal);
    expect(result.current(undefined)).toBe(zhCN.error.internal);
  });

  it('语言没变时返回同一个函数引用：组件可以把它写进依赖数组', () => {
    // 组件常把它用在 useMemo 的依赖里（拼 aria-label 之类）。每次渲染换一个新函数
    // 会让那些 memo 全部失效——这是 useCallback 存在的理由，退化成普通箭头函数
    // 不会有任何测试变红，所以在这里钉住。
    const { result, rerender } = renderHook(() => useApiErrorMessage());
    const before = result.current;

    rerender();

    expect(result.current).toBe(before);
  });
});
