/**
 * 右侧停靠的文件预览面板。
 *
 * 固定在视口右边，不是弹窗：页面根加 `ac--dock-open` 把内容挤压过去（见
 * agent-create.css），三个 stage 共用；窗口窄于 768px 时退化成全宽覆盖。
 *
 * 高度这里不用管：本仓 `.app-shell` 是 min-height: 100vh，链路上没有确定高度，
 * 所以面板用 `position: fixed; top/right/bottom: 0` 自己钉 —— 不要指望父级 flex 给高度。
 */

import { useEffect, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { fsApi } from '../../api/fs';
import { fileNameOf } from '../../file-name';
import { fileIcon, isHtml, isMarkdown, labelOf } from '../../file-kind';
import { Icon } from '../Icon';
import { FilePreviewBody } from './FilePreviewBody';
import { useFilePreview } from './FilePreviewProvider';
import './FilePreview.css';

const COPY_RESET_MS = 1500;

export function FilePreviewPanel() {
  const { t } = useI18n();
  const { tabs, active, close, focus } = useFilePreview();

  /** 源码 / 预览：只对 md、html 有意义，切文件时复位成预览 */
  const [source, setSource] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<number | null>(null);

  useEffect(() => {
    setSource(false);
    setCopied(false);
  }, [active]);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  // Esc 关面板：它是覆盖在页面右侧的一层，不给键盘出口会显得「关不掉」
  useEffect(() => {
    if (active === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [active, close]);

  if (active === null) return null;

  const toggleable = isMarkdown(active) || isHtml(active);

  const copyPath = () => {
    void navigator.clipboard
      .writeText(active)
      .then(() => {
        setCopied(true);
        if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
        copyTimer.current = window.setTimeout(() => setCopied(false), COPY_RESET_MS);
      })
      .catch(() => {
        // 非安全上下文下剪贴板不可用：静默失败
      });
  };

  return (
    <aside className="fp-dock" aria-label={t('filePreview.title')}>
      <div className="fp-tabs" role="tablist" aria-label={t('filePreview.tabsLabel')}>
        {tabs.map((tab) => {
          const current = tab === active;
          return (
            <div key={tab} className={`fp-tab${current ? ' fp-tab--active' : ''}`}>
              <button
                type="button"
                role="tab"
                aria-selected={current}
                className="fp-tab__label"
                title={tab}
                onClick={() => focus(tab)}
              >
                <Icon name={fileIcon(tab)} size={12} />
                <span>{fileNameOf(tab)}</span>
              </button>
              <button
                type="button"
                className="fp-tab__x"
                aria-label={t('filePreview.closeTab', { name: fileNameOf(tab) })}
                onClick={() => close(tab)}
              >
                <Icon name="close" size={11} />
              </button>
            </div>
          );
        })}
        <button
          type="button"
          className="fp-tab-close"
          aria-label={t('filePreview.close')}
          title={t('filePreview.close')}
          onClick={() => close()}
        >
          <Icon name="close" size={13} />
        </button>
      </div>

      <div className="fp-path">
        <code title={active}>{active}</code>
        <button
          type="button"
          className="fp-icon-btn"
          aria-label={t('filePreview.copyPath')}
          title={copied ? t('filePreview.pathCopied') : t('filePreview.copyPath')}
          onClick={copyPath}
        >
          <Icon name={copied ? 'check' : 'copy'} size={12} />
        </button>
      </div>

      <div className="fp-toolbar">
        <span className="fp-lang">{labelOf(active)}</span>

        {toggleable && (
          <div className="fp-toggle" role="group">
            <button
              type="button"
              className={`fp-toggle__item${source ? '' : ' fp-toggle__item--active'}`}
              aria-pressed={!source}
              onClick={() => setSource(false)}
            >
              {t('filePreview.preview')}
            </button>
            <button
              type="button"
              className={`fp-toggle__item${source ? ' fp-toggle__item--active' : ''}`}
              aria-pressed={source}
              onClick={() => setSource(true)}
            >
              {t('filePreview.source')}
            </button>
          </div>
        )}

        <span className="fp-toolbar-spacer" />

        <button
          type="button"
          className="fp-icon-btn"
          aria-label={t('filePreview.reload')}
          title={t('filePreview.reload')}
          onClick={() => setReloadKey((current) => current + 1)}
        >
          <Icon name="refresh" size={13} />
        </button>
        <a
          className="fp-icon-btn"
          href={fsApi.rawUrl(active)}
          download
          aria-label={t('filePreview.download')}
          title={t('filePreview.download')}
        >
          <Icon name="download" size={13} />
        </a>
      </div>

      <div className="fp-content">
        <FilePreviewBody
          path={active}
          view={source ? 'source' : 'preview'}
          reloadKey={reloadKey}
        />
      </div>
    </aside>
  );
}
