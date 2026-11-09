// SPDX-License-Identifier: Apache-2.0
/**
 * @file session.ts
 * @description Core session and agent types, plus derived helpers for
 * computing effective (UI-overlay) statuses.
 */

import type { AgentStatus, EffectiveAgentStatus, EffectiveSessionStatus, SessionStatus } from "./common";
import { AWAITING_STATUS } from "./common";

export interface Session {
  id: string;
  name: string | null;
  status: SessionStatus;
  cwd: string | null;
  model: string | null;
  started_at: string;
  ended_at: string | null;
  metadata: string | null;
  agent_count?: number;
  last_activity?: string;
  cost?: number;
  /** ISO timestamp set when Claude Code is blocked waiting for the user
   * (permission prompt or "waiting for your input" notice). Cleared on the
   * next non-Notification hook event. Null when the session is not waiting. */
  awaiting_input_since?: string | null;
  /** First user-typed prompt (beautified, truncated to 2000 chars).
   *  NULL for old sessions or sessions that haven't received a prompt yet. */
  first_prompt?: string | null;
  /** User-set title via /rename command (from JSONL custom-title entry).
   *  Highest priority for display. NULL if never renamed. */
  custom_title?: string | null;
  /** AI-generated title (from JSONL ai-title entry).
   *  Second priority for display. NULL if AI hasn't generated a title. */
  ai_title?: string | null;
  /** Last scanned line number in JSONL for incremental title extraction.
   *  Used to avoid re-scanning the entire file on each SessionEnd. */
  last_scanned_line?: number;
  /** Agent-runtime session ID for direct session restoration.
   *  When a session is created via "Run Agent", this stores the agent-runtime's
   *  session ID, eliminating the need for fuzzy matching when resuming. */
  agent_runtime_session_id?: string | null;
}

/**
 * A session as returned by the agent-runtime service
 * (`GET /api/agent-runtime/v1/sessions`).
 *
 * Deliberately kept separate from {@link Session}: the two share only `id` and
 * `name`, and their `id` values mean different things (this one is `sess_…`,
 * the viewer's is the Claude Code session UUID). Treating one as the other is
 * what previously produced wrong field lookups on the dashboard modal.
 */
export interface AgentRuntimeSession {
  id: string;
  instanceId: string;
  agentId: string;
  skillId: string | null;
  name: string | null;
  modelId: string | null;
  status: string;
  effort: string | null;
  approvalMode: string | null;
  approvedAll: boolean;
  /** Viewer session UUID this agent-runtime session is linked to, or null when
   *  the session has no viewer-side counterpart. Doubles as the `/sessions/:id`
   *  route param when navigating to the viewer session detail page. */
  resumeSessionId: string | null;
  lastMessage: string | null;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface Agent {
  id: string;
  session_id: string;
  name: string;
  type: "main" | "subagent";
  subagent_type: string | null;
  status: AgentStatus;
  task: string | null;
  current_tool: string | null;
  started_at: string;
  ended_at: string | null;
  updated_at: string;
  parent_agent_id: string | null;
  metadata: string | null;
  /** Mirrors the parent session: ISO timestamp when set, null otherwise. */
  awaiting_input_since?: string | null;
}

export interface DashboardEvent {
  id: number;
  session_id: string;
  agent_id: string | null;
  event_type: string;
  tool_name: string | null;
  summary: string | null;
  data: string | null;
  created_at: string;
}

export interface SessionStats {
  session_id: string;
  total_events: number;
  events_by_type: Array<{ event_type: string; count: number }>;
  tools_used: Array<{ tool_name: string; count: number }>;
  error_count: number;
  first_event_at: string | null;
  last_event_at: string | null;
  agents: {
    total: number;
    main: number;
    subagent: number;
    compaction: number;
    by_status: Record<string, number>;
  };
  subagent_types: Array<{ subagent_type: string; count: number }>;
  tokens: {
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
  };
  compaction_count: number;
}

// ── Status helpers ──

/** True when a session is paused on a permission prompt or input request. */
export function isSessionAwaitingInput(session: Session | undefined | null): boolean {
  return !!session?.awaiting_input_since && session.status === "active";
}

/** True when an agent is the one blocked on user input (typically a main agent). */
export function isAgentAwaitingInput(agent: Agent | undefined | null): boolean {
  if (!agent?.awaiting_input_since) return false;
  // Once the agent's lifecycle has ended, the waiting flag is stale; ignore it.
  return agent.status !== "completed" && agent.status !== "error";
}

export function effectiveAgentStatus(agent: Agent): EffectiveAgentStatus {
  return isAgentAwaitingInput(agent) ? AWAITING_STATUS : agent.status;
}

export function effectiveSessionStatus(session: Session): EffectiveSessionStatus {
  return isSessionAwaitingInput(session) ? AWAITING_STATUS : session.status;
}
