// SPDX-License-Identifier: Apache-2.0
/**
 * @file sessions.ts
 * @description Sessions API — list, get, create, import, export, transcripts,
 * and transcript-watch lifecycle endpoints.
 */

import { request, dedupedRequest, BASE } from "./core";
import type {
  Agent,
  DashboardEvent,
  Session,
  SessionStats,
  TranscriptListResult,
  TranscriptResult,
} from "../types";

export const sessionsApi = {
  facets: () => dedupedRequest<{ cwds: string[] }>("/sessions/facets"),

  list: (params?: {
    status?: string;
    q?: string;
    cwd?: string;
    cwds?: string; // comma-separated list of directories
    sort_by?: string;
    sort_desc?: boolean;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.q) qs.set("q", params.q);
    if (params?.cwd) qs.set("cwd", params.cwd);
    if (params?.cwds) qs.set("cwds", params.cwds);
    if (params?.sort_by) qs.set("sort_by", params.sort_by);
    if (params?.sort_desc !== undefined) qs.set("sort_desc", String(params.sort_desc));
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const queryString = qs.toString();
    return request<{ sessions: Session[]; total: number; limit: number; offset: number }>(
      `/sessions${queryString ? `?${queryString}` : ""}`
    );
  },

  get: (id: string, opts?: { limit?: number; offset?: number; include_events?: boolean }) => {
    const qs = new URLSearchParams();
    if (opts?.limit) qs.set("limit", String(opts.limit));
    if (opts?.offset) qs.set("offset", String(opts.offset));
    // Default: don't load events (they're loaded via api.events.list pagination).
    // Only SessionDetail's legacy event timeline needs this, and it uses
    // api.events.list() instead.
    qs.set("include_events", String(opts?.include_events ?? false));
    const q = qs.toString();
    return request<{
      session: Session;
      agents: Agent[];
      events: DashboardEvent[] | null;
      total?: number;
      has_more?: boolean;
    }>(`/sessions/${encodeURIComponent(id)}${q ? `?${q}` : ""}`);
  },

  stats: (id: string) => request<SessionStats>(`/sessions/${encodeURIComponent(id)}/stats`),

  transcripts: (id: string) =>
    request<TranscriptListResult>(`/sessions/${encodeURIComponent(id)}/transcripts`),

  transcript: (
    id: string,
    params?: {
      agent_id?: string;
      limit?: number;
      offset?: number;
      after?: number;
      before?: number;
      /** Load messages around the given uuid (for task-flow scroll-to-message linkage) */
      around_uuid?: string;
      /** Client-reported file size — server skips O(n) scan if unchanged */
      fileSize?: number;
    }
  ) => {
    const qs = new URLSearchParams();
    if (params?.agent_id) qs.set("agent_id", params.agent_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    if (params?.after != null) qs.set("after", String(params.after));
    if (params?.before != null) qs.set("before", String(params.before));
    if (params?.around_uuid) qs.set("around_uuid", params.around_uuid);
    if (params?.fileSize != null) qs.set("fileSize", String(params.fileSize));
    const q = qs.toString();
    return request<TranscriptResult>(
      `/sessions/${encodeURIComponent(id)}/transcript${q ? `?${q}` : ""}`
    );
  },

  // Start watching a session's transcript for real-time updates
  watch: (id: string, params: { clientId: string }) =>
    request<{ ok: boolean; sessionId: string; clientId: string }>(
      `/sessions/${encodeURIComponent(id)}/watch`,
      { method: "POST", body: JSON.stringify(params) }
    ),

  // Stop watching a session's transcript
  unwatch: (id: string, params: { clientId: string }) =>
    request<{ ok: boolean; sessionId: string; clientId: string }>(
      `/sessions/${encodeURIComponent(id)}/unwatch`,
      { method: "POST", body: JSON.stringify(params) }
    ),

  // Update client heartbeat for watched session
  heartbeat: (id: string, params: { clientId: string }) =>
    request<{ ok: boolean }>(`/sessions/${encodeURIComponent(id)}/heartbeat`, {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Create a new session (for "New Session" button)
  create: (params: { id: string; name?: string; cwd?: string; status?: string }) =>
    request<{ session: Session; created: boolean }>("/sessions", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Export session data as ZIP (returns URL for download)
  exportUrl: (id: string) => `${BASE}/sessions/${encodeURIComponent(id)}/export`,

  // Import a session from a ZIP file upload
  import: async (
    file: File
  ): Promise<{
    success: boolean;
    session: Session;
    files: { jsonl: number; subagents: number; tasks: number };
    message: string;
  }> => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`${BASE}/sessions/import`, {
      method: "POST",
      body: formData,
    }).then((r) => {
      if (!r.ok) {
        return r.json().then((err) => {
          throw new Error(err.error?.message || `导入失败（${r.status}）`);
        });
      }
      return r.json();
    });
  },
};
