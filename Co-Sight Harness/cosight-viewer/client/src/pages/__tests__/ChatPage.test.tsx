// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ChatPage } from "../ChatPage";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const { socket, api } = vi.hoisted(() => ({
  socket: {
    state: "connected" as string,
    sessionId: null as string | null,
    runId: null as string | null,
    reconnectAttempts: 0,
    retryNow: vi.fn(),
    connect: vi.fn(() => Promise.resolve()),
    createInstanceAndSend: vi.fn((_params: { agentId?: string; modelId?: string; prompt: string }) =>
      Promise.resolve({ payload: { sessionId: "sess_1", runId: "run_1" } }),
    ),
    sendMessage: vi.fn((_params: { prompt: string; sessionId: string }) =>
      Promise.resolve({ payload: { runId: "run_2" } }),
    ),
    sendRequest: vi.fn((_method: string, _payload: Record<string, unknown>) => Promise.resolve({})),
    subscribe: vi.fn((_sessionId: string) => Promise.resolve()),
    on: vi.fn((_method: string, _handler: (event: unknown) => void) => undefined),
    off: vi.fn((_method: string, _handler: (event: unknown) => void) => undefined),
  },
  api: {
    fetchAgentPickerPage: vi.fn(() =>
      Promise.resolve({
        items: [{ id: "a1", name: "Agent One", createdAt: "", updatedAt: "" }],
        total: 1,
        hasMore: false,
      }),
    ),
    fetchModels: vi.fn(() =>
      Promise.resolve({
        options: [
          { id: "m1", name: "Model One" },
          { id: "m2", name: "Model Two" },
        ],
        defaultModelId: "m1",
      }),
    ),
    fetchAgentDetail: vi.fn(() =>
      Promise.resolve({
        id: "a1",
        name: "Agent One",
        createdAt: "",
        updatedAt: "",
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

vi.mock("../../api/chat-socket", () => ({
  getChatSocket: () => socket,
  resetChatSocket: vi.fn(),
}));

vi.mock("../../api/agent-api", () => ({
  fetchAgentPickerPage: api.fetchAgentPickerPage,
  fetchModels: api.fetchModels,
  fetchAgentDetail: api.fetchAgentDetail,
}));

// 恢复会话时的会话详情/历史查询(走 HTTP,单独 mock 掉)
const {
  fetchAgentRuntimeSession,
  fetchAgentRuntimeSessionOutcome,
  fetchSessionIdByResumeSessionId,
  fetchSessionMessages,
} = vi.hoisted(() => ({
    fetchAgentRuntimeSession: vi.fn(),
    fetchAgentRuntimeSessionOutcome: vi.fn(),
    fetchSessionIdByResumeSessionId: vi.fn(),
    fetchSessionMessages: vi.fn((sessionId: string, _limit: number) =>
      Promise.resolve({
        items: [
          {
            id: "m1",
            sessionId,
            runId: "run_old",
            seq: 1,
            role: "user",
            type: "text",
            content: { text: "earlier question" },
            createdAt: "2024-03-01T10:00:00.000Z",
          },
          {
            id: "m2",
            sessionId,
            runId: "run_old",
            seq: 2,
            role: "assistant",
            type: "text",
            content: { text: "earlier answer" },
            createdAt: "2024-03-01T10:00:05.000Z",
          },
        ],
        nextAfterSeq: 2,
      }),
    ),
  }));

vi.mock("../chat/session-api", () => ({
  fetchAgentRuntimeSession,
  fetchAgentRuntimeSessionOutcome,
  fetchSessionIdByResumeSessionId,
  fetchSessionMessages,
  fetchRunDetail: vi.fn(() => Promise.resolve(null)),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderPage(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ChatPage />
    </MemoryRouter>,
  );
}

/** 触发一个 hook 已注册的 WS 事件;未注册直接失败,避免静默通过。 */
function fire(method: string, payload: unknown): void {
  const handlers: Record<string, (event: unknown) => void> = {};
  for (const [registered, handler] of socket.on.mock.calls) {
    handlers[registered] = handler;
  }
  const handler = handlers[method];
  if (!handler) throw new Error(`no handler registered for ${method}`);
  handler({ payload });
}

/** 首次 send 的入参(调用前已断言过只调用一次)。 */
function sentParams() {
  const call = socket.createInstanceAndSend.mock.calls[0];
  if (!call) throw new Error("createInstanceAndSend was not called");
  return call[0];
}

function composerInput(): HTMLElement {
  return screen.getByLabelText("Input message...");
}

/** 输入框是 contentEditable：写文本后手动发 input 事件，走组件的 onInput。 */
function setComposerText(text: string) {
  const editor = composerInput();
  editor.textContent = text;
  fireEvent.input(editor);
}

function typeAndSend(text: string) {
  setComposerText(text);
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

/** 让当前这一轮 run 结束(清掉 isLoading,使发送按钮回到 Send)。 */
async function finishTurn(content: string) {
  await act(async () => {
    fire("chat.final", { content });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  socket.state = "connected";
  socket.sessionId = null;
  socket.runId = null;
  socket.reconnectAttempts = 0;
  fetchAgentRuntimeSession.mockResolvedValue(null);
  fetchAgentRuntimeSessionOutcome.mockImplementation(async (sessionId: string) => {
    const detail = await fetchAgentRuntimeSession(sessionId);
    // 旧用例用 null 表示“详情暂时读不到”，继续恢复；404 才用 missing
    return detail ? { status: "ok", detail } : { status: "error" };
  });
  fetchSessionIdByResumeSessionId.mockResolvedValue(null);
});

// ── 空态 ──────────────────────────────────────────────────────────────────────

describe("ChatPage empty state", () => {
  it("shows the title and composer with no agent chip", async () => {
    renderPage("/chat");

    expect(await screen.findByText("Co-Sight Harness")).toBeInTheDocument();
    expect(composerInput()).toBeInTheDocument();
  });

  it("sends as free chat when no agent is selected", async () => {
    renderPage("/chat");
    await screen.findByText("Co-Sight Harness");

    typeAndSend("hello");

    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1));
    const sent = socket.createInstanceAndSend.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(sent).toMatchObject({ prompt: "hello" });
    expect(sent).not.toHaveProperty("agentId");
  });

  it("resumeSessionId 反查不到时提示会话可能已被清理", async () => {
    fetchSessionIdByResumeSessionId.mockResolvedValue(null);

    renderPage("/chat?resumeSessionId=cc_gone");

    expect(
      await screen.findByText(/cleaned up|已被清理/i),
    ).toBeInTheDocument();
  });
});

// ── 预选 ──────────────────────────────────────────────────────────────────────

describe("ChatPage agent preselection", () => {
  it("shows the agent from ?agentId as a chip", async () => {
    renderPage("/chat?agentId=a1");

    expect(await screen.findByText("Agent One")).toBeInTheDocument();
  });

  it("首屏尚未连接时发送按钮仍可用（首帧按需连接）", async () => {
    // 单例 socket 在没人 connect 之前就是 disconnected；这不是"断线"，
    // 首帧由 startSession 自己 connect，按钮不能被锁死。
    socket.state = "disconnected";
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Model" })).toHaveTextContent("Model One"),
    );

    setComposerText("hello");
    const sendButton = screen.getByRole("button", { name: "Send" });
    expect(sendButton).not.toBeDisabled();
    fireEvent.click(sendButton);

    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1));
  });

  it("首帧带 agentId 与选中的模型(versionId 不再参与)", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");
    // 等模型加载完:首帧要把模型一起带上
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Model" })).toHaveTextContent("Model One"),
    );

    typeAndSend("hello");

    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1));
    expect(sentParams()).toEqual({
      agentId: "a1",
      modelId: "m1",
      prompt: "hello",
    });
  });
});

