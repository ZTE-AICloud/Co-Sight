// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { AGENT_PICKER_LIMIT, resolveVersion, useChatSession } from "../useChatSession";
import type { AgentPickerPage, AgentVersion } from "../../../api/agent-api";
import { makeAgents, slicePage } from "../../../test-utils/agent-fixtures";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const { socket, api } = vi.hoisted(() => ({
  socket: {
    state: "connected" as string,
    sessionId: null as string | null,
    runId: null as string | null,
    reconnectAttempts: 0,
    retryNow: vi.fn(),
    connect: vi.fn(() => Promise.resolve()),
    createInstanceAndSend: vi.fn(
      (_params: { agentId?: string; modelId?: string; prompt: string; attachments?: unknown[] }) =>
        Promise.resolve({ payload: { sessionId: "sess_1", runId: "run_1" } }),
    ),
    sendMessage: vi.fn((_params: { prompt: string; sessionId: string; attachments?: unknown[] }) =>
      Promise.resolve({
        payload: { runId: "run_2" } as Record<string, unknown>,
      }),
    ),
    sendRequest: vi.fn((_method: string, _payload: Record<string, unknown>) => Promise.resolve({})),
    switchModel: vi.fn((_sessionId: string, _modelId: string) => Promise.resolve({})),
    history: vi.fn((_params: { sessionId: string; limit?: number }) =>
      Promise.resolve({ payload: { messages: [] } }),
    ),
    subscribe: vi.fn((_sessionId: string) =>
      Promise.resolve({ payload: { subscribed: true, status: "completed" } }),
    ),
    on: vi.fn((_method: string, _handler: (event: unknown) => void) => undefined),
    off: vi.fn((_method: string, _handler: (event: unknown) => void) => undefined),
  },
  api: {
    fetchAgentPickerPage: vi.fn((): Promise<AgentPickerPage> =>
      Promise.resolve({
        items: [
          {
            id: "a1",
            name: "Agent One",
            icon: "🤖",
            createdAt: "",
            updatedAt: "",
          },
        ],
        total: 1,
        hasMore: false,
      }),
    ),
    fetchModels: vi.fn(() =>
      Promise.resolve({
        options: [{ id: "m1", name: "Model One" }],
        defaultModelId: "m1",
      }),
    ),
    fetchAgentDetail: vi.fn(() =>
      Promise.resolve({
        id: "a1",
        name: "Agent One",
        createdAt: "",
        updatedAt: "",
        commands: [
          {
            name: "build",
            namespace: "",
            description: "构建项目",
            path: "/ws/.claude/commands/build.md",
            updatedAt: "2026-01-01T00:00:00.000Z",
          },
        ],
        skills: [
          {
            name: "weather-query",
            displayName: "weather-query",
            description: "城市天气查询",
            path: "/ws/.claude/skills/weather-query",
            updatedAt: "2026-01-01T00:00:00.000Z",
          },
        ],
        versions: [
          {
            id: "v2",
            version: "2.0",
            status: "published",
            updatedAt: "2024-02-01",
          },
          {
            id: "v1",
            version: "1.0",
            status: "draft",
            updatedAt: "2024-01-01",
          },
        ],
      }),
    ),
  },
}));

vi.mock("../../../api/chat-socket", () => ({
  getChatSocket: () => socket,
  resetChatSocket: vi.fn(),
}));

vi.mock("../../../api/agent-api", () => ({
  fetchAgentPickerPage: api.fetchAgentPickerPage,
  fetchModels: api.fetchModels,
  fetchAgentDetail: api.fetchAgentDetail,
}));

const sessionApi = vi.hoisted(() => ({
  fetchAgentRuntimeSession: vi.fn(() => Promise.resolve(null)),
  fetchAgentRuntimeSessionOutcome: vi.fn(() => Promise.resolve({ status: "error" })),
  fetchSessionIdByResumeSessionId: vi.fn(() => Promise.resolve(null)),
  fetchRunDetail: vi.fn((): Promise<unknown> => Promise.resolve(null)),
  fetchSessionMessages: vi.fn(() =>
    Promise.resolve({ items: [], nextAfterSeq: null } as {
      items: unknown[];
      nextAfterSeq: number | null;
    }),
  ),
}));

vi.mock("../session-api", () => sessionApi);

/** 取出 hook 注册到 socket 上的处理器,按 method 建索引。 */
function registeredHandlers(): Record<string, (event: unknown) => void> {
  const map: Record<string, (event: unknown) => void> = {};
  for (const [method, handler] of socket.on.mock.calls) {
    map[method] = handler;
  }
  return map;
}

/** 触发一个已注册的 WS 事件;未注册直接失败,避免静默通过。 */
function fire(method: string, payload: unknown): void {
  const handler = registeredHandlers()[method];
  if (!handler) throw new Error(`no handler registered for ${method}`);
  handler({ payload });
}

/** 取最后一条消息。 */
function lastMessage(messages: { role: string; content: string }[]) {
  return messages[messages.length - 1];
}

/** 首次 send 的入参(调用前已断言过只调用一次)。 */
function sentParams() {
  const call = socket.createInstanceAndSend.mock.calls[0];
  if (!call) throw new Error("createInstanceAndSend was not called");
  return call[0];
}

/** 渲染 hook 并等到预选的智能体解析出版本、模型也选好。 */
async function renderReady() {
  const view = renderHook(() => useChatSession({ initialAgentId: "a1" }));
  await waitFor(() => expect(view.result.current.selectedAgent?.versionId).toBe("v2"));
  // 首帧 modelId 是服务端必填项,发送前必须就绪
  await waitFor(() => expect(view.result.current.modelId).not.toBe(""));
  return view;
}

beforeEach(() => {
  vi.clearAllMocks();
  socket.state = "connected";
  socket.sessionId = null;
  socket.runId = null;
  socket.reconnectAttempts = 0;
});

// ── resolveVersion ────────────────────────────────────────────────────────────

describe("resolveVersion", () => {
  const versions: AgentVersion[] = [
    { id: "v2", version: "2.0", status: "published", updatedAt: "2024-02-01" },
    { id: "v1", version: "1.0", status: "draft", updatedAt: "2024-01-01" },
  ];

  it("takes the first version when nothing is preferred", () => {
    expect(resolveVersion(versions)?.id).toBe("v2");
  });

  it("honours the preferred version when it belongs to the agent", () => {
    expect(resolveVersion(versions, "v1")?.id).toBe("v1");
  });

  it("falls back to the first version when the preferred id is unknown", () => {
    expect(resolveVersion(versions, "does-not-exist")?.id).toBe("v2");
  });

  it("returns null when the agent has no versions", () => {
    expect(resolveVersion([])).toBeNull();
  });
});

// ── 预选 ──────────────────────────────────────────────────────────────────────

