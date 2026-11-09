/**
 * 文件类型判定：按扩展名把一条路径分成「怎么预览」。
 *
 * 两个使用点共用这一份：
 *   - 创建页右栏的工作空间（`features/agent-create/components/FileViewer.tsx`）；
 *   - 对话文件引用的右侧预览面板（`shared/components/FilePreview/*`）。
 *
 * 判定只看扩展名，不读内容 —— 前缀对不上的（无后缀可执行文件等）由后端的
 * 二进制探测（`/fs/read` 的 415）兜底。反过来，后缀写着 `.md` 但内容是二进制时，
 * 前端会先按文本请求，后端 415 后再降级成下载，不会把乱码铺满面板。
 */

import { msg } from '../i18n/useI18n';
import type { IconName } from './components/Icon';

/**
 * `svg` 单列一类：它也是图片，但内容是 UTF-8 文本。
 *
 * 历史原因保留这个分类（FileViewer 用文本读出来再转 data URL）；
 * 新的预览面板对 svg 直接走 `/fs/raw`，与栅格图同一套。
 */
export type FileKind = 'text' | 'svg' | 'image' | 'binary';

/** 这些后缀走图片预览 */
export const IMAGE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'ico',
  'avif',
]);

/** 这些后缀不尝试当文本读，只给下载 */
export const BINARY_EXTENSIONS = new Set([
  'pdf', 'zip', 'gz', 'tgz', 'tar', 'rar', '7z', 'whl', 'jar', 'exe', 'dll', 'so', 'dylib',
  'woff', 'woff2', 'ttf', 'otf', 'eot', 'mp3', 'mp4', 'mov', 'avi', 'webm', 'wav', 'ogg',
  'xls', 'xlsx', 'doc', 'docx', 'ppt', 'pptx',
]);

/** 预览头里的语言标签；没列到的按纯文本处理 */
export const LANGUAGE_BY_EXT: Record<string, string> = {
  md: 'markdown',
  markdown: 'markdown',
  json: 'json',
  jsonc: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'toml',
  ini: 'ini',
  conf: 'config',
  env: 'env',
  ts: 'typescript',
  tsx: 'tsx',
  js: 'javascript',
  jsx: 'jsx',
  mjs: 'javascript',
  cjs: 'javascript',
  css: 'css',
  scss: 'scss',
  less: 'less',
  html: 'html',
  htm: 'html',
  xml: 'xml',
  svg: 'svg',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  fish: 'shell',
  ps1: 'powershell',
  py: 'python',
  go: 'go',
  rs: 'rust',
  java: 'java',
  kt: 'kotlin',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  graphql: 'graphql',
  gql: 'graphql',
  txt: 'text',
  log: 'text',
  lock: 'text',
};

export function extensionOf(path: string): string {
  const index = path.lastIndexOf('.');
  // 隐藏文件（.gitignore）没有后缀 —— `lastIndexOf('.') === 0` 不算扩展名
  if (index <= 0 || index === path.length - 1) return '';
  // 查询串 / 片段不该混进扩展名（预览路径本身不带，但 Markdown 链接可能带）
  return path.slice(index + 1).replace(/[?#].*$/u, '').toLowerCase();
}

export function classify(path: string): FileKind {
  const ext = extensionOf(path);
  if (ext === 'svg') return 'svg';
  if (IMAGE_EXTENSIONS.has(ext)) return 'image';
  if (BINARY_EXTENSIONS.has(ext)) return 'binary';
  return 'text';
}

export function isMarkdown(path: string): boolean {
  const ext = extensionOf(path);
  return ext === 'md' || ext === 'markdown';
}

export function isHtml(path: string): boolean {
  const ext = extensionOf(path);
  return ext === 'html' || ext === 'htm';
}

export function isSvg(path: string): boolean {
  return extensionOf(path) === 'svg';
}

export function isImage(path: string): boolean {
  return classify(path) === 'image';
}

export function isBinary(path: string): boolean {
  return classify(path) === 'binary';
}

/** 需要（也允许）按文本读入内存的类型：md / html / 代码 / 配置 / svg */
export function isTextual(path: string): boolean {
  const kind = classify(path);
  return kind === 'text' || kind === 'svg';
}

export function labelOf(path: string): string {
  const kind = classify(path);
  if (kind === 'svg') return 'svg';
  if (kind === 'image') return msg('fileViewer.kindImage');
  if (kind === 'binary') return msg('fileViewer.kindBinary');
  return LANGUAGE_BY_EXT[extensionOf(path)] ?? 'text';
}

/** .md 用普通文件图标，常见代码/配置后缀用 fileCode，其余按普通文件。 */
export function fileIcon(path: string): IconName {
  if (/\.(json|jsonc|ya?ml|toml|ini|ts|tsx|js|jsx|mjs|cjs|sh|bash|py|go|rs|java|css|scss|html?)$/i.test(path)) {
    return 'fileCode';
  }
  return 'file';
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${String(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
