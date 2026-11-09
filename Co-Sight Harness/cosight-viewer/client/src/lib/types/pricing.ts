// SPDX-License-Identifier: Apache-2.0
/**
 * @file pricing.ts
 * @description Model pricing rules and cost computation result types.
 */

export interface ModelPricing {
  model_pattern: string;
  display_name: string;
  input_per_mtok: number;
  output_per_mtok: number;
  cache_read_per_mtok: number;
  cache_write_per_mtok: number;
  updated_at: string;
}

export interface CostBreakdown {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost: number;
  matched_rule: string | null;
}

export interface CostResult {
  total_cost: number;
  breakdown: CostBreakdown[];
  daily_costs: Array<{ date: string; cost: number }>;
}
