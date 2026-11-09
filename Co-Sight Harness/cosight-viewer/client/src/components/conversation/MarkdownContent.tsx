// SPDX-License-Identifier: Apache-2.0
/**
 * @file MarkdownContent.tsx
 * @description Lightweight markdown renderer for conversation messages. Supports the
 * subset of CommonMark + GFM that actually appears in Claude Code transcripts:
 * fenced code blocks, ATX headings, ordered/unordered lists, task lists, blockquotes,
 * horizontal rules, simple tables, inline code, bold, italic, strikethrough, links,
 * and auto-linked URLs.
 *
 * Output is built as a React element tree (no dangerouslySetInnerHTML) so user content
 * is escaped by React. Code blocks delegate to <CodeBlock /> for syntax highlighting and
 * copy-to-clipboard.
 *
 */

import React from "react";
import { FileText } from "lucide-react";
import { CodeBlock } from "./CodeBlock";

/**
 * 行内文件引用：哪个词是文件、点了之后打开哪个路径。
 *
 * 仅在会话页（`/chat`）由 `ChatConversation` 传入；观测页等其它调用方不传，
 * 行为与之前完全一致。
 */
export interface FileMentions {
  /** 返回产物集合里的绝对路径；`undefined` = 保持纯文本 */
  resolve(value: string): string | undefined;
  /**
   * 相对路径 → **已校验存在**的真实绝对路径。
   *
   * 调用方（会话页）会先按候选基准问服务端"哪个根下真的存在这个文件"；
   * `undefined` = 还没校验完 / 不存在，调用方保持纯文本，不制造死链。
   */
  resolvePath?(value: string): string | undefined;
  /** 打开文件（右侧面板） */
  open(path: string): void;
}

/**
 * 显式写出的绝对文件路径：盘符路径、POSIX 绝对路径、`~/`，且**末段带扩展名**。
 *
 * 纯文本里只认这种形态。裸文件名（`hate.txt`）不认——误报噪音太大；
 * 只有命中产物集合时才会变成链接（见 `FileMentions.resolve`）。
 *
 * 这里**不限制文件类型**：PPTX / PDF / 压缩包等也可以点开，右侧面板会给出
 * “暂不支持预览 + 下载”的出口；能不能内联预览由 `FilePreview` 决定。
 */
