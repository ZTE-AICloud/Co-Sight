// SPDX-License-Identifier: Apache-2.0
/**
 * @file api.ts
 * @description Backward-compatibility shim.
 *
 * The implementation has been split into domain-specific modules under ./api/:
 *   ./api/core.ts      — request helpers (request, dedupedRequest)
 *   ./api/updates.ts   — updates namespace
 *   ./api/sessions.ts  — sessions namespace
 *   ./api/events.ts    — events namespace
 *   ./api/pricing.ts   — pricing namespace
 *   ./api/run.ts       — cwd suggestions (`/run/cwds`)
 *   ./api/index.ts     — assembles the `api` object
 *
 * This shim keeps the historical import path working so the ~11 call-sites
 * that do `import { api } from "../lib/api"` need zero changes.
 */

export { api } from "./api/index";
