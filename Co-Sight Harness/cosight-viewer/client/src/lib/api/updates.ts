// SPDX-License-Identifier: Apache-2.0
/**
 * @file updates.ts
 * @description Update-status API — check whether a newer version of the app is
 * available on the configured remote.
 */

import { request } from "./core";
import type { UpdateStatusPayload } from "../types";

export const updatesApi = {
  status: () => request<UpdateStatusPayload>("/updates/status"),
  check: () =>
    request<UpdateStatusPayload>("/updates/check", {
      method: "POST",
      body: JSON.stringify({}),
    }),
};
