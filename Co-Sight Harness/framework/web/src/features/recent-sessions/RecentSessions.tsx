/**
 * 侧栏「最近」：最近用过的会话（最多 100 条，默认露出 5 条）。
 *
 * 只负责"展示 + 把选择交出去"：
 * - 取数与领域规则在 `useRecentSessions` / `session-view`；
 * - 数据来源在 `smart-factory-source`（唯一认识 smart-factory 的地方）；
 * - **点一条之后去哪由壳层决定**（`onOpenSession`），组件不依赖路由。
 */

import { useState } from 'react';

import { useI18n } from '../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../i18n/types';
import { formatDateTime } from '../../lib/formatDateTime';
import { relativeTimeOf, type RelativeTime } from './relative-time';
import { useRecentSessions } from './useRecentSessions';
import styles from './RecentSessions.module.css';

/** 未展开时露出的条数（需求：默认显示 5 条，点「查看更多」展开）。 */
const DEFAULT_VISIBLE = 5;

type Translate = (key: MessageKey, params?: MessageParams) => string;

function timeLabel(relative: RelativeTime, t: Translate): string {
  switch (relative.unit) {
    case 'justNow':
      return t('recent.justNow');
    case 'minutes':
      return t('recent.minutesAgo', { count: relative.count });
    case 'hours':
      return t('recent.hoursAgo', { count: relative.count });
    case 'days':
      return t('recent.daysAgo', { count: relative.count });
  }
}

export interface RecentSessionsProps {
  /** 侧栏折叠时整块不渲染：窄条里放不下一列会话，硬塞会把图标挤成两行。 */
  collapsed: boolean;
  /**
   * 用户选中一条会话。**壳层负责跳到对话页并带上恢复会话需要的参数**，
   * 这个组件不拼路由、也不认识 `agentRuntimeSessionId`。
   */
  onOpenSession: (sessionId: string) => void;
}

export function RecentSessions({ collapsed, onOpenSession }: RecentSessionsProps) {
  const { t, locale } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const query = useRecentSessions({ enabled: !collapsed });

  if (collapsed) {
    return null;
  }

  const sessions = query.data ?? [];
  const visible = expanded ? sessions : sessions.slice(0, DEFAULT_VISIBLE);
  // 恰好 5 条时按钮没有可展开的内容，不给它；展开后始终给「收起」，用户能退回去。
  const canToggle = sessions.length > DEFAULT_VISIBLE;

  /*
   * 用 `role="group"` + `aria-labelledby` 而不是 `<section><h2>`：侧栏不是内容章节，
   * 往里放标题元素会让读屏软件的大纲里凭空多一层（`tests/shell.test.tsx` 钉住了
   * "侧栏里没有标题元素"）。分组名照样念给读屏用户。
   */
  return (
    <div className={styles.recent} role="group" aria-labelledby="sidebar-recent-label">
      <div id="sidebar-recent-label" className={styles.heading}>
        {t('recent.heading')}
      </div>

      {query.isPending ? <p className={styles.hint}>{t('recent.loading')}</p> : null}

      {query.isError ? (
        <p className={styles.hint}>
          {t('recent.error')}{' '}
          <button
            type="button"
            className={styles.linkButton}
            onClick={() => {
              void query.refetch();
            }}
          >
            {t('recent.retry')}
          </button>
        </p>
      ) : null}

      {!query.isPending && !query.isError && sessions.length === 0 ? (
        <p className={styles.hint}>{t('recent.empty')}</p>
      ) : null}

      {sessions.length > 0 ? (
        <ul className={styles.list}>
          {visible.map((session) => {
            const title = session.title ?? t('recent.untitled');
            const relative = relativeTimeOf(session.updatedAt);
            const timeText =
              relative === null
                ? (formatDateTime(session.updatedAt, locale) ?? '')
                : timeLabel(relative, t);
            return (
              <li key={session.id}>
                <button
                  type="button"
                  className={styles.item}
                  title={title}
                  onClick={() => {
                    onOpenSession(session.id);
                  }}
                >
                  <span className={styles.title}>{title}</span>
                  <span className={styles.time}>{timeText}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {canToggle ? (
        <button
          type="button"
          className={styles.more}
          onClick={() => {
            setExpanded((value) => !value);
          }}
        >
          {expanded ? t('recent.showLess') : t('recent.showMore', { count: sessions.length })}
        </button>
      ) : null}
    </div>
  );
}
