import { useEffect, useRef } from 'react';

/**
 * 触底加载更多（D18 = A：无限滚动）。
 *
 * 返回一个**回调 ref**，挂到列表末尾的哨兵元素上：
 *
 * ```tsx
 * const sentinelRef = useInfiniteScroll(hasNextPage && !isFetching, loadMore);
 * ...
 * <div ref={sentinelRef} aria-hidden="true" />
 * ```
 *
 * 三个细节都不是可选的：
 *
 * 1. **rootMargin 预取。** 提前 200px 就开始加载，等哨兵真的进入视口再请求，
 *    用户会看到一段空白加载；工作台用的是本机接口，200px 足够在滚动到底前拿到数据。
 * 2. **`onLoadMore` 走 ref 而不是依赖。** 它通常是内联箭头函数，每次渲染都是新的；
 *    放进依赖数组会导致每次渲染都重建 observer（先断后连），滚动中很容易漏掉一次触发。
 * 3. **不自动重试。** 加载失败时 `enabled` 会变 false（调用方把 `isError` 也算进去），
 *    observer 随之断开——否则一次失败会变成对同一个失败页签的无限重试。
 */
export function useInfiniteScroll(
  enabled: boolean,
  onLoadMore: () => void,
): (node: HTMLElement | null) => void {
  const nodeRef = useRef<HTMLElement | null>(null);
  const callbackRef = useRef(onLoadMore);

  // 在 effect 里同步，不在渲染期直接赋值：渲染期改 ref 在并发渲染下可能被丢弃。
  useEffect(() => {
    callbackRef.current = onLoadMore;
  });

  useEffect(() => {
    const node = nodeRef.current;
    if (!enabled || node === null) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          callbackRef.current();
        }
      },
      { rootMargin: '0px 0px 200px 0px' },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [enabled]);

  return (node) => {
    nodeRef.current = node;
  };
}
