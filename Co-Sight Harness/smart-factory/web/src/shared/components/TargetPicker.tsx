import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { Icon } from '../../shared/components/Icon';

/**
 * 目标选择弹层（技能优化选技能 / 评估智能体选专家）。
 *
 * 为什么是弹层而不是常驻列表：正文里点了名就不用选（解析命中直接进落点），
 * 弹层只在「认不出来 / 点到多个」时兜底，所以它不该占首页版面。
 *
 * 组件只管「列出候选、筛、选一个」—— 数据由页面拉、落点由页面定，
 * 两类目标（专家 / 技能）共用这一份，避免两套列表各写一遍然后长歪。
 */
export interface PickerOption {
  id: string;
  name: string;
  /** 副行：专家是简介，技能是来源（技能库 / 智能体名） */
  description: string;
  /** 悬停提示（技能放目录路径，专家放 id） */
  title?: string;
}

interface TargetPickerProps {
  title: string;
  desc: string;
  searchPlaceholder: string;
  loading: boolean;
  /** 清单拉失败的人话；有值时列表位置显示它 */
  error: string | null;
  options: PickerOption[];
  onPick: (option: PickerOption) => void;
  onCancel: () => void;
}

export function TargetPicker({
  title,
  desc,
  searchPlaceholder,
  loading,
  error,
  options,
  onPick,
  onCancel,
}: TargetPickerProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  /** 打开前的焦点：关闭时还回去，键盘用户不会掉到页面开头 */
  const returnFocusRef = useRef<Element | null>(null);

  /** 打开就把焦点放进搜索框；关闭时把焦点还给打开它的那颗 chip */
  useEffect(() => {
    returnFocusRef.current = document.activeElement;
    inputRef.current?.focus();
    return () => {
      const previous = returnFocusRef.current;
      if (previous instanceof HTMLElement && document.contains(previous)) previous.focus();
    };
  }, []);

  /** Esc 关掉（与 Composer 的下拉同一口径） */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  /** Tab 不逃出弹层：aria-modal 的承诺要实际做到 */
  function trapTab(event: ReactKeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'Tab') return;
    const root = dialogRef.current;
    if (root === null) return;
    const focusables = [...root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )];
    if (focusables.length === 0) return;
    const first = focusables[0]!;
    const last = focusables[focusables.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === '') return options;
    return options.filter(
      (option) =>
        option.name.toLowerCase().includes(needle) ||
        option.description.toLowerCase().includes(needle),
    );
  }, [options, query]);

  function renderBody() {
    if (loading) return <p className="home-pick__note">{t('home.target.loading')}</p>;
    if (error !== null) return <p className="home-pick__note home-pick__note--error">{error}</p>;
    if (options.length === 0) return <p className="home-pick__note">{t('home.target.empty')}</p>;
    if (visible.length === 0) {
      return <p className="home-pick__note">{t('home.target.noMatch', { query })}</p>;
    }
    return (
      <div className="home-pick__list">
        {visible.map((option) => (
          <button
            key={option.id}
            type="button"
            className="home-pick__row"
            title={option.title ?? option.description}
            onClick={() => onPick(option)}
          >
            <span className="home-pick__icon" aria-hidden="true">
              <Icon name="sparkle" size={14} />
            </span>
            <span className="home-pick__body">
              <strong>{option.name}</strong>
              {option.description !== '' && <span>{option.description}</span>}
            </span>
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="home-pick__mask" onClick={onCancel}>
      {/* 点内容不关：mask 上的 onClick 只该由真正点到遮罩触发 */}
      <div
        ref={dialogRef}
        className="home-pick"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapTab}
      >
        <h3 className="home-pick__title">{title}</h3>
        <p className="home-pick__desc">{desc}</p>
        <input
          ref={inputRef}
          className="home-pick__search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
        />
        {renderBody()}
        <div className="home-pick__footer">
          <button type="button" className="home-pick__cancel" onClick={onCancel}>
            {t('home.target.cancel')}
          </button>
        </div>
      </div>
    </div>
  );
}
