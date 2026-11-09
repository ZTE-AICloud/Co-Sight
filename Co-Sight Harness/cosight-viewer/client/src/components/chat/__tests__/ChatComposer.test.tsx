// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AgentCommand, AgentSkill } from "../../../api/agent-api";
import type { EngineSlashCommand } from "../../../api/harness-api";
import type { UseChatSessionResult } from "../../../pages/chat/useChatSession";
import {
  ChatComposer,
  ENGINE_COMMANDS_CACHE_KEY,
  sameSlashCommands,
} from "../ChatComposer";

const { fetchEngineCommandsMock } = vi.hoisted(() => ({
  fetchEngineCommandsMock: vi.fn(),
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

vi.mock("../../../attachments/useAttachmentPicker", () => ({
  useAttachmentPicker: () => ({ pick: vi.fn(), element: null }),
}));

vi.mock("../../../api/harness-api", () => ({
  fetchEngineCommands: fetchEngineCommandsMock,
}));

beforeEach(() => {
  window.localStorage.clear();
  fetchEngineCommandsMock.mockReset();
  fetchEngineCommandsMock.mockResolvedValue([]);
});

function cacheEngineCommands(items: EngineSlashCommand[]): void {
  window.localStorage.setItem(
    ENGINE_COMMANDS_CACHE_KEY,
    JSON.stringify({ fetchedAt: Date.now(), items }),
  );
}

const commands: AgentCommand[] = [
  {
    name: "build",
    namespace: "",
    description: "构建项目并跑全量校验",
    path: "/ws/.claude/commands/build.md",
    updatedAt: "2026-01-01T00:00:00.000Z",
  },
  {
    name: "test",
    namespace: "ci",
    description: "跑测试",
    path: "/ws/.claude/commands/ci/test.md",
    updatedAt: "2026-01-01T00:00:00.000Z",
  },
];

const skills: AgentSkill[] = [
  {
    name: "weather-query",
    displayName: "weather-query",
    description: "城市天气查询",
    path: "/ws/.claude/skills/weather-query",
    updatedAt: "2026-01-01T00:00:00.000Z",
  },
];

const send = vi.fn(() => Promise.resolve(true));

function makeSession(
  agentCommands: AgentCommand[],
  agentSkills: AgentSkill[] = [],
  selectedAgent: UseChatSessionResult["selectedAgent"] | undefined = undefined
): UseChatSessionResult {
  return {
    agents: [],
    loadingAgents: false,
    models: [],
    loadingModels: false,
    selectedAgent:
      selectedAgent === undefined
        ? {
            id: "agt_1",
            name: "天气智能体",
            versionId: "v1",
            resolving: false,
            commands: agentCommands,
            skills: agentSkills,
          }
        : selectedAgent,
    selectAgent: vi.fn(() => Promise.resolve()),
    clearAgent: vi.fn(),
    hasSession: false,
    modelId: "",
    setModelId: vi.fn(),
    switchingModel: false,
    refreshAgents: vi.fn(() => Promise.resolve()),
    refreshModels: vi.fn(() => Promise.resolve()),
    refreshingModels: false,
    messages: [],
    historyReady: true,
    streamingContent: "",
    toolExecutions: [],
    pendingApprovals: [],
    interactiveTools: [],
    toolAnswers: {},
    setToolAnswer: vi.fn(),
    isRunning: false,
    connectionState: "connected",
    reconnectAttempts: 0,
    isOffline: false,
    reconnect: vi.fn(),
    isLoading: false,
    error: null,
    clearError: vi.fn(),
    canSend: true,
    send,
    stop: vi.fn(() => Promise.resolve()),
    respondApproval: vi.fn(),
    respondTool: vi.fn(),
  };
}

function Harness({
  session,
  initial = "",
}: {
  session: UseChatSessionResult;
  initial?: string;
}) {
  const [prompt, setPrompt] = useState(initial);
  return (
    <ChatComposer
      session={session}
      prompt={prompt}
      onPromptChange={setPrompt}
      onBrowseMoreAgents={vi.fn()}
      variant="hero"
    />
  );
}

function renderComposer(
  agentCommands: AgentCommand[] = commands,
  agentSkills: AgentSkill[] = skills
) {
  send.mockClear();
  render(<Harness session={makeSession(agentCommands, agentSkills)} />);
  return screen.getByRole("textbox");
}

describe("sameSlashCommands", () => {
  const base = [
    { kind: "command" as const, name: "a", description: "A" },
    { kind: "skill" as const, name: "b", description: "B" },
  ];

  it("treats identical lists as unchanged", () => {
    expect(sameSlashCommands(base, base.map((item) => ({ ...item })))).toBe(true);
  });

  it("detects description, order and length changes", () => {
    expect(
      sameSlashCommands(base, [{ ...base[0]!, description: "changed" }, base[1]!]),
    ).toBe(false);
    expect(sameSlashCommands(base, [base[1]!, base[0]!])).toBe(false);
    expect(sameSlashCommands(base, [base[0]!])).toBe(false);
  });
});

describe("<ChatComposer /> slash commands", () => {
  it("opens the menu grouped by commands and skills after typing /", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");

    expect(await screen.findByText("/build")).toBeInTheDocument();
    expect(screen.getByText("/test")).toBeInTheDocument();
    expect(screen.getByText("/weather-query")).toBeInTheDocument();
    expect(screen.getByText("构建项目并跑全量校验")).toBeInTheDocument();
    expect(screen.getByText("城市天气查询")).toBeInTheDocument();
    expect(screen.getByText("run.slashCommandsSection")).toBeInTheDocument();
    expect(screen.getByText("run.slashSkillsSection")).toBeInTheDocument();
  });

  it("filters commands and skills by the typed query", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/wea");

    expect(await screen.findByText("/weather-query")).toBeInTheDocument();
    expect(screen.queryByText("/build")).toBeNull();
    expect(screen.queryByText("run.slashCommandsSection")).toBeNull();
  });

  it("inserts the highlighted command as a token instead of sending", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");
    await screen.findByText("/build");
    await user.type(editor, "{ArrowDown}{Enter}");

    expect(editor.textContent).toBe("/test ");
    // 命令变成不可编辑的 token，退格会整颗删除
    expect(editor.querySelector(".slash-command-chip")?.textContent).toBe("/test");
    expect(send).not.toHaveBeenCalled();
  });

  it("inserts a skill from the skill section", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/wea");
    await screen.findByText("/weather-query");
    await user.type(editor, "{Enter}");

    expect(editor.textContent).toBe("/weather-query ");
    expect(editor.querySelector(".slash-command-chip")?.textContent).toBe("/weather-query");
    expect(send).not.toHaveBeenCalled();
  });

  it("Tab also inserts the command", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");
    await screen.findByText("/build");
    await user.type(editor, "{Tab}");

    expect(editor.textContent).toBe("/build ");
    expect(send).not.toHaveBeenCalled();
  });

  it("Escape closes the menu without changing the text", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");
    await screen.findByText("/build");
    await user.type(editor, "{Escape}");

    await waitFor(() => expect(screen.queryByText("/build")).toBeNull());
    expect(editor.textContent).toBe("/");
  });

  it("clicking an option inserts it", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");
    const options = await screen.findAllByRole("option");
    await user.click(options[1]!);

    expect(editor.textContent).toBe("/test ");
  });

  it("sends the inserted command and its arguments", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");
    await screen.findByText("/build");
    await user.type(editor, "{Enter}");
    await user.type(editor, "--fast{Enter}");

    expect(send).toHaveBeenCalledWith("/build --fast", []);
  });

  it("sends normally when the menu is closed", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "hello{Enter}");

    expect(send).toHaveBeenCalledWith("hello", []);
  });

  it("does not open without commands or skills", async () => {
    const user = userEvent.setup();
    const editor = renderComposer([], []);

    await user.type(editor, "/");

    expect(screen.queryByText("/build")).toBeNull();
  });

  it("does not open when / is not the first token", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "请用 /bu");

    expect(screen.queryByText("/build")).toBeNull();
  });

  it("selected agents never query the engine command list", async () => {
    const user = userEvent.setup();
    const editor = renderComposer();

    await user.type(editor, "/");

    await screen.findByText("/build");
    expect(fetchEngineCommandsMock).not.toHaveBeenCalled();
  });

  it("free chat uses the engine command list", async () => {
    fetchEngineCommandsMock.mockResolvedValue([
      { name: "task-monitor", description: "监控", argumentHint: "" },
    ]);

    render(<Harness session={makeSession([], [], null)} initial="" />);
    await waitFor(() => expect(fetchEngineCommandsMock).toHaveBeenCalledTimes(1));

    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "/");

    expect(await screen.findByText("/task-monitor")).toBeInTheDocument();
  });

  it("free chat does not refetch while the command list is fresh", async () => {
    fetchEngineCommandsMock.mockResolvedValue([
      { name: "task-monitor", description: "监控", argumentHint: "" },
    ]);

    const session = makeSession([], [], null);
    const { unmount } = render(<Harness session={session} initial="" />);
    await waitFor(() => expect(fetchEngineCommandsMock).toHaveBeenCalledTimes(1));

    const editor = screen.getByRole("textbox");
    const user = userEvent.setup();
    await user.type(editor, "/");
    await screen.findByText("/task-monitor");

    expect(fetchEngineCommandsMock).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("remounting the page fetches the latest engine commands again", async () => {
    const first = render(<Harness session={makeSession([], [], null)} initial="" />);
    await waitFor(() => expect(fetchEngineCommandsMock).toHaveBeenCalledTimes(1));
    first.unmount();

    render(<Harness session={makeSession([], [], null)} initial="" />);
    await waitFor(() => expect(fetchEngineCommandsMock).toHaveBeenCalledTimes(2));
  });

  it("shows cached engine commands immediately while refreshing", async () => {
    cacheEngineCommands([{ name: "cached-cmd", description: "缓存", argumentHint: "" }]);
    // 刷新请求一直不返回：菜单必须先用缓存
    fetchEngineCommandsMock.mockReturnValue(new Promise(() => undefined));

    render(<Harness session={makeSession([], [], null)} initial="" />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "/");

    expect(await screen.findByText("/cached-cmd")).toBeInTheDocument();
  });

  it("shows a loading row on the first cold start", async () => {
    let resolveFetch!: (items: EngineSlashCommand[]) => void;
    fetchEngineCommandsMock.mockReturnValue(
      new Promise<EngineSlashCommand[]>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    render(<Harness session={makeSession([], [], null)} initial="" />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "/");

    expect(await screen.findByText("run.slashCommandsLoading")).toBeInTheDocument();

    await act(async () => {
      resolveFetch([{ name: "late-cmd", description: "晚到", argumentHint: "" }]);
    });

    expect(await screen.findByText("/late-cmd")).toBeInTheDocument();
    expect(screen.queryByText("run.slashCommandsLoading")).not.toBeInTheDocument();
  });

  it("does not send when Enter is pressed while commands are loading", async () => {
    fetchEngineCommandsMock.mockReturnValue(new Promise(() => undefined));

    render(<Harness session={makeSession([], [], null)} initial="" />);
    const user = userEvent.setup();
    const editor = screen.getByRole("textbox");
    await user.type(editor, "/");
    await screen.findByText("run.slashCommandsLoading");

    await user.keyboard("{Enter}");

    expect(send).not.toHaveBeenCalled();
  });

  it("writes the fetched engine commands to the local cache", async () => {
    fetchEngineCommandsMock.mockResolvedValue([
      { name: "persisted-cmd", description: "持久化", argumentHint: "" },
    ]);

    render(<Harness session={makeSession([], [], null)} initial="" />);

    await waitFor(() => {
      const raw = window.localStorage.getItem(ENGINE_COMMANDS_CACHE_KEY);
      expect(raw).toContain("persisted-cmd");
    });
  });

  it("does not reopen a menu the user already dismissed when commands arrive", async () => {
    let resolveFetch!: (items: EngineSlashCommand[]) => void;
    fetchEngineCommandsMock.mockReturnValue(
      new Promise<EngineSlashCommand[]>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    render(<Harness session={makeSession([], [], null)} initial="" />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "/");
    await screen.findByText("run.slashCommandsLoading");

    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("run.slashCommandsLoading")).not.toBeInTheDocument();

    await act(async () => {
      resolveFetch([{ name: "late-cmd", description: "晚到", argumentHint: "" }]);
    });

    expect(screen.queryByText("/late-cmd")).not.toBeInTheDocument();
  });
});
