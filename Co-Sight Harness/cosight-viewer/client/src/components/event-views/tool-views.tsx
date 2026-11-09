// SPDX-License-Identifier: Apache-2.0
/**
 * @file tool-views.tsx
 * @description Per-tool renderers for `tool_input` and `tool_response` fields.
 * Dispatched from EventDetail when the event's `tool_name` is recognised.
 * Unknown tools fall back to the caller's generic JSON code view.
 *
 * Handled tools:
 *   - Bash / PowerShell  → Terminal + TerminalOutput
 *   - Edit / NotebookEdit → Terminal + UnifiedDiff (from old/new + structuredPatch)
 *   - Read                → Terminal + LineNumberedCode
 *   - Write               → Terminal + LineNumberedCode
 *   - Grep                → Terminal + MatchList
 *   - Glob                → Terminal + FileList
 *   - WebFetch            → Terminal + LineNumberedCode
 *   - Task / Agent        → metadata + prompt
 *   - mcp__*              → KeyValueCard with known semantic fields promoted
 *   - AskUserQuestion     → formatted Q with options
 *   - Any other           → returns null (caller falls back to generic JSON)
 *
 */

import {
  FileList,
  KeyValueCard,
  LineNumberedCode,
  MatchList,
  Terminal,
  TerminalOutput,
  UnifiedDiff,
} from "./primitives";
import type { DiffHunk, GrepMatch } from "./primitives";

// ───────────────────────── Helpers ─────────────────────────

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function obj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function isMcp(toolName: string): boolean {
  return toolName.startsWith("mcp__");
}

/** Builds a unified-diff hunk from a bare old_string / new_string pair. One
 *  hunk, minimal context — good enough for the input preview before the
 *  actual structuredPatch comes back in the response. */
function diffFromStrings(oldStr: string, newStr: string): DiffHunk[] {
  if (!oldStr && !newStr) return [];
  const oldLines = oldStr ? oldStr.split(/\r?\n/) : [];
  const newLines = newStr ? newStr.split(/\r?\n/) : [];
  const lines: string[] = [];
  for (const l of oldLines) lines.push(`-${l}`);
  for (const l of newLines) lines.push(`+${l}`);
  return [
    {
      oldStart: 1,
      newStart: 1,
      oldLines: oldLines.length,
      newLines: newLines.length,
      lines,
    },
  ];
}

/** Normalises the `structuredPatch` array that shows up in Edit/NotebookEdit
 *  tool_response into DiffHunk shape. Tolerates missing fields. */
function parseStructuredPatch(value: unknown): DiffHunk[] {
  if (!Array.isArray(value)) return [];
  const hunks: DiffHunk[] = [];
  for (const raw of value) {
    const r = obj(raw);
    if (!r) continue;
    const lines = Array.isArray(r.lines)
      ? (r.lines.filter((l) => typeof l === "string") as string[])
      : [];
    hunks.push({
      oldStart: typeof r.oldStart === "number" ? r.oldStart : 1,
      newStart: typeof r.newStart === "number" ? r.newStart : 1,
      oldLines: typeof r.oldLines === "number" ? r.oldLines : lines.length,
      newLines: typeof r.newLines === "number" ? r.newLines : lines.length,
      lines,
    });
  }
  return hunks;
}

/** Best-effort match list from a Grep tool_response. Supports the common
 *  shapes: array of strings, array of {file,line,text}, or an object with
 *  `matches` / `files` keys. */
function parseGrepMatches(value: unknown): GrepMatch[] {
  if (Array.isArray(value)) return value.map(toMatch).filter(Boolean) as GrepMatch[];
  const o = obj(value);
  if (!o) return [];
  if (Array.isArray(o.matches)) return o.matches.map(toMatch).filter(Boolean) as GrepMatch[];
  if (Array.isArray(o.files))
    return (o.files as unknown[])
      .map((f) => (typeof f === "string" ? ({ file: f } as GrepMatch) : null))
      .filter(Boolean) as GrepMatch[];
  return [];
}

function toMatch(raw: unknown): GrepMatch | null {
  if (typeof raw === "string") {
    const m = raw.match(/^(.+?):(\d+):(.*)$/);
    if (m) return { file: m[1], line: Number(m[2]), text: m[3] };
    return { text: raw };
  }
  const o = obj(raw);
  if (!o) return null;
  const match: GrepMatch = {};
  if (typeof o.file === "string") match.file = o.file;
  if (typeof o.path === "string" && !match.file) match.file = o.path;
  if (typeof o.line === "number") match.line = o.line;
  if (typeof o.line_number === "number" && match.line == null) match.line = o.line_number;
  if (typeof o.text === "string") match.text = o.text;
  if (typeof o.match === "string" && !match.text) match.text = o.match;
  if (typeof o.content === "string" && !match.text) match.text = o.content;
  return match;
}

