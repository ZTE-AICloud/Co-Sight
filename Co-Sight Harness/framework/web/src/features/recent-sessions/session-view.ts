/**
 * 会话 → 「最近」列表项 的纯映射（过滤、标题、排序）。
 *
 * 放在与传输无关的单独文件里：这些是**领域规则**，不是渲染细节，也不是地址拼接。
 * 将来 smart-factory 直接下发 `title` 时，改这一个文件即可，UI 与数据源都不用动。
 */

import type { RecentSession } from './source';

/** 列表最多显示多少条（需求：暂定最大 100）。取数与截断共用。 */
export const RECENT_SESSION_LIMIT = 100;

/**
 * smart-factory `Session` 里本功能用得到的字段（契约见
 * `server/docs/04-api/4.03-会话.md` §3.1）。
 *
 * 只声明读到的字段：服务端加字段不影响这里，少字段会在这里立刻暴露。
 */
export interface ServiceSession {
  id: string;
  name: string;
  messageCount: number;
  lastMessage: string | null;
  /**
   * smart-factory **计划新增**的派生字段（最早一条用户文本）。
   * 未上线时接口里没有这个键，因此必须保持可选。
   */
  firstUserMessage?: string | null;
  updatedAt: string;
  instance: { agentId: string | null };
}

/** 首个非空行；用于 `name` 这类不该做 Markdown 处理的文本。 */
function firstNonEmptyLine(text: string | null | undefined): string | null {
  if (text === null || text === undefined || text === '') {
    return null;
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (line !== '') {
      return line;
    }
  }
  return null;
}

/** 消息正文的标题：取首个非空行，并去掉 Markdown 的标题/列表前缀。 */
function messageTitle(text: string | null | undefined): string | null {
  const line = firstNonEmptyLine(text);
  if (line === null) {
    return null;
  }
  const stripped = line.replace(/^#{1,6}\s+/, '').replace(/^[-*+]\s+/, '');
  return stripped === '' ? null : stripped;
}

/**
 * 标题优先级（与 smart-factory 约定）：`name` → `firstUserMessage` → `lastMessage`。
 *
 * 最后一项只是兜底：现有会话的 `name` 都是空串，而 `firstUserMessage` 要等
 * smart-factory 上线；在那之前标题会退化成助手最后一段回复的首行，这是已知的中间态。
 */
export function titleOf(session: ServiceSession): string | null {
  return (
    firstNonEmptyLine(session.name) ??
    messageTitle(session.firstUserMessage) ??
    messageTitle(session.lastMessage)
  );
}

/**
 * 过滤 + 映射 + 排序。
 *
 * 只过滤 `messageCount === 0`（建了但没用过的空会话，列出来只是噪音）。
 *
 * **自由对话也要保留**：它的实例 `agentId === null`，但对话页用
 * `?agentRuntimeSessionId=` 恢复时并不要求 agentId（只有存在 agentId 时才额外还原
 * 专家），历史与继续发送都正常。此前按 `agentId !== null` 过滤，导致自由对话落库后
 * 在侧栏没有任何入口。
 *
 * 技能工坊的目录会话（`stage=development`）不会被这条查询带入：smart-factory 的
 * `/sessions/list` 默认只看 `stage=runtime`，自由对话也正好是 runtime。
 *
 * 排序按 `updatedAt` 降序：服务端列表固定按 `updatedAt` 排，但取数已在 100 条以内，
 * 客户端重排一次，避免依赖分页边界。
 */
export function toRecentSessions(items: readonly ServiceSession[]): RecentSession[] {
  return items
    .filter((session) => session.messageCount > 0)
    .map((session) => ({ id: session.id, title: titleOf(session), updatedAt: session.updatedAt }))
    .toSorted((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    .slice(0, RECENT_SESSION_LIMIT);
}