describe("useChatSession preselect", () => {
  it("resolves the agent and its version from the entry param", async () => {
    const { result } = await renderReady();

    expect(result.current.selectedAgent).toMatchObject({
      id: "a1",
      name: "Agent One",
      versionId: "v2",
      versionName: "2.0",
      commands: [
        {
          name: "build",
          namespace: "",
          description: "构建项目",
          path: "/ws/.claude/commands/build.md",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
      skills: [
        {
          name: "weather-query",
          displayName: "weather-query",
          description: "城市天气查询",
          path: "/ws/.claude/skills/weather-query",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
    });
    expect(result.current.canSend).toBe(true);
  });

  it("has no selection but can still send (free chat)", async () => {
    const { result } = renderHook(() => useChatSession());

    await waitFor(() => expect(result.current.loadingModels).toBe(false));
    await waitFor(() => expect(result.current.modelId).not.toBe(""));
    expect(result.current.selectedAgent).toBeNull();
    expect(result.current.canSend).toBe(true);
  });
});

// ── 列表刷新 ──────────────────────────────────────────────────────────────────

describe("useChatSession 列表刷新", () => {
  it("刷新后新增的模型出现在列表里", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingModels).toBe(false));

    api.fetchModels.mockResolvedValueOnce({
      options: [
        { id: "m1", name: "Model One" },
        { id: "m2", name: "Model Two" },
      ],
      defaultModelId: "m1",
    });

    await act(async () => {
      await result.current.refreshModels();
    });

    expect(result.current.models).toEqual([
      { id: "m1", name: "Model One" },
      { id: "m2", name: "Model Two" },
    ]);
  });

  it("没手选过时，默认模型变化会跟着变", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.modelId).toBe("m1"));

    api.fetchModels.mockResolvedValueOnce({
      options: [
        { id: "m1", name: "Model One" },
        { id: "m2", name: "Model Two" },
      ],
      defaultModelId: "m2",
    });

    await act(async () => {
      await result.current.refreshModels();
    });

    expect(result.current.modelId).toBe("m2");
  });

  it("手选过时，默认模型变化不覆盖用户选择", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.modelId).toBe("m1"));

    act(() => {
      result.current.setModelId("m2");
    });

    api.fetchModels.mockResolvedValueOnce({
      options: [
        { id: "m1", name: "Model One" },
        { id: "m2", name: "Model Two" },
        { id: "m3", name: "Model Three" },
      ],
      defaultModelId: "m3",
    });

    await act(async () => {
      await result.current.refreshModels();
    });

    expect(result.current.modelId).toBe("m2");
  });

  it("手选的模型被删除后回退到当前默认", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.modelId).toBe("m1"));

    act(() => {
      result.current.setModelId("m2");
    });

    api.fetchModels.mockResolvedValueOnce({
      options: [{ id: "m1", name: "Model One" }],
      defaultModelId: "m1",
    });

    await act(async () => {
      await result.current.refreshModels();
    });

    expect(result.current.modelId).toBe("m1");
  });

  it("后台刷新失败时保留上一次的列表与选择", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingModels).toBe(false));
    expect(result.current.modelId).toBe("m1");

    api.fetchModels.mockRejectedValueOnce(new Error("framework down"));

    await act(async () => {
      await result.current.refreshModels();
    });

    expect(result.current.models).toEqual([{ id: "m1", name: "Model One" }]);
    expect(result.current.modelId).toBe("m1");
    expect(result.current.loadingModels).toBe(false);
  });

  it("并发刷新合并成一次请求", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingModels).toBe(false));
    expect(api.fetchModels).toHaveBeenCalledTimes(1);

    let resolveRefresh!: (value: {
      options: { id: string; name: string }[];
      defaultModelId: string;
    }) => void;
    api.fetchModels.mockImplementationOnce(
      () =>
        new Promise<{ options: { id: string; name: string }[]; defaultModelId: string }>(
          (resolve) => {
            resolveRefresh = resolve;
          },
        ),
    );

    let first!: Promise<void>;
    let second!: Promise<void>;
    await act(async () => {
      first = result.current.refreshModels();
      second = result.current.refreshModels();
    });
    expect(api.fetchModels).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveRefresh({ options: [{ id: "m1", name: "Model One" }], defaultModelId: "m1" });
      await Promise.all([first, second]);
    });
  });

  it("1 秒内的重复刷新被节流", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingModels).toBe(false));

    await act(async () => {
      await result.current.refreshModels();
    });
    await act(async () => {
      await result.current.refreshModels();
    });

    // 首载 1 次 + 刷新 1 次；第二次刷新落在节流窗口里
    expect(api.fetchModels).toHaveBeenCalledTimes(2);
  });

  it("页面重新获得焦点时自动刷新模型", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingModels).toBe(false));

    api.fetchModels.mockResolvedValueOnce({
      options: [{ id: "m2", name: "Model Two" }],
      defaultModelId: "m2",
    });

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(result.current.modelId).toBe("m2"));
  });

  it("开聊后焦点刷新不再发请求", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hello");
    });
    await waitFor(() => expect(result.current.hasSession).toBe(true));

    const callsBefore = api.fetchModels.mock.calls.length;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    expect(api.fetchModels.mock.calls.length).toBe(callsBefore);
  });

  it("首载只取前 N 个智能体", async () => {
    // 服务端有 21 个，但首屏只请求 5 个；返回的也只有 5 个
    const all = makeAgents(21);
    api.fetchAgentPickerPage.mockResolvedValueOnce(slicePage(all, 1, AGENT_PICKER_LIMIT));

    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingAgents).toBe(false));

    expect(api.fetchAgentPickerPage).toHaveBeenCalledWith(
      { pageSize: AGENT_PICKER_LIMIT, status: "completed" },
      1,
    );
    expect(result.current.agents).toHaveLength(AGENT_PICKER_LIMIT);
  });

  it("刷新智能体列表后按服务端结果整体替换", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingAgents).toBe(false));

    api.fetchAgentPickerPage.mockResolvedValueOnce({
      items: [{ id: "a2", name: "Agent Two", icon: "", createdAt: "", updatedAt: "" }],
      total: 1,
      hasMore: false,
    });

    await act(async () => {
      await result.current.refreshAgents();
    });

    expect(result.current.agents.map((agent) => agent.id)).toEqual(["a2"]);
  });

  it("智能体刷新失败时保留旧列表", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.loadingAgents).toBe(false));

    api.fetchAgentPickerPage.mockRejectedValueOnce(new Error("smart-factory down"));

    await act(async () => {
      await result.current.refreshAgents();
    });

    expect(result.current.agents.map((agent) => agent.id)).toEqual(["a1"]);
  });

  it("旧的首载失败不会清掉刷新后的智能体列表", async () => {
    let rejectInitial!: (error: Error) => void;
    const initial = new Promise<never>((_resolve, reject) => {
      rejectInitial = reject;
    });
    api.fetchAgentPickerPage
      .mockImplementationOnce(() => initial)
      .mockResolvedValueOnce({
        items: [{ id: "a2", name: "Agent Two", icon: "", createdAt: "", updatedAt: "" }],
        total: 1,
        hasMore: false,
      });

    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(api.fetchAgentPickerPage).toHaveBeenCalledTimes(1));

    // 服务已恢复：刷新先成功
    await act(async () => {
      await result.current.refreshAgents();
    });
    expect(result.current.agents.map((agent) => agent.id)).toEqual(["a2"]);

    // 首载请求晚失败：不能把刷新拿到的列表清空
    await act(async () => {
      rejectInitial(new Error("slow smart-factory"));
      await initial.catch(() => undefined);
    });

    expect(result.current.agents.map((agent) => agent.id)).toEqual(["a2"]);
  });

  it("旧的首载失败不会清掉刷新后的模型列表", async () => {
    let rejectInitial!: (error: Error) => void;
    const initial = new Promise<never>((_resolve, reject) => {
      rejectInitial = reject;
    });
    api.fetchModels
      .mockImplementationOnce(() => initial)
      .mockResolvedValueOnce({
        options: [{ id: "m2", name: "Model Two" }],
        defaultModelId: "m2",
      });

    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(api.fetchModels).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.refreshModels();
    });
    expect(result.current.models.map((model) => model.id)).toEqual(["m2"]);

    await act(async () => {
      rejectInitial(new Error("slow framework"));
      await initial.catch(() => undefined);
    });

    expect(result.current.models.map((model) => model.id)).toEqual(["m2"]);
  });
});

