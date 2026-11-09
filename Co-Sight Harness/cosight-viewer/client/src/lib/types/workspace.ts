// SPDX-License-Identifier: Apache-2.0
/**
 * @file workspace.ts
 * @description Workspace type definitions.
 */

/** A workspace from the framework API */
export interface Workspace {
  id: string;
  name: string;
  directory: string | null;
  defaultModelId?: string | null;
  /** Workspace kind: "default" for the built-in default workspace (always
   *  included in session filters), "workspace" for regular user workspaces. */
  kind?: "workspace" | "default";
}

/** Response from GET /workspaces */
export interface WorkspaceListResponse {
  items: Workspace[];
  activeId: string | null;
}
