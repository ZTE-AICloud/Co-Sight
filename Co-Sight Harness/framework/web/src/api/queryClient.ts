/**
 * TanStack Query 配置（D5 = A）。
 *
 * 默认值是为"本机单用户工作台"调的，与面向公网的 SPA 默认值不同：
 *
 * - **不重试 4xx。** 404/409/422 重试三次的结果仍然是同样的 404/409/422，
 *   只会让用户多等 2 秒才看到错误。只对 5xx 与网络故障各重试一次
 *   （本机服务刚启动的一瞬确实可能连接被拒，这一次重试有意义）。
 * - **窗口重新聚焦时刷新。** 默认开着，且这里显式写出来：工作台经常和
 *   Agent 开发页并排开着，用户切回来时希望看到的是最新状态而不是几分钟前的缓存。
 * - **staleTime 30s。** 挡住同一屏内多个组件各发一次同样请求的情况，
 *   又不至于让"刚创建的专家不出现"。
 * - **networkMode: 'always'。** 不接受浏览器自报离线就把查询挂成 paused
 *   （本机工作台，服务就在 localhost）。
 *
 * 没有做的一件事：**请求超时**。服务端半途死掉时 fetch 会一直挂着，
 * 加载态不会自己结束——见 docs/task-list.md §9.15。
 */

import { QueryClient } from '@tanstack/react-query';

import { isApiNetworkError, isApiRequestError } from './errors';

/** 最多重试一次，且必须"值得重试"。 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) {
    return false;
  }
  if (isApiRequestError(error)) {
    // 4xx 是确定的答案，重试不会改变它；5xx 值得再试一次。
    return error.status >= 500;
  }
  // 网络层失败：后端可能刚起来，值得再试一次。
  return isApiNetworkError(error);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        /*
         * `networkMode: 'always'`：默认值 `'online'` 会在浏览器自报离线时把查询
         * 挂成 paused——既不报错也不加载，用户看到的是一个转不完的圈。工作台跑在
         * localhost 上，宁可让请求真的发出去，由失败给出明确结论。
         *
         * 注意这**不是**超时：接口请求没有任何超时保护，服务端半途死掉时这次 fetch
         * 会一直挂着，加载态不会自己结束。要加得在 `client.ts` 里把调用方的 signal
         * 与 `AbortSignal.timeout()` 合起来（见 docs/task-list.md §9.15）。
         */
        networkMode: 'always',
      },
      mutations: {
        // 写操作不自动重试：创建/删除重试有可能产生重复记录。
        retry: false,
      },
    },
  });
}

/**
 * 全局单例。
 *
 * 模块级单例在测试里要显式重建（见 tests/helpers/render.tsx），
 * 否则用例之间会共享缓存、互相看到对方造的数据。
 */
export const queryClient = createQueryClient();
