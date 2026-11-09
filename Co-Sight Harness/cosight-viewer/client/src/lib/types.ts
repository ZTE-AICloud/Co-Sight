// SPDX-License-Identifier: Apache-2.0
/**
 * @file types.ts
 * @description Backward-compatibility shim.
 *
 * The implementation has been split into domain-specific modules under ./types/:
 *   ./types/common.ts      — status enums, effective-status helpers, UI config
 *   ./types/session.ts     — Session, Agent, DashboardEvent, SessionStats + status helpers
 *   ./types/transcript.ts  — Transcript types, SystemEvent, TranscriptUpdatePayload
 *   ./types/pricing.ts     — ModelPricing, CostBreakdown, CostResult
 *   ./types/updates.ts     — UpdateStatusPayload
 *   ./types/websocket.ts   — WSMessage + all WS payload types
 *   ./types/index.ts       — barrel re-export
 *
 * This shim keeps the historical import path working so the ~40 call-sites
 * that do `import type { Session } from "../lib/types"` need zero changes.
 */

export * from "./types/index";
