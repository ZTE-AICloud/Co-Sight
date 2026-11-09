/**
 * 工坊的历史抽屉（`docs/capability-routing.md` §3.4）。
 *
 * 数据就是 `GET /sessions/list?cwd=<cwd>&stage=development`：目录会话的历史不需要新端点。
 * 行上的状态与时间直接取 DTO，不猜；会话名空时按 `firstUserMessage` → `lastMessage`
 * 取首行兜底 —— 两者都是列表派生字段，同一次请求已经带回，不用额外请求。
 *
 * 从技能卡的「历史」打开时按会话名筛选（优化场固定叫 `优化 <name>`）；抽屉现在
 * 长在技能库页（`SkillLibraryPanel`），选中会话才跳 `/workshop?session=`。
 * 筛选在**已加载的页**上做：接口没有按名字过滤的参数，而一个目录下的会话量本来就不大；
 * 没拉完时底部仍有「加载更多」，筛掉的是别的技能的场次。
 */

import { useCallback, useEffect, useState } from 'react';
import { msg, useI18n } from '../../../i18n/useI18n';
import { ApiError } from '../../../shared/api/client';
import { sessionsApi } from '../../../shared/api/sessions';
import type { Session } from '../../../shared/api/sessions';
import { Icon } from '../../../shared/components/Icon';
import { timeAgo } from '../../../shared/time';

const PAGE_SIZE = 50;

export interface HistoryDrawerProps {
  cwd: string;
  /** 当前打开的那一场（删除它要通知页面放下） */
  currentSessionId: string | null;
  /** 只显示这个名字的会话；null = 全部 */
  filter: string | null;
  /**
   * 正在准备会话（建会话 + 发首轮还在路上）：这时的会话行不可点开 ——
   * 切走会让这一轮发到切过去的会话上。行的禁用原因在抽屉顶部说明。
   * 跑着一轮**不**算 busy：那一轮留在服务端跑完，回来重拉即可见到结果。
   */
  busy?: boolean;
  onClose: () => void;
  onOpen: (session: Session) => void;
  /** 删掉的正好是当前场（技能库页没有“当前场”，可以不传） */
  onCurrentDeleted?: () => void;
}

