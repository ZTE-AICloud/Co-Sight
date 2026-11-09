/**
 * 工坊右侧的技能库文件面板：左边目录树，右边预览。
 *
 * 数据只走 `/fs/list` 与 `/fs/read`（`shared/api/fs.ts`）—— 技能库是端侧目录，
 * 前端没有第二份索引；树根 `root` 由 `GET /skills` 给出，前端不拼路径。
 *
 * - **懒加载**：一次只列一层，展开时才请求（与 `FileViewer` 同口径）。技能库通常
 *   不大，但按需加载不会因为将来塞进大目录而卡住整页。
 * - **预览复用 `FilePreviewBody`**：md / html / 图片 / 二进制 / 过大的分流都在那里，
 *   这里不再按扩展名写第二套。
 * - **刷新**：接口没有订阅。一轮对话结束后页面把 `refreshSignal` 加一，这里重拉
 *   根与已展开的目录 —— 刚产出的技能只有重拉才看得见。
 *
 * 目录不存在（技能库还没产出过任何技能）按空目录处理：后端 `fs/list` 给 404，
 * 这不是故障。
 */

import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { msg, useI18n } from '../../../i18n/useI18n';
import type { FsEntry } from '../../../shared/api/fs';
import { fsApi } from '../../../shared/api/fs';
import { backendDownHint, isBackendDown } from '../../../shared/api/agents';
import { ApiError } from '../../../shared/api/client';
import { fileNameOf } from '../../../shared/file-name';
import { fileIcon } from '../../../shared/file-kind';
import { FilePreviewBody } from '../../../shared/components/FilePreview/FilePreviewBody';
import { Icon } from '../../../shared/components/Icon';

/** 一层目录的加载状态；`entries === null` 表示还没有成功加载过 */
interface DirState {
  loading: boolean;
  error: string | null;
  entries: FsEntry[] | null;
}

interface SkillFilesPanelProps {
  /** 技能库根目录（`GET /skills` 的 `root`）；null = 还没拿到 */
  root: string | null;
  /** 技能库请求还在路上 */
  loading: boolean;
  /** 技能库请求失败的原因（页面已经拿到的那句） */
  error: string | null;
  /** 一轮对话结束后由页面加一：重拉目录树与预览 */
  refreshSignal?: number;
}

