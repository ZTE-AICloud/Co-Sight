// SPDX-License-Identifier: Apache-2.0
/**
 * @file WorkspaceFileTree.tsx
 * @description 会话工作区的懒加载目录树（只读）。
 *
 * 数据源是 viewer 自己的 `/fs/list`，并始终带上 `root`：服务端会拒绝工作区之外的路径，
 * 所以这里不需要（也不应该）自己拼路径做越界判断。目录逐层展开、逐层请求，
 * 不预拉整棵树 —— 打开一个代码仓库时那是几百次请求。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, FileText, Folder, FolderOpen, Loader2, RefreshCw } from "lucide-react";

import { fileBrowserApi, type FsEntry } from "../../../api/file-browser-api";
import { formatBytes } from "./file-kind";

interface WorkspaceFileTreeProps {
  /** 工作区根（绝对路径） */
  root: string;
  /** 当前预览的文件路径（用于高亮） */
  selectedPath?: string;
  onOpenFile: (path: string) => void;
}

interface TreeState {
  children: Record<string, FsEntry[]>;
  loading: Record<string, boolean>;
  errors: Record<string, string>;
}

const EMPTY_TREE: TreeState = { children: {}, loading: {}, errors: {} };

function baseNameOf(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const index = normalized.lastIndexOf("/");
  return index < 0 ? normalized : normalized.slice(index + 1);
}

/**
 * 路径比较：统一 `/`；Windows 盘符路径大小写不敏感。
 * 服务端 `path.join` 在 Windows 下返回 `\`，而预览路径已归一化成 `/`。
 */
function samePath(left: string, right: string): boolean {
  const normalize = (value: string) => {
    const path = value.replace(/\\/g, "/");
    return /^[A-Za-z]:\//.test(path) ? path.toLowerCase() : path;
  };
  return normalize(left) === normalize(right);
}

export function WorkspaceFileTree({ root, selectedPath, onOpenFile }: WorkspaceFileTreeProps) {
  const { t } = useTranslation();
  const [tree, setTree] = useState<TreeState>(EMPTY_TREE);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [reloadToken, setReloadToken] = useState(0);
  /** 防止切换工作区后旧请求把结果写回新树 */
  const rootRef = useRef(root);
  rootRef.current = root;

  const load = useCallback(async (path: string) => {
    const loadingRoot = rootRef.current;
    setTree((prev) => ({
      ...prev,
      loading: { ...prev.loading, [path]: true },
      errors: { ...prev.errors, [path]: "" },
    }));
    try {
      const listing = await fileBrowserApi.list(path, loadingRoot);
      if (rootRef.current !== loadingRoot) return;
      setTree((prev) => ({
        ...prev,
        children: { ...prev.children, [path]: listing.items },
        loading: { ...prev.loading, [path]: false },
      }));
    } catch (error) {
      if (rootRef.current !== loadingRoot) return;
      setTree((prev) => ({
        ...prev,
        loading: { ...prev.loading, [path]: false },
        errors: {
          ...prev.errors,
          [path]: error instanceof Error ? error.message : String(error),
        },
      }));
    }
  }, []);

  // 换工作区 / 手动刷新：整棵树重新来
  useEffect(() => {
    setTree(EMPTY_TREE);
    setExpanded(new Set([root]));
    void load(root);
  }, [root, reloadToken, load]);

  function toggle(path: string): void {
    const next = new Set(expanded);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
      if (tree.children[path] === undefined && tree.loading[path] !== true) void load(path);
    }
    setExpanded(next);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1.5 border-b border-border/50 px-2 py-1.5">
        <Folder className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
        <span
          className="min-w-0 flex-1 truncate text-[11px] text-muted"
          title={root}
        >
          {baseNameOf(root)}
        </span>
        <button
          type="button"
          onClick={() => setReloadToken((current) => current + 1)}
          aria-label={t("run.fileRefresh")}
          title={t("run.fileRefresh")}
          className="flex-shrink-0 rounded p-1 text-muted transition-colors hover:bg-surface-4 hover:text-primary"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        <TreeLevel
          path={root}
          depth={0}
          tree={tree}
          expanded={expanded}
          selectedPath={selectedPath}
          onToggle={toggle}
          onOpenFile={onOpenFile}
        />
      </div>
    </div>
  );
}

interface TreeLevelProps {
  path: string;
  depth: number;
  tree: TreeState;
  expanded: ReadonlySet<string>;
  selectedPath?: string;
  onToggle: (path: string) => void;
  onOpenFile: (path: string) => void;
}

/** 一个目录的下一层。根目录没有自身的行，直接从 depth 0 的子项开始。 */
function TreeLevel({
  path,
  depth,
  tree,
  expanded,
  selectedPath,
  onToggle,
  onOpenFile,
}: TreeLevelProps) {
  const { t } = useTranslation();
  const loading = tree.loading[path] === true;
  const error = tree.errors[path] ?? "";

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted" style={{ paddingLeft: 12 + depth * 14 }}>
        <Loader2 className="h-3 w-3 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }
  if (error !== "") {
    return (
      <div className="px-3 py-1.5 text-xs text-red-400" style={{ paddingLeft: 12 + depth * 14 }}>
        {error}
      </div>
    );
  }

  const items = tree.children[path];
  if (items === undefined) return null;
  if (items.length === 0) {
    return (
      <p className="px-3 py-1.5 text-xs text-muted" style={{ paddingLeft: 12 + depth * 14 }}>
        {t("run.filesEmptyDir")}
      </p>
    );
  }

  return (
    <ul className="min-w-0">
      {items.map((entry) => {
        const isDir = entry.type === "dir";
        const isOpen = expanded.has(entry.path);
        const isSelected =
          !isDir && selectedPath !== undefined && samePath(entry.path, selectedPath);

        return (
          <li key={entry.path} className="min-w-0">
            <button
              type="button"
              onClick={() => (isDir ? onToggle(entry.path) : onOpenFile(entry.path))}
              className={`flex w-full min-w-0 items-center gap-1.5 py-1 pr-2 text-left text-xs transition-colors hover:bg-surface-3 ${
                isSelected ? "bg-accent/10 text-primary" : "text-secondary"
              }`}
              style={{ paddingLeft: 8 + depth * 14 }}
              title={entry.path}
            >
              {isDir ? (
                <ChevronRight
                  className={`h-3 w-3 flex-shrink-0 text-muted transition-transform ${
                    isOpen ? "rotate-90" : ""
                  }`}
                />
              ) : (
                <span className="w-3 flex-shrink-0" />
              )}
              {isDir ? (
                isOpen ? (
                  <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
                ) : (
                  <Folder className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
                )
              ) : (
                <FileText className="h-3.5 w-3.5 flex-shrink-0 text-muted" />
              )}
              <span className="min-w-0 flex-1 truncate">{entry.name}</span>
              {!isDir && (
                <span className="flex-shrink-0 text-[10px] text-faint">
                  {formatBytes(entry.size)}
                </span>
              )}
            </button>

            {isDir && isOpen && (
              <TreeLevel
                path={entry.path}
                depth={depth + 1}
                tree={tree}
                expanded={expanded}
                selectedPath={selectedPath}
                onToggle={onToggle}
                onOpenFile={onOpenFile}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
