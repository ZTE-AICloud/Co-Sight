// SPDX-License-Identifier: Apache-2.0
/**
 * @file ToolCallBlock.tsx
 * @description Collapsible block rendered inside an assistant message for each
 * tool_use / tool_result pair. Shows tool icon + name in the header, with the
 * paired result inline when present. Per-tool styling comes from toolStyle.ts;
 * the tool's input/output payload is delegated to <CodeBlock /> for syntax
 * highlighting.
 */
import { useState } from "react";
import { ChevronRight, AlertCircle, FileText, CheckCircle2 } from "lucide-react";
import type { TranscriptContent } from "../../lib/types";
import { CodeBlock } from "./CodeBlock";
import { styleForTool } from "./toolStyle";

interface ToolCallBlockProps {
  toolUse: TranscriptContent;
  toolResult?: TranscriptContent | null;
  /**
   * 可选：把摘要里的文件路径渲染成可点链接（会话页传入；观测页不传）。
   * 点击时 `stopPropagation()`，不触发折叠。
   */
  onOpenPath?: (path: string) => void;
}

/** Detect a likely language from a file path's extension. */
function langFromPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "ts",
    tsx: "ts",
    js: "js",
    jsx: "js",
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
    sql: "sql",
    md: "plain",
    txt: "plain",
    diff: "diff",
    patch: "diff",
  };
  return map[ext] ?? "plain";
}

/** Build a one-line summary of the tool call to show in the collapsed header. */
function buildSummary(toolUse: TranscriptContent): string | null {
  const input = toolUse.input;
  if (!input || typeof input !== "object" || "_truncated" in input) return null;
  const obj = input as Record<string, unknown>;
  if (typeof obj.file_path === "string") return obj.file_path;
  if (typeof obj.path === "string") return obj.path;
  if (typeof obj.notebook_path === "string") return obj.notebook_path;
  if (typeof obj.command === "string") return obj.command.slice(0, 200);
  if (typeof obj.pattern === "string") return obj.pattern;
  if (typeof obj.query === "string") return obj.query;
  if (typeof obj.url === "string") return obj.url;
  if (typeof obj.description === "string") return obj.description;
  return null;
}

/** Render the input pane with tool-aware formatting. */
function renderInput(toolUse: TranscriptContent) {
  const input = toolUse.input;
  if (!input) return null;

  // Truncated payload from the backend
  if (typeof input === "object" && "_truncated" in input) {
    return (
      <CodeBlock
        code={String((input as { _truncated: string })._truncated)}
        lang="plain"
        label="Input (truncated)"
      />
    );
  }

  const obj = input as Record<string, unknown>;
  const tool = (toolUse.name ?? "").toLowerCase();

  // Bash: show the command with shell highlighting
  if (tool === "bash" && typeof obj.command === "string") {
    return (
      <div className="space-y-2">
        <CodeBlock code={obj.command} lang="bash" label="Command" />
        {typeof obj.description === "string" && (
          <p className="text-xs text-muted italic px-1">{obj.description}</p>
        )}
      </div>
    );
  }

  // Write: render new content as code with the file path as the chrome label
  if (tool === "write" && typeof obj.file_path === "string" && typeof obj.content === "string") {
    return (
      <CodeBlock
        code={obj.content}
        lang={langFromPath(obj.file_path)}
        filename={obj.file_path}
        label="New file"
      />
    );
  }

  // Edit: side-by-side old/new
  if (tool === "edit" && typeof obj.file_path === "string") {
    const lang = langFromPath(obj.file_path);
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs text-tertiary">
          <FileText className="w-3.5 h-3.5 text-violet-500" />
          <span className="font-mono">{obj.file_path}</span>
          {obj.replace_all === true && (
            <span className="text-[10px] uppercase tracking-wider text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
              replace all
            </span>
          )}
        </div>
        {typeof obj.old_string === "string" && (
          <CodeBlock code={obj.old_string} lang={lang} label="Removed" tone="danger" />
        )}
        {typeof obj.new_string === "string" && (
          <CodeBlock code={obj.new_string} lang={lang} label="Added" tone="success" />
        )}
      </div>
    );
  }

  // Read: just show the path with offset/limit
  if (tool === "read" && typeof obj.file_path === "string") {
    return (
      <div className="flex items-center gap-1.5 text-xs text-faint bg-surface-4/40 border border-surface-3 rounded-md px-3 py-2">
        <FileText className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
        <span className="font-mono break-all">{obj.file_path}</span>
        {(typeof obj.offset === "number" || typeof obj.limit === "number") && (
          <span className="text-muted font-mono ml-auto flex-shrink-0">
            {typeof obj.offset === "number" ? `:${obj.offset}` : ""}
            {typeof obj.limit === "number" ? `+${obj.limit}` : ""}
          </span>
        )}
      </div>
    );
  }

  // Grep: pattern + path
  if (tool === "grep" && typeof obj.pattern === "string") {
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted font-mono uppercase tracking-wider text-[10px]">
            Pattern
          </span>
          <code className="font-mono text-cyan-700 bg-surface-4 border border-surface-3 rounded px-1.5 py-0.5">
            {obj.pattern}
          </code>
        </div>
        {typeof obj.path === "string" && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted font-mono uppercase tracking-wider text-[10px]">
              Path
            </span>
            <code className="font-mono text-faint">{obj.path}</code>
          </div>
        )}
        {typeof obj.glob === "string" && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted font-mono uppercase tracking-wider text-[10px]">
              Glob
            </span>
            <code className="font-mono text-faint">{obj.glob}</code>
          </div>
        )}
      </div>
    );
  }

  // Default: pretty JSON
  return <CodeBlock code={JSON.stringify(obj, null, 2)} lang="json" label="Input" />;
}

