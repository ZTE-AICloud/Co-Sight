// SPDX-License-Identifier: Apache-2.0
/**
 * @file events.ts
 * @description Events API — query dashboard events with rich filters and fetch
 * facet values for filter dropdowns.
 */

import { request } from "./core";
import type { DashboardEvent } from "../types";

export const eventsApi = {
  list: (params?: {
    event_type?: string[];
    tool_name?: string[];
    agent_id?: string[];
    session_id?: string | string[];
    q?: string;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    const csv = (v?: string[]) => (v && v.length > 0 ? v.join(",") : undefined);
    const et = csv(params?.event_type);
    const tn = csv(params?.tool_name);
    const ag = csv(params?.agent_id);
    const sid = Array.isArray(params?.session_id) ? csv(params?.session_id) : params?.session_id;
    if (et) qs.set("event_type", et);
    if (tn) qs.set("tool_name", tn);
    if (ag) qs.set("agent_id", ag);
    if (sid) qs.set("session_id", sid);
    if (params?.q) qs.set("q", params.q);
    if (params?.from) qs.set("from", params.from);
    if (params?.to) qs.set("to", params.to);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<{
      events: DashboardEvent[];
      limit: number;
      offset: number;
      total: number;
    }>(`/events${q ? `?${q}` : ""}`);
  },

  facets: () => request<{ event_types: string[]; tool_names: string[] }>("/events/facets"),
};
