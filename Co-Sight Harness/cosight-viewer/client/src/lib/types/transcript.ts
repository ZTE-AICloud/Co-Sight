// SPDX-License-Identifier: Apache-2.0
/**
 * @file transcript.ts
 * @description Transcript and conversation types — messages, content blocks,
 * transcript results/info/list, system events, and the WebSocket payload for
 * live transcript updates.
 */

export interface TranscriptContent {
  type: "text" | "tool_use" | "tool_result" | "thinking";
  text?: string;
  name?: string;
  id?: string;
  input?: Record<string, unknown> | { _truncated: string };
  output?: string;
  is_error?: boolean;
}

export interface TranscriptMessage {
  type: "user" | "assistant" | "system";
  /** uuid of the source jsonl entry; aligns with step.uuid/messageUuid for chat scroll-to-message linkage */
  uuid?: string;
  /** API-level message.id — stable across streaming partials of the same response. Used for cross-batch TPS/usage dedup. */
  _messageId?: string | null;
  timestamp: string | null;
  content: TranscriptContent[];
  model?: string;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
  };
  /** Turn duration in ms, paired from the subsequent system/turn_duration entry */
  durationMs?: number;
  /** Tokens per second computed from output_tokens / (durationMs / 1000) */
  tps?: number;
  // System-type message fields (turn_duration / compaction / api_error),
  // present only when type === "system". Mirrors SystemEvent.data so system
  // messages can be rendered by SystemEventMessage directly.
  subtype?: "turn_duration" | "compaction" | "api_error";
  data?: {
    summary?: string;
    durationMs?: number;
    uuid?: string | null;
    compaction_number?: number;
    total_compactions?: number;
    error_type?: string;
  };
}

export interface TranscriptResult {
  messages: TranscriptMessage[];
  total: number;
  has_more: boolean;
  last_line: number;
  first_line: number;
  /** File size in bytes — clients use this to skip unnecessary polls */
  fileSize?: number;
}

export interface TranscriptInfo {
  id: string;
  name: string;
  type: "main" | "subagent" | "compaction";
  subagent_type?: string | null;
  has_transcript: boolean;
  db_agent_id?: string | null;
}

export interface TranscriptListResult {
  transcripts: TranscriptInfo[];
}

/**
 * System event extracted from JSONL transcript for display as System-role
 * messages in the conversation timeline.
 */
export interface SystemEvent {
  type: "system";
  subtype: "turn_duration" | "compaction" | "api_error";
  timestamp: string | null;
  data: {
    summary: string;
    durationMs?: number;
    uuid?: string | null;
    compaction_number?: number;
    total_compactions?: number;
    error_type?: string;
  };
}

export interface TranscriptUpdatePayload {
  sessionId: string;
  messages: TranscriptMessage[];
  lastLine: number;
}
