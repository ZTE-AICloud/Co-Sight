// SPDX-License-Identifier: Apache-2.0
/**
 * @file websocket.ts
 * @description WebSocket message envelope and the per-event payload types
 * carried inside it. Also includes the import-progress message shape (sent
 * over the same socket).
 */

import type { Session, Agent, DashboardEvent } from "./session";
import type { TranscriptUpdatePayload } from "./transcript";
import type { UpdateStatusPayload } from "./updates";

export interface CcConfigChangedPayload {
  source: "dashboard" | "fs";
  action?: "write" | "delete";
  scope?: "user" | "project";
  type?: string;
  name?: string | null;
  paths?: string[];
}

export interface WSMessage {
  type:
    | "session_created"
    | "session_updated"
    | "agent_created"
    | "agent_updated"
    | "new_event"
    | "update_status"
    | "cc_config_changed"
    | "transcript_update";
  data:
    | Session
    | Agent
    | DashboardEvent
    | UpdateStatusPayload
    | CcConfigChangedPayload
    | TranscriptUpdatePayload;
  timestamp: string;
}
