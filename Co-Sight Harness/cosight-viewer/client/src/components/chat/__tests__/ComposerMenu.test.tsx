// SPDX-License-Identifier: Apache-2.0
import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef } from "react";
import type { Agent } from "../../../api/agent-api";
import { AGENT_PICKER_LIMIT } from "../../../pages/chat/useChatSession";
import { makeAgents, slicePage } from "../../../test-utils/agent-fixtures";
import { AGENT_SEARCH_LIMIT, ComposerMenu } from "../ComposerMenu";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const { fetchAgentPickerPage } = vi.hoisted(() => ({
  fetchAgentPickerPage: vi.fn(),
}));

vi.mock("../../../api/agent-api", () => ({
  fetchAgentPickerPage,
  // useChatSession（只为拿 AGENT_PICKER_LIMIT）在模块初始化时会引用这两个导入
  fetchAgentDetail: vi.fn(),
  fetchModels: vi.fn(),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const AGENTS: Agent[] = makeAgents(9);
const SELECTED: Agent = { id: "a2", name: "Agent 2", createdAt: "", updatedAt: "" };

/** 渲染菜单,并返回各回调便于断言。 */
function renderMenu(
  options: { canSelectAgent?: boolean; selectedAgent?: Agent | null } = {},
) {
  const handlers = {
    onSelectAgent: vi.fn(),
    onBrowseMoreAgents: vi.fn(),
    onPickLocalFiles: vi.fn(),
    onOpenAgentSection: vi.fn(),
    onClose: vi.fn(),
  };

  function Harness() {
    const triggerRef = useRef<HTMLButtonElement>(null);
    return (
      <>
        <button ref={triggerRef} type="button">
          +
        </button>
        <ComposerMenu
          open
          triggerRef={triggerRef}
          agents={AGENTS}
          selectedAgent={options.selectedAgent === undefined ? SELECTED : options.selectedAgent}
          canSelectAgent={options.canSelectAgent ?? true}
          {...handlers}
        />
      </>
    );
  }

  render(<Harness />);
  return handlers;
}

/** 打开某个二级面板。 */
function openSection(label: string) {
  fireEvent.click(screen.getByRole("menuitem", { name: label }));
}

/** 在智能体面板里输入搜索词。 */
function typeSearch(value: string) {
  fireEvent.change(screen.getByLabelText("Search agents"), { target: { value } });
}

beforeEach(() => {
  fetchAgentPickerPage.mockReset();
});

// ── 一级菜单 ──────────────────────────────────────────────────────────────────

describe("ComposerMenu root level", () => {
  it("lists add-file above the agent entry", () => {
    renderMenu();

    // 审批模式 / 推理强度属于 agent-runtime 的能力,开源版不支持,已移除
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Add file");
    expect(items[1]).toHaveTextContent("Agent");
    expect(screen.queryByRole("menuitem", { name: "Approval Mode" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reasoning Effort" })).not.toBeInTheDocument();
  });

  it("hides the agent entry once a session is established", () => {
    renderMenu({ canSelectAgent: false });

    expect(screen.getAllByRole("menuitem")).toHaveLength(1);
    expect(screen.getByRole("menuitem", { name: "Add file" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Agent" })).not.toBeInTheDocument();
  });

  it("shows no second level until an entry is opened", () => {
    renderMenu();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

// ── 添加文件二级面板 ──────────────────────────────────────────────────────────

describe("ComposerMenu file panel", () => {
  it("opens the local-file panel and reports the pick", () => {
    const handlers = renderMenu();
    openSection("Add file");

    fireEvent.click(screen.getByRole("menuitem", { name: "Local file" }));

    expect(handlers.onPickLocalFiles).toHaveBeenCalledTimes(1);
    expect(handlers.onClose).toHaveBeenCalled();
  });
});

// ── 智能体二级面板：默认展示 ──────────────────────────────────────────────────

describe("ComposerMenu agent panel", () => {
  it("shows only the first N agents while the search box is empty", () => {
    renderMenu();
    openSection("Agent");

    expect(screen.getAllByRole("option")).toHaveLength(AGENT_PICKER_LIMIT);
    expect(fetchAgentPickerPage).not.toHaveBeenCalled();
  });

  it("pins the selected agent when it is outside the first page", () => {
    const selected: Agent = { id: "a9", name: "Agent 9", createdAt: "", updatedAt: "" };
    renderMenu({ selectedAgent: selected });
    openSection("Agent");

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(AGENT_PICKER_LIMIT + 1);
    expect(options[0]).toHaveTextContent("Agent 9");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("asks the caller to refresh agents when the panel opens", () => {
    const handlers = renderMenu();
    openSection("Agent");

    expect(handlers.onOpenAgentSection).toHaveBeenCalledTimes(1);
  });

  it("does not ask for an agent refresh when the file panel opens", () => {
    const handlers = renderMenu();
    openSection("Add file");

    expect(handlers.onOpenAgentSection).not.toHaveBeenCalled();
  });

  it("picks an agent object and closes", () => {
    const handlers = renderMenu();
    openSection("Agent");

    fireEvent.click(screen.getByRole("option", { name: /Agent 3/ }));

    expect(handlers.onSelectAgent).toHaveBeenCalledWith(
      expect.objectContaining({ id: "a3", name: "Agent 3" }),
    );
    expect(handlers.onClose).toHaveBeenCalled();
  });

  it("jumps to the browse-more page without selecting anyone", () => {
    const handlers = renderMenu();
    openSection("Agent");

    fireEvent.click(screen.getByRole("button", { name: /Summon more agents/ }));

    expect(handlers.onBrowseMoreAgents).toHaveBeenCalled();
    expect(handlers.onSelectAgent).not.toHaveBeenCalled();
  });
});

// ── 智能体二级面板：服务端搜索 ────────────────────────────────────────────────

describe("ComposerMenu agent search", () => {
  it("queries the server with keyword after the debounce", async () => {
    fetchAgentPickerPage.mockResolvedValue({
      items: [
        { id: "s1", name: "SQL Agent", createdAt: "", updatedAt: "" },
        { id: "s2", name: "Data Agent", createdAt: "", updatedAt: "" },
      ],
      total: 2,
      hasMore: false,
    });

    renderMenu();
    openSection("Agent");
    typeSearch("sql");

    await waitFor(() =>
      expect(fetchAgentPickerPage).toHaveBeenCalledWith(
        { keyword: "sql", pageSize: AGENT_SEARCH_LIMIT, status: "completed" },
        1,
      ),
    );

    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["SQL Agent", "Data Agent"]);
  });

  it("shows 20 of 21 matches and points at the full list", async () => {
    const all = makeAgents(21, "Match");
    fetchAgentPickerPage.mockImplementation((_query: unknown, page: number) =>
      Promise.resolve(slicePage(all, page, 20)),
    );

    renderMenu();
    openSection("Agent");
    typeSearch("match");

    await screen.findByText("Match 1");
    expect(screen.getAllByRole("option")).toHaveLength(20);
    expect(screen.queryByText("Match 21")).not.toBeInTheDocument();
    expect(screen.getByText("Showing the first 20 of 21")).toBeInTheDocument();
  });

  it("shows an error instead of an empty result when the query fails", async () => {
    fetchAgentPickerPage.mockRejectedValue(new Error("smart-factory down"));

    renderMenu();
    openSection("Agent");
    typeSearch("boom");

    expect(await screen.findByText("Failed to load agents")).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("shows the empty state when nothing matches", async () => {
    fetchAgentPickerPage.mockResolvedValue({ items: [], total: 0, hasMore: false });

    renderMenu();
    openSection("Agent");
    typeSearch("zzzz-not-an-agent");

    expect(await screen.findByText("No matching agents found")).toBeInTheDocument();
  });

  it("returns to the first page when the search box is cleared", async () => {
    const all = makeAgents(21, "Match");
    fetchAgentPickerPage.mockImplementation((_query: unknown, page: number) =>
      Promise.resolve(slicePage(all, page, 20)),
    );

    renderMenu();
    openSection("Agent");
    typeSearch("match");
    await screen.findByText("Match 1");

    typeSearch("");

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(AGENT_PICKER_LIMIT));
    expect(screen.getByRole("option", { name: /Agent 1/ })).toBeInTheDocument();
  });

  it("ignores a stale response that resolves after a newer query", async () => {
    let resolveFirst!: (value: unknown) => void;
    const first = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    fetchAgentPickerPage
      .mockImplementationOnce(() => first)
      .mockResolvedValueOnce({
        items: [{ id: "s2", name: "Second Query", createdAt: "", updatedAt: "" }],
        total: 1,
        hasMore: false,
      });

    renderMenu();
    openSection("Agent");
    typeSearch("first");
    await waitFor(() => expect(fetchAgentPickerPage).toHaveBeenCalledTimes(1));

    typeSearch("second");
    await screen.findByText("Second Query");

    resolveFirst({
      items: [{ id: "s1", name: "First Query", createdAt: "", updatedAt: "" }],
      total: 1,
      hasMore: false,
    });

    // 先发的旧请求回来时不能覆盖新结果
    await waitFor(() => expect(screen.queryByText("First Query")).not.toBeInTheDocument());
    expect(screen.getByText("Second Query")).toBeInTheDocument();
  });
});

// ── 关闭 ──────────────────────────────────────────────────────────────────────

describe("ComposerMenu dismissal", () => {
  it("closes on a mousedown outside the menu", () => {
    const handlers = renderMenu();

    fireEvent.mouseDown(document.body);

    expect(handlers.onClose).toHaveBeenCalled();
  });

  it("stays open on a mousedown inside the menu", () => {
    const handlers = renderMenu();

    fireEvent.mouseDown(screen.getByRole("menu"));

    expect(handlers.onClose).not.toHaveBeenCalled();
  });

  it("steps back from the second level before closing on Escape", () => {
    const handlers = renderMenu();
    openSection("Agent");
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    // 第一次 Esc:收起二级
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(handlers.onClose).not.toHaveBeenCalled();

    // 第二次 Esc:关闭菜单
    fireEvent.keyDown(document, { key: "Escape" });
    expect(handlers.onClose).toHaveBeenCalled();
  });
});
