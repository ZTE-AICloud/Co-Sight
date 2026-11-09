// SPDX-License-Identifier: Apache-2.0
/**
 * @file agent-fixtures.ts
 * @description 智能体分页测试夹具。
 *
 * 分页接口的边界几乎都在「总数 / 页大小 / 最后一页」上（例如 21 条只返回 20 条、
 * 61 条要翻两页），这里用同一组函数生成数据并按真实分页语义切片，避免每个测试
 * 手写一堆相似对象、也避免把 total / hasMore 算错。
 */

import type { Agent } from "../api/agent-api";
import type { HarnessAgent } from "../api/harness-api";

const CREATED_AT = "2026-01-01T00:00:00.000Z";

export interface PageSlice<T> {
  items: T[];
  total: number;
  hasMore: boolean;
}

/** 生成 `count` 个 `Agent`（`+` 菜单 / `agent-api` 用）。 */
export function makeAgents(count: number, prefix = "Agent"): Agent[] {
  return Array.from({ length: count }, (_, index) => {
    const n = index + 1;
    return {
      id: `a${String(n)}`,
      name: `${prefix} ${String(n)}`,
      createdAt: CREATED_AT,
      updatedAt: CREATED_AT,
    };
  });
}

/** 生成 `count` 个 `HarnessAgent`（「召唤更多智能体」直接用服务端形状）。 */
export function makeHarnessAgents(count: number, prefix = "Agent"): HarnessAgent[] {
  return Array.from({ length: count }, (_, index) => {
    const n = index + 1;
    return {
      id: `a${String(n)}`,
      workspaceId: null,
      name: `${prefix} ${String(n)}`,
      description: "",
      tags: [],
      icon: "",
      status: "completed",
      createdAt: CREATED_AT,
      updatedAt: CREATED_AT,
      source: "user",
    };
  });
}

/** 按 page/pageSize 切一页；`total`/`hasMore` 与后端口径一致。 */
export function slicePage<T>(all: T[], page: number, pageSize: number): PageSlice<T> {
  const start = (page - 1) * pageSize;
  const items = all.slice(start, start + pageSize);
  return {
    items,
    total: all.length,
    hasMore: start + items.length < all.length,
  };
}
