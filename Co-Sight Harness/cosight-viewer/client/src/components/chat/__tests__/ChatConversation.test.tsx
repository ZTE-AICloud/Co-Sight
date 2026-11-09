// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ChatMessage } from "../../../pages/chat/useChatSession";
import { ChatConversation } from "../ChatConversation";

const baseProps = {
  historyReady: true,
  streamingContent: "",
  toolExecutions: [],
  pendingApprovals: [],
  interactiveTools: [],
  toolAnswers: {},
  connectionState: "connected" as const,
  isLoading: false,
  onAnswerChange: vi.fn(),
  onApprovalRespond: vi.fn(),
  onToolSubmit: vi.fn(),
};

function renderConversation(messages: ChatMessage[]) {
  return render(<ChatConversation {...baseProps} messages={messages} />);
}

describe("ChatConversation run errors", () => {
  it("renders a run failure as an in-flow alert", () => {
    renderConversation([
      {
        id: "u1",
        role: "user",
        content: "你好",
        timestamp: Date.now(),
      },
      {
        id: "e1",
        role: "assistant",
        system: true,
        systemError: true,
        runId: "run_failed",
        content: "Claude Code native binary failed to launch",
        timestamp: Date.now(),
      },
    ]);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Run failed");
    expect(alert).toHaveTextContent("Claude Code native binary failed to launch");
    // 用户消息仍在，错误不是替代而是追加在对话流里
    expect(screen.getByText("你好")).toBeInTheDocument();
  });

  it("keeps non-error system notices in the muted style", () => {
    renderConversation([
      {
        id: "s1",
        role: "assistant",
        system: true,
        content: "Reconnected",
        timestamp: Date.now(),
      },
    ]);

    expect(screen.getByText("Reconnected")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
