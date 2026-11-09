/**
 * 系统接口的查询层。
 *
 * 这一层值得单测：路径、queryKey 什么形状、缓存策略全在这里；页面组件只负责渲染。
 * 其中两条的故障表现都在界面之外，靠页面用例很难定位：
 * - `useHealth` 跟着客户端的默认策略重试 → 后端没启动时用户要等一整轮退避才看到错误；
 * - 清单缓存没有预置 `staleTime` → 每次进页面都重拉一份运行期不会变的清单。
 */

import { QueryClient } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApiRequestError } from '../src/api/errors';
import { createQueryClient } from '../src/api/queryClient';
import { systemApi, systemKeys, useHealth, useModules } from '../src/api/system';
import {
  callUrl,
  envelope,
  errorEnvelope,
  jsonResponse,
  providersFor,
  stubFetch,
  stubFetchSequence,
} from './helpers/render';

describe('systemApi', () => {
  it('health / modules 都解到 data 那一层，路径不带查询串', async () => {
    const mock = stubFetchSequence([
      jsonResponse(
        envelope({
          status: 'ok',
          version: '0.1.0',
          uptimeSeconds: 12,
          cosightHome: '/home/me/.cosight',
          database: '/home/me/.cosight/harness.db',
        }),
      ),
      jsonResponse(envelope({ modules: [], invalid: [] })),
    ]);

    await expect(systemApi.health()).resolves.toMatchObject({ status: 'ok', version: '0.1.0' });
    await expect(systemApi.modules()).resolves.toEqual({ modules: [], invalid: [] });

    expect(callUrl(mock)).toBe('/api/health');
    expect(callUrl(mock, 1)).toBe('/api/modules');
  });
});

describe('useHealth', () => {
  it('失败时只请求一次：hook 上的 retry:false 覆盖了客户端的重试策略', async () => {
    /*
     * 这里刻意用**生产**配置的客户端（createQueryClient）：它对 5xx 会重试一次。
     * 若改用 createTestQueryClient()，helper 预置的 retry:false 会替这个 hook
     * 完成它自己要做的决定，用例在"hook 删掉 retry:false"时照样通过。
     *
     * 区分"重试了"与"没重试"不靠等定时器：query-core 把重试收在 retryer 内部，
     * 每次失败只发 onFail（更新 failureCount，**不动 status**），要等退避结束后
     * 仍未成功才 reject 并让查询进入 error。所以"failureCount 已经是 1 但 isError
     * 还是 false"正是"正在退避、还没放弃"的特征；hook 写了 retry:false 时这两件事
     * 在同一次 dispatch 里发生，看不到这个中间态。
     */
    const mock = stubFetch(jsonResponse(errorEnvelope('INTERNAL', 'error.internal'), 500));
    const client = createQueryClient();

    const { result } = renderHook(() => useHealth(), { wrapper: providersFor(client) });

    await waitFor(
      () => {
        expect(result.current.failureCount).toBe(1);
      },
      { timeout: 500 },
    );
    expect(result.current.isError).toBe(true);
    // 健康检查不到就说明后端没起来，此时反复重试只会推迟用户看到错误的时间。
    expect(mock).toHaveBeenCalledTimes(1);
    // 错误要落在 hook 声明的那个键上，页面与别的失效逻辑都按它找数据。
    expect(client.getQueryState(systemKeys.health)?.error).toBeInstanceOf(ApiRequestError);
  });
});

describe('useModules', () => {
  it('卸载再挂载只请求一次：清单在运行期不会变', async () => {
    /*
     * 同样不能用 createTestQueryClient()：它把 staleTime 预置成 Infinity，
     * 于是"hook 有没有写 staleTime: Infinity"完全看不出来。这里用一个只关掉
     * 重试、其余走默认值的客户端——默认 staleTime 为 0，缓存一挂载就算过期，
     * 若 hook 没写 Infinity，第二次挂载会立刻再发一次请求。
     */
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const mock = stubFetch(jsonResponse(envelope({ modules: [], invalid: [] })));

    const first = renderHook(() => useModules(), { wrapper: providersFor(client) });
    await waitFor(() => {
      expect(first.result.current.isSuccess).toBe(true);
    });
    first.unmount();

    const second = renderHook(() => useModules(), { wrapper: providersFor(client) });

    // 数据从缓存来，立即可用且没有在途请求。
    expect(second.result.current.data).toEqual({ modules: [], invalid: [] });
    expect(second.result.current.isFetching).toBe(false);
    expect(mock).toHaveBeenCalledTimes(1);
    expect(callUrl(mock)).toBe('/api/modules');
  });
});
