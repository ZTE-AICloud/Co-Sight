// SPDX-License-Identifier: Apache-2.0
/**
 * @file primitives.tsx
 * @description Presentational building blocks used by the per-tool input and
 * response renderers. Each primitive is a pure component with a narrow,
 * typed contract so they can be composed freely (Terminal + TerminalOutput for
 * Bash; Terminal + UnifiedDiff for Edit; LineNumberedCode for Read/Write;
 * FileList/MatchList for Grep/Glob; KeyValueCard for MCP tools).
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Check } from "lucide-react";

// ───────────────────────── Copy button ─────────────────────────

export function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail in insecure contexts — silently ignore.
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1 text-[10px] py-0.5 px-1.5 rounded text-tertiary hover:text-secondary hover:bg-surface-2 cursor-pointer"
      aria-label={t("eventDetail.copy")}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? t("eventDetail.copied") : t("eventDetail.copy")}
    </button>
  );
}

// ───────────────────────── Terminal (command) ─────────────────────────

export function Terminal({ command, description }: { command: string; description?: string }) {
  return (
    <div className="relative bg-surface-2/60 border border-border/50 rounded font-mono text-[11px] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-surface-1/40">
        <span className="text-muted text-[10px] uppercase tracking-wide">terminal</span>
        <CopyButton text={command} />
      </div>
      <pre className="px-3 py-2 text-secondary whitespace-pre-wrap break-words">
        {description && <div className="text-muted mb-1"># {description}</div>}
        <div>
          <span className="text-emerald-400 select-none">$ </span>
          {command}
        </div>
      </pre>
    </div>
  );
}

// ───────────────────────── Terminal output (stdout/stderr) ─────────────────────────

export function TerminalOutput({
  stdout,
  stderr,
  interrupted,
  exitCode,
}: {
  stdout?: string;
  stderr?: string;
  interrupted?: boolean;
  exitCode?: number;
}) {
  const hasStdout = typeof stdout === "string" && stdout.length > 0;
  const hasStderr = typeof stderr === "string" && stderr.length > 0;
  const flag =
    interrupted === true
      ? { label: "interrupted", color: "text-red-400 border-red-500/40 bg-red-500/10" }
      : typeof exitCode === "number" && exitCode !== 0
        ? {
            label: `exit ${exitCode}`,
            color: "text-red-400 border-red-500/40 bg-red-500/10",
          }
        : null;

  return (
    <div className="space-y-2">
      {hasStdout && <OutputBlock label="stdout" text={stdout!} variant="out" />}
      {hasStderr && <OutputBlock label="stderr" text={stderr!} variant="err" />}
      {flag && (
        <span
          className={`inline-block text-[10px] px-2 py-0.5 rounded border font-mono ${flag.color}`}
        >
          {flag.label}
        </span>
      )}
    </div>
  );
}

function OutputBlock({
  label,
  text,
  variant,
}: {
  label: string;
  text: string;
  variant: "out" | "err";
}) {
  const color = variant === "err" ? "text-red-300" : "text-secondary";
  return (
    <div className="relative bg-surface-2/60 border border-border/50 rounded font-mono text-[11px] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-surface-1/40">
        <span className="text-muted text-[10px] uppercase tracking-wide">{label}</span>
        <CopyButton text={text} />
      </div>
      <pre className={`px-3 py-2 whitespace-pre-wrap break-words max-h-96 overflow-auto ${color}`}>
        {text}
      </pre>
    </div>
  );
}

// ───────────────────────── Line-numbered code ─────────────────────────

export function LineNumberedCode({
  text,
  maxHeight = "24rem",
  startLine = 1,
  label,
}: {
  text: string;
  maxHeight?: string;
  startLine?: number;
  label?: string;
}) {
  const lines = text.split(/\r?\n/);
  return (
    <div className="relative bg-surface-2/60 border border-border/50 rounded font-mono text-[11px] overflow-hidden">
      {label && (
        <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-surface-1/40">
          <span className="text-muted text-[10px] uppercase tracking-wide">{label}</span>
          <CopyButton text={text} />
        </div>
      )}
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, i) => (
              <tr key={i}>
                <td className="px-2 text-right text-faint select-none bg-surface-1/40 border-r border-border align-top">
                  {i + startLine}
                </td>
                <td className="px-3 text-secondary whitespace-pre-wrap break-words">{line}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ───────────────────────── Unified diff ─────────────────────────

export type DiffHunk = {
  oldStart: number;
  newStart: number;
  oldLines: number;
  newLines: number;
  lines: string[];
};

export function UnifiedDiff({ hunks }: { hunks: DiffHunk[] }) {
  if (hunks.length === 0) {
    return <p className="text-[11px] text-muted italic">no diff</p>;
  }
  return (
    <div className="relative bg-surface-2/60 border border-border/50 rounded font-mono text-[11px] overflow-hidden">
      <div className="overflow-auto max-h-96">
        {hunks.map((hunk, i) => (
          <HunkView key={i} hunk={hunk} />
        ))}
      </div>
    </div>
  );
}

function HunkView({ hunk }: { hunk: DiffHunk }) {
  let oldLine = hunk.oldStart;
  let newLine = hunk.newStart;
  return (
    <div>
      <div className="px-3 py-1 text-[10px] text-cyan-300 bg-cyan-500/10 border-y border-cyan-500/20 font-mono">
        @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
      </div>
      <table className="w-full border-collapse">
        <tbody>
          {hunk.lines.map((line, i) => {
            const kind = line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : "ctx";
            const body = line.slice(kind === "ctx" ? 0 : 1);
            const showOld = kind !== "add";
            const showNew = kind !== "remove";
            const rowBg =
              kind === "add"
                ? "bg-green-500/10 text-green-200"
                : kind === "remove"
                  ? "bg-red-500/10 text-red-200"
                  : "text-faint";
            const oldCell = showOld ? oldLine++ : "";
            const newCell = showNew ? newLine++ : "";
            const sign = kind === "add" ? "+" : kind === "remove" ? "-" : " ";
            return (
              <tr key={i} className={rowBg}>
                <td className="px-2 text-right text-faint select-none border-r border-border/40 w-[36px]">
                  {oldCell}
                </td>
                <td className="px-2 text-right text-faint select-none border-r border-border/40 w-[36px]">
                  {newCell}
                </td>
                <td className="px-1 text-center select-none w-[16px]">{sign}</td>
                <td className="px-2 whitespace-pre-wrap break-words">{body}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ───────────────────────── Key-value card ─────────────────────────

export function KeyValueCard({
  data,
  priority = [],
}: {
  data: Record<string, unknown>;
  priority?: string[];
}) {
  const entries = Object.entries(data);
  const priorityEntries = priority
    .map((k) => [k, data[k]] as [string, unknown])
    .filter(([, v]) => v !== undefined);
  const restEntries = entries.filter(([k]) => !priority.includes(k));
  const ordered = [...priorityEntries, ...restEntries];

  if (ordered.length === 0) {
    return <p className="text-[11px] text-muted italic">empty</p>;
  }

  return (
    <table className="w-full text-[11px] border border-border/50 rounded overflow-hidden">
      <tbody>
        {ordered.map(([k, v], i) => (
          <tr key={k} className={i > 0 ? "border-t border-border" : ""}>
            <td className="text-muted align-top py-1.5 px-2 font-mono bg-surface-3/60 w-[28%] break-all">
              {k}
            </td>
            <td className="text-faint align-top py-1.5 px-2">
              <ValueCell value={v} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ValueCell({ value }: { value: unknown }) {
  if (value == null) return <span className="text-muted italic">null</span>;
  if (typeof value === "boolean")
    return (
      <span
        className={`inline-block px-2 py-0.5 rounded border text-[11px] font-mono ${
          value
            ? "text-green-400 border-green-500/30 bg-green-500/10"
            : "text-tertiary border-muted/30 bg-muted/10"
        }`}
      >
        {String(value)}
      </span>
    );
  if (typeof value === "number") return <span className="font-mono text-faint">{value}</span>;
  if (typeof value === "string") {
    if (value.length > 120 || value.includes("\n")) {
      return (
        <pre className="bg-surface-3 text-faint text-[11px] font-mono p-2 rounded border border-border whitespace-pre-wrap break-words max-h-48 overflow-auto">
          {value}
        </pre>
      );
    }
    return <span className="font-mono text-faint break-all">{value}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted italic">[]</span>;
    return (
      <ol className="list-decimal pl-4 space-y-1">
        {value.map((item, i) => (
          <li key={i}>
            <ValueCell value={item} />
          </li>
        ))}
      </ol>
    );
  }
  return (
    <pre className="bg-surface-3 text-faint text-[11px] font-mono p-2 rounded border border-border whitespace-pre-wrap break-words max-h-48 overflow-auto">
      {safeStringify(value)}
    </pre>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// ───────────────────────── File list / match list ─────────────────────────

export function FileList({ paths }: { paths: string[] }) {
  if (paths.length === 0) return <p className="text-[11px] text-muted italic">no files</p>;
  return (
    <ul className="divide-y divide-border border border-border/50 rounded overflow-hidden text-[11px] max-h-80 overflow-y-auto">
      {paths.map((p, i) => (
        <li key={i} className="px-3 py-1 font-mono text-faint break-all">
          {p}
        </li>
      ))}
    </ul>
  );
}

export type GrepMatch = {
  file?: string;
  line?: number;
  text?: string;
};

export function MatchList({ matches }: { matches: GrepMatch[] }) {
  if (matches.length === 0) return <p className="text-[11px] text-muted italic">no matches</p>;
  return (
    <ul className="divide-y divide-border border border-border/50 rounded overflow-hidden text-[11px] max-h-80 overflow-y-auto font-mono">
      {matches.map((m, i) => (
        <li key={i} className="px-3 py-1 text-faint break-all">
          {m.file && <span className="text-cyan-300">{m.file}</span>}
          {m.line != null && <span className="text-muted">:{m.line}</span>}
          {m.text && <span className="text-tertiary">: {m.text}</span>}
        </li>
      ))}
    </ul>
  );
}
