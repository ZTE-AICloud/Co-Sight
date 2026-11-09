// SPDX-License-Identifier: Apache-2.0
/**
 * @file StatusBadge.tsx
 * @description Defines reusable React components for displaying the status of agents and sessions in a visually distinct way using badges. The AgentStatusBadge component shows the current status of an agent with an optional pulsing effect for active states, while the SessionStatusBadge component indicates the status of a session. Both components utilize predefined configurations for consistent styling across the application.
 */
import { useTranslation } from "react-i18next";
import { STATUS_CONFIG, SESSION_STATUS_CONFIG } from "../lib/types";
import type { EffectiveAgentStatus, EffectiveSessionStatus } from "../lib/types";

interface AgentStatusBadgeProps {
  status: EffectiveAgentStatus;
  pulse?: boolean;
}

export function AgentStatusBadge({ status, pulse }: AgentStatusBadgeProps) {
  const { t } = useTranslation();
  const config = STATUS_CONFIG[status];
  // "waiting" pulses by default so the user's eye is drawn to sessions that
  // need their attention, matching the pulsing for active/working states.
  const shouldPulse = pulse ?? (status === "working" || status === "waiting");

  return (
    <span className={`badge ${config.bg} ${config.darkBg} ${config.color}`}>
      <span
        className={`w-1.5 h-1.5 rounded-full ${config.dot} ${
          shouldPulse ? "animate-pulse-dot" : ""
        }`}
      />
      {t(config.labelKey)}
    </span>
  );
}

interface SessionStatusBadgeProps {
  status: EffectiveSessionStatus;
  pulse?: boolean;
}

export function SessionStatusBadge({ status, pulse }: SessionStatusBadgeProps) {
  const { t } = useTranslation();
  const config = SESSION_STATUS_CONFIG[status];
  const shouldPulse = pulse ?? status === "waiting";
  return (
    <span className={`badge ${config.bg} ${config.darkBg} ${config.color}`}>
      <span
        className={`w-1.5 h-1.5 rounded-full ${config.dot}${
          shouldPulse ? " animate-pulse-dot" : ""
        }`}
        aria-hidden="true"
      />
      {t(config.labelKey)}
    </span>
  );
}
