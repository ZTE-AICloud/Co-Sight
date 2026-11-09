/**
 * 「最近会话」的公开出口。
 *
 * 只导出三样：组件、主动刷新入口、数据类型。外部（侧栏）**不要**从
 * `features/recent-sessions/xxx` 深引用——数据源与领域规则的变化都收在目录内部。
 */

export { RecentSessions, type RecentSessionsProps } from './RecentSessions';
export { invalidateRecentSessions } from './useRecentSessions';
export type { RecentSession, RecentSessionSource } from './source';
