/**
 * 本机文件选择器：发送框左侧 `+` → 「添加文件」打开的弹窗。
 *
 * 端侧形态，**没有上传**：选中的文件就是一个绝对路径，随消息发给引擎自己读。
 * 所以这个组件只做两件事 —— 把服务端列出来的目录摆成可点的列表，把选中项的**路径**交出去。
 * 浏览范围不设限（整机任意目录都能点进去），路径是否合法由服务端判定（见 `shared/api/fs.ts`）；
 * 顶部的主目录 / 工作区只是快捷入口。
 *
 * 为什么不用 `<input type="file">`：浏览器安全模型下 `File` 对象**永远不暴露绝对路径**
 * （File System Access API 的 handle 也只有名字）。同机部署也绕不过这条，
 * 路径只能由服务端列目录时回给我们。
 *
 * 交互约定：
 * - 单击目录进入、单击文件选中，双击文件直接确认；
 * - **路径行点一下变输入框**（像文件管理器）——直接粘一个路径回车直达：
 *   `~` 展开成主目录、相对路径按当前目录补全、外层的引号（Windows「复制为路径」会带）自动剥掉；
 *   粘的是**文件**时退到它所在目录并选中它，不用再翻一层；
 * - 「上一级」只在前端拿得到 `parent` 时可用（一路能退到文件系统根）；
 * - **搜索只在当前目录里过滤**（不递归）：目录是懒加载的，子目录里有什么这里根本不知道，
 *   真做全树搜索得让服务端遍历，那是另一件事。换目录时过滤条件自动清空；
 * - **以点开头的条目默认收起**，标题行的开关可以临时放出来 —— 主目录里 `.cache` / `.git`
 *   这类会淹掉真正要找的东西；
 * - Esc：搜索框展开时只收搜索框（再按一次才收搜索框本身），否则关窗；
 *   点遮罩关闭，关闭等于取消（`onCancel`）。
 *
 * 弹窗用原生 `<dialog>`（`showModal()`）：焦点陷阱、Esc、`::backdrop` 都是白送的，
 * 全仓也没有另一套手搓遮罩的写法。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import { msg, useI18n } from '../../i18n/useI18n';
import { fsApi } from '../api/fs';
import type { FsEntry, FsListing, FsRoot } from '../api/fs';
import { ApiError } from '../api/client';
import { backendDownHint, isBackendDown } from '../api/agents';
import { Icon } from './Icon';
import './FilePicker.css';

export interface FilePickerProps {
  /** 挂载即打开（调用方按需挂载，见 `useFilePicker`） */
  open: boolean;
  /** 取消：Esc / 点遮罩 / 关闭按钮 */
  onCancel: () => void;
  /** 选中一个文件，参数是**绝对路径** */
  onPick: (path: string) => void;
  /** 打开时直接进入的目录；缺省进第一个快捷入口 */
  initialPath?: string;
}

/** 后端的报错原话优先；「后端没起」有自己的判据（响应不是 JSON），不能混成一句网络错误 */
function describeError(error: unknown): string {
  if (isBackendDown(error)) return backendDownHint();
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : msg('common.unknownError');
}

/**
 * 「输入路径」失败后要不要试着当文件处理。
 *
 * 形态已在前端拦过（空、相对、`~` 展开），所以剩下能回 400 的几乎只有「这是个文件不是目录」；
 * 404 是「不存在」，不能再退到父目录 —— 那会把用户打错的目录名悄悄变成一次成功跳转。
 */
function isNotADirectory(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400;
}

/** 刚粘进来的那个文件：按名字找，别按路径 —— 用户输入的写法可能经过软链、和列表里的对不上 */
function arrivalSelection(result: FsListing, name: string | undefined): FsEntry | null {
  if (name === undefined) return null;
  return result.items.find((entry) => entry.type === 'file' && entry.name === name) ?? null;
}