export function SkillFilesPanel({
  root,
  loading,
  error,
  refreshSignal = 0,
}: SkillFilesPanelProps) {
  const { t } = useI18n();

  const [dirs, setDirs] = useState<Record<string, DirState>>({});
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set<string>());
  const [selected, setSelected] = useState<string | null>(null);
  /** 重拉预览（文件内容变了，路径可能没变） */
  const [previewNonce, setPreviewNonce] = useState(0);

  /** 换根就换代：旧请求的响应一律丢掉 */
  const generationRef = useRef(0);
  /** 同一目录的并发请求去重，键里带代次 */
  const inFlightRef = useRef<Set<string>>(new Set());
  const lastSignalRef = useRef(refreshSignal);

  const loadDir = useCallback(
    (path: string) => {
      const generation = generationRef.current;
      const flightKey = `${String(generation)}:${path}`;
      if (inFlightRef.current.has(flightKey)) return;
      inFlightRef.current.add(flightKey);

      setDirs((previous) => ({
        ...previous,
        [path]: {
          loading: true,
          error: null,
          // 已有内容时保留：重拉期间树不闪空
          entries: previous[path]?.entries ?? null,
        },
      }));

      void fsApi.list({ path }).then(
        (page) => {
          if (generation !== generationRef.current) return;
          setDirs((previous) => ({
            ...previous,
            [path]: { loading: false, error: null, entries: page.items },
          }));
        },
        (cause: unknown) => {
          if (generation !== generationRef.current) return;
          // 技能库根 / 技能目录还没建出来：不是故障，按空目录呈现
          if (cause instanceof ApiError && cause.status === 404) {
            setDirs((previous) => ({
              ...previous,
              [path]: { loading: false, error: null, entries: [] },
            }));
            return;
          }
          setDirs((previous) => ({
            ...previous,
            [path]: {
              loading: false,
              error: describeListError(cause),
              entries: previous[path]?.entries ?? null,
            },
          }));
        },
      ).finally(() => {
        inFlightRef.current.delete(flightKey);
      });
    },
    [],
  );

  // 换根（首次拿到 / 技能库重试后换了目录）就整块重来
  useEffect(() => {
    generationRef.current += 1;
    inFlightRef.current.clear();
    setDirs({});
    setExpanded(new Set<string>());
    setSelected(null);
    if (root !== null) loadDir(root);
  }, [root, loadDir]);

  /** 重拉根与所有已展开目录；选中文件保留（预览跟着重读） */
  const refresh = useCallback(() => {
    if (root === null) return;
    generationRef.current += 1;
    inFlightRef.current.clear();
    setDirs({});
    setPreviewNonce((current) => current + 1);
    loadDir(root);
    for (const path of expanded) loadDir(path);
  }, [root, expanded, loadDir]);

  // 一轮对话结束：技能库里可能刚多了文件
  useEffect(() => {
    if (lastSignalRef.current === refreshSignal) return;
    lastSignalRef.current = refreshSignal;
    refresh();
  }, [refreshSignal, refresh]);

  const toggle = (path: string) => {
    const opening = !expanded.has(path);
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    // 展开时才拉这一层；收起保留缓存，再次展开不重复请求
    if (opening) loadDir(path);
  };

  return (
    <aside className="sw-files" aria-label={t('workshop.files.title')}>
      <header className="sw-files-head">
        <span className="sw-files-title" title={root ?? undefined}>
          <Icon name="folderOpen" size={13} />
          {t('workshop.files.title')}
        </span>
        <button
          type="button"
          className="sw-files-refresh"
          title={t('workshop.files.refresh')}
          aria-label={t('workshop.files.refresh')}
          disabled={root === null}
          onClick={refresh}
        >
          <Icon name="refresh" size={13} />
        </button>
      </header>

      {root === null ? (
        <div className="sw-files-state">
          {loading ? (
            <>
              <span className="sw-spinner" aria-hidden="true" />
              <p>{t('workshop.files.reading')}</p>
            </>
          ) : (
            <>
              <Icon name="alert" size={20} />
              <p>{error ?? t('workshop.files.unavailable')}</p>
            </>
          )}
        </div>
      ) : (
        <div className="sw-files-body">
          <div className="sw-files-tree">
            <TreeRows
              dir={root}
              root={root}
              depth={0}
              dirs={dirs}
              expanded={expanded}
              selected={selected}
              onToggle={toggle}
              onSelect={setSelected}
              onRetry={loadDir}
            />
          </div>

          <section className="sw-files-preview">
            {selected === null ? (
              <div className="sw-files-placeholder">
                <Icon name="file" size={22} />
                <p>{t('workshop.files.pickHint')}</p>
              </div>
            ) : (
              <>
                <div className="sw-files-file">
                  <Icon name={fileIcon(selected)} size={13} />
                  <span className="sw-files-file-name">{fileNameOf(selected)}</span>
                  <code className="sw-files-file-path" title={selected}>
                    {relativeTo(root, selected)}
                  </code>
                  <a
                    className="sw-files-download"
                    href={fsApi.rawUrl(selected)}
                    download
                    title={t('filePreview.download')}
                    aria-label={t('filePreview.download')}
                  >
                    <Icon name="download" size={13} />
                  </a>
                </div>
                <div className="sw-files-preview-body">
                  <FilePreviewBody path={selected} reloadKey={previewNonce} />
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}

/* ---------- 目录树 ---------- */

interface TreeRowsProps {
  /** 要渲染的目录（绝对路径） */
  dir: string;
  /** 技能库根：用来算相对路径 / 判「根」层 */
  root: string;
  depth: number;
  dirs: Record<string, DirState>;
  expanded: ReadonlySet<string>;
  selected: string | null;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  onRetry: (path: string) => void;
}

/** 递归渲染一层节点；子目录展开时才继续往下画。 */
function TreeRows({
  dir,
  root,
  depth,
  dirs,
  expanded,
  selected,
  onToggle,
  onSelect,
  onRetry,
}: TreeRowsProps) {
  const { t } = useI18n();
  const state = dirs[dir];
  const indent = { paddingLeft: 8 + depth * 14 };

  // 首次加载（或刷新后重载）还没有任何数据：只画一行加载态
  if (!state || (state.loading && state.entries === null)) {
    return (
      <div className="sw-tree-note" style={indent}>
        <span className="sw-spinner" aria-hidden="true" />
        <span>{t('workshop.files.loading')}</span>
      </div>
    );
  }

  if (state.error !== null) {
    return (
      <div className="sw-tree-note sw-tree-note--error" style={indent}>
        <Icon name="alert" size={12} />
        <span title={state.error}>{t('workshop.files.loadFailed')}</span>
        <button type="button" className="sw-tree-retry" onClick={() => onRetry(dir)}>
          {t('workshop.retry')}
        </button>
      </div>
    );
  }

  const entries = state.entries ?? [];

  if (entries.length === 0) {
    // 根目录为空 = 技能库还没有产出；子目录为空只说这一层没有东西
    if (dir === root) {
      return (
        <div className="sw-tree-empty">
          <Icon name="folderOpen" size={20} />
          <p>{t('workshop.files.empty')}</p>
          <span>{t('workshop.files.emptyHint')}</span>
        </div>
      );
    }
    return (
      <div className="sw-tree-note sw-tree-note--empty" style={indent}>
        {t('workshop.files.emptyDir')}
      </div>
    );
  }

  return (
    <>
      {entries.map((entry) => {
        const path = entry.path;
        const isDir = entry.type === 'dir';
        const open = isDir && expanded.has(path);
        const active = !isDir && path === selected;

        return (
          <Fragment key={path}>
            <button
              type="button"
              className={`sw-tree-row${active ? ' sw-tree-row--active' : ''}`}
              style={indent}
              title={relativeTo(root, path)}
              aria-expanded={isDir ? open : undefined}
              onClick={() => (isDir ? onToggle(path) : onSelect(path))}
            >
              <span className="sw-tree-caret">
                {isDir ? <Icon name={open ? 'chevronDown' : 'chevronRight'} size={13} /> : null}
              </span>
              <span className="sw-tree-icon">
                <Icon
                  name={isDir ? (open ? 'folderOpen' : 'folder') : fileIcon(path)}
                  size={14}
                />
              </span>
              <span className="sw-tree-name">{entry.name}</span>
            </button>

            {open ? (
              <TreeRows
                dir={path}
                root={root}
                depth={depth + 1}
                dirs={dirs}
                expanded={expanded}
                selected={selected}
                onToggle={onToggle}
                onSelect={onSelect}
                onRetry={onRetry}
              />
            ) : null}
          </Fragment>
        );
      })}
    </>
  );
}

/* ---------- 工具 ---------- */

/** 相对技能库根的路径；不在根下时原样返回（服务端可能解了 symlink） */
function relativeTo(root: string, path: string): string {
  const prefix = root.endsWith('/') ? root : `${root}/`;
  return path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

function describeListError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) return backendDownHint();
    return msg('workshop.files.loadFailedDetail', { message: cause.message, status: cause.status });
  }
  return cause instanceof Error ? cause.message : msg('workshop.files.loadFailed');
}