// ── 发送 ──────────────────────────────────────────────────────────────────────

describe("useChatSession send", () => {
  it("首帧只发 prompt + agentId + modelId,不发任何 switch", async () => {
    const { result } = await renderReady();
    await waitFor(() => expect(result.current.modelId).toBe("m1"));

    await act(async () => {
      await result.current.send("  hello  ");
    });

    expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1);
    const sent = sentParams();
    expect(Object.keys(sent).sort()).toEqual(["agentId", "modelId", "prompt"]);
    expect(sent).toEqual({ agentId: "a1", modelId: "m1", prompt: "hello" });

    // 开源版不再支持 model/mode/effort.switch —— 一个都不该发
    expect(socket.sendRequest).not.toHaveBeenCalled();
  });

  it("starts a free-chat session without agentId when no agent is selected", async () => {
    const { result } = renderHook(() => useChatSession());
    await waitFor(() => expect(result.current.modelId).not.toBe(""));

    await act(async () => {
      expect(await result.current.send("hello")).toBe(true);
    });

    expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1);
    const sent = sentParams();
    expect(sent).toEqual({ modelId: "m1", prompt: "hello" });
    expect(sent).not.toHaveProperty("agentId");
    expect(result.current.hasSession).toBe(true);
  });

  it("没有模型时首帧不发,给出可操作的提示", async () => {
    // 框架没有生效模型时不回落第一项,modelId 保持空串 —— 服务端会以 VALIDATION 拒绝
    api.fetchModels.mockResolvedValueOnce({ options: [], defaultModelId: "" });
    const { result } = renderHook(() => useChatSession({ initialAgentId: "a1" }));
    await waitFor(() => expect(result.current.selectedAgent?.versionId).toBe("v2"));
    await waitFor(() => expect(result.current.loadingModels).toBe(false));

    expect(result.current.modelId).toBe("");
    expect(result.current.canSend).toBe(false);

    await act(async () => {
      expect(await result.current.send("hello")).toBe(false);
    });

    expect(socket.createInstanceAndSend).not.toHaveBeenCalled();
    expect(result.current.error).toBe("Please select a model");
  });

  it("reuses the created session for follow-up sends", async () => {
    const { result } = await renderReady();

    await act(async () => {
      await result.current.send("first");
    });
    await act(async () => {
      await result.current.send("second");
    });

    expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1);
    expect(socket.sendMessage).toHaveBeenCalledWith({
      prompt: "second",
      sessionId: "sess_1",
    });
  });

  it("carries attachments on the first send and allows an empty prompt", async () => {
    const { result } = await renderReady();
    const attachment = {
      id: "/tmp/a.md",
      name: "/tmp/a.md",
      source: "local-path" as const,
      path: "/tmp/a.md",
    };

    await act(async () => {
      expect(await result.current.send("", [attachment])).toBe(true);
    });

    expect(sentParams()).toEqual({
      agentId: "a1",
      modelId: "m1",
      prompt: "",
      attachments: [{ path: "/tmp/a.md" }],
    });
    expect(result.current.messages[0]?.files).toEqual([
      { id: expect.any(String), name: "/tmp/a.md" },
    ]);
  });

  it("carries attachments on follow-up sends", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    await act(async () => {
      await result.current.send("", [
        {
          id: "/tmp/b.md",
          name: "/tmp/b.md",
          source: "local-path",
          path: "/tmp/b.md",
        },
      ]);
    });

    expect(socket.sendMessage).toHaveBeenLastCalledWith({
      prompt: "",
      sessionId: "sess_1",
      attachments: [{ path: "/tmp/b.md" }],
    });
  });

  it("ignores an empty prompt", async () => {
    const { result } = await renderReady();

    await act(async () => {
      await result.current.send("   ");
    });

    expect(socket.createInstanceAndSend).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("reports whether the send actually went out", async () => {
    const ready = await renderReady();
    await act(async () => {
      expect(await ready.result.current.send("hello")).toBe(true);
    });

    // 未选智能体不再是失败路径：走自由对话，同样应该返回 true
    const bare = renderHook(() => useChatSession());
    await waitFor(() => expect(bare.result.current.modelId).not.toBe(""));
    await act(async () => {
      expect(await bare.result.current.send("hello")).toBe(true);
    });
  });

  it("does not start a second session on a re-entrant send", async () => {
    const { result } = await renderReady();

    // 同一个 tick 内两次发送(双击 / 双回车):只应建一个会话
    await act(async () => {
      await Promise.all([result.current.send("one"), result.current.send("two")]);
    });

    expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1);
  });

  it("unlocks sending again after a refused send", async () => {
    const { result } = await renderReady();

    await act(async () => {
      await result.current.send("first");
    });
    await act(async () => {
      await result.current.send("second");
    });

    expect(socket.sendMessage).toHaveBeenCalledTimes(1);
  });
});

// ── WS 事件 ───────────────────────────────────────────────────────────────────

