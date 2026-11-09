// SPDX-License-Identifier: Apache-2.0
/**
 * @file common.ts
 * @description Common status enums, effective-status helpers, and UI config
 * tables shared across session and agent rendering.
 */

export type SessionStatus = "active" | "completed" | "error" | "abandoned" | "imported";
export type AgentStatus = "working" | "waiting" | "completed" | "error";
export type AgentType = "main" | "subagent";

/**
 * UI-only status that overlays the persisted SessionStatus/AgentStatus when
 * `awaiting_input_since` is set on a session or agent. Renders as a yellow
 * "Waiting" badge so the dashboard can flag sessions blocked on a Claude Code
 * permission prompt without changing the underlying lifecycle enum.
 */
export const AWAITING_STATUS = "waiting" as const;
export type EffectiveAgentStatus = AgentStatus | typeof AWAITING_STATUS;
export type EffectiveSessionStatus = SessionStatus | typeof AWAITING_STATUS;

export const STATUS_CONFIG: Record<
  EffectiveAgentStatus,
  { labelKey: string; color: string; bg: string; darkBg: string; dot: string }
> = {
  working: {
    labelKey: "common:status.working",
    color: "text-blue-400 dark:text-blue-400",
    bg: "bg-blue-500/10 border-blue-500/20",
    darkBg: "dark:bg-blue-500/20 dark:border-blue-500/40",
    dot: "bg-blue-400",
  },
  waiting: {
    labelKey: "common:status.waiting",
    color: "text-yellow-400 dark:text-yellow-400",
    bg: "bg-yellow-500/10 border-yellow-500/20",
    darkBg: "dark:bg-yellow-500/20 dark:border-yellow-500/40",
    dot: "bg-yellow-400",
  },
  completed: {
    labelKey: "common:status.completed",
    color: "text-emerald-400 dark:text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/20",
    darkBg: "dark:bg-emerald-500/20 dark:border-emerald-500/40",
    dot: "bg-emerald-400",
  },
  error: {
    labelKey: "common:status.error",
    color: "text-red-400 dark:text-red-400",
    bg: "bg-red-500/10 border-red-500/20",
    darkBg: "dark:bg-red-500/20 dark:border-red-500/40",
    dot: "bg-red-400",
  },
};

export const SESSION_STATUS_CONFIG: Record<
  EffectiveSessionStatus,
  { labelKey: string; color: string; bg: string; darkBg: string; dot: string }
> = {
  active: {
    labelKey: "common:status.active",
    color: "text-blue-400 dark:text-blue-400",
    bg: "bg-blue-500/10 border-blue-500/20",
    darkBg: "dark:bg-blue-500/20 dark:border-blue-500/40",
    dot: "bg-blue-400",
  },
  waiting: {
    labelKey: "common:status.waiting",
    color: "text-yellow-400 dark:text-yellow-400",
    bg: "bg-yellow-500/10 border-yellow-500/20",
    darkBg: "dark:bg-yellow-500/20 dark:border-yellow-500/40",
    dot: "bg-yellow-400",
  },
  completed: {
    labelKey: "common:status.completed",
    color: "text-emerald-400 dark:text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/20",
    darkBg: "dark:bg-emerald-500/20 dark:border-emerald-500/40",
    dot: "bg-emerald-400",
  },
  error: {
    labelKey: "common:status.error",
    color: "text-red-400 dark:text-red-400",
    bg: "bg-red-500/10 border-red-500/20",
    darkBg: "dark:bg-red-500/20 dark:border-red-500/40",
    dot: "bg-red-400",
  },
  abandoned: {
    // Muted slate distinguishes "given up / faded out" from yellow Waiting
    // (attention required).
    labelKey: "common:status.abandoned",
    color: "text-slate-400 dark:text-slate-400",
    bg: "bg-slate-500/10 border-slate-500/20",
    darkBg: "dark:bg-slate-500/20 dark:border-slate-500/40",
    dot: "bg-slate-400",
  },
  imported: {
    // Purple for imported sessions — visually distinct from active/completed
    // states, signals "read-only snapshot from another source".
    labelKey: "common:status.imported",
    color: "text-purple-400 dark:text-purple-400",
    bg: "bg-purple-500/10 border-purple-500/20",
    darkBg: "dark:bg-purple-500/20 dark:border-purple-500/40",
    dot: "bg-purple-400",
  },
};