export function HistoryDrawer({
  cwd,
  currentSessionId,
  filter,
  busy = false,
  onClose,
  onOpen,
  onCurrentDeleted,
}: HistoryDrawerProps) {
  const { t, locale } = useI18n();

  const [items, setItems] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(
    async (nextPage: number) => {
      setLoading(true);
      try {
        const result = await sessionsApi.list({ cwd, stage: 'development', page: nextPage, pageSize: PAGE_SIZE });
        setItems((current) => (nextPage === 1 ? result.items : [...current, ...result.items]));
        setTotal(result.total);
        setPage(nextPage);
        setError(null);
      } catch (cause) {
        setError(describeError(cause));
      } finally {
        setLoading(false);
      }
    },
    [cwd],
  );

  // 每次打开 / 换 cwd 都从第一页重来：抽屉是短命的，不做跨次缓存
  useEffect(() => {
    void load(1);
  }, [load]);

  async function remove(session: Session) {
    setDeleting(session.id);
    try {
      await sessionsApi.remove(session.id);
      setItems((current) => current.filter((item) => item.id !== session.id));
      setTotal((value) => Math.max(0, value - 1));
      setConfirming(null);
      if (session.id === currentSessionId) onCurrentDeleted?.();
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setDeleting(null);
    }
  }

  const shown = filter === null ? items : items.filter((session) => session.name === filter);
  const hasMore = items.length < total;

  return (
    <>
      <button type="button" className="sw-drawer-mask" aria-label={t('workshop.history.close')} onClick={onClose} />
      <aside className="sw-drawer" role="dialog" aria-label={t('workshop.history.title')}>
        <header className="sw-drawer-head">
          <div>
            <h2>{t('workshop.history.title')}</h2>
            <p>{t('workshop.history.subtitle')}</p>
          </div>
          <button type="button" className="sw-icon-btn" title={t('workshop.history.close')} onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        </header>

        {busy && (
          <div className="sw-drawer-filter">
            <span>{t('workshop.notice.preparing')}</span>
          </div>
        )}

        {filter !== null && (
          <div className="sw-drawer-filter">
            <span>{t('workshop.history.filter', { name: filter })}</span>
            <button type="button" onClick={() => load(1)}>
              {t('workshop.history.refresh')}
            </button>
          </div>
        )}

        {error !== null && (
          <div className="sw-drawer-error" role="status">
            <Icon name="alert" size={13} />
            <span>{error}</span>
            <button type="button" onClick={() => void load(1)}>
              {t('workshop.history.retry')}
            </button>
          </div>
        )}

        <div className="sw-drawer-list">
          {loading && items.length === 0 ? (
            <div className="sw-drawer-hint">{t('workshop.history.loading')}</div>
          ) : shown.length === 0 ? (
            <div className="sw-drawer-empty">
              <Icon name="clock" size={20} />
              <p>
                {filter === null
                  ? t('workshop.history.empty')
                  : t('workshop.history.emptyFiltered', { name: filter })}
              </p>
            </div>
          ) : (
            shown.map((session) => (
              <div
                key={session.id}
                className="sw-session"
                role="button"
                tabIndex={busy ? -1 : 0}
                aria-current={session.id === currentSessionId ? 'true' : undefined}
                aria-disabled={busy || undefined}
                title={busy ? t('workshop.notice.preparing') : undefined}
                onClick={busy ? undefined : () => onOpen(session)}
                onKeyDown={(event) => {
                  if (!busy && event.key === 'Enter') onOpen(session);
                }}
              >
                <div className="sw-session-main">
                  <strong className="sw-session-name">
                    {session.name === ''
                      ? (fallbackTitle(session) ?? t('workshop.history.untitled'))
                      : session.name}
                  </strong>
                  {confirming === session.id && (
                    <div className="sw-session-confirm" onClick={(event) => event.stopPropagation()}>
                      <span>{t('workshop.history.deleteConfirm')}</span>
                      <button
                        type="button"
                        className="sw-btn sw-btn--danger"
                        disabled={deleting === session.id}
                        onClick={() => void remove(session)}
                      >
                        {t('workshop.history.delete')}
                      </button>
                      <button type="button" className="sw-btn" onClick={() => setConfirming(null)}>
                        {t('workshop.history.cancel')}
                      </button>
                    </div>
                  )}
                </div>
                <div className="sw-session-side">
                  <span className="sw-session-time">{timeAgo(session.updatedAt, locale)}</span>
                  <span
                    className={`sw-session-state${
                      session.status === 'in_progress' ? ' sw-session-state--running' : ''
                    }`}
                  >
                    {t(`workshop.history.state.${session.status}`)}
                  </span>
                </div>
                <button
                  type="button"
                  className="sw-session-del"
                  title={t('workshop.history.delete')}
                  onClick={(event) => {
                    event.stopPropagation();
                    setConfirming(session.id);
                  }}
                >
                  <Icon name="trash" size={13} />
                </button>
              </div>
            ))
          )}

          {hasMore && (
            <button
              type="button"
              className="sw-drawer-more"
              disabled={loading}
              onClick={() => void load(page + 1)}
            >
              {loading ? t('workshop.history.loading') : t('workshop.history.loadMore')}
            </button>
          )}
        </div>

        <footer className="sw-drawer-foot">
          <span>{t('workshop.history.count', { count: shown.length })}</span>
          <span>{t('workshop.history.footHint')}</span>
        </footer>
      </aside>
    </>
  );
}

/**
 * 会话名为空时的标题：首条用户消息优先，其次最后一条正文。
 * 只取首个非空行，并去掉 Markdown 的标题 / 列表前缀（与宿主「最近会话」同一口径）。
 */
function fallbackTitle(session: Session): string | null {
  for (const text of [session.firstUserMessage, session.lastMessage]) {
    if (text === null) continue;
    for (const raw of text.split(/\r?\n/u)) {
      const line = raw.trim().replace(/^#{1,6}\s+/u, '').replace(/^[-*+]\s+/u, '');
      if (line !== '') return line;
    }
  }
  return null;
}

function describeError(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message;
  if (cause instanceof Error) return cause.message;
  return msg('common.unknownError');
}