function parseFileList(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((v): v is string => typeof v === "string");
  const o = obj(value);
  if (!o) return [];
  if (Array.isArray(o.files))
    return (o.files as unknown[]).filter((v): v is string => typeof v === "string");
  if (Array.isArray(o.paths))
    return (o.paths as unknown[]).filter((v): v is string => typeof v === "string");
  return [];
}

// ───────────────────────── Top-level dispatchers ─────────────────────────

/** Returns a rendered view for the tool's input, or null when the tool isn't
 *  specifically handled (caller renders JSON fallback). */
export function ToolInputView({
  toolName,
  input,
}: {
  toolName: string | null;
  input: unknown;
}): React.ReactNode | null {
  if (!toolName) return null;
  const i = obj(input);
  if (!i) return null;

  // MCP tools — show the input as a key-value card with URL/query/id promoted.
  if (isMcp(toolName)) {
    return (
      <KeyValueCard
        data={i}
        priority={[
          "url",
          "query",
          "q",
          "title",
          "name",
          "id",
          "page_id",
          "task_id",
          "merge_request_iid",
          "issue_iid",
        ]}
      />
    );
  }

  switch (toolName) {
    case "Bash":
    case "PowerShell": {
      const cmd = str(i.command);
      const desc = str(i.description);
      if (!cmd) return null;
      return <Terminal command={cmd} description={desc || undefined} />;
    }
    case "Read": {
      const path = str(i.file_path);
      if (!path) return null;
      const flags: string[] = [];
      if (i.offset != null) flags.push(`--offset=${i.offset}`);
      if (i.limit != null) flags.push(`--limit=${i.limit}`);
      return <Terminal command={`read ${path}${flags.length ? " " + flags.join(" ") : ""}`} />;
    }
    case "Write": {
      const path = str(i.file_path);
      const content = str(i.content);
      return (
        <div className="space-y-2">
          {path && <Terminal command={`write ${path}`} />}
          {content && <LineNumberedCode text={content} label="content" />}
        </div>
      );
    }
    case "Edit":
    case "NotebookEdit": {
      const path = str(i.file_path);
      const oldStr = str(i.old_string);
      const newStr = str(i.new_string);
      const hunks = diffFromStrings(oldStr, newStr);
      const replaceAll = i.replace_all === true ? " --replace-all" : "";
      return (
        <div className="space-y-2">
          {path && <Terminal command={`edit ${path}${replaceAll}`} />}
          {hunks.length > 0 && <UnifiedDiff hunks={hunks} />}
        </div>
      );
    }
    case "Grep": {
      const pattern = str(i.pattern);
      const path = str(i.path);
      const flags = [
        i.glob ? `--glob=${str(i.glob)}` : null,
        i.type ? `--type=${str(i.type)}` : null,
        i.output_mode ? `--mode=${str(i.output_mode)}` : null,
        i["-i"] ? "-i" : null,
        i["-n"] ? "-n" : null,
      ].filter(Boolean) as string[];
      const cmd = `grep "${pattern}"${path ? " " + path : ""}${flags.length ? " " + flags.join(" ") : ""}`;
      return <Terminal command={cmd} />;
    }
    case "Glob": {
      const pattern = str(i.pattern);
      const path = str(i.path);
      return <Terminal command={`glob "${pattern}"${path ? " " + path : ""}`} />;
    }
    case "WebFetch": {
      const url = str(i.url);
      const prompt = str(i.prompt);
      return (
        <div className="space-y-2">
          {url && <Terminal command={`fetch ${url}`} description={prompt || undefined} />}
        </div>
      );
    }
    case "Task":
    case "Agent": {
      const desc = str(i.description);
      const subtype = str(i.subagent_type);
      const prompt = str(i.prompt);
      return (
        <div className="space-y-2">
          <KeyValueCard
            data={{
              ...(desc ? { description: desc } : {}),
              ...(subtype ? { subagent_type: subtype } : {}),
            }}
          />
          {prompt && <LineNumberedCode text={prompt} label="prompt" maxHeight="16rem" />}
        </div>
      );
    }
    case "TaskCreate":
    case "TaskUpdate":
    case "TaskGet":
    case "TaskStop":
    case "TaskOutput":
    case "TaskList":
      return <KeyValueCard data={i} priority={["description", "id", "status", "activeForm"]} />;
    case "AskUserQuestion": {
      const questions = Array.isArray(i.questions) ? i.questions : null;
      if (!questions) return null;
      return (
        <div className="space-y-2">
          {questions.map((q, idx) => {
            const qo = obj(q);
            if (!qo) return null;
            return (
              <KeyValueCard
                key={idx}
                data={qo}
                priority={["question", "options", "multiSelect", "header"]}
              />
            );
          })}
        </div>
      );
    }
    default:
      return null;
  }
}

