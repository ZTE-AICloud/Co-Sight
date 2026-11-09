// SPDX-License-Identifier: Apache-2.0
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAgentProduction } from "../../../api/harness-api";
import type { ChatMessage, ToolExecution } from "../useChatSession";
import { agentLinkRoots, useSessionFiles } from "../useSessionFiles";

vi.mock("../../../api/harness-api", () => ({
  fetchAgentProduction: vi.fn(),
}));

const production = vi.mocked(fetchAgentProduction);

const agentDir = "C:/ws/.smart-factory/agents/agt_1";
const runtimeRoot = `${agentDir}/development/output/agents/demo/v1`;

function toolMessage(
  overrides: Partial<ChatMessage> & Pick<ChatMessage, "id" | "toolName" | "toolInput">
): ChatMessage {
  return {
    role: "tool",
    content: "",
    timestamp: 1,
    ...overrides,
  };
}

describe("useSessionFiles", () => {
  beforeEach(() => {
    production.mockReset();
    production.mockResolvedValue({
      product: {
        name: "demo",
        version: "v1",
        path: "output/agents/demo/v1",
        updatedAt: "",
      },
    });
  });

  it("collects successful Write/Edit tools under the runtime root", async () => {
    const messages: ChatMessage[] = [
      toolMessage({
        id: "t1",
        toolName: "Write",
        toolInput: { file_path: `${runtimeRoot}/hate.txt` },
      }),
      toolMessage({
        id: "t2",
        toolName: "Edit",
        toolInput: { file_path: `${runtimeRoot}/love.txt` },
      }),
    ];

    const { result } = renderHook(() =>
      useSessionFiles({
        messages,
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.runtimeRoot).toBe(runtimeRoot));

    expect(result.current.files).toHaveLength(2);
    expect(result.current.files[0]).toMatchObject({
      name: "hate.txt",
      change: "written",
      inRoot: true,
      relativePath: "hate.txt",
    });
    expect(result.current.files[1]).toMatchObject({
      name: "love.txt",
      change: "modified",
      inRoot: true,
    });
  });

  it("resolves relative paths against the runtime root", async () => {
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: "nested/out.md" },
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.runtimeRoot).toBe(runtimeRoot));
    expect(result.current.files[0]?.path).toBe(`${runtimeRoot}/nested/out.md`);
    expect(result.current.files[0]?.relativePath).toBe("nested/out.md");
  });

  it("ignores failed and pending writes", async () => {
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: `${runtimeRoot}/a.txt` },
            toolError: true,
          }),
          toolMessage({
            id: "t2",
            toolName: "Write",
            toolInput: { file_path: `${runtimeRoot}/b.txt` },
            toolPending: true,
          }),
          toolMessage({
            id: "t3",
            toolName: "Write",
            toolInput: { file_path: `${runtimeRoot}/ok.txt` },
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.files).toHaveLength(1));
    expect(result.current.files[0]?.name).toBe("ok.txt");
  });

  it("shows executing writes as writing and keeps the completed entry", async () => {
    const executions: ToolExecution[] = [
      {
        toolCallId: "t9",
        toolName: "Write",
        input: { file_path: `${runtimeRoot}/new.txt` },
        status: "executing",
      },
    ];

    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: `${runtimeRoot}/done.txt` },
          }),
        ],
        toolExecutions: executions,
        agentId: "agt_1",
        agentDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.files).toHaveLength(2));
    const writing = result.current.files.find((file) => file.name === "new.txt");
    expect(writing?.writing).toBe(true);
    expect(result.current.files.find((file) => file.name === "done.txt")?.writing).toBe(false);
  });

  it("deduplicates by path and keeps the last change", async () => {
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: `${runtimeRoot}/same.txt` },
            timestamp: 1,
          }),
          toolMessage({
            id: "t2",
            toolName: "Edit",
            toolInput: { file_path: `C:\\ws\\.smart-factory\\agents\\agt_1\\development\\output\\agents\\demo\\v1\\same.txt` },
            timestamp: 2,
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.files).toHaveLength(1));
    expect(result.current.files[0]).toMatchObject({
      name: "same.txt",
      change: "modified",
      at: 2,
    });
  });

  it("resolves Linux absolute and relative paths without lowercasing", async () => {
    const linuxDir = "/home/u/.smart-factory/agents/agt_1";
    const linuxRoot = "/home/u/.smart-factory/agents/agt_1/development/output/agents/demo/v1";
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: `${linuxRoot}/UART_PATTERN_GUIDE.md` },
          }),
          toolMessage({
            id: "t2",
            toolName: "Edit",
            toolInput: { file_path: "nested/uart_patterns.h" },
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir: linuxDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.runtimeRoot).toBe(linuxRoot));
    expect(result.current.files.map((file) => file.path)).toEqual([
      `${linuxRoot}/UART_PATTERN_GUIDE.md`,
      `${linuxRoot}/nested/uart_patterns.h`,
    ]);
    expect(result.current.files[0]).toMatchObject({
      name: "UART_PATTERN_GUIDE.md",
      inRoot: true,
      relativePath: "UART_PATTERN_GUIDE.md",
    });
    expect(result.current.files[1]).toMatchObject({
      name: "uart_patterns.h",
      inRoot: true,
      relativePath: "nested/uart_patterns.h",
    });
  });

  it("prefers the server-provided runtimeDir and skips /production", async () => {
    const serverRuntimeDir = `${agentDir}/development/output/agents/echo/v2`;
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: "pics/answer.png" },
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentRuntimeDir: serverRuntimeDir,
        agentSource: "user",
      })
    );

    await waitFor(() => expect(result.current.runtimeRoot).toBe(serverRuntimeDir));
    expect(result.current.files[0]?.path).toBe(`${serverRuntimeDir}/pics/answer.png`);
    // 有了 runtimeDir 就不该再打 /production
    expect(production).not.toHaveBeenCalled();
  });

  it("uses the definition directory directly for builtin agents", async () => {
    const { result } = renderHook(() =>
      useSessionFiles({
        messages: [
          toolMessage({
            id: "t1",
            toolName: "Write",
            toolInput: { file_path: `${agentDir}/builtin.txt` },
          }),
        ],
        toolExecutions: [],
        agentId: "agt_1",
        agentDir,
        agentSource: "builtin",
      })
    );

    await waitFor(() => expect(result.current.runtimeRoot).toBe(agentDir));
    expect(production).not.toHaveBeenCalled();
    expect(result.current.files[0]?.inRoot).toBe(true);
  });
});

describe("agentLinkRoots", () => {
  const agentDir = "C:/ws/.smart-factory/agents/agt_1";
  const runtimeRoot = `${agentDir}/development/output/agents/demo/v1`;

  it("按 cwd → development → 智能体根 → 工作区根 排优先级", () => {
    expect(agentLinkRoots(runtimeRoot, agentDir)).toEqual([
      runtimeRoot,
      `${agentDir}/development`,
      agentDir,
      "C:/ws",
    ]);
  });

  it("反斜杠路径归一，且重复项只留一次", () => {
    expect(agentLinkRoots(runtimeRoot, "C:\\ws\\.smart-factory\\agents\\agt_1")).toEqual([
      runtimeRoot,
      `${agentDir}/development`,
      agentDir,
      "C:/ws",
    ]);
    expect(agentLinkRoots(agentDir, agentDir)).toEqual([
      agentDir,
      `${agentDir}/development`,
      "C:/ws",
    ]);
  });

  it("没有 runtime 根 / 智能体目录时只返回能确定的项", () => {
    expect(agentLinkRoots(null)).toEqual([]);
    expect(agentLinkRoots(null, agentDir)).toEqual([
      `${agentDir}/development`,
      agentDir,
      "C:/ws",
    ]);
  });
});