export function looksLikeAbsoluteFilePath(value: string): boolean {
  const text = value.trim().replace(/^file:\/\//i, "");
  if (!/^(?:[A-Za-z]:[\\/]|\/|~\/)/.test(text)) return false;
  const last = text.split(/[\\/]/).pop() ?? "";
  return last.length > 1 && last.includes(".") && !last.endsWith(".");
}

/**
 * 相对文件路径（`output/agents/<name>/v1/a.png`、`./a.png`）。
 *
 * 只有“有明确边界”的位置才敢用（行内代码 / 显式链接）：相对路径没有盘符或前导 `/`，
 * 在纯文本里和普通词组无法区分。必须带目录分隔符、末段带扩展名，且不能是 URL 或
 * 带 scheme 的地址。
 */
function looksLikeRelativeFilePath(value: string): boolean {
  const text = value.trim();
  if (text === "" || /\s/.test(text)) return false;
  if (/^(?:[A-Za-z][A-Za-z0-9+.-]*:|\/|~\/|[A-Za-z]:[\\/])/.test(text)) return false;
  if (!text.includes("/") && !text.includes("\\")) return false;
  const last = text.split(/[\\/]/).pop() ?? "";
  return last.length > 1 && last.includes(".") && !last.endsWith(".");
}

/** 去掉路径末尾的标点 / 引号 / 括号，避免把句号也当成路径的一部分。 */
function trimTrailingPunctuation(value: string): string {
  return value.replace(/[\s。，；：、！？）》」』】”’"',.;:!?)\]}]+$/u, "");
}

/**
 * 中文标点几乎不可能出现在文件名里，出现在路径之后就是正文起点。
 * 带空格的路径（`/home/u/my docs/a.pptx，请查收`）靠它截断，否则会把
 * “请查收”也吞进路径。
 */
const CJK_PUNCTUATION_RE = /[，。；：、！？）》」』】]/u;

/**
 * 纯文本里额外要求扩展名至少含一个字母：`/home/u/a b.pdf v2.0` 的尾词
 * `v2.0` 扩展名是纯数字 `0`，不算文件；从右往左收缩到 `a b.pdf` 才停。
 *
 * 只用于**没有边界**的纯文本；行内代码 / 链接 / 代码块里的路径有明确边界，
 * 仍按 `looksLikeAbsoluteFilePath` 判断（`/tmp/out.1` 之类也允许打开）。
 */
function hasWordLikeExtension(value: string): boolean {
  const last = value.split(/[\\/]/).pop() ?? "";
  const dot = last.lastIndexOf(".");
  const extension = dot <= 0 ? last.slice(1) : last.slice(dot + 1);
  return extension !== "" && /[A-Za-z]/.test(extension);
}

function looksLikePlainTextFilePath(value: string): boolean {
  return looksLikeAbsoluteFilePath(value) && hasWordLikeExtension(value);
}

/**
 * 从当前位置起尝试识别一条纯文本绝对路径。
 *
 * 路径本身可能带空格，也可能后面还跟着正文：
 * - 先拿整行（去掉句末标点）试；
 * - 不成立再从右往左按空白收缩，找到第一个仍然像文件路径的片段。
 */
function matchPlainFilePath(text: string): string | null {
  if (!/^(?:[A-Za-z]:[\\/]|\/|~\/)/.test(text)) return null;

  const lineEnd = text.search(/[\r\n]/);
  const line = lineEnd < 0 ? text : text.slice(0, lineEnd);
  const breakIndex = line.search(CJK_PUNCTUATION_RE);
  let candidate = trimTrailingPunctuation(breakIndex < 0 ? line : line.slice(0, breakIndex));
  if (candidate.length < 4) return null;
  if (looksLikePlainTextFilePath(candidate)) return candidate;

  let end = candidate.length;
  while (end > 0) {
    const cut = candidate.lastIndexOf(" ", end - 1);
    if (cut <= 0) break;
    end = cut;
    candidate = trimTrailingPunctuation(candidate.slice(0, end));
    if (candidate.length < 4) break;
    if (looksLikePlainTextFilePath(candidate)) return candidate;
  }
  return null;
}

/**
 * 纯文本里的裸文件名：带扩展名、且唯一命中本次产物集合时才链接。
 *
 * 与行内代码的规则一致（精确 / 后缀 / 唯一 basename），但更保守：
 * - 必须出现在词边界上（前后不能是字母、数字、下划线、路径分隔符、`@`）；
 * - 必须带扩展名；
 * - 必须命中产物集合（类型不限，面板决定预览或下载）；
 * - 同名歧义、没写过的名字不链接。
 */
const BARE_FILENAME_RE = /^[A-Za-z0-9_\-一-龥]+(?:\.[A-Za-z0-9]{1,10})+/;

function matchBareFilenameAt(
  rest: string,
  before: string,
  mentions: FileMentions
): { raw: string; target: string } | null {
  if (before !== "" && /[A-Za-z0-9_\-.\\/一-龥@]/.test(before)) return null;

  const match = BARE_FILENAME_RE.exec(rest);
  if (match === null) return null;
  const raw = match[0]!;
  if (raw.endsWith(".")) return null;

  const target = mentions.resolve(raw);
  return target === undefined ? null : { raw, target };
}

/**
 * 整个 fenced code block 只有一行、且这行是绝对文件路径时，视为“文件位置”
 * 而不是代码示例（例如助手在代码块里单独给出 `C:\...\x.pptx`）。
 *
 * 只放行无语言 / 纯文本语言标签：带 `bash` / `json` 等标签的代码块仍按代码渲染。
 */
const PATH_ONLY_LANGS = new Set(["", "text", "plaintext", "plain", "path"]);

function matchPathOnlyCodeBlock(
  block: { lang: string; code: string },
  mentions: FileMentions
): string | null {
  if (!PATH_ONLY_LANGS.has(block.lang.toLowerCase())) return null;
  const value = block.code.trim();
  if (value === "" || /[\r\n]/.test(value)) return null;
  if (!looksLikeAbsoluteFilePath(value)) return null;
  return mentions.resolve(value) ?? value;
}

/** 文件引用按钮：文件图标 + 路径；点击打开右侧抽屉。 */
function FileMentionButton({
  label,
  target,
  onOpen,
}: {
  label: React.ReactNode;
  target: string;
  onOpen: (path: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(target)}
      title={target}
      className="inline-flex max-w-full items-start gap-1 rounded border border-surface-3 bg-surface-4 px-1.5 py-0.5 align-baseline font-mono text-[12.5px] text-left text-secondary transition-colors hover:border-blue-400/50 hover:text-primary"
    >
      <FileText className="mt-0.5 h-3 w-3 flex-shrink-0 text-muted" />
      <span className="break-all">{label}</span>
    </button>
  );
}

type Block =
  | { kind: "code"; lang: string; code: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "hr" }
  | {
      kind: "table";
      header: string[];
      aligns: ("left" | "center" | "right" | null)[];
      rows: string[][];
    }
  | { kind: "para"; text: string };

const FENCE_RE = /^([ \t]*)(```|~~~)(\s*[\w+-]*)\s*$/;
const HEADING_RE = /^(#{1,6})\s+(.+?)\s*#*\s*$/;
const HR_RE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const UL_RE = /^(\s*)([-*+])\s+(.*)$/;
const OL_RE = /^(\s*)(\d+)\.\s+(.*)$/;
const QUOTE_RE = /^\s*>\s?(.*)$/;
const TABLE_DIVIDER_RE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/;

/** 单词字符：用于判断 `_` / `__` 是否处在单词内部（intraword emphasis）。 */
const WORD_CHAR_RE = /[A-Za-z0-9_一-龥]/;

function splitTableRow(line: string): string[] {
  // Trim leading/trailing pipes, then split, respecting escaped pipes.
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  // Split on unescaped pipes
  const parts: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
      continue;
    }
    if (s[i] === "|") {
      parts.push(cur.trim());
      cur = "";
    } else {
      cur += s[i];
    }
  }
  parts.push(cur.trim());
  return parts;
}

function parseAlignments(divider: string): ("left" | "center" | "right" | null)[] {
  return splitTableRow(divider).map((cell) => {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    if (left) return "left";
    return null;
  });
}

function parseBlocks(src: string): Block[] {
  const lines = src.split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;

    // Fenced code block
    const fence = line.match(FENCE_RE);
    if (fence) {
      const fenceMarker = fence[2]!;
      const lang = (fence[3] ?? "").trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length) {
        const closing = lines[i]!.match(/^([ \t]*)(```|~~~)\s*$/);
        if (closing && closing[2] === fenceMarker) {
          i++;
          break;
        }
        codeLines.push(lines[i]!);
        i++;
      }
      blocks.push({ kind: "code", lang, code: codeLines.join("\n") });
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // ATX heading
    const heading = line.match(HEADING_RE);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
      i++;
      continue;
    }

    // Horizontal rule
    if (HR_RE.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }

    // Table: header line followed by an alignment divider
    if (line.includes("|") && i + 1 < lines.length && TABLE_DIVIDER_RE.test(lines[i + 1]!)) {
      const header = splitTableRow(line);
      const aligns = parseAlignments(lines[i + 1]!);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.includes("|") && lines[i]!.trim() !== "") {
        rows.push(splitTableRow(lines[i]!));
        i++;
      }
      blocks.push({ kind: "table", header, aligns, rows });
      continue;
    }

    // Lists
    const ulMatch = line.match(UL_RE);
    const olMatch = line.match(OL_RE);
    if (ulMatch || olMatch) {
      const ordered = !!olMatch;
      const itemRe = ordered ? OL_RE : UL_RE;
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i]!.match(itemRe);
        if (m) {
          items.push(m[3]!);
          i++;
          while (
            i < lines.length &&
            lines[i]!.trim() !== "" &&
            !lines[i]!.match(UL_RE) &&
            !lines[i]!.match(OL_RE) &&
            /^\s+\S/.test(lines[i]!)
          ) {
            items[items.length - 1] += "\n" + lines[i]!.trim();
            i++;
          }
        } else {
          break;
        }
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    // Blockquote
    if (QUOTE_RE.test(line)) {
      const qLines: string[] = [];
      while (i < lines.length) {
        const m = lines[i]!.match(QUOTE_RE);
        if (!m) break;
        qLines.push(m[1]!);
        i++;
      }
      blocks.push({ kind: "quote", text: qLines.join("\n") });
      continue;
    }

    // Paragraph: collect until a blank line or the start of another block
    const paraLines: string[] = [line];
    i++;
    while (i < lines.length) {
      const nl = lines[i]!;
      if (
        nl.trim() === "" ||
        FENCE_RE.test(nl) ||
        HEADING_RE.test(nl) ||
        HR_RE.test(nl) ||
        UL_RE.test(nl) ||
        OL_RE.test(nl) ||
        QUOTE_RE.test(nl)
      ) {
        break;
      }
      paraLines.push(nl);
      i++;
    }
    blocks.push({ kind: "para", text: paraLines.join("\n") });
  }
  return blocks;
}