/** Returns a rendered view for the tool's response, or null when the tool
 *  isn't specifically handled (caller renders JSON fallback). */
export function ToolResponseView({
  toolName,
  response,
}: {
  toolName: string | null;
  response: unknown;
}): React.ReactNode | null {
  if (!toolName) return null;

  if (isMcp(toolName)) {
    const r = obj(response);
    if (r)
      return (
        <KeyValueCard
          data={r}
          priority={[
            "title",
            "name",
            "state",
            "status",
            "url",
            "id",
            "iid",
            "author",
            "created_at",
            "updated_at",
          ]}
        />
      );
    // Non-object responses (string, array) fall through to generic.
    return null;
  }

  switch (toolName) {
    case "Bash":
    case "PowerShell": {
      const r = obj(response);
      if (!r) return null;
      return (
        <TerminalOutput
          stdout={typeof r.stdout === "string" ? r.stdout : undefined}
          stderr={typeof r.stderr === "string" ? r.stderr : undefined}
          interrupted={r.interrupted === true}
          exitCode={typeof r.exitCode === "number" ? r.exitCode : undefined}
        />
      );
    }
    case "Edit":
    case "NotebookEdit": {
      const r = obj(response);
      if (!r) return null;
      const hunks = parseStructuredPatch(r.structuredPatch);
      const originalFile = typeof r.originalFile === "string" ? r.originalFile : "";
      return (
        <div className="space-y-2">
          {hunks.length > 0 && <UnifiedDiff hunks={hunks} />}
          {originalFile && (
            <details className="bg-surface-2/40 border border-border/50 rounded overflow-hidden">
              <summary className="cursor-pointer select-none px-3 py-1.5 text-[11px] text-tertiary hover:text-secondary hover:bg-surface-2">
                <span className="font-semibold uppercase tracking-wide">original file</span>
                <span className="text-muted font-normal ml-2">
                  ({originalFile.split(/\r?\n/).length} lines)
                </span>
              </summary>
              <div className="p-2">
                <LineNumberedCode text={originalFile} maxHeight="24rem" />
              </div>
            </details>
          )}
        </div>
      );
    }
    case "Read": {
      if (typeof response === "string") return <LineNumberedCode text={response} />;
      const r = obj(response);
      if (r && typeof r.content === "string") return <LineNumberedCode text={r.content} />;
      return null;
    }
    case "Write": {
      const r = obj(response);
      if (!r) return null;
      return <KeyValueCard data={r} priority={["filePath", "type", "bytes"]} />;
    }
    case "Grep": {
      const matches = parseGrepMatches(response);
      if (matches.length === 0) return null;
      return <MatchList matches={matches} />;
    }
    case "Glob": {
      const files = parseFileList(response);
      if (files.length === 0) return null;
      return <FileList paths={files} />;
    }
    case "WebFetch": {
      if (typeof response === "string") return <LineNumberedCode text={response} />;
      const r = obj(response);
      if (r && typeof r.content === "string") return <LineNumberedCode text={r.content} />;
      if (r) return <KeyValueCard data={r} priority={["url", "title", "status", "content"]} />;
      return null;
    }
    case "Task":
    case "Agent": {
      if (typeof response === "string") return <LineNumberedCode text={response} label="output" />;
      const r = obj(response);
      if (r) return <KeyValueCard data={r} />;
      return null;
    }
    case "TaskCreate":
    case "TaskUpdate":
    case "TaskGet":
    case "TaskStop":
    case "TaskOutput":
    case "TaskList": {
      const r = obj(response);
      if (r)
        return <KeyValueCard data={r} priority={["description", "status", "id", "activeForm"]} />;
      return null;
    }
    case "AskUserQuestion": {
      const r = obj(response);
      if (r) return <KeyValueCard data={r} priority={["answer", "option", "question"]} />;
      return null;
    }
    default:
      return null;
  }
}