describe("useChatSession events", () => {
  it("accumulates chat.delta and commits an assistant message on chat.final", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => fire("chat.delta", { delta: "Hel" }));
    act(() => fire("chat.delta", { delta: "lo" }));
    expect(result.current.streamingContent).toBe("Hello");

    act(() => fire("chat.final", { content: "Hello" }));
    expect(result.current.streamingContent).toBe("");
    expect(lastMessage(result.current.messages)).toMatchObject({
      role: "assistant",
      content: "Hello",
    });
    expect(result.current.isLoading).toBe(false);
  });

  it("commits each text segment from message and starts a new streaming segment", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    // 第一段：delta 流式 → message 落库
    act(() => fire("chat.delta", { delta: "第一段" }));
    expect(result.current.streamingContent).toBe("第一段");
    act(() =>
      fire("message", {
        id: "msg_a1",
        role: "assistant",
        type: "text",
        content: { text: "第一段" },
        createdAt: "2024-03-01T10:00:00.000Z",
      }),
    );
    expect(result.current.streamingContent).toBe("");
    expect(lastMessage(result.current.messages)).toMatchObject({
      id: "msg_a1",
      role: "assistant",
      content: "第一段",
    });

    // 第二段：清除后重新从 0 累加，不会拼成“第一段第二段”
    act(() => fire("chat.delta", { delta: "第二段" }));
    expect(result.current.streamingContent).toBe("第二段");
    act(() =>
      fire("message", {
        id: "msg_a2",
        role: "assistant",
        type: "text",
        content: { text: "第二段" },
        createdAt: "2024-03-01T10:00:05.000Z",
      }),
    );

    expect(
      result.current.messages
        .filter((message) => message.role === "assistant")
        .map((message) => message.id),
    ).toEqual(["msg_a1", "msg_a2"]);
  });

  it("upserts chat.final by messageId instead of appending a duplicate", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("message", {
        id: "msg_a3",
        role: "assistant",
        type: "text",
        content: { text: "终稿" },
        createdAt: "2024-03-01T10:00:10.000Z",
      }),
    );
    act(() => fire("chat.final", { content: "终稿", messageId: "msg_a3" }));

    const assistants = result.current.messages.filter((message) => message.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0]).toMatchObject({ id: "msg_a3", content: "终稿" });
    expect(result.current.isLoading).toBe(false);
  });

  it("does not append an empty assistant bubble for a pure tool run", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("tool.executed", {
        toolCallId: "t9",
        toolName: "Bash",
        input: {},
        output: "ok",
      }),
    );
    const before = result.current.messages.length;

    act(() => fire("chat.final", { content: "", messageId: null }));
    expect(result.current.messages).toHaveLength(before);
    expect(result.current.isLoading).toBe(false);
  });

  it("records an executed tool call as a tool message", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("tool.executing", {
        toolCallId: "t1",
        toolName: "Bash",
        input: { command: "ls" },
      }),
    );
    expect(result.current.toolExecutions).toHaveLength(1);

    act(() =>
      fire("tool.executed", {
        toolCallId: "t1",
        toolName: "Bash",
        input: { command: "ls" },
        output: "ok",
      }),
    );
    expect(result.current.toolExecutions).toEqual([]);
    expect(lastMessage(result.current.messages)).toMatchObject({
      role: "tool",
      toolName: "Bash",
      content: "ok",
    });
  });

  it("answers an approval request over approval.respond", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("approval.request", {
        approvalId: "ap_1",
        toolName: "Bash",
        title: "Run",
        description: "",
        input: {},
        options: [],
      }),
    );
    expect(result.current.pendingApprovals[0]?.approvalId).toBe("ap_1");

    act(() => result.current.respondApproval("ap_1", "approved"));
    expect(socket.sendRequest).toHaveBeenCalledWith("approval.respond", {
      approvalId: "ap_1",
      decision: "approved",
    });
    expect(result.current.pendingApprovals).toEqual([]);
  });

  it("answers an interactive tool over tool.respond with the collected answers", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("tool.interactive", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
        input: {
          questions: [
            {
              question: "Which one?",
              multiSelect: false,
              options: [{ label: "A" }, { label: "B" }],
            },
          ],
        },
      }),
    );

    act(() => result.current.setToolAnswer("tc_1", "Which one?", "B"));
    act(() => result.current.respondTool("tc_1"));

    expect(socket.sendRequest).toHaveBeenCalledWith("tool.respond", {
      toolCallId: "tc_1",
      answers: [{ question: "Which one?", answer: ["B"] }],
    });
    expect(result.current.interactiveTools).toEqual([]);
  });

  it("aborts the current run on stop", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    await act(async () => {
      await result.current.stop();
    });

    expect(socket.sendRequest).toHaveBeenCalledWith("run.abort", {
      runId: "run_1",
    });
    expect(result.current.isLoading).toBe(false);
  });
});

// ── 运行态同步（恢复 / 多窗口 / 冲突） ───────────────────────────────────────