/** Render inline markdown (bold/italic/code/strikethrough/links/auto-links). */
function renderInline(
  text: string,
  baseKey = "",
  mentions?: FileMentions
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let i = 0;
  let buf = "";
  let n = 0;
  const flush = () => {
    if (buf) {
      out.push(buf);
      buf = "";
    }
  };
  const push = (node: React.ReactNode) => {
    flush();
    out.push(<React.Fragment key={`${baseKey}-${n++}`}>{node}</React.Fragment>);
  };

  while (i < text.length) {
    const rest = text.slice(i);

    // Inline code: `...`
    const codeM = rest.match(/^`([^`\n]+)`/);
    if (codeM) {
      const code = codeM[1]!;
      /*
       * 这里**不做相对路径补全**：行内代码经常是普通标识符（`src/api/client.ts`），
       * 补全后会把它们都变成注定打不开的按钮。相对路径的入口放在显式链接上 ——
       * 那是用户/助手明确表达的“文件引用”。
       */
      const target =
        mentions?.resolve(code) ??
        (mentions !== undefined && looksLikeAbsoluteFilePath(code) ? code : undefined) ??
        /*
         * 行内代码里的相对路径：只有在 `useResolvedLinks` 里登记过、且服务端
         * 校验存在的候选才会命中（调用方只登记“与本次产物同名”的路径）。
         * 普通代码引用（`src/api/client.ts`）不会被登记，仍然保持纯文本。
         */
        (mentions !== undefined && looksLikeRelativeFilePath(code)
          ? mentions.resolvePath?.(code)
          : undefined);
      if (target !== undefined) {
        push(<FileMentionButton label={code} target={target} onOpen={mentions!.open} />);
      } else {
        push(
          <code className="rounded bg-surface-4 border border-surface-3 px-1.5 py-0.5 font-mono text-[12.5px] text-secondary">
            {code}
          </code>
        );
      }
      i += codeM[0].length;
      continue;
    }

    // Bold: **...** or __...__
    const boldM = rest.match(/^(\*\*|__)(.+?)\1/);
    if (boldM) {
      const marker = boldM[1]!;
      const before = i === 0 ? "" : text[i - 1]!;
      const after = rest[boldM[0].length] ?? "";
      // CommonMark：`__` 出现在单词内部时不是强调，例如 foo__bar__
      const intrawordStrong =
        marker === "__" && (WORD_CHAR_RE.test(before) || WORD_CHAR_RE.test(after));

      if (!intrawordStrong) {
        push(
          <strong className="font-semibold text-primary">
            {renderInline(boldM[2]!, `${baseKey}-b${n}`, mentions)}
          </strong>
        );
        i += boldM[0].length;
        continue;
      }
    }

    // Italic: *...* or _..._
    const italicM = rest.match(/^(\*|_)([^*_\n]+?)\1/);
    if (italicM) {
      /*
       * CommonMark 不把**单词内部**的下划线当强调：
       * `uart_pattern_examples.c` 里的 `_pattern_` 是文件名的一部分。
       * 只有 `_` 两侧不在单词内部、且内容首尾不是空白时才按斜体处理。
       * `*` 保持原行为。
       */
      const marker = italicM[1]!;
      const inner = italicM[2]!;
      const before = i === 0 ? "" : text[i - 1]!;
      const after = rest[italicM[0].length] ?? "";
      const intrawordUnderscore =
        marker === "_" &&
        (WORD_CHAR_RE.test(before) || WORD_CHAR_RE.test(after) || /^\s|\s$/.test(inner));

      if (!intrawordUnderscore) {
        push(
          <em className="italic text-secondary">
            {renderInline(inner, `${baseKey}-i${n}`, mentions)}
          </em>
        );
        i += italicM[0].length;
        continue;
      }
    }

    // Strikethrough
    const strikeM = rest.match(/^~~(.+?)~~/);
    if (strikeM) {
      push(
        <span className="line-through text-muted">
          {renderInline(strikeM[1]!, `${baseKey}-s${n}`, mentions)}
        </span>
      );
      i += strikeM[0].length;
      continue;
    }

    // Markdown link
    const linkM = rest.match(/^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/);
    if (linkM) {
      const href = linkM[2]!;
      const external = /^(https?:|mailto:|#)/i.test(href);
      /*
       * 会话页：本地链接只在命中本次产物集合时才可点。不命中时**不渲染 `<a>`** ——
       * 相对地址会被 SPA 路由当成站内导航，点一下页面就被兜底路由送走。
       */
      if (mentions !== undefined && !external) {
        // 相对地址（`output/agents/<name>/v1/a.png`）：由 resolvePath 返回**已校验存在**的
        // 绝对路径。图片常由脚本生成，不在 Write/Edit 产物集合里，只靠 resolve 点不开；
        // 而基准目录不一定是会话 cwd，所以必须先让服务端按候选根试出来。
        const directTarget =
          mentions.resolve(href) ??
          (looksLikeAbsoluteFilePath(href) ? href : undefined) ??
          (looksLikeRelativeFilePath(href) ? mentions.resolvePath?.(href) : undefined);
        // 链接文字里不再递归文件引用：按钮里不能再嵌按钮
        const label = renderInline(linkM[1]!, `${baseKey}-l${n}`);
        push(
          directTarget !== undefined ? (
            <FileMentionButton label={label} target={directTarget} onOpen={mentions.open} />
          ) : (
            <span className="font-mono text-[12.5px] text-secondary">{label}</span>
          )
        );
      } else {
        push(
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-500 underline underline-offset-2 decoration-blue-400/40 hover:decoration-blue-400/70"
          >
            {renderInline(linkM[1]!, `${baseKey}-l${n}`)}
          </a>
        );
      }
      i += linkM[0].length;
      continue;
    }

    // Auto-link
    const urlM = rest.match(/^https?:\/\/[^\s<>()]+[^\s<>().,!?;:'"]/);
    if (urlM) {
      push(
        <a
          href={urlM[0]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:text-blue-500 underline underline-offset-2 decoration-blue-400/40 hover:decoration-blue-400/70 break-all"
        >
          {urlM[0]}
        </a>
      );
      i += urlM[0].length;
      continue;
    }

    // 纯文本里的显式绝对路径（例如「文件位置： F:\...\AI助手能力介绍.pptx」）
    if (mentions !== undefined) {
      const before = i === 0 ? "" : text[i - 1]!;
      const atBoundary = before === "" || /[\s(（[【\]"'`：:,，、>]/.test(before);
      if (atBoundary) {
        const plainPath = matchPlainFilePath(rest);
        if (plainPath !== null) {
          push(
            <FileMentionButton label={plainPath} target={plainPath} onOpen={mentions.open} />
          );
          i += plainPath.length;
          continue;
        }
      }
    }

    // 纯文本里的裸文件名：唯一命中产物集合才链接（类型不限）
    if (mentions !== undefined) {
      const before = i === 0 ? "" : text[i - 1]!;
      const bare = matchBareFilenameAt(rest, before, mentions);
      if (bare !== null) {
        push(
          <FileMentionButton label={bare.raw} target={bare.target} onOpen={mentions.open} />
        );
        i += bare.raw.length;
        continue;
      }
    }

    buf += text[i]!;
    i++;
  }
  flush();
  return out;
}

