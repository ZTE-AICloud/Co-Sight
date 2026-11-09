// SPDX-License-Identifier: Apache-2.0
/**
 * @file MessageList.tsx
 * @description Renders the chronological message stream of a Claude Code
 * transcript: alternating user / assistant rows with collapsible thinking
 * blocks, inline ToolCallBlocks for tool_use / tool_result pairs, and
 * MarkdownContent for prose. Used as the main body of the Conversation tab
 * on the Session detail page.
 */
import React, { useState, useMemo } from "react";
import {
  ChevronDown,
  ChevronRight,
  Bot,
  User,
  Brain,
  ScrollText,
  Terminal,
  Info,
  AlertTriangle,
} from "lucide-react";
import type { TranscriptMessage, TranscriptContent, SystemEvent } from "../../lib/types";
import { ToolCallBlock } from "./ToolCallBlock";
import { MarkdownContent } from "./MarkdownContent";
import { SystemEventMessage } from "./SystemEventMessage";
import { fmt, formatModelName } from "../../lib/format";
import { parseTuiSegments, stripAnsi, hasTuiTags, type TuiSegment } from "./tuiSegments";

interface MessageListProps {
  messages: TranscriptMessage[];
  loading: boolean;
}

/** Build a map from tool_use id → tool_result for matching */
function buildToolResultMap(messages: TranscriptMessage[]): Map<string, TranscriptContent> {
  const map = new Map<string, TranscriptContent>();
  for (const msg of messages) {
    if (msg.type !== "user") continue;
    for (const c of msg.content) {
      if (c.type === "tool_result" && c.id) {
        map.set(c.id, c);
      }
    }
  }
  return map;
}

/** Detect if text is skill loading content (starts with "Base directory for this skill:") */
function isSkillContent(text: string): boolean {
  return text.startsWith("Base directory for this skill:");
}

/** Detect if text is a task notification (contains <task-notification> tag) */
function isTaskNotification(text: string): boolean {
  return text.includes("<task-notification>") || text.includes("<task-id>");
}

/** Format a timestamp as local date + time (e.g. "2026-08-13 09:16:51") so
 *  multi-day sessions don't mix up times across different days. */
function formatLocalTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "";
  }
}

/** Compact pill for /command invocations parsed out of TUI markup. */
function CommandPill({ display }: { display: string }) {
  return (
    <div className="inline-flex items-center gap-2 text-sm text-emerald-700 font-mono bg-emerald-50 border border-emerald-200 rounded-md px-3 py-1.5 max-w-full">
      <span className="text-emerald-500">›</span>
      <span className="break-all">{display}</span>
    </div>
  );
}

