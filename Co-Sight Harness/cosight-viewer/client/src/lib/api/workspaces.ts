// SPDX-License-Identifier: Apache-2.0
/**
 * @file workspaces.ts
 * @description Workspaces API — fetch workspace list from framework.
 */

import { request } from "./core";
import type { WorkspaceListResponse } from "../types";

export const workspacesApi = {
  /**
   * Fetch all workspaces and the active workspace ID.
   * Backend proxies to framework module-facing API.
   */
  list: () => request<WorkspaceListResponse>("/workspaces"),
};
