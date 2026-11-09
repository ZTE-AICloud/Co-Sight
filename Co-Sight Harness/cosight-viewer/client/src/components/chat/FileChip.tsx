// SPDX-License-Identifier: Apache-2.0
/**
 * @file FileChip.tsx
 * @description 附件 chip：输入框里待发的文件、已发出消息里的文件共用一种长相。
 *
 * 显示只用 basename，完整路径挂 `title`；远端 / 本机路径都可能是反斜杠，
 * 所以分隔符两种都认。
 */

import { useTranslation } from "react-i18next";
import { FileText, X } from "lucide-react";

export interface FileChipFile {
  /** 展示名（local-path 模式存绝对路径） */
  name: string;
  /** 完整路径；upload 模式下可能没有 */
  path?: string;
}

export function fileNameOf(value: string): string {
  const normalized = value.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || value;
}

export interface FileChipProps {
  file: FileChipFile;
  size?: "md" | "sm";
  /** 不传 = 只读展示（已发出的消息） */
  onRemove?: () => void;
  removeDisabled?: boolean;
}

export function FileChip({ file, size = "md", onRemove, removeDisabled }: FileChipProps) {
  const { t } = useTranslation();
  const label = fileNameOf(file.path ?? file.name);

  const base = size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs";

  return (
    <span
      title={file.path ?? file.name}
      className={`flex max-w-[14rem] items-center gap-1.5 rounded-md border border-border/60 bg-surface-3 text-secondary ${base}`}
    >
      <FileText className="h-3 w-3 flex-shrink-0 text-accent" />
      <span className="min-w-0 truncate">{label}</span>
      {onRemove !== undefined && (
        <button
          type="button"
          aria-label={t("run.removeFile", { name: label })}
          disabled={removeDisabled}
          onClick={onRemove}
          className="flex-shrink-0 text-muted transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}
