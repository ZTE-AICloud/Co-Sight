// SPDX-License-Identifier: Apache-2.0
/**
 * `fetchAgentDetail` 的数据源约定。
 *
 * 这里钉住的是**请求次数**:选中一个智能体只该打一次单条详情接口。
 * 旧实现是"全量翻页再 find",agent 多时一次选择要串行拉 ⌈总数/60⌉ 页,
 * 而结果里只有 name/icon/description 和一个伪造版本真的被用到。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AGENT_RUNTIME_API_URL } from "../../config/api-config";
import { fetchAgentDetail } from "../agent-api";

const fetchMock = vi.fn();

function respondAgent(body: unknown): unknown {
  return { ok: true, status: 200, statusText: "OK", json: async () => body };
}

function serviceAgent(id: string): Record<string, unknown> {
  return {
    id,
    workspaceId: "ws-1",
    name: "四则运算",
    description: "帮我算数",
    tags: ["自定义"],
    icon: "",
    status: "ready",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchAgentDetail", () => {
  it("只打一次单条接口,并带上 OSS 伪造的唯一版本", async () => {
    fetchMock.mockResolvedValueOnce(respondAgent(serviceAgent("agt_42")));

    const detail = await fetchAgentDetail("agt_42");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${AGENT_RUNTIME_API_URL}/agents/agt_42`);
    expect(detail).toMatchObject({ id: "agt_42", name: "四则运算", description: "帮我算数" });
    // 界面不呈现版本概念:固定一个 `default`,让上游 resolveVersion 原样可用
    expect(detail?.versions).toHaveLength(1);
    expect(detail?.versions[0]).toMatchObject({ id: "default", version: "default", status: "published" });
  });

  it("查不到时返回 null(调用方据此提示没有可用版本)", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404, statusText: "Not Found" });

    await expect(fetchAgentDetail("agt_missing")).resolves.toBeNull();
  });
});
