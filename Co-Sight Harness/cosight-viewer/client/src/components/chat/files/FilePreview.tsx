// SPDX-License-Identifier: Apache-2.0
/**
 * @file FilePreview.tsx
 * @description 会话文件面板的右侧内容区：按扩展名分流渲染。
 *
 * | 类型 | 渲染 |
 * |---|---|
 * | `.md` | `MarkdownContent`（预览）/ 源码 |
 * | `.html` | 沙箱 iframe（`srcDoc`，**不带 `allow-same-origin`**）/ 源码 |
 * | `.pdf` | 浏览器原生 `<iframe>`（`raw` 流） |
 * | 图片 | `<img>`；SVG 读文本后转 data URL |
 * | 其它文本 | `<pre>` |
 * | 二进制（PPTX/Word/压缩包等） | 提示不支持预览 + 下载 |
 *
 * 数据源：**cosight-viewer 自己的 server**（`/session-files/read`、`/session-files/raw`），
 * 按绝对路径读取；不再经过 smart-factory 的 `/fs/*` 或 `/artifacts/*`。
 */

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { BareJsonError } from "../../../api/bare-json";
import { fsApi } from "../../../api/fs-api";
import type { SessionFile } from "../../../pages/chat/useSessionFiles";
import { MarkdownContent } from "../../conversation/MarkdownContent";
import { classify, formatBytes, languageOf, type FileKind } from "./file-kind";

interface FilePreviewProps {
  file: SessionFile;
}

interface ReadState {
  loading: boolean;
  error: string | null;
  content: string | null;
  size: number | null;
  /** 404：文件不存在，下载入口也只会得到 404，直接隐藏 */
  missing: boolean;
}

const EMPTY_READ: ReadState = {
  loading: false,
  error: null,
  content: null,
  size: null,
  missing: false,
};

function isTextKind(kind: FileKind): boolean {
  return kind === "markdown" || kind === "html" || kind === "text" || kind === "svg";
}