/** Render a single list item, handling [ ] / [x] task list prefixes. */
function renderListItem(
  item: string,
  key: string,
  mentions?: FileMentions
): React.ReactNode {
  const taskMatch = item.match(/^\[([ xX])\]\s+(.*)$/s);
  if (taskMatch) {
    const checked = taskMatch[1]!.toLowerCase() === "x";
    return (
      <span className="inline-flex items-baseline gap-2">
        <span
          className={`inline-block w-3 h-3 rounded-sm border flex-shrink-0 translate-y-0.5 ${
            checked ? "bg-emerald-500/40 border-emerald-400/60" : "bg-surface-4 border-surface-3"
          }`}
          aria-hidden="true"
        />
        <span className={checked ? "text-muted line-through" : ""}>
          {renderInline(taskMatch[2]!, key, mentions)}
        </span>
      </span>
    );
  }
  return renderInline(item, key, mentions);
}

interface MarkdownContentProps {
  text: string;
  /** Tighter spacing for nested contexts (list items, quotes). */
  dense?: boolean;
  /** 行内文件引用；不传时行为与之前完全一致 */
  fileMentions?: FileMentions;
}

const HEADING_STYLES = [
  "text-[18px] font-semibold text-primary mt-2 pb-1 border-b border-surface-3",
  "text-[16px] font-semibold text-primary mt-2",
  "text-[15px] font-semibold text-primary",
  "text-sm font-semibold text-primary",
  "text-sm font-medium text-secondary",
  "text-xs font-medium text-muted uppercase tracking-wider",
];

