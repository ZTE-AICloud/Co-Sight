// SPDX-License-Identifier: Apache-2.0
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchActiveWorkspaceDirectory,
  fetchWorkspaceDirectory,
} from "../../../api/harness-api";
import { resolveWorkspaceRoot, workspaceRootFromAgentDir } from "../workspace-root";

vi.mock("../../../api/harness-api", () => ({
  fetchWorkspaceDirectory: vi.fn(),
  fetchActiveWorkspaceDirectory: vi.fn(),
}));

const byId = vi.mocked(fetchWorkspaceDirectory);
const active = vi.mocked(fetchActiveWorkspaceDirectory);

beforeEach(() => {
  byId.mockReset();
  active.mockReset();
  byId.mockResolvedValue(null);
  active.mockResolvedValue(null);
});

describe("workspaceRootFromAgentDir", () => {
  it("从约定布局反推工作区根（Windows 反斜杠也认）", () => {
    expect(
      workspaceRootFromAgentDir(
        "F:\\code\\test\\cosight-harness\\.smart-factory\\agents\\agt_97077706"
      )
    ).toBe("F:/code/test/cosight-harness");
  });

  it("POSIX 路径同样适用", () => {
    expect(workspaceRootFromAgentDir("/home/u/ws/.smart-factory/agents/agt_1")).toBe("/home/u/ws");
  });

  it("不符合布局 / 空值返回 null", () => {
    expect(workspaceRootFromAgentDir("/home/u/other/agt_1")).toBeNull();
    expect(workspaceRootFromAgentDir("")).toBeNull();
    expect(workspaceRootFromAgentDir(undefined)).toBeNull();
  });
});

describe("resolveWorkspaceRoot", () => {
  it("优先用 dir 反推，不再发请求", async () => {
    const root = await resolveWorkspaceRoot({
      dir: "F:\\code\\test\\ws\\.smart-factory\\agents\\agt_1",
      workspaceId: "ws-1",
    });

    expect(root).toBe("F:/code/test/ws");
    expect(byId).not.toHaveBeenCalled();
    expect(active).not.toHaveBeenCalled();
  });

  it("dir 不符合布局时按 workspaceId 查框架", async () => {
    byId.mockResolvedValue("F:/code/custom-workspace");

    const root = await resolveWorkspaceRoot({ dir: "F:/somewhere/else", workspaceId: "ws-1" });

    expect(root).toBe("F:/code/custom-workspace");
    expect(byId).toHaveBeenCalledWith("ws-1");
    expect(active).not.toHaveBeenCalled();
  });

  it("查不到时退回当前默认工作区（目录实例会话也走这条）", async () => {
    active.mockResolvedValue("F:/code/default-ws");

    expect(await resolveWorkspaceRoot({ dir: "F:/somewhere/else", workspaceId: "ws-1" })).toBe(
      "F:/code/default-ws"
    );
    expect(await resolveWorkspaceRoot(null)).toBe("F:/code/default-ws");
  });

  it("全部失败返回 null，不抛错", async () => {
    expect(await resolveWorkspaceRoot({ workspaceId: "ws-1" })).toBeNull();
  });
});
