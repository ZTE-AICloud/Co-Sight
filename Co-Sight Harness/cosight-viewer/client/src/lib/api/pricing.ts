// SPDX-License-Identifier: Apache-2.0
/**
 * @file pricing.ts
 * @description Pricing API — list model pricing rules, compute total and
 * per-session cost across the configured models.
 */

import { request } from "./core";
import type { CostResult, ModelPricing } from "../types";

export const pricingApi = {
  list: () => request<{ pricing: ModelPricing[] }>("/pricing"),

  totalCost: () =>
    request<CostResult>(`/pricing/cost?tz_offset=${new Date().getTimezoneOffset()}`),

  sessionCost: (sessionId: string) =>
    request<CostResult>(
      `/pricing/cost/${encodeURIComponent(sessionId)}?tz_offset=${new Date().getTimezoneOffset()}`
    ),
};
