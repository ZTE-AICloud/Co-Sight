// SPDX-License-Identifier: Apache-2.0
/**
 * @file FilePickerDialog.tsx
 * @description 发送框「添加文件 → 本地文件」的自研选择器。
 *
 * 端侧单机形态，**没有上传**：选中的文件就是一个真实绝对路径，随消息交给
 * 会话服务，引擎用 Read 工具自己读。路径来自 viewer 自己的 server
 * （`server/routes/fs.js`），不依赖 smart-factory。
 *
 * 交互：
 * - 左侧是常用目录 / 盘符；右侧列当前目录，单击目录进入、单击文件切换选中；
 * - 双击文件直接确认；
 * - 支持多选（受 `max` 限制）、当前目录内搜索、隐藏文件开关；
 * - Esc / 点遮罩 = 取消。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  Download,
  FileText,
  Folder,
  HardDrive,
  Home,
  Loader2,
  Monitor,
  Search,
  X,
} from "lucide-react";
import { fileBrowserApi, FsApiError } from "../../api/file-browser-api";
import type { FsEntry, FsListing, FsRoot } from "../../api/file-browser-api";

export interface PickedFile {
  /** 绝对路径 */
  path: string;
  /** basename */
  name: string;
}

export interface FilePickerDialogProps {
  open: boolean;
  /** 还能再选多少个 */
  max: number;
  onCancel: () => void;
  onConfirm: (files: PickedFile[]) => void;
}

function describeError(error: unknown, fallback: string): string {
  if (error instanceof FsApiError) return error.message;
  return error instanceof Error ? error.message : fallback;
}

