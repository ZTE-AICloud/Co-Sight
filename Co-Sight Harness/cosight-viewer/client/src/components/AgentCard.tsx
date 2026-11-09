// SPDX-License-Identifier: Apache-2.0
/**
 * @file AgentCard.tsx
 * @description Defines the AgentCard component that displays a summary of an agent's information, including its name, status, task, current tool, and timestamps. The card is clickable and navigates to the agent's session details when clicked. It also visually distinguishes active agents with a border highlight.
 */
import { useTranslation } from "react-i18next";
import { Bot, GitBranch, Clock, Wrench, Cpu, Coins } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AgentStatusBadge } from "./StatusBadge";
import { effectiveAgentStatus, isAgentAwaitingInput } from "../lib/types";
import type { Agent, Session } from "../lib/types";
import { formatDuration, timeAgo, formatModelName, pathBasename, fmtCost } from "../lib/format";

interface AgentCardProps {
  agent: Agent;
  /** Optional session data for richer main-agent rendering (model, cwd,
   *  cost). Subagent display ignores this. When omitted, the card falls
   *  back to the original minimal layout. */
  session?: Session;
  label?: string;
  onClick?: () => void;
}

export function AgentCard({ agent, session, label, onClick }: AgentCardProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const isWaiting = agent.status === "waiting" || isAgentAwaitingInput(agent);
  const status = effectiveAgentStatus(agent);
  const isActive = agent.status === "working";
  const isMain = agent.type === "main";

  // Session-level metadata applies to every card in the session — main and
  // subagents alike. Subtitle differs by type: main uses model+cwd (its
  // auto-generated name carries no info), subagents stick with their
  // subagent_type label (more useful than repeating the session model).
  const model = formatModelName(session?.model);
  const cwdBase = pathBasename(session?.cwd);
  const cost = typeof session?.cost === "number" ? session.cost : 0;
  const subtitle = isMain
    ? [model, cwdBase].filter(Boolean).join(" · ") || null
    : label || agent.subagent_type;

  function handleClick() {
    if (onClick) {
      onClick();
    } else {
      navigate(`/sessions/${agent.session_id}`);
    }
  }

  return (
    <div
      onClick={handleClick}
      className={`rounded-xl border border-border/50 dark:border-border/30 bg-surface-1 dark:bg-surface-2/40 p-4 cursor-pointer hover:shadow-sm dark:hover:shadow-black/20 hover:border-border/70 dark:hover:border-border/50 transition-all ${
        isWaiting
          ? "border-l-2 border-l-amber-400"
          : isActive
            ? "border-l-2 border-l-emerald-400"
            : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-3 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0 overflow-hidden">
          <div
            className={`w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 ring-1 ring-inset ${
              isMain
                ? "bg-indigo-100 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300 dark:ring-indigo-500/20"
                : "bg-violet-100 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/20"
            }`}
          >
            {isMain ? <Bot className="w-3.5 h-3.5" /> : <GitBranch className="w-3.5 h-3.5" />}
          </div>
          <div className="min-w-0 overflow-hidden">
            <p className="text-sm font-medium text-tertiary dark:text-secondary truncate">
              {agent.name}
            </p>
            {subtitle && (
              <p className="text-[11px] text-faint dark:text-faint/80 truncate">{subtitle}</p>
            )}
          </div>
        </div>
        <AgentStatusBadge status={status} />
      </div>

      {agent.task && (
        <p className="text-xs text-faint dark:text-faint/80 mb-3 line-clamp-2 leading-relaxed">
          {agent.task}
        </p>
      )}

      <div className="flex items-center gap-3 text-[11px] text-faint dark:text-faint/80 min-w-0 overflow-hidden flex-wrap">
        {agent.current_tool && (
          <span className="flex items-center gap-1 flex-shrink-0">
            <Wrench className="w-3 h-3" />
            {agent.current_tool}
          </span>
        )}
        {model && !agent.current_tool && (
          <span className="flex items-center gap-1 flex-shrink-0">
            <Cpu className="w-3 h-3" />
            {model}
          </span>
        )}
        {cost > 0 && (
          <span className="flex items-center gap-1 flex-shrink-0">
            <Coins className="w-3 h-3" />
            {fmtCost(cost)}
          </span>
        )}
        {agent.ended_at ? (
          <>
            <span className="flex items-center gap-1 flex-shrink-0">
              <Clock className="w-3 h-3" />
              {t("ran")}
              {formatDuration(agent.started_at, agent.ended_at)}
            </span>
            <span className="text-faint flex-shrink-0">{timeAgo(agent.ended_at)}</span>
          </>
        ) : (
          <span className="flex items-center gap-1 flex-shrink-0">
            <Clock className="w-3 h-3" />
            {timeAgo(agent.updated_at || agent.started_at)}
          </span>
        )}
        <span className="ml-auto font-mono text-faint flex-shrink-0">
          {agent.session_id.slice(0, 8)}
        </span>
      </div>
    </div>
  );
}