describe("useChatSession 运行态同步", () => {
  const approvalFrame = {
    approvalId: "ap_1",
    sessionId: "sess_1",
    runId: "run_1",
    toolName: "Bash",
    title: "Run",
    description: "",
    input: {},
    options: [],
  };

  it("重连成功后自动重新订阅并补齐历史", async () => {
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    // 恢复本身：一次 subscribe + 一次历史
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(sessionApi.fetchSessionMessages).toHaveBeenCalledTimes(1));

    act(() => fire("stateChange", { state: "disconnected" }));
    expect(result.current.connectionState).toBe("disconnected");

    socket.state = "connected";
    act(() => fire("stateChange", { state: "connected" }));

    // 重连后必须重新订阅（补挂起审批）并再拉一次历史（补断线期间的消息）
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(sessionApi.fetchSessionMessages).toHaveBeenCalledTimes(2));
    expect(socket.subscribe).toHaveBeenLastCalledWith("sess_1");
    expect(result.current.connectionState).toBe("connected");
  });

  it("断线后发送先重连并重订阅，再发消息", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    socket.state = "disconnected";
    act(() => fire("stateChange", { state: "disconnected" }));
    expect(result.current.connectionState).toBe("disconnected");

    // 重连成功；连接本身由 ChatSocket 负责，这里模拟它把状态置回 connected
    socket.connect.mockImplementationOnce(async () => {
      socket.state = "connected";
    });

    await act(async () => {
      expect(await result.current.send("second")).toBe(true);
    });

    expect(socket.connect).toHaveBeenCalled();
    expect(socket.subscribe).toHaveBeenCalledWith("sess_1");
    expect(socket.sendMessage).toHaveBeenCalledWith({
      prompt: "second",
      sessionId: "sess_1",
    });
  });

  it("重连失败时给出连接错误，而不是「请先启动会话」", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    socket.state = "disconnected";
    act(() => fire("stateChange", { state: "disconnected" }));
    socket.connect.mockRejectedValueOnce(new Error("refused"));

    await act(async () => {
      expect(await result.current.send("second")).toBe(false);
    });

    expect(result.current.error).toBe(
      "Connection lost. Automatic reconnect failed, please try again.",
    );
    expect(socket.sendMessage).not.toHaveBeenCalled();
  });

  it("重连后丢弃断线期间已结算的挂起卡，只保留服务端仍挂起的", async () => {
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(1));

    act(() => fire("approval.request", approvalFrame));
    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_1",
    ]);

    act(() => fire("stateChange", { state: "disconnected" }));
    socket.state = "connected";
    act(() => fire("stateChange", { state: "connected" }));
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(2));

    // 服务端补发只会包含仍需应答的 ap_2；断线期间被别处结算的 ap_1 不能复活
    act(() => fire("approval.request", { ...approvalFrame, approvalId: "ap_2" }));
    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_2",
    ]);
  });

  it("重连后清掉断线前执行中的工具行", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("tool.executing", {
        toolCallId: "t1",
        toolName: "WebSearch",
        input: { query: "x" },
      }),
    );
    expect(result.current.toolExecutions).toHaveLength(1);

    socket.state = "disconnected";
    act(() => fire("stateChange", { state: "disconnected" }));
    socket.state = "connected";
    act(() => fire("stateChange", { state: "connected" }));

    await waitFor(() => expect(result.current.toolExecutions).toEqual([]));
  });

  it("恢复会话时用 runs/detail 解释上一轮为何终止", async () => {
    sessionApi.fetchSessionMessages.mockResolvedValueOnce({
      items: [
        {
          id: "m1",
          sessionId: "sess_1",
          runId: "run_old",
          seq: 1,
          role: "assistant",
          type: "text",
          content: { text: "其他两个任务仍在运行中，请稍候…" },
          createdAt: "2026-10-21T07:21:49.000Z",
        },
      ],
      nextAfterSeq: null,
    });
    sessionApi.fetchRunDetail.mockResolvedValueOnce({
      id: "run_old",
      status: "failed",
      error: "服务重启",
      finishedAt: "2026-10-21T07:22:23.000Z",
    });

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));

    await waitFor(() =>
      expect(result.current.messages.some((message) => message.system)).toBe(true),
    );
    // 已知原因随界面语言渲染（测试环境是英文），不再中英混排
    expect(result.current.messages.find((message) => message.system)?.content).toContain(
      "the service restarted",
    );
  });

  it("重连时订阅失败不会清空已有的审批卡", async () => {
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(1));

    act(() => fire("approval.request", approvalFrame));
    expect(result.current.pendingApprovals).toHaveLength(1);

    socket.state = "disconnected";
    act(() => fire("stateChange", { state: "disconnected" }));
    socket.state = "connected";
    socket.subscribe.mockRejectedValueOnce(new Error("timeout"));
    act(() => fire("stateChange", { state: "connected" }));

    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledTimes(2));
    // 订阅失败时保留旧卡，用户仍可应答；不能因为拿到不 snapshot 就把入口清空
    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_1",
    ]);
  });

  it("子代理 run 的终态沿 parentRunId 归到顶层，不误报中止", async () => {
    sessionApi.fetchSessionMessages.mockResolvedValueOnce({
      items: [
        {
          id: "m1",
          sessionId: "sess_1",
          runId: "run_child",
          seq: 1,
          role: "assistant",
          type: "text",
          content: { text: "子任务输出" },
          createdAt: "2026-10-21T07:21:49.000Z",
        },
      ],
      nextAfterSeq: null,
    });
    sessionApi.fetchRunDetail
      // 最后一条消息属于子 run：状态是 aborted
      .mockResolvedValueOnce({
        id: "run_child",
        parentRunId: "run_top",
        status: "aborted",
        error: null,
        finishedAt: "2026-10-21T07:22:00.000Z",
      })
      // 顶层 run 才是"上一轮"的权威状态：failed / 服务重启
      .mockResolvedValueOnce({
        id: "run_top",
        parentRunId: null,
        status: "failed",
        error: "服务重启",
        finishedAt: "2026-10-21T07:22:23.000Z",
      });

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));

    await waitFor(() =>
      expect(result.current.messages.some((message) => message.system)).toBe(true),
    );
    expect(result.current.messages.find((message) => message.system)?.content).toContain(
      "the service restarted",
    );
  });

  it("重连次数达到阈值后进入无法连接态，并可手动重连", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    socket.reconnectAttempts = 10;
    act(() => fire("stateChange", { state: "disconnected" }));
    expect(result.current.isOffline).toBe(true);

    act(() => result.current.reconnect());
    expect(socket.retryNow).toHaveBeenCalled();
  });

  it("断线时停止不会本地假装已中止", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    socket.state = "disconnected";
    act(() => fire("stateChange", { state: "disconnected" }));

    await act(async () => {
      await result.current.stop();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe("Connection lost. Reconnect before stopping.");
    expect(socket.sendRequest).not.toHaveBeenCalledWith("run.abort", expect.anything());
  });

  it("已建立的连接断开/恢复各记一条系统事件", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    // 首连成功（建立 everConnected 标记）
    act(() => fire("stateChange", { state: "connected" }));
    act(() => fire("stateChange", { state: "disconnected" }));
    expect(
      result.current.messages.some(
        (message) => message.system && message.content === "Connection lost",
      ),
    ).toBe(true);

    socket.state = "connected";
    act(() => fire("stateChange", { state: "connected" }));
    expect(
      result.current.messages.some(
        (message) => message.system && message.content === "Reconnected",
      ),
    ).toBe(true);
  });

  it("恢复 in_progress 会话时保持锁定，收到 completed 后解锁", async () => {
    socket.subscribe.mockResolvedValueOnce({
      payload: { subscribed: true, status: "in_progress" },
    });
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));

    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_1"));
    await waitFor(() => expect(result.current.isRunning).toBe(true));
    expect(result.current.isLoading).toBe(true);

    act(() => fire("session.status", { sessionId: "sess_1", status: "completed" }));
    expect(result.current.isLoading).toBe(false);
  });

  it("恢复到已结束的会话不锁定", async () => {
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));

    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_1"));
    await waitFor(() => expect(result.current.isRunning).toBe(true));
    expect(result.current.isLoading).toBe(false);
  });

  it("恢复到等待审批的会话：弹窗出现且保持锁定", async () => {
    socket.subscribe.mockResolvedValueOnce({
      payload: { subscribed: true, status: "in_progress" },
    });
    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_1"));

    act(() => fire("approval.request", approvalFrame));

    expect(result.current.pendingApprovals[0]?.approvalId).toBe("ap_1");
    expect(result.current.isLoading).toBe(true);
  });

  it("另一个窗口结算审批后，本窗口的弹窗关闭", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });
    act(() => fire("approval.request", approvalFrame));
    expect(result.current.pendingApprovals[0]?.approvalId).toBe("ap_1");

    act(() =>
      fire("message", {
        id: "ap_1",
        sessionId: "sess_1",
        runId: "run_1",
        seq: 2,
        role: "assistant",
        type: "approval",
        status: "approved",
        content: { decision: "approved", toolCallId: "t1" },
        createdAt: "2024-03-01T10:00:00.000Z",
      }),
    );

    expect(result.current.pendingApprovals).toEqual([]);
  });

  it("同时挂起的多条审批全部保留，逐条应答互不影响", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => {
      fire("approval.request", {
        ...approvalFrame,
        approvalId: "ap_1",
        toolName: "Bash",
      });
      fire("approval.request", {
        ...approvalFrame,
        approvalId: "ap_2",
        toolName: "Write",
      });
    });
    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_1",
      "ap_2",
    ]);

    act(() => result.current.respondApproval("ap_1", "approved"));
    expect(socket.sendRequest).toHaveBeenCalledWith("approval.respond", {
      approvalId: "ap_1",
      decision: "approved",
    });
    // 只移除已应答的那一条，后到的审批仍在队列里等用户处理
    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_2",
    ]);

    act(() => result.current.respondApproval("ap_2", "rejected"));
    expect(socket.sendRequest).toHaveBeenCalledWith("approval.respond", {
      approvalId: "ap_2",
      decision: "rejected",
    });
    expect(result.current.pendingApprovals).toEqual([]);
  });

  it("重复补发同一条审批不产生重复卡", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => {
      fire("approval.request", approvalFrame);
      fire("approval.request", approvalFrame);
    });

    expect(result.current.pendingApprovals).toHaveLength(1);
  });

  it("其它窗口结算其中一条审批时，其余审批仍保留", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => {
      fire("approval.request", { ...approvalFrame, approvalId: "ap_1" });
      fire("approval.request", { ...approvalFrame, approvalId: "ap_2" });
    });

    act(() =>
      fire("message", {
        id: "ap_1",
        sessionId: "sess_1",
        runId: "run_1",
        seq: 2,
        role: "assistant",
        type: "approval",
        status: "approved",
        content: { decision: "approved", toolCallId: "t1" },
        createdAt: "2024-03-01T10:00:00.000Z",
      }),
    );

    expect(result.current.pendingApprovals.map((approval) => approval.approvalId)).toEqual([
      "ap_2",
    ]);
  });

  it("另一个窗口结算交互后，本窗口的交互弹窗关闭", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });
    act(() =>
      fire("tool.interactive", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
        input: { questions: [] },
      }),
    );
    expect(result.current.interactiveTools[0]?.toolCallId).toBe("tc_1");

    act(() =>
      fire("message", {
        id: "msg_i1",
        sessionId: "sess_1",
        runId: "run_1",
        seq: 3,
        role: "assistant",
        type: "tool_interactive",
        status: "answered",
        content: { toolCallId: "tc_1", answers: {} },
        createdAt: "2024-03-01T10:00:01.000Z",
      }),
    );

    expect(result.current.interactiveTools).toEqual([]);
  });

  it("同时挂起的多条交互各自保留答案，逐条提交互不覆盖", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => {
      fire("tool.interactive", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
        input: {
          questions: [
            {
              question: "Q1",
              multiSelect: false,
              options: [{ label: "A" }, { label: "B" }],
            },
          ],
        },
      });
      fire("tool.interactive", {
        toolCallId: "tc_2",
        toolName: "AskUserQuestion",
        input: {
          questions: [
            {
              question: "Q2",
              multiSelect: false,
              options: [{ label: "C" }, { label: "D" }],
            },
          ],
        },
      });
    });
    expect(result.current.interactiveTools.map((tool) => tool.toolCallId)).toEqual([
      "tc_1",
      "tc_2",
    ]);

    act(() => result.current.setToolAnswer("tc_2", "Q2", "D"));
    act(() => result.current.respondTool("tc_2"));

    expect(socket.sendRequest).toHaveBeenCalledWith("tool.respond", {
      toolCallId: "tc_2",
      answers: [{ question: "Q2", answer: ["D"] }],
    });
    expect(result.current.interactiveTools.map((tool) => tool.toolCallId)).toEqual(["tc_1"]);

    act(() => result.current.respondTool("tc_1"));
    expect(socket.sendRequest).toHaveBeenCalledWith("tool.respond", {
      toolCallId: "tc_1",
      answers: [],
    });
    expect(result.current.interactiveTools).toEqual([]);
  });

  it("交互超时只收掉超时的那张卡，其余挂起仍保持锁定", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => {
      fire("tool.interactive", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
        input: { questions: [] },
      });
      fire("tool.interactive", {
        toolCallId: "tc_2",
        toolName: "AskUserQuestion",
        input: { questions: [] },
      });
    });

    act(() =>
      fire("interactive.timeout", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
      }),
    );

    expect(result.current.interactiveTools.map((tool) => tool.toolCallId)).toEqual(["tc_2"]);
    expect(result.current.isLoading).toBe(true);
  });

  it("run 失败时收掉仍在执行中的工具行", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("tool.executing", {
        toolCallId: "t1",
        toolName: "Bash",
        input: { command: "ls" },
      }),
    );
    expect(result.current.toolExecutions).toHaveLength(1);

    act(() => fire("chat.error", { code: "RUN_ERROR", message: "boom" }));

    expect(result.current.toolExecutions).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  });

  it("run 失败：message(system/error) 渲染到消息流，chat.error 不重复", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("message", {
        id: "msg_err_1",
        sessionId: "sess_1",
        runId: "run_err_1",
        seq: 2,
        role: "system",
        type: "error",
        status: null,
        content: { message: "binary failed to launch" },
        createdAt: "2026-10-20T00:00:01.000Z",
      }),
    );

    const errors = () => result.current.messages.filter((message) => message.systemError);
    expect(errors()).toHaveLength(1);
    expect(errors()[0]).toMatchObject({
      id: "msg_err_1",
      content: "binary failed to launch",
      runId: "run_err_1",
    });
    // run 失败走对话流，不再叠顶部横幅
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);

    act(() =>
      fire("chat.error", {
        code: "RUN_ERROR",
        runId: "run_err_1",
        message: "binary failed to launch",
      }),
    );

    expect(errors()).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it("run 失败：没有 message 帧时用 chat.error 补一条兜底错误", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() =>
      fire("chat.error", {
        code: "RUN_ERROR",
        runId: "run_err_2",
        message: "boom without message frame",
      }),
    );

    const errors = result.current.messages.filter((message) => message.systemError);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatchObject({
      id: "error_run_err_2",
      content: "boom without message frame",
      runId: "run_err_2",
    });
    expect(result.current.error).toBeNull();
  });

  it("非 RUN_ERROR 的 chat.error 仍走顶部横幅", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => fire("chat.error", { code: "INTERNAL", message: "server exploded" }));

    expect(result.current.error).toContain("server exploded");
    expect(result.current.messages.filter((message) => message.systemError)).toHaveLength(0);
  });

  it("审批已在别处结算时视为成功，不报错", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });
    act(() => fire("approval.request", approvalFrame));

    socket.sendRequest.mockRejectedValueOnce(
      Object.assign(new Error("消息已结算"), {
        code: "CONFLICT",
        messageKey: "error.conflict.message_settled",
      }),
    );
    act(() => result.current.respondApproval("ap_1", "approved"));

    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_1"));
    expect(result.current.error).toBeNull();
    expect(result.current.pendingApprovals).toEqual([]);
  });

  it("发送撞上活跃 run 时提示、撤回乐观消息并重新锁定", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    socket.sendMessage.mockRejectedValueOnce(
      Object.assign(new Error("会话 sess_1 已有活跃 run"), {
        code: "CONFLICT",
        messageKey: "error.conflict.active_run",
      }),
    );
    socket.subscribe.mockResolvedValueOnce({
      payload: { subscribed: true, status: "in_progress" },
    });

    await act(async () => {
      expect(await result.current.send("second")).toBe(false);
    });

    expect(result.current.error).toBe(
      "A task is still running in this session. Wait for it to finish or stop it first.",
    );
    // 没有发出去的用户消息不能留在界面上
    expect(
      result.current.messages
        .filter((message) => message.role === "user")
        .map((message) => message.content),
    ).toEqual(["first"]);
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_1"));
    await waitFor(() => expect(result.current.isLoading).toBe(true));
  });
});