/** 粘贴的是文件时拆出「所在目录 + 文件名」；拆不动（根目录之类）返回 null */
function splitFilePath(path: string): { parent: string; name: string } | null {
  const trimmed = path.replace(/[\\/]+$/, '');
  if (trimmed === '') return null;
  const index = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
  if (index < 0) return null;
  const name = trimmed.slice(index + 1);
  if (name === '') return null;
  let parent = index === 0 ? trimmed.slice(0, 1) : trimmed.slice(0, index);
  // Windows 盘根：C:\a.txt 的父目录是 C:，补上分隔符才是绝对路径
  if (/^[A-Za-z]:$/.test(parent)) parent = `${parent}\\`;
  return { parent, name };
}

export function FilePicker({ open, onCancel, onPick, initialPath }: FilePickerProps) {
  // 每次打开都重新挂载：目录缓存与选中项归零，不把上一次的状态带进来
  if (!open) return null;
  return <FilePickerDialog onCancel={onCancel} onPick={onPick} initialPath={initialPath} />;
}

function FilePickerDialog({
  onCancel,
  onPick,
  initialPath,
}: {
  onCancel: () => void;
  onPick: (path: string) => void;
  initialPath?: string;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [listing, setListing] = useState<FsListing | null>(null);
  const [selected, setSelected] = useState<FsEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** 搜索框是否展开；只在**当前目录**里过滤，不递归 */
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  /** 以点开头的条目默认收起：主目录里 `.cache` / `.git` 这类会淹掉真正要找的东西 */
  const [showHidden, setShowHidden] = useState(false);
  /** 路径行是否切换成输入框（点一下路径就进编辑态，粘完回车直达） */
  const [pathEditing, setPathEditing] = useState(false);
  const [pathDraft, setPathDraft] = useState('');

  /** 进过的目录不再重复请求：来回点「上一级」时不该每次都等一下 */
  const cache = useRef(new Map<string, FsListing>());
  /** 连续快速点击时只认最后一次请求的结果 */
  const requestSeq = useRef(0);
  /** 列表滚动容器：「粘路径」选中的文件可能排在几百行之后，得滚过去才看得见 */
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = dialogRef.current;
    // StrictMode 会跑两遍 effect：已经 open 了再 showModal() 会抛 InvalidStateError
    if (node && !node.open) node.showModal();
  }, []);

  /**
   * 进目录。返回值给「输入路径」用：`notDir` 是「这其实是个文件」的信号，
   * 调用方据此退到父目录重来（见 `submitPathEdit`）。
   * `selectName` 只在从输入框直达时给 —— 落到父目录后顺手把那个文件选中。
   */
  const openDir = useCallback(async (path: string, selectName?: string): Promise<'ok' | 'notDir' | 'failed'> => {
    const arrive = (result: FsListing) => {
      const entry = arrivalSelection(result, selectName);
      setListing(result);
      setSelected(entry);
      // 选中的是隐藏文件时把开关打开，否则「选中了一个看不见的条目」
      if (entry !== null && entry.name.startsWith('.')) setShowHidden(true);
    };

    const cached = cache.current.get(path);
    if (cached !== undefined) {
      setError(null);
      setLoading(false);
      arrive(cached);
      return 'ok';
    }

    const seq = (requestSeq.current += 1);
    setLoading(true);
    setError(null);
    try {
      const result = await fsApi.list({ path });
      if (requestSeq.current !== seq) return 'failed';
      cache.current.set(path, result);
      arrive(result);
      return 'ok';
    } catch (cause) {
      if (requestSeq.current !== seq) return 'failed';
      setError(describeError(cause));
      // 列表已经不在屏幕上了，别让「选中项」还挂着上一处目录里的文件
      setSelected(null);
      // 「不是目录」交给调用方当文件再试一次；其余错误就此收住
      return isNotADirectory(cause) ? 'notDir' : 'failed';
    } finally {
      if (requestSeq.current === seq) setLoading(false);
    }
  }, []);

  /**
   * 选中项始终在视野里：从输入框直接落到的文件可能排在几百行之后（目录在前、文件在后），
   * 不滚过去的话，底栏明明选了东西、列表却是一片别的目录。
   */
  useEffect(() => {
    const box = listRef.current;
    if (box === null) return;
    if (selected === null) {
      box.scrollTop = 0;
      return;
    }
    const row = box.querySelector<HTMLElement>(`[data-path="${CSS.escape(selected.path)}"]`);
    row?.scrollIntoView({ block: 'nearest' });
  }, [selected, listing?.path]);

  // 打开时先读根，再进起点目录
  useEffect(() => {
    let alive = true;
    void fsApi
      .roots()
      .then(({ items }) => {
        if (!alive) return;
        setRoots(items);
        // 缺省进框架当前生效的工作区（没有生效工作区才回落主目录）：
        // 用户要找的文件基本都在工作区里，从主目录起步每次都得先往下点几层。
        const start = initialPath ?? items.find((root) => root.active)?.path ?? items[0]?.path;
        if (start !== undefined) return openDir(start);
        setLoading(false);
        setError(t('filePicker.noRoots'));
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        setError(describeError(cause));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // t 只会随语言变化；换语言时若还在读根，重读一遍让空态文案也跟着换
  }, [initialPath, openDir, t]);

  /** 当前目录属于哪个根（用于高亮根标签）。分隔符两种都认：端侧也可能跑在 Windows 上 */
  const activeRoot = roots.find(
    (root) =>
      listing !== null &&
      (listing.path === root.path ||
        listing.path.startsWith(`${root.path}/`) ||
        listing.path.startsWith(`${root.path}\\`)),
  );

  /** 只过滤当前这一层：目录是懒加载的，子目录里有什么这里根本不知道 */
  const needle = query.trim().toLowerCase();
  const visibleItems = (listing?.items ?? []).filter((entry) => {
    if (!showHidden && entry.name.startsWith('.')) return false;
    return needle === '' || entry.name.toLowerCase().includes(needle);
  });
  /** 目录里确实有东西，只是都被当前条件藏起来了 —— 空态文案要分得开 */
  const filteredOut = (listing?.items.length ?? 0) > 0 && visibleItems.length === 0;

  /** 换目录 = 换一套条目：过滤条件与选中项都跟着重来，不然会留下「选中了看不见的东西」 */
  function go(path: string) {
    setQuery('');
    setSearchOpen(false);
    setSelected(null);
    void openDir(path);
  }

  function closeSearch() {
    setQuery('');
    setSearchOpen(false);
    setSelected(null);
  }

  function startPathEdit() {
    setPathDraft(listing?.path ?? '');
    setPathEditing(true);
    // 上一次的错误留着只会让人以为新输入也有问题
    setError(null);
  }

  function finishPathEdit() {
    setPathEditing(false);
    setPathDraft('');
  }

  /**
   * 输入框里的一行 → 可请求的路径。
   *
   * 剥外层引号是因为 Windows 资源管理器「复制为路径」会给路径套一对双引号；
   * `~` / `~/x` 用主目录展开（前端已知主目录，不必让服务端懂 shell 语法）；
   * 相对路径按当前目录补全 —— 输入框里打 `docs` 就该进当前目录下的 `docs`。
   */
  function resolveTypedPath(raw: string): string | null {
    let value = raw.trim();
    if (value.length >= 2) {
      const first = value[0];
      if ((first === '"' || first === "'") && value[value.length - 1] === first) {
        value = value.slice(1, -1).trim();
      }
    }
    if (value === '') return null;

    if (value.startsWith('~')) {
      const home = roots.find((root) => root.workspaceId === null)?.path;
      if (home === undefined) return null;
      if (value === '~') return home;
      if (!value.startsWith('~/') && !value.startsWith('~\\')) return null;
      return home + value.slice(1);
    }

    const absolute = value.startsWith('/') || /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\');
    if (absolute) return value;
    if (listing === null) return null;
    return `${listing.path.replace(/[\\/]+$/, '')}/${value}`;
  }

  /** 回车直达：先当目录进；进不去且是「不是目录」时，再当文件处理 */
  async function submitPathEdit() {
    const target = resolveTypedPath(pathDraft);
    if (target === null) {
      setError(t('filePicker.pathInvalid'));
      return;
    }

    const outcome = await openDir(target);
    if (outcome === 'ok') {
      finishPathEdit();
      return;
    }
    if (outcome !== 'notDir') return; // 不存在 / 别的错误：留在编辑态，错误显示在列表区

    // 粘贴的常常是**文件**的完整路径：退到它所在目录并选中，省得用户再翻一层
    const split = splitFilePath(target);
    if (split !== null && (await openDir(split.parent, split.name)) === 'ok') {
      finishPathEdit();
    }
  }

  const stop = (event: MouseEvent) => event.stopPropagation();

  return (
    <dialog
      ref={dialogRef}
      className="fp-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={onCancel}
    >
      {/* 点弹窗内部不该关窗；遮罩的点击落在 dialog 本身 */}
      <div className="fp-panel" onClick={stop}>
        <header className="fp-head">
          <span className="fp-title">{t('filePicker.title')}</span>
          <div className="fp-head-actions">
            <label className="fp-toggle" title={t('filePicker.showHiddenHint')}>
              <input
                type="checkbox"
                checked={showHidden}
                onChange={(event) => {
                  setShowHidden(event.target.checked);
                  // 藏起来的条目可能正是刚选中的那个
                  setSelected(null);
                }}
              />
              {t('filePicker.showHidden')}
            </label>
            <button
              type="button"
              className="fp-icon-btn"
              aria-label={t('common.close')}
              onClick={onCancel}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        </header>

        <div className="fp-roots" role="group" aria-label={t('filePicker.roots')}>
          {roots.map((root) => {
            const on = root === activeRoot;
            return (
              <button
                key={root.path}
                type="button"
                className={`fp-root${on ? ' fp-root--on' : ''}`}
                title={root.path}
                onClick={() => go(root.path)}
              >
                <Icon name={on ? 'folderOpen' : 'folder'} size={13} />
                {root.label}
                {root.active && <span className="fp-root-badge">{t('filePicker.current')}</span>}
              </button>
            );
          })}
        </div>

        <div className="fp-path">
          <button
            type="button"
            className="fp-icon-btn"
            aria-label={t('filePicker.up')}
            disabled={listing?.parent === null || listing === null}
            onClick={() => {
              if (listing?.parent) go(listing.parent);
            }}
          >
            <Icon name="arrowLeft" size={15} />
          </button>

          {searchOpen ? (
            <>
              <input
                className="fp-search"
                // 带值自动聚焦：点了放大镜就是要打字，不用再点一下输入框
                autoFocus
                value={query}
                placeholder={t('filePicker.searchPlaceholder')}
                aria-label={t('filePicker.searchAria')}
                onChange={(event) => {
                  setQuery(event.target.value);
                  // 过滤掉的条目可能正是刚选中的那个，别让「选中项」和画面对不上
                  setSelected(null);
                }}
                onKeyDown={(event) => {
                  if (event.key !== 'Escape') return;
                  // Esc 只收搜索框，不关整个弹窗：输到一半整窗没了是最烦的一种
                  event.preventDefault();
                  event.stopPropagation();
                  if (query !== '') setQuery('');
                  else closeSearch();
                }}
              />
              <button
                type="button"
                className="fp-icon-btn"
                aria-label={t('filePicker.closeSearch')}
                onClick={closeSearch}
              >
                <Icon name="close" size={14} />
              </button>
            </>
          ) : pathEditing ? (
            <input
              className="fp-search"
              autoFocus
              value={pathDraft}
              placeholder={t('filePicker.pathPlaceholder')}
              aria-label={t('filePicker.pathAria')}
              // 点进来就全选：粘贴会整段替换，不用先手动删掉旧路径
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setPathDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void submitPathEdit();
                } else if (event.key === 'Escape') {
                  // 与搜索框一致：Esc 只退出输入，不关整个弹窗
                  event.preventDefault();
                  event.stopPropagation();
                  finishPathEdit();
                }
              }}
              onBlur={finishPathEdit}
            />
          ) : (
            <>
              <button
                type="button"
                className="fp-path-text"
                title={t('filePicker.editPathHint', { path: listing?.path ?? '' })}
                onClick={startPathEdit}
              >
                {listing?.path ?? '…'}
              </button>
              <button
                type="button"
                className="fp-icon-btn"
                aria-label={t('filePicker.searchHere')}
                disabled={listing === null}
                onClick={() => setSearchOpen(true)}
              >
                <Icon name="search" size={15} />
              </button>
            </>
          )}
        </div>

        {/* 搜索时路径让位给了输入框，得补一行说清「在哪个目录里搜」 */}
        {searchOpen && (
          <div className="fp-scope" title={listing?.path ?? ''}>
            {t('filePicker.searchingIn', { path: listing?.path ?? '…' })}
          </div>
        )}

        <div
          ref={listRef}
          className="fp-list"
          role="listbox"
          aria-label={t('filePicker.dirContents')}
          aria-busy={loading}
        >
          {error !== null ? (
            <div className="fp-state fp-state--error" role="alert">
              <Icon name="alert" size={16} />
              <span>{error}</span>
            </div>
          ) : loading ? (
            <div className="fp-state">{t('filePicker.loading')}</div>
          ) : listing === null ? (
            <div className="fp-state">{t('filePicker.emptyDir')}</div>
          ) : visibleItems.length === 0 ? (
            <div className="fp-state">
              {!filteredOut
                ? t('filePicker.emptyDir')
                : needle !== ''
                  ? t('filePicker.noMatch', { query: query.trim() })
                  : t('filePicker.onlyHidden')}
            </div>
          ) : (
            visibleItems.map((entry) => {
              const on = selected?.path === entry.path;
              return (
                <button
                  key={entry.path}
                  type="button"
                  role="option"
                  aria-selected={on}
                  className={`fp-row${on ? ' fp-row--on' : ''}`}
                  data-path={entry.path}
                  title={entry.path}
                  onClick={() => {
                    if (entry.type === 'dir') go(entry.path);
                    else setSelected(entry);
                  }}
                  onDoubleClick={() => {
                    if (entry.type === 'file') onPick(entry.path);
                  }}
                >
                  <Icon name={entry.type === 'dir' ? 'folder' : 'file'} size={15} />
                  <span className="fp-row-name">{entry.name}</span>
                </button>
              );
            })
          )}

          {/* 条目被服务端截断时说清楚：搜索也只覆盖拿到的这些，找不到就进子目录 */}
          {error === null && !loading && listing?.truncated === true && (
            <div className="fp-state">
              {t('filePicker.truncated')}
            </div>
          )}
        </div>

        <footer className="fp-foot">
          <span className="fp-selected" title={selected?.path ?? ''}>
            {selected === null ? t('filePicker.noSelection') : selected.path}
          </span>
          <button
            type="button"
            className="fp-btn fp-btn--primary"
            disabled={selected === null}
            onClick={() => {
              if (selected !== null) onPick(selected.path);
            }}
          >
            {t('filePicker.select')}
          </button>
        </footer>
      </div>
    </dialog>
  );
}

/**
 * 把「打开选择器 → 等一个结果」包成一个 Promise 给 Composer 用。
 *
 * Composer 只认 `pickFile: () => Promise<ComposerAttachment | null>`，
 * 不知道弹窗长什么样、数据从哪来（见 Composer 文件头「分层原则」）。
 */
export function useFilePicker(): {
  pickFile: () => Promise<string | null>;
  /** 挂在页面任意位置即可（它自带 dialog，不需要额外的容器） */
  element: ReactNode;
} {
  const [open, setOpen] = useState(false);
  const resolveRef = useRef<((value: string | null) => void) | null>(null);

  const pickFile = useCallback(() => {
    return new Promise<string | null>((resolve) => {
      resolveRef.current = resolve;
      setOpen(true);
    });
  }, []);

  const settle = useCallback((value: string | null) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setOpen(false);
    resolve?.(value);
  }, []);

  return {
    pickFile,
    element: (
      <FilePicker
        open={open}
        onCancel={() => settle(null)}
        onPick={(path) => settle(path)}
      />
    ),
  };
}
