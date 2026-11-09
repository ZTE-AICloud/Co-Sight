import { useCallback, useEffect, useRef, useState } from 'react';
import { msg, useI18n } from '../../../i18n/useI18n';
import { backendDownHint, agentsApi, isBackendDown } from '../../../shared/api/agents';
import type { AgentTagCount } from '../../../shared/api/agents';
import { ApiError } from '../../../shared/api/client';
import { Icon } from '../../../shared/components/Icon';

interface TagFilterProps {
  /** 只列这个工作区里的标签；与列表的 `workspaceId` 同一个值 */
  workspaceId: string;
  /** 当前生效的标签；`null` = 不筛 */
  value: string | null;
  /** 选中一个标签（同一标签的「再点取消」由调用方决定），或 `null` 清空 */
  onChange: (tag: string | null) => void;
}

/** listbox 的 id。页面上只有这一个标签筛选器，写死常量不会撞。 */
const LIST_ID = 'al-tag-filter-list';

/**
 * 工具条上的「标签」入口：可搜索的标签下拉。
 *
 * 为什么要有它：卡片上的标签点击只能命中「当前列表里恰好出现的那几颗」，
 * 想按一个没在眼前出现的标签筛，用户得先翻卡片。这个下拉直接列出**当前工作区**
 * 的标签（`GET /agents/tags?workspaceId=`，带计数），输入即过滤，选中即筛。
 *
 * 必须跟着工作区走：专家页按当前工作区展示，下拉里混进别的工作区的标签，
 * 选中后只会得到一个空列表。
 *
 * 交互约定与仓库现有浮层一致：
 * - 点外部（`mousedown`，同 Composer 的菜单）或 Esc 关闭；Esc 关闭后焦点还给触发器；
 * - 选中后关闭，焦点同样还给触发器；
 * - 选项是原生 `button`，Tab / Enter / Space 自带键盘行为；方向键导航本轮不做，
 *   全仓也还没有 listbox 的方向键实现可抄。
 */
export function TagFilter({ workspaceId, value, onChange }: TagFilterProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<AgentTagCount[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  /** 只认最后一次请求的响应：关掉再打开、连续重试都不会串结果 */
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await agentsApi.listTags(workspaceId);
      if (seq !== requestSeq.current) return;
      setItems(result.items);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(describeTagError(err));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [workspaceId]);

  /**
   * 每次打开都重拉：标签可能在别处被编辑过，缓存的清单没有意义。
   * 同时清空上一次的搜索词 —— 重新打开应该从完整清单开始。
   */
  useEffect(() => {
    if (!open) return;
    setQuery('');
    void load();
  }, [open, load]);

  /** 工作区变了就先丢掉旧清单：别让上一个工作区的标签在新响应回来前继续挂着 */
  useEffect(() => {
    setItems(null);
    setError(null);
  }, [workspaceId]);

  /** 点外部 / Esc 关闭。用 mousedown 与 Composer 的菜单保持同一时机。 */
  useEffect(() => {
    if (!open) return;

    function onDocMouseDown(event: MouseEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const trimmed = query.trim();
  const filtered =
    items === null
      ? []
      : trimmed === ''
        ? items
        : items.filter((item) => item.tag.toLowerCase().includes(trimmed.toLowerCase()));

  function choose(next: string | null) {
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div className="al-menu-root" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`al-chip al-menu-trigger${open ? ' al-chip--on' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={LIST_ID}
        title={t('agentList.tagFilter.triggerTitle')}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name="list" size={12} />
        {t('agentList.tagFilter.trigger')}
        <Icon name="chevronDown" size={12} />
      </button>

      {open && (
        <div className="al-menu">
          <label className="al-menu__search">
            <Icon name="search" size={13} />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('agentList.tagFilter.searchPlaceholder')}
              aria-label={t('agentList.tagFilter.searchAria')}
            />
            {query !== '' && (
              <button
                type="button"
                className="al-menu__clear"
                onClick={() => setQuery('')}
                aria-label={t('agentList.tagFilter.clearSearch')}
              >
                <Icon name="close" size={12} />
              </button>
            )}
          </label>

          <div
            className="al-menu__list"
            id={LIST_ID}
            role="listbox"
            aria-label={t('agentList.tagFilter.listAria')}
          >
            <button
              type="button"
              role="option"
              aria-selected={value === null}
              className={`al-menu__option${value === null ? ' al-menu__option--on' : ''}`}
              onClick={() => choose(null)}
            >
              <span className="al-menu__option-label">{t('agentList.tagFilter.all')}</span>
              {value === null && <Icon name="check" size={13} />}
            </button>

            {filtered.map((item) => (
              <button
                key={item.tag}
                type="button"
                role="option"
                aria-selected={value === item.tag}
                className={`al-menu__option${value === item.tag ? ' al-menu__option--on' : ''}`}
                title={item.tag}
                onClick={() => choose(item.tag)}
              >
                <span className="al-menu__option-tag">
                  <span className="al-tag">{item.tag}</span>
                </span>
                <span className="al-menu__option-count">{item.count}</span>
                {value === item.tag && <Icon name="check" size={13} />}
              </button>
            ))}
          </div>

          {loading && <p className="al-menu__state">{t('agentList.tagFilter.loading')}</p>}

          {!loading && error !== null && (
            <div className="al-menu__state al-menu__state--error">
              <span>{error}</span>
              <button type="button" className="al-btn al-btn--sm" onClick={() => void load()}>
                {t('agentList.tagFilter.retry')}
              </button>
            </div>
          )}

          {!loading && error === null && items !== null && items.length === 0 && (
            <p className="al-menu__state">{t('agentList.tagFilter.empty')}</p>
          )}

          {!loading && error === null && items !== null && items.length > 0 && filtered.length === 0 && (
            <p className="al-menu__state">
              {t('agentList.tagFilter.noMatch', { query: trimmed })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** 标签清单的失败提示：与列表页同一套判据，措辞指向「下一步能做什么」。 */
function describeTagError(err: unknown): string {
  if (isBackendDown(err))
    return msg('agentList.tagFilter.errorUnavailable', { hint: backendDownHint() });
  // fetch 本身失败（断网、请求被拦）不是 ApiError，是 TypeError: Failed to fetch。
  if (err instanceof TypeError)
    return msg('agentList.tagFilter.errorUnavailable', { hint: backendDownHint() });
  if (err instanceof ApiError)
    return msg('agentList.tagFilter.errorStatus', { message: err.message, status: err.status });
  return err instanceof Error ? err.message : msg('agentList.tagFilter.error');
}