// ── 用户消息同步（多窗口） ───────────────────────────────────────────────────

describe("useChatSession 用户消息同步", () => {
  /** 服务端落库后广播的用户消息帧（形状与真实抓包一致）。 */
  function userFrame(text: string, id = "msg_u1") {
    return {
      id,
      sessionId: "sess_1",
      runId: null,
      seq: 15,
      role: "user",
      type: "text",
      status: null,
      content: { text },
      createdAt: "2026-10-21T01:19:24.256Z",
    };
  }

  function userContents(messages: { role: string; content: string }[]) {
    return messages.filter((message) => message.role === "user").map((message) => message.content);
  }

  it("另一个窗口收到用户消息事件后直接显示", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    act(() => fire("message", userFrame("来自另一个窗口")));

    expect(userContents(result.current.messages)).toEqual(["hi", "来自另一个窗口"]);
    expect(result.current.messages[result.current.messages.length - 1]?.id).toBe("msg_u1");
  });

  it("发送方用服务端消息原地替换乐观消息，不出现两条", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    let resolveSend: ((value: { payload: Record<string, unknown> }) => void) | undefined;
    socket.sendMessage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSend = resolve;
        }),
    );

    let pending: Promise<boolean> | undefined;
    act(() => {
      pending = result.current.send("你好");
    });
    // 服务端先广播，再返回响应
    act(() => fire("message", userFrame("你好", "msg_u2")));
    await act(async () => {
      resolveSend?.({ payload: { runId: "run_3" } });
      await pending;
    });

    expect(userContents(result.current.messages)).toEqual(["first", "你好"]);
    expect(result.current.messages[result.current.messages.length - 1]?.id).toBe("msg_u2");
  });

  it("事件与响应都带回执时按 id 幂等，重复事件也不叠加", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    socket.sendMessage.mockResolvedValueOnce({
      payload: {
        runId: "run_3",
        message: userFrame("你好", "msg_u2"),
      },
    });

    await act(async () => {
      await result.current.send("你好");
    });
    // 事件晚到（响应已归并）
    act(() => fire("message", userFrame("你好", "msg_u2")));
    // 事件重复
    act(() => fire("message", userFrame("你好", "msg_u2")));

    expect(userContents(result.current.messages)).toEqual(["first", "你好"]);
    expect(result.current.messages.filter((message) => message.id === "msg_u2")).toHaveLength(1);
  });

  it("另一个窗口发了同会话的消息时不吞掉本窗口的乐观消息", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    let resolveSend: ((value: { payload: Record<string, unknown> }) => void) | undefined;
    socket.sendMessage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSend = resolve;
        }),
    );

    let pending: Promise<boolean> | undefined;
    act(() => {
      pending = result.current.send("我的提问");
    });
    // 另一窗口的提问（内容不同）：乐观消息先入列，所以它在前面
    act(() => fire("message", userFrame("别人的提问", "msg_other")));
    expect(userContents(result.current.messages)).toEqual(["first", "我的提问", "别人的提问"]);

    await act(async () => {
      resolveSend?.({ payload: { runId: "run_3" } });
      await pending;
    });
    // 自己的回执到达后原地替换自己的乐观消息，别人的那条保留
    act(() => fire("message", userFrame("我的提问", "msg_mine")));
    expect(userContents(result.current.messages)).toEqual(["first", "我的提问", "别人的提问"]);
    expect(result.current.messages.find((message) => message.content === "我的提问")?.id).toBe(
      "msg_mine",
    );
  });

  it("事件已到但响应失败时保留已落库的消息，不误报发送失败", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("first");
    });

    socket.sendMessage.mockImplementationOnce(() => {
      // 服务端其实收下了：先广播，再让响应失败
      act(() => fire("message", userFrame("你好", "msg_u3")));
      return Promise.reject(new Error("Request timeout: send"));
    });

    await act(async () => {
      expect(await result.current.send("你好")).toBe(false);
    });

    expect(userContents(result.current.messages)).toEqual(["first", "你好"]);
    expect(result.current.error).toBeNull();
  });
});