// ── 对话态 ────────────────────────────────────────────────────────────────────

describe("ChatPage conversation", () => {
  it("首帧带 agentId/modelId,续聊只带 sessionId", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Model" })).toHaveTextContent("Model One"),
    );

    typeAndSend("first");
    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1));

    // 首帧:agentId + 选中的模型
    expect(sentParams()).toEqual({
      agentId: "a1",
      modelId: "m1",
      prompt: "first",
    });

    await finishTurn("first answer");

    typeAndSend("second");
    await waitFor(() => expect(socket.sendMessage).toHaveBeenCalledTimes(1));
    expect(socket.sendMessage).toHaveBeenCalledWith({
      prompt: "second",
      sessionId: "sess_1",
    });
    // 第二轮不该再建会话
    expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1);
  });

  it("replaces the model label with the picked one", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    // 默认选中 isDefault 的模型
    const trigger = screen.getByRole("button", { name: "Model" });
    expect(trigger).toHaveTextContent("Model One");

    // 点开 → 列表出现在 body 里(portal),不再被 composer 的 overflow 裁掉
    fireEvent.click(trigger);
    const listbox = await screen.findByRole("listbox", { name: "Model" });
    expect(listbox.parentElement).toBe(document.body);
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.getByRole("option", { name: /Model One/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // 选另一个 → 触发器文案立刻替换,列表收起
    fireEvent.click(screen.getByRole("option", { name: /Model Two/ }));
    await waitFor(() => expect(trigger).toHaveTextContent("Model Two"));
    expect(screen.queryByRole("listbox", { name: "Model" })).not.toBeInTheDocument();
  });

  it("打开模型下拉时重拉列表，新模型直接出现并成为默认", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");
    const trigger = screen.getByRole("button", { name: "Model" });
    expect(trigger).toHaveTextContent("Model One");

    // 宿主在设置弹窗里新增并启用了模型 —— iframe 不会重建，只能靠打开下拉时刷新
    api.fetchModels.mockResolvedValueOnce({
      options: [{ id: "m3", name: "Model Three" }],
      defaultModelId: "m3",
    });

    fireEvent.click(trigger);

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
    expect(screen.getByRole("option", { name: /Model Three/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => expect(trigger).toHaveTextContent("Model Three"));
  });

  it("打开智能体子菜单时重拉列表，删除/新增立刻生效", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    api.fetchAgentPickerPage.mockResolvedValueOnce({
      items: [{ id: "a2", name: "Agent Two", createdAt: "", updatedAt: "" }],
      total: 1,
      hasMore: false,
    });

    fireEvent.click(screen.getByRole("button", { name: "Open more options" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Agent" }));

    expect(await screen.findByRole("option", { name: /Agent Two/ })).toBeInTheDocument();
  });

  it("locks the agent once the conversation starts, but keeps the model switchable after the run ends", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    // 开聊前:`+`(智能体)与模型选择器都在
    expect(screen.getByRole("button", { name: "Open more options" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Model" })).toBeInTheDocument();

    typeAndSend("first");
    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalledTimes(1));
    await finishTurn("first answer");

    // 开聊后:智能体不可再改，但 `+` 保留「添加文件」入口
    const plus = screen.getByRole("button", { name: "Open more options" });
    fireEvent.click(plus);
    expect(await screen.findByRole("menuitem", { name: "Add file" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Agent" })).not.toBeInTheDocument();

    // run 结束后模型重新可切换；智能体仍不可移除
    expect(screen.getByRole("button", { name: "Model" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Remove agent")).not.toBeInTheDocument();

    expect(screen.getByText("Agent One")).toBeInTheDocument();
    expect(screen.getAllByText("Model One").length).toBeGreaterThan(0);
  });

  it("resumes an existing session from ?agentRuntimeSessionId", async () => {
    fetchAgentRuntimeSession.mockResolvedValue({
      id: "sess_old",
      instanceId: "inst_1",
      agentId: "a1",
      modelId: "m2",
      status: "active",
      effort: "low",
      approvalMode: "read_only",
      resumeSessionId: null,
    });

    renderPage("/chat?agentRuntimeSessionId=sess_old");

    // 进入对话态并渲染历史消息
    expect(await screen.findByText("earlier question")).toBeInTheDocument();
    expect(screen.getByText("earlier answer")).toBeInTheDocument();

    // 不是新建会话
    expect(socket.createInstanceAndSend).not.toHaveBeenCalled();
    expect(socket.sessionId).toBe("sess_old");

    // 恢复时补一次 subscribe:服务端据此回放已挂起的审批/提问
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_old"));

    // 会话里已存在的那条 run 被拾回,停止按钮因此能命中它
    await waitFor(() => expect(socket.runId).toBe("run_old"));

    // 智能体与模型按会话详情还原(而不是默认值)
    await waitFor(() => expect(screen.getByText("Agent One")).toBeInTheDocument());
    expect(screen.getAllByText("Model Two").length).toBeGreaterThan(0);

    // 续聊复用同一会话,不再建新会话
    typeAndSend("follow up");
    await waitFor(() => expect(socket.sendMessage).toHaveBeenCalledTimes(1));
    expect(socket.sendMessage).toHaveBeenCalledWith({
      prompt: "follow up",
      sessionId: "sess_old",
    });
    expect(socket.createInstanceAndSend).not.toHaveBeenCalled();
  });

  it("断线时显示重连横幅，重连成功后消失", async () => {
    fetchAgentRuntimeSession.mockResolvedValue({
      id: "sess_old",
      instanceId: "inst_1",
      agentId: "a1",
      modelId: "m2",
      status: "active",
      effort: "low",
      approvalMode: "read_only",
      resumeSessionId: null,
    });

    renderPage("/chat?agentRuntimeSessionId=sess_old");
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_old"));

    act(() => fire("stateChange", { state: "disconnected" }));
    expect(screen.getByText("Connection lost. Reconnecting (attempt 1)…")).toBeInTheDocument();

    socket.state = "connected";
    act(() => fire("stateChange", { state: "connected" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Connection lost. Reconnecting (attempt 1)…"),
      ).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("Reconnected. Syncing…")).toBeInTheDocument();
  });

  it("重连次数达到阈值后显示无法连接，并可手动重连", async () => {
    fetchAgentRuntimeSession.mockResolvedValue({
      id: "sess_old",
      instanceId: "inst_1",
      agentId: "a1",
      modelId: "m2",
      status: "active",
      effort: "low",
      approvalMode: "read_only",
      resumeSessionId: null,
    });

    renderPage("/chat?agentRuntimeSessionId=sess_old");
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_old"));

    socket.reconnectAttempts = 10;
    act(() => fire("stateChange", { state: "disconnected" }));

    expect(
      screen.getByText("Cannot reach the server. Make sure smart-factory is running."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reconnect"));
    expect(socket.retryNow).toHaveBeenCalled();
  });

  it("共享 socket 已离线时，首屏挂载后能跟随后台重连恢复", async () => {
    socket.state = "disconnected";
    socket.reconnectAttempts = 10;
    renderPage("/chat");

    expect(
      await screen.findByText("Cannot reach the server. Make sure smart-factory is running."),
    ).toBeInTheDocument();

    // 后台自动重连成功：即使还没建立会话，挂载时就订阅了 stateChange，横幅应消失
    socket.state = "connected";
    socket.reconnectAttempts = 0;
    act(() => fire("stateChange", { state: "connected" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Cannot reach the server. Make sure smart-factory is running."),
      ).not.toBeInTheDocument(),
    );
    setComposerText("hello");
    expect(screen.getByRole("button", { name: "Send" })).not.toBeDisabled();
  });

  it("新标签页首次打开已有会话不显示「已重新连接」", async () => {
    fetchAgentRuntimeSession.mockResolvedValue({
      id: "sess_old",
      instanceId: "inst_1",
      agentId: "a1",
      modelId: "m2",
      status: "active",
      effort: "low",
      approvalMode: "read_only",
      resumeSessionId: null,
    });

    renderPage("/chat?agentRuntimeSessionId=sess_old");
    await waitFor(() => expect(socket.subscribe).toHaveBeenCalledWith("sess_old"));

    expect(screen.queryByText("Reconnected. Syncing…")).not.toBeInTheDocument();
  });

  it("会话已被清理时提示无法恢复", async () => {
    fetchAgentRuntimeSessionOutcome.mockResolvedValueOnce({ status: "missing" });

    renderPage("/chat?agentRuntimeSessionId=sess_gone");

    expect(await screen.findByText(/cleaned up|已被清理/i)).toBeInTheDocument();
    expect(screen.queryByText("earlier question")).not.toBeInTheDocument();
  });

  it("still resumes when the session detail lookup fails", async () => {
    fetchAgentRuntimeSession.mockResolvedValue(null);

    renderPage("/chat?agentRuntimeSessionId=sess_old");

    // 详情拿不到也不能阻断恢复:消息照样出来,会话照样能续
    expect(await screen.findByText("earlier question")).toBeInTheDocument();
    typeAndSend("follow up");
    await waitFor(() =>
      expect(socket.sendMessage).toHaveBeenCalledWith({
        prompt: "follow up",
        sessionId: "sess_old",
      }),
    );
  });

  it("renders streamed assistant text", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    typeAndSend("hi");
    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalled());

    await act(async () => {
      fire("chat.delta", { delta: "Streamed answer" });
    });

    expect(await screen.findByText("Streamed answer")).toBeInTheDocument();
  });

  it("renders an approval request from the run", async () => {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    typeAndSend("hi");
    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalled());

    await act(async () => {
      fire("approval.request", {
        approvalId: "ap_1",
        toolName: "Bash",
        title: "Run a command",
        description: "wants to run ls",
        input: { command: "ls" },
        options: [{ value: "approved", label: "Approve" }],
      });
    });

    expect(await screen.findByText("Run a command")).toBeInTheDocument();
    // `value` 是语义来源：按钮文案按 i18n 渲染，与服务端下发的 label 无关
    fireEvent.click(screen.getByRole("button", { name: "Allow once" }));

    expect(socket.sendRequest).toHaveBeenCalledWith("approval.respond", {
      approvalId: "ap_1",
      decision: "approved",
    });
  });
});

// ── 交互问答：选项 + 「其他」 ────────────────────────────────────────────────

describe("ChatPage AskUserQuestion", () => {
  /** 进入对话态并挂起一张交互卡。 */
  async function showQuestion(input: {
    question: string;
    multiSelect: boolean;
    options: Array<{ label: string }>;
  }) {
    renderPage("/chat?agentId=a1");
    await screen.findByText("Agent One");

    typeAndSend("hi");
    await waitFor(() => expect(socket.createInstanceAndSend).toHaveBeenCalled());

    await act(async () => {
      fire("tool.interactive", {
        toolCallId: "tc_1",
        toolName: "AskUserQuestion",
        input: { questions: [input] },
      });
    });

    expect(await screen.findByText(input.question)).toBeInTheDocument();
  }

  it("提交单选「其他」时用自定义文本替代选项", async () => {
    await showQuestion({
      question: "Which one?",
      multiSelect: false,
      options: [{ label: "A" }, { label: "B" }],
    });

    // 没答题前不能提交
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("Other: Which one?"), {
      target: { value: "custom choice" },
    });

    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(socket.sendRequest).toHaveBeenCalledWith("tool.respond", {
      toolCallId: "tc_1",
      answers: [{ question: "Which one?", answer: ["custom choice"] }],
    });
  });

  it("多选时「其他」追加在已选选项后面", async () => {
    await showQuestion({
      question: "Which ones?",
      multiSelect: true,
      options: [{ label: "A" }, { label: "B" }],
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "A" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("Other: Which ones?"), {
      target: { value: "C" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(socket.sendRequest).toHaveBeenCalledWith("tool.respond", {
      toolCallId: "tc_1",
      answers: [{ question: "Which ones?", answer: ["A", "C"] }],
    });
  });

});
