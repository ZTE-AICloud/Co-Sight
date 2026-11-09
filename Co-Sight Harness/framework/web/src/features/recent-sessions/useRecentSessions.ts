/**
 * 「最近会话」的查询层。
 *
 * 查询、轮询、缓存键都收在这里：侧栏组件只拿 `data` / `isPending` / `isError`，
 * 不关心从哪来、多久刷一次。数据源可注入，默认是当前使用的 smart-factory 实现。
 */

import { useQuery, type QueryClient } from '@tanstack/react-query';

import { smartFactoryRecentSource } from './smart-factory-source';
import type { RecentSessionSource } from './source';

export const recentSessionsKeys = {
  list: ['recent-sessions'] as const,
};

export interface UseRecentSessionsOptions {
  /** 数据源；测试或将来换实现时注入，缺省用 smart-factory。 */
  source?: RecentSessionSource;
  /** 侧栏折叠时关掉：列表不渲染，没必要继续轮询。 */
  enabled?: boolean;
}

/**
 * 侧栏用的查询。
 *
 * 一分钟轮询：对话在 iframe 里进行，宿主的 window 始终是聚焦的，
 * `refetchOnWindowFocus` 在聊完一轮后不会触发；不轮询的话新建的会话要等刷新
 * 才出现。一分钟是本机 SQLite 上能接受的最小噪音。
 */
export function useRecentSessions(options: UseRecentSessionsOptions = {}) {
  const source = options.source ?? smartFactoryRecentSource;
  return useQuery({
    queryKey: recentSessionsKeys.list,
    queryFn: ({ signal }) => source.list(signal),
    refetchInterval: 60_000,
    enabled: options.enabled ?? true,
  });
}

/**
 * 让列表立刻重取一次（例如将来宿主要在新建会话后主动刷新）。
 * 与查询共用同一个 key，调用方不必知道 key 长什么样。
 */
export function invalidateRecentSessions(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: recentSessionsKeys.list });
}
