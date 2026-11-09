/**
 * 生成阶段右侧的**工作空间**：文件树 + 文件预览，数据来自后端的产物浏览接口。
 *
 * 后端只读 stage 目录（`server/docs/03-architecture/07-artifact.md`），这里只负责
 * 把它摆成能用的界面：
 *
 * - **懒加载的目录树**：`artifacts/list` 一次只列一层，所以目录在**展开时**才请求，
 *   收起再展开用缓存。整棵递归拉一遍在真实工程（可能带 `node_modules`）上代价太大。
 * - **预览按扩展名分流**：文本与 SVG 走 `artifacts/file`（UTF-8，后端上限默认 2 MiB），
 *   其余图片用 `artifacts/download` 的地址当 `<img src>`，二进制只给下载 ——
 *   让 `file` 去读二进制只会得到一屏替换字符。SVG 单独走文本，是因为文本内容能直接
 *   内联成 data URL，不必依赖下载端点。
 *
 * - **下载**：后端 `artifacts/download` 已带 `dotfiles: 'allow'`（`.smart-factory` 这类点段
 *   不再被挡住）。文本 / SVG 仍用 Blob 下载 —— 内容已经在手里，不必再发一次请求。
 * - **md / html 走真渲染**：文本读回来之后交给 `FilePreviewBody`（Markdown 渲染 / iframe），
 *   不再一律铺成 `<pre>`。其它代码仍是深色源码视图。
 * - **刷新**：文件是会话里的引擎写的，接口没有订阅（07-artifact §4），所以只能拉。
 *   页面在一轮对话结束后把 `refreshSignal` 加一，这里收到就重拉已展开的目录。
 *
 * 路径约定见 `shared/api/artifacts.ts` —— 接口的 `path` 从 **stage 根**算起（不带 agentId），
 * 组件内部用的也是「相对 stage 根」的路径，两侧逐字相同，不需要再拼前缀。
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { msg, useI18n } from '../../../i18n/useI18n';
import type { ArtifactEntry, ArtifactFile } from '../../../shared/api/artifacts';
import { artifactsApi } from '../../../shared/api/artifacts';
import { backendDownHint, isBackendDown } from '../../../shared/api/agents';
import { ApiError } from '../../../shared/api/client';
import { FilePreviewBody } from '../../../shared/components/FilePreview/FilePreviewBody';
import { Icon } from '../../../shared/components/Icon';
import {
  classify,
  fileIcon,
  formatBytes,
  isHtml,
  isMarkdown,
  labelOf,
} from '../../../shared/file-kind';
import type { StageId } from '../types';
import './FileViewer.css';

/** 一层目录的加载状态；`entries === null` 表示还没有成功加载过 */
interface DirState {
  loading: boolean;
  error: string | null;
  entries: ArtifactEntry[] | null;
}

/** 文本文件的预览状态 */
interface PreviewState {
  loading: boolean;
  error: string | null;
  file: ArtifactFile | null;
  /** 出错时是否仍可下载（413 / 404 / 网络故障都值得给一个出口） */
  canDownload: boolean;
}

const EMPTY_PREVIEW: PreviewState = {
  loading: false,
  error: null,
  file: null,
  canDownload: false,
};

/**
 * `svg` 也是图片，但内容是 UTF-8 文本：走文本读出来再转 data URL，
 * 与栅格图的下载流分开处理。
 */