// ── 恢复历史（REST messages/list） ─────────────────────────────────────────────

interface HistoryItemInput {
  id: string;
  type: string;
  content: Record<string, unknown>;
  seq?: number;
  role?: string;
  runId?: string | null;
}

/** `fetchSessionMessages` 的返回形状（与 session-api 的 ServiceMessagePage 对齐）。 */
type HistoryPage = { items: unknown[]; nextAfterSeq: number | null };

/** 构造一条 `messages/list` 返回的历史消息。 */
function historyItem({
  id,
  type,
  content,
  seq = 1,
  role = "assistant",
  runId = "run_1",
}: HistoryItemInput) {
  return {
    id,
    sessionId: "sess_1",
    runId,
    seq,
    role,
    type,
    content,
    createdAt: "2026-10-20T00:00:00.000Z",
  };
}

describe("useChatSession 恢复历史", () => {
  it("用 REST 历史还原文本与工具卡，并按 toolCallId 配对结果", async () => {
    sessionApi.fetchSessionMessages.mockResolvedValueOnce({
      items: [
        historyItem({
          id: "m1",
          seq: 1,
          role: "user",
          runId: null,
          type: "text",
          content: { text: "帮我看看" },
        }),
        historyItem({
          id: "m2",
          seq: 2,
          type: "text",
          content: { text: "我来执行" },
        }),
        historyItem({
          id: "m3",
          seq: 3,
          type: "tool_use",
          content: {
            toolCallId: "t1",
            toolName: "Bash",
            input: { command: "ls" },
          },
        }),
        historyItem({
          id: "m4",
          seq: 4,
          type: "tool_result",
          content: { toolCallId: "t1", output: "a.txt\n", isError: false },
        }),
        // thinking 不渲染
        historyItem({
          id: "m5",
          seq: 5,
          type: "thinking",
          content: { text: "..." },
        }),
        // 只有调用、没有结果：卡片显示 pending
        historyItem({
          id: "m6",
          seq: 6,
          type: "tool_use",
          content: {
            toolCallId: "t2",
            toolName: "Read",
            input: { file_path: "/x" },
          },
        }),
      ],
      nextAfterSeq: 6,
    });

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(result.current.historyReady).toBe(true));

    expect(result.current.messages.map((message) => message.id)).toEqual([
      "m1",
      "m2",
      "tool_t1",
      "tool_t2",
    ]);
    expect(result.current.messages.find((message) => message.id === "tool_t1")).toMatchObject({
      role: "tool",
      toolName: "Bash",
      toolOutput: "a.txt\n",
      toolError: false,
      toolPending: false,
    });
    expect(result.current.messages.find((message) => message.id === "tool_t2")?.toolPending).toBe(
      true,
    );
    // 恢复不再走 WS history
    expect(socket.history).not.toHaveBeenCalled();
  });

  it("渲染历史里的 system/error，且不再重复追加 runTerminated", async () => {
    sessionApi.fetchSessionMessages.mockResolvedValueOnce({
      items: [
        historyItem({
          id: "u1",
          seq: 1,
          role: "user",
          runId: null,
          type: "text",
          content: { text: "你好" },
        }),
        historyItem({
          id: "e1",
          seq: 2,
          role: "system",
          runId: "run_failed_1",
          type: "error",
          content: { message: "binary failed to launch" },
        }),
      ],
      nextAfterSeq: 2,
    });
    sessionApi.fetchRunDetail.mockResolvedValueOnce({
      id: "run_failed_1",
      status: "failed",
      error: "binary failed to launch",
      parentRunId: null,
    });

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(result.current.historyReady).toBe(true));

    const errors = result.current.messages.filter((message) => message.systemError);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatchObject({
      id: "e1",
      content: "binary failed to launch",
      runId: "run_failed_1",
    });
    // 历史里已有 error 消息：noticeRunTerminal 不应再补一条
    expect(
      result.current.messages.some((message) => message.content.includes("Previous run terminated")),
    ).toBe(false);
  });

  it("还原用户消息里的附件", async () => {
    sessionApi.fetchSessionMessages.mockResolvedValueOnce({
      items: [
        historyItem({
          id: "m1",
          seq: 1,
          role: "user",
          runId: null,
          type: "text",
          content: {
            text: "看看这两份材料",
            files: [{ id: "file-1", name: "/tmp/a.md" }],
          },
        }),
      ],
      nextAfterSeq: null,
    });

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(result.current.historyReady).toBe(true));

    expect(result.current.messages[0]?.files).toEqual([{ id: "file-1", name: "/tmp/a.md" }]);
  });

  it("历史未就绪时 historyReady 为 false，落位后放行", async () => {
    let resolveHistory: ((value: HistoryPage) => void) | undefined;
    sessionApi.fetchSessionMessages.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveHistory = resolve;
        }),
    );

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(sessionApi.fetchSessionMessages).toHaveBeenCalled());
    expect(result.current.historyReady).toBe(false);

    await act(async () => {
      resolveHistory?.({ items: [], nextAfterSeq: null });
    });
    await waitFor(() => expect(result.current.historyReady).toBe(true));
  });

  it("查询期间到达的实时消息在历史落位后保留", async () => {
    let resolveHistory: ((value: HistoryPage) => void) | undefined;
    sessionApi.fetchSessionMessages.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveHistory = resolve;
        }),
    );

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(sessionApi.fetchSessionMessages).toHaveBeenCalled());

    act(() =>
      fire("message", {
        id: "live1",
        sessionId: "sess_1",
        role: "assistant",
        type: "text",
        content: { text: "实时" },
        createdAt: "2026-10-20T00:00:09.000Z",
      }),
    );

    await act(async () => {
      resolveHistory?.({
        items: [
          historyItem({
            id: "m1",
            seq: 1,
            role: "user",
            runId: null,
            type: "text",
            content: { text: "历史" },
          }),
        ],
        nextAfterSeq: 1,
      });
    });
    await waitFor(() => expect(result.current.historyReady).toBe(true));

    expect(result.current.messages.map((message) => message.id)).toEqual(["m1", "live1"]);
  });

  it("历史查询失败也能恢复，historyReady 照样放行", async () => {
    sessionApi.fetchSessionMessages.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useChatSession({ initialSessionId: "sess_1" }));
    await waitFor(() => expect(result.current.historyReady).toBe(true));
    expect(result.current.messages).toHaveLength(0);
    expect(result.current.isRunning).toBe(true);
  });
});