export const MarkdownContent = React.memo(function MarkdownContent({
  text,
  dense = false,
  fileMentions,
}: MarkdownContentProps) {
  const blocks = parseBlocks(text);
  const gap = dense ? "space-y-1.5" : "space-y-2.5";

  return (
    <div className={`text-sm text-tertiary leading-relaxed ${gap}`}>
      {blocks.map((b, idx) => {
        switch (b.kind) {
          case "code": {
            const codeBlockTarget =
              fileMentions === undefined ? null : matchPathOnlyCodeBlock(b, fileMentions);
            if (codeBlockTarget !== null) {
              return (
                <div key={idx}>
                  <FileMentionButton
                    label={b.code.trim()}
                    target={codeBlockTarget}
                    onOpen={fileMentions!.open}
                  />
                </div>
              );
            }
            return <CodeBlock key={idx} code={b.code} lang={b.lang} />;
          }

          case "heading": {
            const cls = HEADING_STYLES[b.level - 1] ?? HEADING_STYLES[5];
            return (
              <div key={idx} className={cls}>
                {renderInline(b.text, `h${idx}`, fileMentions)}
              </div>
            );
          }

          case "list":
            if (b.ordered) {
              return (
                <ol
                  key={idx}
                  className="list-decimal pl-5 space-y-1 marker:text-muted marker:font-mono marker:text-xs"
                >
                  {b.items.map((item, i) => (
                    <li key={i} className="text-sm text-tertiary">
                      {renderListItem(item, `li${idx}-${i}`, fileMentions)}
                    </li>
                  ))}
                </ol>
              );
            }
            return (
              <ul key={idx} className="list-disc pl-5 space-y-1 marker:text-blue-500">
                {b.items.map((item, i) => (
                  <li key={i} className="text-sm text-tertiary">
                    {renderListItem(item, `li${idx}-${i}`, fileMentions)}
                  </li>
                ))}
              </ul>
            );

          case "quote":
            return (
              <blockquote
                key={idx}
                className="relative border-l-2 border-violet-400/50 pl-3 pr-2 py-1 text-tertiary italic bg-violet-500/[0.04] rounded-r"
              >
                {renderInline(b.text, `q${idx}`, fileMentions)}
              </blockquote>
            );

          case "hr":
            return (
              <hr
                key={idx}
                className="border-0 h-px bg-gradient-to-r from-transparent via-surface-3 to-transparent my-2"
              />
            );

          case "table": {
            const alignClass = (a: "left" | "center" | "right" | null) =>
              a === "center" ? "text-center" : a === "right" ? "text-right" : "text-left";
            return (
              <div
                key={idx}
                className="overflow-x-auto rounded-md border border-surface-3 bg-surface-4/40"
              >
                <table className="w-full text-xs border-collapse">
                  <thead className="bg-surface-3/60">
                    <tr>
                      {b.header.map((cell, i) => (
                        <th
                          key={i}
                          className={`px-3 py-1.5 font-semibold text-secondary border-b border-surface-3 ${alignClass(b.aligns[i] ?? null)}`}
                        >
                          {renderInline(cell, `th${idx}-${i}`, fileMentions)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        className="border-b border-surface-3/50 last:border-b-0 hover:bg-surface-3/30"
                      >
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className={`px-3 py-1.5 text-tertiary align-top ${alignClass(b.aligns[ci] ?? null)}`}
                          >
                            {renderInline(cell, `td${idx}-${ri}-${ci}`, fileMentions)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }

          case "para":
            return (
              <p key={idx} className="text-sm text-tertiary whitespace-pre-wrap break-words">
                {renderInline(b.text, `p${idx}`, fileMentions)}
              </p>
            );
        }
      })}
    </div>
  );
});
