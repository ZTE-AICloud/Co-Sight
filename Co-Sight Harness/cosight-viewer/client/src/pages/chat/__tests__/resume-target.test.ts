// SPDX-License-Identifier: Apache-2.0
/**
 * @file resume-target.test.ts
 * @description 「恢复对话」的 id 解析：有缓存 id 就不再反查，没有才反查。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSessionIdByResumeSessionId } from "../session-api";
import { resolveResumeTarget } from "../resume-target";

vi.mock("../session-api", () => ({
  fetchSessionIdByResumeSessionId: vi.fn(),
}));

const lookup = vi.mocked(fetchSessionIdByResumeSessionId);

describe("resolveResumeTarget", () => {
  beforeEach(() => {
    lookup.mockReset();
  });

  it("会话上已记录 smart-factory id 时直接用它，不再反查", async () => {
    const target = await resolveResumeTarget({
      id: "viewer-session-1",
      agent_runtime_session_id: "sess_abc",
    });

    expect(target).toBe("sess_abc");
    expect(lookup).not.toHaveBeenCalled();
  });

  it("老数据没有记录时按看板 id 反查", async () => {
    lookup.mockResolvedValue("sess_looked_up");

    const target = await resolveResumeTarget({
      id: "viewer-session-2",
      agent_runtime_session_id: null,
    });

    expect(target).toBe("sess_looked_up");
    expect(lookup).toHaveBeenCalledWith("viewer-session-2");
  });

  it("反查不到时返回 null，交给调用方提示恢复失败", async () => {
    lookup.mockResolvedValue(null);

    await expect(resolveResumeTarget({ id: "viewer-session-3" })).resolves.toBeNull();
  });
});
