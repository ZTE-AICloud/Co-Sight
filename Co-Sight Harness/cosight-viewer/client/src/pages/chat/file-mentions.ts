// SPDX-License-Identifier: Apache-2.0
/**
 * @file file-mentions.ts
 * @description 把助手正文里的行内代码/本地链接解析成**本次对话写过的文件**。
 *
 * 逻辑对齐 smart-factory 的 `web/src/shared/file-ref.ts`：
 *
 * 1. 精确命中（归一化后完全相等）；
 * 2. 后缀命中（正文写 `output/x/SKILL.md`，工具给的是绝对路径）；
 * 3. basename 唯一命中——**只对不带目录的纯文件名生效**（正文只写 `hate.txt`）；
 * 4. 0 个或多于 1 个 → 不猜，保持纯文本。
 *
 * **不用正则判断“像不像文件名”**：只有出现在产物集合里的词才可能是链接。
 * 这样普通代码片段不会被误伤，同名文件也不会被随便指到一个。
 */

function isWindowsPath(path: string): boolean {
  return /^[A-Za-z]:\//.test(path);
}

/**
 * Markdown 链接 / 图片链接的目标：`[文字](目标)`、`![alt](目标)`。
 *
 * 与 `MarkdownContent` 的行内解析用同一条形态（可选的 `"title"` 也认）；
 * 那里是逐个位置匹配，这里是全文扫描，供"先校验存在性、再出链接"用。
 */
const MARKDOWN_LINK_RE = /\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;

/**
 * 正文里的**相对**链接目标（去重，保持出现顺序）。
 *
 * 绝对路径 / URL / 锚点不在内 —— 它们不依赖"基准目录"，渲染侧本来就按原样处理。
 * 要求带目录分隔符与扩展名，避免把 `[文档](docs)` 这类描述性链接当成文件。
 */
export function collectRelativeMarkdownLinks(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(MARKDOWN_LINK_RE)) {
    const raw = match[1] ?? "";
    if (!looksLikeRelativeLinkTarget(raw) || seen.has(raw)) continue;
    seen.add(raw);
    out.push(raw);
  }
  return out;
}

/** 行内代码：`` `...` ``（不含换行）。 */
const INLINE_CODE_RE = /`([^`\n]+)`/g;

/**
 * 正文行内代码里形似**相对路径**的候选（去重，保持出现顺序）。
 *
 * 供 `useResolvedLinks` 做存在性校验：行内代码以前刻意不做补全，因为
 * `src/api/client.ts` 这类代码引用很常见；调用方会再用产物集合的 basename
 * 过滤一次，只校验“和本次产物同名”的路径，避免把普通代码变成按钮。
 */
export function collectInlineCodePaths(texts: readonly string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const text of texts) {
    for (const match of text.matchAll(INLINE_CODE_RE)) {
      const raw = match[1] ?? "";
      if (!looksLikeRelativeLinkTarget(raw) || seen.has(raw)) continue;
      seen.add(raw);
      out.push(raw);
    }
  }
  return out;
}

/** 与 `MarkdownContent.looksLikeRelativeFilePath` 同口径（那里在渲染侧用）。 */
function looksLikeRelativeLinkTarget(value: string): boolean {
  const text = value.trim();
  if (text === "" || /\s/.test(text)) return false;
  if (/^(?:[A-Za-z][A-Za-z0-9+.-]*:|\/|#|~\/|[A-Za-z]:[\\/])/.test(text)) return false;
  if (!text.includes("/") && !text.includes("\\")) return false;
  const last = text.split(/[\\/]/).pop() ?? "";
  return last.length > 1 && last.includes(".") && !last.endsWith(".");
}

/** 可比较形式：Windows 统一小写（含 basename）；其余平台保持大小写敏感。 */
function comparable(path: string, windows: boolean): string {
  return windows ? path.toLowerCase() : path;
}

/** 去掉 `file://`、`#L24`、`#fragment`、开头的 `./`，并解一次百分号编码。 */
function normalizeValue(value: string): string {
  let text = value.trim();
  if (text === "") return "";
  try {
    text = decodeURIComponent(text);
  } catch {
    // 不是合法编码：保留原文
  }
  text = text.replace(/^file:\/\//i, "");
  text = text.replace(/#L\d+$/i, "").replace(/#.*$/s, "");
  text = text.replace(/\\/g, "/");
  text = text.replace(/^\/(?=[A-Za-z]:\/)/, "");
  text = text.replace(/^\.\//, "");
  return text;
}

function baseNameOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** 取 basename 的小写形式，用于和产物集合做“同名”过滤（大小写差异不敏感）。 */
export function comparableBaseName(value: string): string {
  return baseNameOf(normalizeValue(value)).toLowerCase();
}

/**
 * 行内代码 / 相对链接 → 产物集合里的绝对路径；返回 `undefined` 表示“保持纯文本”。
 */
export function resolveMention(
  value: string,
  produced: readonly string[]
): string | undefined {
  const target = normalizeValue(value);
  if (target === "" || produced.length === 0) return undefined;

  const windows = isWindowsPath(target) || produced.some(isWindowsPath);
  const cmpTarget = comparable(target, windows);

  const exact = produced.find((path) => comparable(path, windows) === cmpTarget);
  if (exact !== undefined) return exact;

  const bySuffix = produced.filter((path) =>
    comparable(path, windows).endsWith(`/${cmpTarget}`)
  );
  if (bySuffix.length === 1) return bySuffix[0];
  // 多个后缀命中就是歧义（`a/x.ts` 与 `b/x.ts` 都命中正文里的 `x.ts`）
  if (bySuffix.length > 1) return undefined;

  /*
   * 带目录的路径不做 basename 兜底。
   *
   * 典型场景：产物里只有 `out/A.pdf`，正文引用 `B/A.pdf`（B 是 Bash 复制出来的，
   * 不在产物集合里）。若继续按 basename 兜底，会“唯一命中” A，于是 hover/点击
   * 都指向 A。带目录的路径应当交给 exact / suffix 或调用方的 resolvePath；
   * basename 兜底只服务于正文里单独出现的 `A.pdf`。
   */
  if (target.includes("/")) return undefined;

  const name = comparable(baseNameOf(target), windows);
  const byName = produced.filter(
    (path) => comparable(baseNameOf(path), windows) === name
  );
  return byName.length === 1 ? byName[0] : undefined;
}