function svgDataUrl(content: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}`;
}

export function FilePreview({ file }: FilePreviewProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<ReadState>(EMPTY_READ);
  /** md / html 的展示方式 */
  const [view, setView] = useState<"preview" | "source">("preview");
  const [reloadKey, setReloadKey] = useState(0);
  const [imageBroken, setImageBroken] = useState(false);

  const kind = classify(file.path);
  const downloadHref = fsApi.rawUrl(file.path);
  const imageSrc =
    kind === "svg" && state.content !== null
      ? svgDataUrl(state.content)
      : fsApi.rawUrl(file.path);

  // 切换文件 / 重试 / 写入完成后重读
  useEffect(() => {
    setImageBroken(false);
    setView("preview");

    if (!isTextKind(kind) || file.writing) {
      setState(EMPTY_READ);
      return;
    }

    let cancelled = false;
    setState({ loading: true, error: null, content: null, size: null, missing: false });

    const request = fsApi
      .read(file.path)
      .then((result) => ({ content: result.content, size: result.size }));

    void request.then(
      (result) => {
        if (cancelled) return;
        setState({
          loading: false,
          error: null,
          content: result.content,
          size: result.size,
          missing: false,
        });
      },
      (cause: unknown) => {
        if (cancelled) return;
        const failure = describeReadError(cause);
        setState({
          loading: false,
          error: t(failure.key, failure.params),
          content: null,
          size: null,
          missing: failure.key === "run.fileMissing",
        });
      }
    );

    return () => {
      cancelled = true;
    };
    // `t` 是稳定引用；放进依赖会让语言切换时重读一次，可以接受
  }, [file.path, file.writing, kind, reloadKey, t]);

  const formattedSize = state.size !== null ? formatBytes(state.size) : "";

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* 工具栏：路径 + 视图切换 + 操作 */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border/60 px-3 py-1.5">
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted" title={file.path}>
          {file.path}
        </span>
        {formattedSize !== "" && (
          <span className="flex-shrink-0 text-[11px] text-faint">{formattedSize}</span>
        )}
        {(kind === "markdown" || kind === "html") && state.content !== null && !file.writing && (
          <button
            type="button"
            onClick={() => setView((current) => (current === "preview" ? "source" : "preview"))}
            className="flex-shrink-0 rounded px-1.5 py-0.5 text-[11px] text-muted transition-colors hover:bg-surface-4 hover:text-primary"
          >
            {view === "preview" ? t("run.fileSource") : t("run.filePreview")}
          </button>
        )}
        {/* 文件已不存在时下载也只会 404，隐藏入口 */}
        {!state.missing && (
          <a
            href={downloadHref}
            download={file.name}
            target="_blank"
            rel="noreferrer"
            aria-label={t("run.fileDownload")}
            title={t("run.fileDownload")}
            className="flex-shrink-0 rounded p-1 text-muted transition-colors hover:bg-surface-4 hover:text-primary"
          >
            <Download className="h-3.5 w-3.5" />
          </a>
        )}
        <button
          type="button"
          onClick={() => setReloadKey((current) => current + 1)}
          aria-label={t("run.fileRefresh")}
          title={t("run.fileRefresh")}
          className="flex-shrink-0 rounded p-1 text-muted transition-colors hover:bg-surface-4 hover:text-primary"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {file.writing ? (
          <Centered>
            <Loader2 className="h-4 w-4 animate-spin text-accent" />
            <span>{t("run.fileWriting")}</span>
          </Centered>
        ) : kind === "pdf" ? (
          <iframe
            key={reloadKey}
            title={file.name}
            src={downloadHref}
            className="h-full min-h-[20rem] w-full border-0 bg-white"
          />
        ) : kind === "binary" ? (
          <Centered>
            <p>{t("run.fileBinary")}</p>
            <DownloadLink href={downloadHref} name={file.name} label={t("run.fileDownload")} />
          </Centered>
        ) : kind === "image" ? (
          imageBroken ? (
            <Centered>
              <p>{t("run.fileImageFailed")}</p>
              <DownloadLink href={downloadHref} name={file.name} label={t("run.fileDownload")} />
            </Centered>
          ) : (
            <div className="flex h-full items-center justify-center p-4">
              <img
                src={imageSrc}
                alt={file.name}
                className="max-h-full max-w-full object-contain"
                onError={() => setImageBroken(true)}
              />
            </div>
          )
        ) : state.loading ? (
          <Centered>
            <Loader2 className="h-4 w-4 animate-spin text-accent" />
            <span>{t("common:loading")}</span>
          </Centered>
        ) : state.error !== null ? (
          <Centered>
            <p className="text-red-400">{state.error}</p>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setReloadKey((current) => current + 1)}
                className="rounded px-2 py-1 text-xs text-accent hover:bg-surface-4"
              >
                {t("run.fileRetry")}
              </button>
              {!state.missing && (
                <DownloadLink href={downloadHref} name={file.name} label={t("run.fileDownload")} />
              )}
            </div>
          </Centered>
        ) : state.content !== null ? (
          kind === "markdown" && view === "preview" ? (
            <div className="px-4 py-3 text-sm">
              <MarkdownContent text={state.content} />
            </div>
          ) : kind === "html" && view === "preview" ? (
            <iframe
              title={file.name}
              srcDoc={state.content}
              sandbox="allow-scripts allow-forms allow-popups allow-downloads"
              className="h-full min-h-[20rem] w-full border-0 bg-white"
            />
          ) : kind === "svg" && view === "preview" ? (
            <div className="flex h-full items-center justify-center p-4">
              <img src={imageSrc} alt={file.name} className="max-h-full max-w-full object-contain" />
            </div>
          ) : (
            <pre className="whitespace-pre-wrap break-words p-4 font-mono text-xs leading-relaxed text-primary">
              {state.content}
            </pre>
          )
        ) : null}
      </div>

      {isTextKind(kind) && (
        <div className="border-t border-border/60 px-3 py-1 text-[11px] text-faint">
          {languageOf(file.path) || t("run.filePlainText")}
        </div>
      )}
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-[16rem] flex-col items-center justify-center gap-3 px-6 text-sm text-muted">
      {children}
    </div>
  );
}

function DownloadLink({ href, name, label }: { href: string; name: string; label: string }) {
  return (
    <a
      href={href}
      download={name}
      target="_blank"
      rel="noreferrer"
      className="rounded px-2 py-1 text-xs text-accent hover:bg-surface-4"
    >
      {label}
    </a>
  );
}

interface ReadFailure {
  key: string;
  params?: Record<string, string>;
}

function describeReadError(cause: unknown): ReadFailure {
  if (cause instanceof BareJsonError) {
    if (cause.status === 404) return { key: "run.fileMissing" };
    if (cause.status === 413) return { key: "run.fileTooLarge" };
    if (cause.status === 415) return { key: "run.fileBinary" };
    return { key: "run.fileReadFailedWithMessage", params: { message: cause.message } };
  }
  if (cause instanceof Error && cause.name === "AbortError") return { key: "run.fileReadTimeout" };
  return { key: "run.fileReadFailed" };
}
