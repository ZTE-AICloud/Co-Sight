// SPDX-License-Identifier: Apache-2.0
/**
 * @file index.ts
 * @description Barrel file that re-exports every type from the domain-specific
 * modules under ./ so the historical import path
 * `import type { Session } from "../lib/types"` keeps working via the
 * lib/types.ts shim.
 *
 * Prefer importing from specific sub-modules in new code for clarity, but the
 * barrel exists to avoid churn in the ~40 call-sites that already use the
 * monolithic import.
 */

export * from "./common";
export * from "./session";
export * from "./transcript";
export * from "./pricing";
export * from "./updates";
export * from "./websocket";
export * from "./workspace";
