// SPDX-License-Identifier: Apache-2.0
/**
 * @file FilesDrawer.tsx
 * @description 会话页右侧文件抽屉。
 *
 * 两种预览来源分开呈现，避免“会话文件看起来像工作区文件”：
 * - **工作区**：目录树以会话工作区为根（根由 `workspace-root.ts` 推导），
 *   点开文件后树与预览并排，树保持展开状态；
 * - **会话文件**：从正文引用 / 工具卡打开，只显示独立预览，不显示工作区树 ——
 *   它可能在 runtime 或产物目录里，本来就不属于当前工作区；
 * - 预览只提供「关闭」，不提供“返回工作区”：两种视图不联动，避免暗示
 *   会话文件属于工作区；
 * - 不再单独维护“本次会话产物”清单。
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";

import type { SessionFile } from "../../../pages/chat/useSessionFiles";
import { FilePreview } from "./FilePreview";
import { WorkspaceFileTree } from "./WorkspaceFileTree";

export interface FilesDrawerProps {
  /**
   * 预览来源。
   *
   * - `workspace`：从目录树点开，树与预览并排；
   * - `session`：从正文/工具卡点开，只显示预览 —— 会话文件可能在 runtime 或
   *   产物目录里，并不属于当前工作区，摆在树右侧会产生歧义。
   */
  source: "workspace" | "session";
  onClose: () => void;
  /** 会话工作区根；null = 尚未确定 */
  workspaceRoot: string | null;
  workspaceRootLoading: boolean;
  /** 当前预览的文件；null 时只显示目录树 */
  file: SessionFile | null;
  /** 工作区树里点开一个绝对路径 */
  onOpenPath: (path: string) => void;
}

export function FilesDrawer({
  source,
  onClose,
  workspaceRoot,
  workspaceRootLoading,
  file,
  onOpenPath,
}: FilesDrawerProps) {
  const { t } = useTranslation();

  /*
   * 工作区目录树：预览打开时也要保留（放在左边一栏），否则点一个文件树就消失，
   * 想再开下一个文件还得先返回，展开状态也全丢了。
   */
  const workspaceBody =
    workspaceRootLoading ? (
      <Centered>
        <Loader2 className="h-4 w-4 animate-spin text-accent" />
        <span>{t("common:loading")}</span>
      </Centered>
    ) : workspaceRoot === null ? (
      <Centered>
        <p>{t("run.filesNoWorkspace")}</p>
      </Centered>
    ) : (
      <WorkspaceFileTree
        root={workspaceRoot}
        selectedPath={file?.path}
        onOpenFile={onOpenPath}
      />
    );

  const preview = file !== null ? <FilePreview key={file.path} file={file} /> : null;
  /** 只有工作区来源才把树与预览并排；会话文件是独立预览，不伪装成工作区内容 */
  const splitWorkspace = preview !== null && source === "workspace";

  return (
    /*
     * 不写 `h-full`：空态外层只有 min-height（高度是 auto），百分比高度会退化成
     * auto，抽屉只剩内容高度，左侧分割线到一半就断了。交给 flex 的默认
     * stretch 拉伸，两种状态（空态 / 对话态）都能铺满。
     */
    <aside
      className="flex min-h-0 w-[clamp(380px,46vw,720px)] shrink-0 flex-col border-l border-border/60 bg-surface-1"
      aria-label={t("run.filesTitle")}
    >
      <header className="flex items-center gap-2 border-b border-border/60 px-3 py-2">
        {file !== null ? (
          <h2
            className="min-w-0 flex-1 truncate text-sm font-medium text-primary"
            title={file.path}
          >
            {file.name}
          </h2>
        ) : (
          <h2 className="min-w-0 flex-1 truncate text-sm font-medium text-primary">
            {t("run.filesWorkspace")}
          </h2>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label={t("common:close")}
          className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-4 hover:text-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {source === "session" && preview !== null ? (
        /* 会话文件：独立预览，不显示工作区树 */
        <div className="flex min-h-0 flex-1 flex-col">{preview}</div>
      ) : (
        /*
         * 工作区：树始终渲染在同一个位置（只是宽度变化），这样点文件时 React
         * 不会卸载它，展开状态、已加载的目录层级都保留；右侧只是多出一栏预览。
         */
        <div className="flex min-h-0 flex-1">
          <div
            className={
              splitWorkspace
                ? "flex min-h-0 w-[clamp(160px,32%,240px)] shrink-0 flex-col border-r border-border/60"
                : "flex min-h-0 min-w-0 flex-1 flex-col"
            }
          >
            {workspaceBody}
          </div>
          {preview !== null && (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">{preview}</div>
          )}
        </div>
      )}
    </aside>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted">
      {children}
    </div>
  );
}