/** Terminal-style fenced block for stdout/stderr captured from local commands. */
function TerminalBlock({ text, stream }: { text: string; stream: "stdout" | "stderr" }) {
  const cleaned = stripAnsi(text).replace(/^\n+|\n+$/g, "");
  const isErr = stream === "stderr";
  const accent = isErr
    ? "border-red-200 bg-red-50 text-red-700"
    : "border-surface-3 bg-surface-2 text-secondary";
  const labelColor = isErr ? "text-red-600" : "text-muted";
  return (
    <div className={`rounded-lg border ${accent} overflow-hidden`}>
      <div
        className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-wider border-b border-current/10 ${labelColor}`}
      >
        <Terminal className="w-3 h-3" />
        <span>{stream}</span>
      </div>
      <pre className="px-3 py-2 text-xs font-mono whitespace-pre-wrap break-words leading-relaxed max-h-96 overflow-y-auto">
        {cleaned}
      </pre>
    </div>
  );
}

/** Subtle inline note for the local-command-caveat banner. */
function CaveatBlock({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-700">
      <Info className="w-3.5 h-3.5 mt-px flex-shrink-0 text-amber-500" />
      <span className="leading-relaxed italic">{stripAnsi(text).trim()}</span>
    </div>
  );
}

/** Render a single segment produced by parseTuiSegments. */
function renderSegment(seg: TuiSegment, key: number): React.ReactNode {
  switch (seg.kind) {
    case "command":
      return <CommandPill key={key} display={seg.display} />;
    case "stdout":
      return <TerminalBlock key={key} text={seg.text} stream="stdout" />;
    case "stderr":
      return <TerminalBlock key={key} text={seg.text} stream="stderr" />;
    case "caveat":
      return <CaveatBlock key={key} text={seg.text} />;
    case "system-reminder":
      return (
        <CollapsibleBlock
          key={key}
          text={seg.text}
          icon={<AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />}
          title="System reminder"
          borderClass="border-amber-200 dark:border-amber-700"
          bgClass="bg-amber-50 dark:bg-amber-900/80"
          textClass="text-amber-700 dark:text-amber-200"
        />
      );
    case "persisted-output":
      return (
        <CollapsibleBlock
          key={key}
          text={seg.text}
          icon={<ScrollText className="w-3.5 h-3.5 text-violet-500 flex-shrink-0" />}
          title="Persisted output"
          borderClass="border-violet-200 dark:border-violet-700"
          bgClass="bg-violet-50 dark:bg-violet-900/80"
          textClass="text-violet-700 dark:text-violet-200"
        />
      );
    case "text": {
      const cleaned = stripAnsi(seg.text);
      if (!cleaned.trim()) return null;
      return (
        <div key={key} className="min-w-0">
          <MarkdownContent text={cleaned} />
        </div>
      );
    }
  }
}

/** Generic collapsible content block */
function CollapsibleBlock({
  text,
  icon,
  title,
  borderClass,
  bgClass,
  textClass,
}: {
  text: string;
  icon: React.ReactNode;
  title: string;
  borderClass: string;
  bgClass: string;
  textClass: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-lg border ${borderClass} ${bgClass} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:opacity-80 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 opacity-60 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 opacity-60 flex-shrink-0" />
        )}
        {icon}
        <span className={`text-xs ${textClass} truncate`}>{title}</span>
      </button>
      {expanded && (
        <div className="border-t border-current/10 px-3 py-2">
          <pre className="text-xs text-gray-800 dark:text-gray-100 opacity-60 whitespace-pre-wrap break-words leading-relaxed max-h-96 overflow-y-auto">
            {text}
          </pre>
        </div>
      )}
    </div>
  );
}

export const MessageList = React.memo(function MessageList({
  messages,
  loading,
}: MessageListProps) {
  const [expandedThinking, setExpandedThinking] = useState<Set<number>>(() => new Set());

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted text-sm">
        Loading conversation...
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="text-center py-12 text-muted text-sm">No conversation records found.</div>
    );
  }

  const toolResultMap = buildToolResultMap(messages);

  // Track which user messages are pure tool_result (no text) — we merge those into the preceding assistant message
  const userMsgHasText = useMemo(() => {
    const map = new Map<number, boolean>();
    messages.forEach((msg, idx) => {
      if (msg.type !== "user") return;
      const hasText = msg.content.some((c) => c.type === "text");
      map.set(idx, hasText);
    });
    return map;
  }, [messages]);

  return (
    <div className="space-y-3">
      {messages.map((msg, idx) => {
        // System messages (turn_duration / compaction / api_error) render as
        // System-role rows in their natural JSONL position — the transcript API
        // now returns them in-place alongside user/assistant messages.
        if (msg.type === "system") {
          return <SystemEventMessage key={`sys-${idx}`} event={msg as unknown as SystemEvent} />;
        }

        // Skip user messages that are purely tool_result — they're rendered inside ToolCallBlock
        if (msg.type === "user" && !userMsgHasText.get(idx)) {
          return null;
        }

        const isAssistant = msg.type === "assistant";
        const accentBar = isAssistant ? "before:bg-violet-400" : "before:bg-blue-400";
        const avatarRing = isAssistant
          ? "bg-gradient-to-br from-violet-100 to-fuchsia-100 text-violet-600 ring-1 ring-violet-200"
          : "bg-gradient-to-br from-blue-100 to-cyan-100 text-blue-600 ring-1 ring-blue-200";

        return (
          <div
            key={`msg-${idx}`}
            data-uuid={msg.uuid}
            className={`relative flex gap-3 rounded-xl px-3 py-2.5 hover:bg-surface-2/30 transition-colors before:absolute before:left-0 before:top-3 before:bottom-3 before:w-0.5 before:rounded-full before:opacity-60 ${accentBar}`}
          >
            {/* Avatar */}
            <div
              className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-0.5 shadow-sm ${avatarRing}`}
            >
              {isAssistant ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />}
            </div>

            {/* Message body */}
            <div className="flex-1 min-w-0 space-y-2">
              {/* Header line */}
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-xs font-semibold tracking-wide ${
                    isAssistant ? "text-violet-600" : "text-blue-600"
                  }`}
                >
                  {isAssistant ? "Assistant" : "User"}
                </span>
                {msg.model && (
                  <span className="text-[10px] text-gray-500 font-mono bg-gray-100 border border-gray-200 rounded px-1.5 py-0.5">
                    {formatModelName(msg.model)}
                  </span>
                )}
                {msg.usage && (
                  <span className="text-[10px] text-faint font-mono inline-flex items-center gap-1">
                    <span className="text-emerald-500">↓ {fmt(msg.usage.input_tokens)}</span>
                    <span className="text-faint">·</span>
                    <span className="text-orange-500">↑ {fmt(msg.usage.output_tokens)}</span>
                    {msg.tps != null && (
                      <>
                        <span className="text-faint">·</span>
                        <span className="text-violet-500">{msg.tps.toFixed(1)} tok/s</span>
                      </>
                    )}
                  </span>
                )}
                <span className="text-[10px] text-muted ml-auto font-mono">
                  {msg.timestamp ? formatLocalTime(msg.timestamp) : ""}
                </span>
              </div>

              {/* Content blocks */}
              {msg.content.map((block, bIdx) => {
                if (block.type === "text" && block.text) {
                  // Detect task notifications, collapsed by default
                  if (isTaskNotification(block.text)) {
                    return (
                      <CollapsibleBlock
                        key={bIdx}
                        text={block.text}
                        icon={<ScrollText className="w-3.5 h-3.5 text-cyan-500 flex-shrink-0" />}
                        title="Task Notification"
                        borderClass="border-cyan-200 dark:border-cyan-700"
                        bgClass="bg-cyan-50 dark:bg-cyan-900/80"
                        textClass="text-cyan-700 dark:text-cyan-200"
                      />
                    );
                  }

                  // Detect skill content, collapsed by default
                  if (isSkillContent(block.text)) {
                    const pathMatch = block.text.match(/^Base directory for this skill:\s*(\S+)/);
                    const skillPath = pathMatch ? pathMatch[1]! : "Skill";
                    return (
                      <CollapsibleBlock
                        key={bIdx}
                        text={block.text}
                        icon={<ScrollText className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />}
                        title={skillPath}
                        borderClass="border-blue-200"
                        bgClass="bg-blue-50"
                        textClass="text-blue-700"
                      />
                    );
                  }

                  // Mixed TUI markup: caveat / command / stdout / stderr / system-reminder
                  // can appear inline (sometimes interleaved with prose). Parse the text
                  // into segments and render each with the appropriate visual treatment.
                  if (hasTuiTags(block.text)) {
                    const segments = parseTuiSegments(block.text);
                    return (
                      <div key={bIdx} className="space-y-2 min-w-0">
                        {segments.map((s, sIdx) => renderSegment(s, sIdx))}
                      </div>
                    );
                  }

                  return (
                    <div key={bIdx} className="min-w-0">
                      <MarkdownContent text={stripAnsi(block.text)} />
                    </div>
                  );
                }

                if (block.type === "thinking" && block.text) {
                  const thinkKey = idx * 100 + bIdx;
                  const isExpanded = expandedThinking.has(thinkKey);
                  return (
                    <div
                      key={bIdx}
                      className="rounded-lg border border-amber-200 bg-amber-50 overflow-hidden"
                    >
                      <button
                        onClick={() =>
                          setExpandedThinking((prev) => {
                            const next = new Set(prev);
                            if (next.has(thinkKey)) next.delete(thinkKey);
                            else next.add(thinkKey);
                            return next;
                          })
                        }
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-amber-100 transition-colors"
                      >
                        <ChevronRight
                          className={`w-3.5 h-3.5 text-amber-500 transition-transform duration-150 ${
                            isExpanded ? "rotate-90" : ""
                          }`}
                        />
                        <Brain className="w-3.5 h-3.5 text-amber-500" />
                        <span className="text-xs text-amber-700 font-medium">Thinking</span>
                        {!isExpanded && (
                          <span className="text-[10px] text-amber-500 font-mono ml-auto">
                            {block.text.length.toLocaleString()} chars
                          </span>
                        )}
                      </button>
                      {isExpanded && (
                        <div className="border-t border-amber-200 px-3 py-2 text-amber-800">
                          <MarkdownContent text={block.text} dense />
                        </div>
                      )}
                    </div>
                  );
                }

                if (block.type === "tool_use") {
                  const matchedResult = block.id ? (toolResultMap.get(block.id) ?? null) : null;
                  return <ToolCallBlock key={bIdx} toolUse={block} toolResult={matchedResult} />;
                }

                // tool_result blocks rendered inside ToolCallBlock, skip standalone
                return null;
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
});