function svgDataUrl(content: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}`;
}

function describeListError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) return backendDownHint();
    return msg('fileViewer.listFailedDetail', { message: cause.message, status: cause.status });
  }
  return cause instanceof Error ? cause.message : msg('fileViewer.listFailed');
}

function describeFileError(cause: unknown, path: string): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) return backendDownHint();
    if (cause.status === 413) {
      return msg('fileViewer.fileTooLarge');
    }
    if (cause.status === 404) {
      return msg('fileViewer.fileMissing', { path });
    }
    return msg('fileViewer.listFailedDetail', { message: cause.message, status: cause.status });
  }
  return cause instanceof Error ? cause.message : msg('fileViewer.fileFailed');
}

interface TreeRowsProps {
  /** 父目录（相对智能体根；根目录是空串） */
  dir: string;
  depth: number;
  dirs: Record<string, DirState>;
  expanded: ReadonlySet<string>;
  selected: string;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  onRetry: (path: string) => void;
}

/** 递归渲染一层节点；目录展开时继续往下画，子目录按需请求。 */
function TreeRows({
  dir,
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

  // 首次加载（或刷新后重载）还没有任何数据：只画一行加载态
  if (!state || (state.loading && state.entries === null)) {
    return (
      <div className="fv-tree-note" style={{ paddingLeft: 8 + depth * 14 }}>
        <span className="fv-spinner" aria-hidden="true" />
        <span>{t('fileViewer.loading')}</span>
      </div>
    );
  }

  if (state.error !== null) {
    return (
      <div className="fv-tree-note fv-tree-note--error" style={{ paddingLeft: 8 + depth * 14 }}>
        <Icon name="alert" size={12} />
        <span title={state.error}>{state.error}</span>
        <button type="button" className="fv-tree-retry" onClick={() => onRetry(dir)}>
          {t('fileViewer.retry')}
        </button>
      </div>
    );
  }

  const entries = state.entries ?? [];

  if (entries.length === 0) {
    if (depth === 0) {
      return (
        <div className="fv-tree-empty">
          <Icon name="folderOpen" size={20} />
          <p>{t('fileViewer.empty')}</p>
          <span>{t('fileViewer.emptyHint')}</span>
        </div>
      );
    }
    return (
      <div className="fv-tree-note fv-tree-note--empty" style={{ paddingLeft: 8 + depth * 14 }}>
        {t('fileViewer.emptyDir')}
      </div>
    );
  }

  return (
    <>
      {entries.map((entry) => {
        const path = dir === '' ? entry.name : `${dir}/${entry.name}`;
        const isDir = entry.type === 'dir';
        const open = isDir && expanded.has(path);
        const active = !isDir && path === selected;

        return (
          <Fragment key={path}>
            <button
              type="button"
              className={`fv-tree-row${active ? ' fv-tree-row--selected' : ''}`}
              style={{ paddingLeft: 8 + depth * 14 }}
              title={path}
              aria-expanded={isDir ? open : undefined}
              onClick={() => (isDir ? onToggle(path) : onSelect(path))}
            >
              <span className="fv-tree-caret">
                {isDir ? <Icon name={open ? 'chevronDown' : 'chevronRight'} size={13} /> : null}
              </span>
              <span className="fv-tree-icon">
                <Icon
                  name={isDir ? (open ? 'folderOpen' : 'folder') : fileIcon(path)}
                  size={14}
                />
              </span>
              <span className="fv-tree-name">{entry.name}</span>
            </button>

            {open ? (
              <TreeRows
                dir={path}
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

export function FileViewer({
  agentId,
  stage = 'development',
  refreshSignal = 0,
  baseDir = null,
}: {
  agentId: string;
  /** 阶段决定接口的 stage 根；创建页目前只有生成阶段会挂这个组件 */
  stage?: StageId;
  /** 外部让它重拉：页面在一轮对话结束时会加一 */
  refreshSignal?: number;
  /**
   * 这个 stage 根的**绝对路径**（`<agent.dir>/<stage>`）。md / html 的真渲染要拼
   * `/fs/raw` 地址，相对 stage 根的 `selected` 自己不够用。详情还没回来时为 null，
   * 这时退回源码视图 —— 不假装能渲染。
   */
  baseDir?: string | null;
}) {
  const { t } = useI18n();
  const [dirs, setDirs] = useState<Record<string, DirState>>({});
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set<string>());
  const [selected, setSelected] = useState('');
  const [preview, setPreview] = useState<PreviewState>(EMPTY_PREVIEW);
  const [imageBroken, setImageBroken] = useState(false);
  /** 预览出错时点「重试」用 */
  const [previewNonce, setPreviewNonce] = useState(0);
  const [copied, setCopied] = useState(false);

  /** 换智能体/阶段时换代：旧请求的响应一律丢掉 */
  const generationRef = useRef(0);
  const bootKeyRef = useRef('');
  /** 同一目录的并发请求去重，键里带代次（换代后旧的键自然失效） */
  const inFlightRef = useRef<Set<string>>(new Set());
  const copyTimerRef = useRef<number | null>(null);
  const lastSignalRef = useRef(refreshSignal);

  const loadDir = useCallback(
    (relative: string) => {
      const generation = generationRef.current;
      const flightKey = `${String(generation)}:${relative}`;
      if (inFlightRef.current.has(flightKey)) return;
      inFlightRef.current.add(flightKey);

      setDirs((prev) => ({
        ...prev,
        [relative]: {
          loading: true,
          error: null,
          // 已有内容时保留，重拉期间树不消失
          entries: prev[relative]?.entries ?? null,
        },
      }));

      void artifactsApi
        .list({ stage, agentId, path: relative === '' ? undefined : relative })
        .then(
          (page) => {
            if (generation !== generationRef.current) return;
            setDirs((prev) => ({
              ...prev,
              [relative]: { loading: false, error: null, entries: page.items },
            }));
            // 根目录里第一个文件先顶上预览位，免得右半边一直空着
            if (relative === '') {
              const firstFile = page.items.find((entry) => entry.type === 'file');
              if (firstFile) {
                setSelected((current) => (current === '' ? firstFile.name : current));
              }
            }
          },
          (cause: unknown) => {
            if (generation !== generationRef.current) return;
            // 开发目录在创建智能体时才建出来；没有目录不是故障，按空工作空间呈现
            if (cause instanceof ApiError && cause.status === 404) {
              setDirs((prev) => ({
                ...prev,
                [relative]: { loading: false, error: null, entries: [] },
              }));
              return;
            }
            setDirs((prev) => ({
              ...prev,
              [relative]: {
                loading: false,
                error: describeListError(cause),
                entries: prev[relative]?.entries ?? null,
              },
            }));
          },
        )
        .finally(() => {
          inFlightRef.current.delete(flightKey);
        });
    },
    [agentId, stage],
  );

  // 换了智能体（或阶段）就整块重来，避免上一个智能体的树/预览串过来
  useEffect(() => {
    const key = `${agentId}#${stage}`;
    if (bootKeyRef.current === key) return;
    bootKeyRef.current = key;
    generationRef.current += 1;
    inFlightRef.current.clear();
    setDirs({});
    setExpanded(new Set<string>());
    setSelected('');
    setPreview(EMPTY_PREVIEW);
    setImageBroken(false);
    loadDir('');
  }, [agentId, stage, loadDir]);

  /** 重拉根目录与所有已展开目录；选中文件保留（预览 effect 会跟着重拉） */
  const refresh = useCallback(() => {
    generationRef.current += 1;
    inFlightRef.current.clear();
    const paths = ['', ...expanded];
    setDirs({});
    setPreview(EMPTY_PREVIEW);
    setImageBroken(false);
    // 预览 effect 的依赖里没有 refreshSignal，靠这个计数让它重读选中文件
    setPreviewNonce((current) => current + 1);
    for (const relative of paths) loadDir(relative);
  }, [expanded, loadDir]);

  // 一轮对话结束（页面把 refreshSignal 加一）：工作空间里可能刚多了文件
  useEffect(() => {
    if (lastSignalRef.current === refreshSignal) return;
    lastSignalRef.current = refreshSignal;
    refresh();
  }, [refreshSignal, refresh]);

  // 文本文件按需读取；图片/二进制不请求 file，直接用下载地址
  useEffect(() => {
    setImageBroken(false);
    if (selected === '') {
      setPreview(EMPTY_PREVIEW);
      return;
    }
    const kind = classify(selected);
    if (kind !== 'text' && kind !== 'svg') {
      setPreview(EMPTY_PREVIEW);
      return;
    }

    let cancelled = false;
    setPreview({ loading: true, error: null, file: null, canDownload: false });

    void artifactsApi.file({ stage, agentId, path: selected }).then(
      (file) => {
        if (!cancelled) setPreview({ loading: false, error: null, file, canDownload: false });
      },
      (cause: unknown) => {
        if (cancelled) return;
        setPreview({
          loading: false,
          error: describeFileError(cause, selected),
          file: null,
          canDownload: true,
        });
      },
    );

    return () => {
      cancelled = true;
    };
  }, [selected, agentId, stage, previewNonce]);

  useEffect(
    () => () => {
      if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
    },
    [],
  );

  /** 已加载目录里的文件项，用来看大小；找不到（还没展开过）就是 undefined */
  const entryByPath = useMemo(() => {
    const map = new Map<string, ArtifactEntry>();
    for (const [dir, state] of Object.entries(dirs)) {
      for (const entry of state.entries ?? []) {
        map.set(dir === '' ? entry.name : `${dir}/${entry.name}`, entry);
      }
    }
    return map;
  }, [dirs]);

  const handleToggle = (path: string) => {
    const opening = !expanded.has(path);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    // 展开时才拉这一层；收起保留缓存，再次展开不重复请求
    if (opening) loadDir(path);
  };

  const handleSelect = (path: string) => {
    setSelected(path);
    setCopied(false);
  };

  /**
   * 文本 / SVG 的下载走 Blob，不经过后端的 `artifacts/download`。
   *
   * 后端那个端点在默认工作目录（`~/.smart-factory`，路径里带点开头的目录）下会 404 ——
   * Express `sendFile` 默认 `dotfiles: 'ignore'`。内容已经在手里，就没必要再依赖它。
   */
  const handleDownload = () => {
    const content = preview.file?.content;
    if (content === undefined) return;
    const fileName = selected.split('/').pop() ?? 'download';
    const type =
      classify(selected) === 'svg' ? 'image/svg+xml;charset=utf-8' : 'text/plain;charset=utf-8';
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const handleCopy = () => {
    const content = preview.file?.content;
    if (content === undefined) return;
    void navigator.clipboard
      .writeText(content)
      .then(() => {
        setCopied(true);
        if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
        copyTimerRef.current = window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        // 剪贴板不可用（非安全上下文等）时静默失败，不改按钮文案。
      });
  };

  const selectedKind = selected === '' ? null : classify(selected);
  const selectedEntry = entryByPath.get(selected);
  const size =
    selectedKind === 'text' || selectedKind === 'svg'
      ? (preview.file?.size ?? selectedEntry?.size)
      : selectedEntry?.size;
  const downloadHref =
    selected === ''
      ? ''
      : artifactsApi.downloadUrl({ stage, agentId, path: selected });

  /** md / html 的绝对路径；拿不到基址时为空串，渲染退回源码 */
  const absoluteSelected =
    selected === '' || baseDir === null
      ? ''
      : `${baseDir.replace(/\/+$/u, '')}/${selected}`;

  return (
    <div className="fv">
      <aside className="fv-tree">
        <div className="fv-tree-head">
          <span className="fv-tree-title">{t('fileViewer.title')}</span>
          <button
            type="button"
            className="fv-tree-refresh"
            title={t('fileViewer.refresh')}
            aria-label={t('fileViewer.refresh')}
            onClick={refresh}
          >
            <Icon name="refresh" size={14} />
          </button>
        </div>

        <div className="fv-tree-body">
          <TreeRows
            dir=""
            depth={0}
            dirs={dirs}
            expanded={expanded}
            selected={selected}
            onToggle={handleToggle}
            onSelect={handleSelect}
            onRetry={loadDir}
          />
        </div>
      </aside>

      <section className="fv-view">
        {selected === '' ? (
          <div className="fv-placeholder">
            <Icon name="file" size={26} />
            <p>{t('fileViewer.selectHint')}</p>
          </div>
        ) : (
          <>
            <header className="fv-view-head">
              <span className="fv-view-path" title={selected}>
                {selected}
              </span>
              <span className="fv-lang">{labelOf(selected)}</span>
              {size !== undefined ? <span className="fv-size">{formatBytes(size)}</span> : null}

              <div className="fv-actions">
                {preview.file !== null &&
                (selectedKind === 'text' || selectedKind === 'svg') ? (
                  <button type="button" className="fv-btn" onClick={handleDownload}>
                    <Icon name="download" size={13} />
                    {t('fileViewer.download')}
                  </button>
                ) : (
                  <a className="fv-btn" href={downloadHref} download>
                    <Icon name="download" size={13} />
                    {t('fileViewer.download')}
                  </a>
                )}
                {selectedKind === 'text' || selectedKind === 'svg' ? (
                  <button
                    type="button"
                    className="fv-btn"
                    onClick={handleCopy}
                    disabled={preview.file === null}
                  >
                    <Icon name={copied ? 'check' : 'copy'} size={13} />
                    {copied ? t('fileViewer.copied') : t('fileViewer.copy')}
                  </button>
                ) : null}
              </div>
            </header>

            {selectedKind === 'image' ? (
              imageBroken ? (
                <PreviewError
                  message={t('fileViewer.imageError')}
                  downloadHref={downloadHref}
                  onRetry={refresh}
                />
              ) : (
                <div className="fv-image-wrap">
                  <img
                    className="fv-image"
                    src={downloadHref}
                    alt={selected}
                    onError={() => setImageBroken(true)}
                  />
                </div>
              )
            ) : selectedKind === 'binary' ? (
              <div className="fv-placeholder">
                <Icon name="file" size={26} />
                <p>{t('fileViewer.noPreview')}</p>
                <a className="fv-btn" href={downloadHref} download>
                  <Icon name="download" size={13} />
                  {t('fileViewer.downloadFile')}
                </a>
              </div>
            ) : preview.loading ? (
              <div className="fv-placeholder" aria-busy="true">
                <span className="fv-spinner" aria-hidden="true" />
                <p>{t('fileViewer.reading')}</p>
              </div>
            ) : preview.error !== null ? (
              <PreviewError
                message={preview.error}
                downloadHref={preview.canDownload ? downloadHref : null}
                onRetry={() => setPreviewNonce((current) => current + 1)}
              />
            ) : preview.file !== null ? (
              preview.file.content === '' ? (
                <div className="fv-placeholder">
                  <Icon name="file" size={26} />
                  <p>{t('fileViewer.emptyFile')}</p>
                </div>
              ) : selectedKind === 'svg' ? (
                <div className="fv-image-wrap">
                  <img
                    className="fv-image"
                    src={svgDataUrl(preview.file.content)}
                    alt={selected}
                  />
                </div>
              ) : (isMarkdown(selected) || isHtml(selected)) && absoluteSelected !== '' ? (
                /*
                 * md 按 Markdown 渲染、html 真渲染（iframe + sandbox）。
                 * 内容已经由 artifacts/file 读回来了，交给 Body 时带上 content，
                 * 不让它再走一次 /fs/read。
                 */
                <FilePreviewBody path={absoluteSelected} content={preview.file.content} />
              ) : (
                <pre className="fv-code">{preview.file.content}</pre>
              )
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

/** 预览区的错误态：一句原因 + 重试 / 下载两个出口 */
function PreviewError({
  message,
  downloadHref,
  onRetry,
}: {
  message: string;
  downloadHref: string | null;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="fv-placeholder fv-placeholder--error" role="alert">
      <Icon name="alert" size={22} />
      <p>{message}</p>
      <div className="fv-actions">
        <button type="button" className="fv-btn" onClick={onRetry}>
          <Icon name="refresh" size={13} />
          {t('fileViewer.retry')}
        </button>
        {downloadHref !== null ? (
          <a className="fv-btn" href={downloadHref} download>
            <Icon name="download" size={13} />
            {t('fileViewer.download')}
          </a>
        ) : null}
      </div>
    </div>
  );
}
