// SPDX-License-Identifier: Apache-2.0
/**
 * @file file-kind.ts
 * @description 按扩展名给文件分流；预览组件据此决定“读文本 / 渲染 md / iframe / 图片 / 下载”。
 *
 * 只做扩展名判断，不嗅探内容：内容嗅探是服务端的职责（`/session-files/read`
 * 遇到二进制会 415），前端先挡一层只是为了少发一次注定失败的请求。
 */

export type FileKind = "markdown" | "html" | "pdf" | "image" | "svg" | "text" | "binary";

const IMAGE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "bmp",
  "ico",
  "avif",
  "tif",
  "tiff",
]);

const BINARY_EXTENSIONS = new Set([
  "zip",
  "7z",
  "rar",
  "tar",
  "gz",
  "bz2",
  "xz",
  "exe",
  "dll",
  "so",
  "dylib",
  "bin",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "mp3",
  "mp4",
  "wav",
  "avi",
  "mov",
  "mkv",
  "woff",
  "woff2",
  "ttf",
  "otf",
]);

export function extensionOf(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const index = name.lastIndexOf(".");
  return index <= 0 ? "" : name.slice(index + 1).toLowerCase();
}

export function classify(path: string): FileKind {
  const extension = extensionOf(path);
  if (extension === "md" || extension === "markdown" || extension === "mdx") return "markdown";
  if (extension === "html" || extension === "htm") return "html";
  if (extension === "pdf") return "pdf";
  if (extension === "svg") return "svg";
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (BINARY_EXTENSIONS.has(extension)) return "binary";
  // 没有扩展名或未知扩展名：按文本试读，读不了由 415 兜底
  return "text";
}

/** 代码块语言标签；未知扩展名给空串（`CodeBlock` 会按纯文本处理）。 */
export function languageOf(path: string): string {
  const map: Record<string, string> = {
    ts: "ts",
    tsx: "tsx",
    js: "js",
    jsx: "jsx",
    mjs: "js",
    cjs: "js",
    py: "python",
    json: "json",
    yml: "yaml",
    yaml: "yaml",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    html: "html",
    htm: "html",
    css: "css",
    scss: "css",
    less: "css",
    sql: "sql",
    md: "markdown",
    markdown: "markdown",
    mdx: "markdown",
    diff: "diff",
    patch: "diff",
    xml: "xml",
    java: "java",
    go: "go",
    rs: "rust",
    c: "c",
    h: "c",
    cpp: "cpp",
    hpp: "cpp",
    toml: "toml",
    ini: "ini",
    csv: "csv",
  };
  return map[extensionOf(path)] ?? "";
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}
