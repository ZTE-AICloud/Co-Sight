// SPDX-License-Identifier: Apache-2.0
/**
 * @file index.ts
 * @description Assembles the domain API modules into the single `api` object
 * consumed by the rest of the app. Existing call-sites (`api.sessions.list`,
 * `api.events.facets`, etc.) keep working unchanged.
 */

import { updatesApi } from "./updates";
import { sessionsApi } from "./sessions";
import { eventsApi } from "./events";
import { pricingApi } from "./pricing";
import { runApi } from "./run";
import { workspacesApi } from "./workspaces";

export const api = {
  updates: updatesApi,
  sessions: sessionsApi,
  events: eventsApi,
  pricing: pricingApi,
  run: runApi,
  workspaces: workspacesApi,
};