/** 当前目录是否落在某个根下（Windows / POSIX 分隔符都认）。 */
function isInside(child: string, parent: string): boolean {
  if (child === parent) return true;
  const normalized =
    parent.endsWith("\\") || parent.endsWith("/")
      ? parent
      : `${parent}${parent.includes("\\") ? "\\" : "/"}`;
  return child.toLowerCase().startsWith(normalized.toLowerCase());
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function RootIcon({ kind }: { kind: string }) {
  if (kind === "desktop") return <Monitor className="h-4 w-4 flex-shrink-0" />;
  if (kind === "downloads") return <Download className="h-4 w-4 flex-shrink-0" />;
  if (kind === "drive" || kind === "mount" || kind === "root") {
    return <HardDrive className="h-4 w-4 flex-shrink-0" />;
  }
  return <Home className="h-4 w-4 flex-shrink-0" />;
}

export function FilePickerDialog({ open, max, onCancel, onConfirm }: FilePickerDialogProps) {
  // 每次打开都重新挂载：目录缓存与选中项归零，不把上一次的状态带进来。
  if (!open) return null;
  return <DialogBody max={max} onCancel={onCancel} onConfirm={onConfirm} />;
}

function DialogBody({ max, onCancel, onConfirm }: Omit<FilePickerDialogProps, "open">) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  /** 进过的目录不再重复请求：来回点「上一级」时不该每次都等一下。 */
  const cache = useRef(new Map<string, FsListing>());
  /** 连续快速点击时只认最后一次请求的结果。 */
  const requestSeq = useRef(0);
  /** 最近一次请求的目录：失败时 listing 还停在上一个目录，重试要回到真正失败的那个。 */
  const lastRequested = useRef<string | null>(null);

  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [listing, setListing] = useState<FsListing | null>(null);
  const [selected, setSelected] = useState<FsEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [limitHit, setLimitHit] = useState(false);
  /** 根列表加载失败后的重试计数（目录失败走 openDir 重试）。 */
  const [rootsReload, setRootsReload] = useState(0);

  const openDir = useCallback(
    async (target: string) => {
      lastRequested.current = target;
      const cached = cache.current.get(target);
      if (cached !== undefined) {
        setListing(cached);
        setError(null);
        setLoading(false);
        return;
      }

      const seq = (requestSeq.current += 1);
      setLoading(true);
      setError(null);
      try {
        const result = await fileBrowserApi.list(target);
        if (requestSeq.current !== seq) return;
        cache.current.set(result.path, result);
        setListing(result);
      } catch (cause) {
        if (requestSeq.current !== seq) return;
        setError(describeError(cause, t("filePicker.loadFailed")));
      } finally {
        if (requestSeq.current === seq) setLoading(false);
      }
    },
    [t],
  );

  // 打开时先读根，再进第一个根。
  useEffect(() => {
    let alive = true;
    void fileBrowserApi
      .roots()
      .then(({ items }) => {
        if (!alive) return;
        setRoots(items);
        const start = items[0]?.path;
        if (start !== undefined) {
          void openDir(start);
          return;
        }
        setLoading(false);
        setError(t("filePicker.noRoots"));
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        setLoading(false);
        setError(describeError(cause, t("filePicker.loadFailed")));
      });
    return () => {
      alive = false;
    };
  }, [openDir, t, rootsReload]);

  /** 失败重试：目录加载失败就重进失败的那个目录；根列表都没拿到就重拉根。 */
  function retry() {
    if (roots.length === 0) {
      setError(null);
      setLoading(true);
      setRootsReload((value) => value + 1);
      return;
    }
    const target = lastRequested.current ?? listing?.path;
    if (target !== undefined && target !== null) {
      cache.current.delete(target);
      void openDir(target);
    }
  }

  // 打开后把焦点放到面板上，Esc 才会落在我们自己的监听里。
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onCancel();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [onCancel]);

  // 取「最具体」的根：桌面/下载都在主目录下，不按长度排会一直高亮主目录。
  const activeRoot = roots
    .filter((root) => listing !== null && isInside(listing.path, root.path))
    .sort((a, b) => b.path.length - a.path.length)[0];

  const needle = query.trim().toLowerCase();
  const visibleItems = (listing?.items ?? []).filter((entry) => {
    if (!showHidden && entry.name.startsWith(".")) return false;
    return needle === "" || entry.name.toLowerCase().includes(needle);
  });
  const hasItems = (listing?.items.length ?? 0) > 0;
  const filteredOut = hasItems && visibleItems.length === 0;

  function go(target: string) {
    setQuery("");
    setLimitHit(false);
    void openDir(target);
  }

  function toggleFile(entry: FsEntry) {
    if (selected.some((item) => item.path === entry.path)) {
      setSelected((current) => current.filter((item) => item.path !== entry.path));
      setLimitHit(false);
      return;
    }
    if (max <= 0 || selected.length >= max) {
      setLimitHit(true);
      return;
    }
    setLimitHit(false);
    setSelected((current) => [...current, entry]);
  }

  function confirmSelection() {
    if (selected.length === 0 || max <= 0) return;
    onConfirm(selected.map((entry) => ({ path: entry.path, name: entry.name })));
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("filePicker.title")}
        tabIndex={-1}
        className="flex h-[min(640px,calc(100vh-2rem))] w-[min(860px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-border/60 bg-surface-2 shadow-2xl outline-none"
      >
        <header className="flex flex-shrink-0 items-center gap-3 border-b border-border/60 px-4 py-3">
          <span className="text-sm font-semibold text-primary">{t("filePicker.title")}</span>
          <span className="text-xs text-muted">
            {max > 0 ? t("filePicker.maxHint", { max }) : t("filePicker.maxReached", { max: 0 })}
          </span>
          <div className="flex-1" />
          <button
            type="button"
            aria-label={t("common:close")}
            onClick={onCancel}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-4 hover:text-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          <aside className="w-52 flex-shrink-0 overflow-y-auto border-r border-border/60 p-2">
            <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-faint">
              {t("filePicker.locations")}
            </p>
            {roots.map((root) => {
              const active = root === activeRoot;
              return (
                <button
                  key={root.path}
                  type="button"
                  title={root.path}
                  onClick={() => go(root.path)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${
                    active
                      ? "bg-surface-4 text-primary"
                      : "text-secondary hover:bg-surface-4 hover:text-primary"
                  }`}
                >
                  <RootIcon kind={root.kind} />
                  <span className="min-w-0 flex-1 truncate">{root.label}</span>
                </button>
              );
            })}
          </aside>

          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
              <button
                type="button"
                aria-label={t("filePicker.up")}
                disabled={listing?.parent === null || listing === null}
                onClick={() => {
                  if (listing?.parent) go(listing.parent);
                }}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-4 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span
                className="min-w-0 flex-1 truncate text-xs text-secondary"
                title={listing?.path ?? ""}
              >
                {listing?.path ?? "…"}
              </span>
              <label
                className="flex flex-shrink-0 items-center gap-1.5 text-[11px] text-muted"
                title={t("filePicker.showHidden")}
              >
                <input
                  type="checkbox"
                  checked={showHidden}
                  onChange={(event) => {
                    setShowHidden(event.target.checked);
                    setSelected([]);
                  }}
                  className="accent-[rgb(var(--accent))]"
                />
                {t("filePicker.showHidden")}
              </label>
            </div>

            <div className="flex flex-shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
              <Search className="h-3.5 w-3.5 flex-shrink-0 text-muted" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("filePicker.search")}
                aria-label={t("filePicker.search")}
                className="w-full bg-transparent text-xs text-primary placeholder:text-muted focus:outline-none"
              />
            </div>

            {limitHit && (
              <div className="flex flex-shrink-0 items-center gap-1.5 border-b border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                {t("filePicker.maxReached", { max })}
              </div>
            )}

            <div
              role="listbox"
              aria-multiselectable="true"
              aria-label={t("filePicker.title")}
              aria-busy={loading}
              className="min-h-0 flex-1 overflow-y-auto p-1.5"
            >
              {error !== null ? (
                <div
                  className="flex items-start gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400"
                  role="alert"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <span className="min-w-0 flex-1">{error}</span>
                  <button
                    type="button"
                    onClick={retry}
                    className="flex-shrink-0 underline underline-offset-2 hover:text-red-300"
                  >
                    {t("common:retry")}
                  </button>
                </div>
              ) : loading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-xs text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("filePicker.loading")}
                </div>
              ) : visibleItems.length === 0 ? (
                <p className="px-3 py-10 text-center text-xs text-muted">
                  {!hasItems
                    ? t("filePicker.empty")
                    : filteredOut
                      ? needle !== ""
                        ? t("filePicker.noMatch")
                        : t("filePicker.hiddenOnly")
                      : t("filePicker.empty")}
                </p>
              ) : (
                visibleItems.map((entry) => {
                  const isSelected = selected.some((item) => item.path === entry.path);
                  return (
                    <button
                      key={entry.path}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      title={entry.path}
                      onClick={() => {
                        if (entry.type === "dir") go(entry.path);
                        else toggleFile(entry);
                      }}
                      onDoubleClick={() => {
                        if (entry.type === "file" && max > 0) {
                          onConfirm([{ path: entry.path, name: entry.name }]);
                        }
                      }}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${
                        isSelected
                          ? "bg-accent-muted text-primary"
                          : "text-secondary hover:bg-surface-4 hover:text-primary"
                      }`}
                    >
                      {entry.type === "dir" ? (
                        <Folder className="h-4 w-4 flex-shrink-0 text-accent" />
                      ) : (
                        <FileText className="h-4 w-4 flex-shrink-0 text-muted" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{entry.name}</span>
                      {entry.type === "file" && (
                        <span className="flex-shrink-0 text-[10px] text-faint">
                          {formatSize(entry.size)}
                        </span>
                      )}
                      {isSelected && <Check className="h-3.5 w-3.5 flex-shrink-0 text-accent" />}
                    </button>
                  );
                })
              )}

              {error === null && !loading && listing?.truncated === true && (
                <p className="px-3 py-2 text-[11px] text-muted">{t("filePicker.truncated")}</p>
              )}
            </div>
          </section>
        </div>

        <footer className="flex flex-shrink-0 items-center gap-3 border-t border-border/60 px-4 py-3">
          <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
            {selected.length === 0 ? (
              <span className="text-xs text-muted">{t("filePicker.noSelection")}</span>
            ) : (
              selected.map((entry) => (
                <span
                  key={entry.path}
                  className="flex max-w-[14rem] items-center gap-1 rounded-md bg-surface-3 px-2 py-1 text-[11px] text-secondary"
                  title={entry.path}
                >
                  <FileText className="h-3 w-3 flex-shrink-0 text-accent" />
                  <span className="truncate">{entry.name}</span>
                  <button
                    type="button"
                    aria-label={t("filePicker.remove", { name: entry.name })}
                    onClick={() => toggleFile(entry)}
                    className="flex-shrink-0 text-muted hover:text-primary"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))
            )}
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="flex-shrink-0 rounded-lg px-3 py-1.5 text-xs text-secondary transition-colors hover:bg-surface-4 hover:text-primary"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            disabled={selected.length === 0 || max <= 0}
            onClick={confirmSelection}
            className="flex-shrink-0 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("filePicker.select")}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