// ── 清理 ──────────────────────────────────────────────────────────────────────

describe("useChatSession cleanup", () => {
  it("detaches every handler on unmount and never resets the shared socket", async () => {
    const { result, unmount } = await renderReady();
    await act(async () => {
      await result.current.send("hi");
    });

    socket.off.mockClear();
    unmount();

    // HANDLER_METHODS 13 个 + 挂载时单独订阅的 stateChange 清理 1 次
    expect(socket.off).toHaveBeenCalledTimes(14);

    // 卸载时不得调 resetChatSocket:那会掐断 RunPage 正要接管的会话
    const chatSocket = await import("../../../api/chat-socket");
    expect(chatSocket.resetChatSocket).not.toHaveBeenCalled();
  });

  it("never registers handlers when the page unmounts mid-connect", async () => {
    // 让 connect 悬停,好在它 resolve 之前卸载
    let releaseConnect: (() => void) | undefined;
    socket.state = "disconnected";
    socket.connect.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseConnect = resolve;
        }),
    );

    const { result, unmount } = await renderReady();

    // 不 await send:它会卡在 connect 上
    let pending: Promise<boolean> | undefined;
    act(() => {
      pending = result.current.send("hi");
    });

    unmount();
    socket.on.mockClear();

    await act(async () => {
      releaseConnect?.();
      await pending;
    });

    // 卸载后 resolve 的连接不得把处理器挂到单例上(清理已经跑过了)
    expect(socket.on).not.toHaveBeenCalled();
  });
});

// ── 按引擎 resume 标识恢复 ────────────────────────────────────────────────────

describe("useChatSession resume by resumeSessionId", () => {
  it("反查不到会话时提示会话可能已被清理", async () => {
    sessionApi.fetchSessionIdByResumeSessionId.mockResolvedValue(null);

    const { result } = renderHook(() =>
      useChatSession({ initialResumeSessionId: "cc_gone" })
    );

    await waitFor(() => expect(result.current.error).toMatch(/cleaned up|已被清理/i));

    expect(sessionApi.fetchSessionIdByResumeSessionId).toHaveBeenCalledWith("cc_gone");
    expect(result.current.isRunning).toBe(false);
  });

  it("会话详情 404 时提示会话不存在，不留下空会话", async () => {
    sessionApi.fetchAgentRuntimeSessionOutcome.mockResolvedValueOnce({
      status: "missing",
    });

    const { result } = renderHook(() =>
      useChatSession({ initialSessionId: "sess_gone" })
    );

    await waitFor(() => expect(result.current.error).toMatch(/cleaned up|已被清理/i));

    expect(result.current.hasSession).toBe(false);
    expect(result.current.isRunning).toBe(false);
  });
});

// ── 模型切换（悲观等待确认） ───────────────────────────────────────────────────

/** 建立会话并模拟本轮 run 结束，返回可切换状态。 */
async function renderIdleSession() {
  const view = await renderReady();
  await act(async () => {
    await view.result.current.send("hello");
  });
  await waitFor(() => expect(view.result.current.hasSession).toBe(true));
  act(() => {
    fire("session.status", { status: "completed" });
  });
  await waitFor(() => expect(view.result.current.isLoading).toBe(false));
  return view;
}

describe("useChatSession model switching", () => {
  it("run 结束后切换模型：发 model.switch，确认后才更新", async () => {
    const { result } = await renderIdleSession();
    socket.switchModel.mockClear();

    act(() => {
      result.current.setModelId("m2");
    });

    await waitFor(() =>
      expect(socket.switchModel).toHaveBeenCalledWith("sess_1", "m2")
    );
    await waitFor(() => expect(result.current.modelId).toBe("m2"));
  });

  it("run 进行中忽略切换，不发 model.switch", async () => {
    const { result } = await renderReady();
    await act(async () => {
      await result.current.send("hello");
    });
    // 不触发 completed：run 仍活跃
    socket.switchModel.mockClear();

    act(() => {
      result.current.setModelId("m2");
    });

    expect(socket.switchModel).not.toHaveBeenCalled();
    expect(result.current.modelId).toBe("m1");
  });

  it("切换失败时保持旧模型并给出错误", async () => {
    const { result } = await renderIdleSession();
    socket.switchModel.mockClear();
    socket.switchModel.mockRejectedValueOnce(new Error("boom"));

    act(() => {
      result.current.setModelId("m2");
    });

    await waitFor(() => expect(result.current.error).toContain("boom"));
    expect(result.current.modelId).toBe("m1");
    expect(result.current.switchingModel).toBe(false);
  });

  it("收到 settings.changed 时同步模型", async () => {
    const { result } = await renderIdleSession();

    act(() => {
      fire("settings.changed", { sessionId: "sess_1", settings: { modelId: "m2" } });
    });

    expect(result.current.modelId).toBe("m2");
  });

  it("忽略其他会话的 settings.changed", async () => {
    const { result } = await renderIdleSession();

    act(() => {
      fire("settings.changed", { sessionId: "sess_other", settings: { modelId: "m2" } });
    });

    expect(result.current.modelId).toBe("m1");
  });
});
