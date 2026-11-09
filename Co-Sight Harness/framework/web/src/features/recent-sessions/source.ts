/**
 * 「最近会话」的数据源契约。
 *
 * 侧栏只依赖这个接口，不认识任何具体后端：换数据来源（smart-factory 现在的 REST、
 * 将来宿主统一代理、或某个模块自己提供）只需要换一个 `RecentSessionSource` 实现，
 * 组合根改一行，UI 与领域规则都不用动。
 *
 * 只暴露列表需要的三个字段：宿主拿不到、也不需要会话的完整 DTO。
 */
export interface RecentSession {
  id: string;
  /** 标题；三个来源都取不到文本时为 `null`，由界面给兜底文案。 */
  title: string | null;
  /** 最后活跃时间（ISO 8601），排序与相对时间都按它。 */
  updatedAt: string;
}

export interface RecentSessionSource {
  /** 取最近会话，按 `updatedAt` 降序，最多 `RECENT_SESSION_LIMIT` 条。 */
  list(signal?: AbortSignal): Promise<RecentSession[]>;
}