/** Render the result pane: detect diff/json/text. */
function renderResult(toolResult: TranscriptContent, toolName: string) {
  const text = toolResult.output ?? "";
  if (text.length === 0) return <div className="text-xs text-muted italic px-1">(empty)</div>;

  const isError = !!toolResult.is_error;
  const tool = toolName.toLowerCase();
  const label = isError ? "Error" : "Output";

  // Heuristics for language
  let lang = "plain";
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      JSON.parse(trimmed);
      lang = "json";
    } catch {
      // fall through
    }
  } else if (/^(\+\+\+|---|@@) /m.test(text) || /^diff --git /m.test(text)) {
    lang = "diff";
  } else if (tool === "bash") {
    lang = "bash";
  }

  return <CodeBlock code={text} lang={lang} label={label} tone={isError ? "danger" : "default"} />;
}

/** 摘要里承载“文件路径”的字段；只有这两类才做成链接。 */
function pathOfToolInput(toolUse: TranscriptContent): string | null {
  const input = toolUse.input;
  if (!input || typeof input !== "object" || "_truncated" in input) return null;
  const obj = input as Record<string, unknown>;
  if (typeof obj.file_path === "string" && obj.file_path !== "") return obj.file_path;
  if (typeof obj.path === "string" && obj.path !== "") return obj.path;
  if (typeof obj.notebook_path === "string" && obj.notebook_path !== "") return obj.notebook_path;
  return null;
}

export function ToolCallBlock({ toolUse, toolResult, onOpenPath }: ToolCallBlockProps) {
  const isError = toolResult?.is_error;
  // 失败的工具默认展开：恢复历史后，报错证据必须一眼可见，不能藏进折叠里。
  const [expanded, setExpanded] = useState(isError === true);
  const hasResult = toolResult != null;
  const summary = buildSummary(toolUse);
  const summaryPath = onOpenPath === undefined ? null : pathOfToolInput(toolUse);
  const style = styleForTool(toolUse.name);
  const Icon = style.Icon;

  const wrapperBorder = isError ? "border-red-500/30" : style.border;
  const wrapperBg = isError ? "bg-red-500/5" : "bg-surface-2/60";

  return (
    <div
      className={`rounded-lg border ${wrapperBorder} ${wrapperBg} overflow-hidden transition-colors`}
    >
      {/* Collapsed/expanded toggle。用 div role=button 而不是 <button>：
          摘要里的文件路径本身是一个按钮，原生 <button> 不能嵌套。 */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(event) => {
          // 焦点在里面的文件路径按钮上时，Enter/Space 属于那个按钮，不在这里折叠
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setExpanded(!expanded);
          }
        }}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-surface-3/40 transition-colors cursor-pointer"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-muted flex-shrink-0 transition-transform duration-150 ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <span
          className={`flex-shrink-0 inline-flex items-center justify-center w-5 h-5 rounded ${style.chip}`}
        >
          <Icon className="w-3 h-3" />
        </span>
        <span className={`font-mono font-medium text-[13px] flex-shrink-0 ${style.text}`}>
          {toolUse.name}
        </span>
        {summary &&
          (summaryPath !== null ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onOpenPath?.(summaryPath);
              }}
              title={summary}
              className="min-w-0 truncate text-left text-xs font-mono text-blue-600 underline underline-offset-2 decoration-blue-400/40 transition-colors hover:text-blue-500 hover:decoration-blue-400/70"
            >
              {summary}
            </button>
          ) : (
            <span className="text-muted text-xs font-mono truncate min-w-0" title={summary}>
              {summary}
            </span>
          ))}
        <span className="ml-auto flex-shrink-0">
          {isError ? (
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-red-600 bg-red-50 border border-red-200 rounded px-1.5 py-0.5">
              <AlertCircle className="w-3 h-3" />
              error
            </span>
          ) : hasResult ? (
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-emerald-600 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5">
              <CheckCircle2 className="w-3 h-3" />
              ok
            </span>
          ) : (
            <span className="text-faint text-[10px] uppercase tracking-wider font-mono">
              pending
            </span>
          )}
        </span>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-surface-3 bg-surface-1/40 px-3 py-3 space-y-2.5 animate-fade-in">
          {renderInput(toolUse)}
          {hasResult && renderResult(toolResult, toolUse.name ?? "")}
        </div>
      )}
    </div>
  );
}
