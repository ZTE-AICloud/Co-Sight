// SPDX-License-Identifier: Apache-2.0
/**
 * @file ToolCallBlock.test.tsx
 * @description 工具卡默认展开规则：失败默认展开，成功默认折叠，无结果显示 pending。
 * 实时链路与恢复历史共用同一个组件，这里的规则对两者同时生效。
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ToolCallBlock } from "../ToolCallBlock";
import type { TranscriptContent } from "../../../lib/types";

const toolUse: TranscriptContent = {
  type: "tool_use",
  id: "t1",
  name: "Bash",
  input: { command: "ls -la" },
};

describe("<ToolCallBlock /> 默认展开", () => {
  it("失败的工具默认展开，错误输出直接可见", () => {
    render(
      <ToolCallBlock
        toolUse={toolUse}
        toolResult={{
          type: "tool_result",
          id: "t1",
          output: "permission denied",
          is_error: true,
        }}
      />
    );

    // 展开态才渲染的 Error 输出标签
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("成功的工具默认折叠", () => {
    render(
      <ToolCallBlock
        toolUse={toolUse}
        toolResult={{ type: "tool_result", id: "t1", output: "a.txt", is_error: false }}
      />
    );

    expect(screen.queryByText("Output")).not.toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("没有配对结果时显示 pending", () => {
    render(<ToolCallBlock toolUse={toolUse} toolResult={null} />);

    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});

describe("<ToolCallBlock /> 文件路径", () => {
  const writeTool: TranscriptContent = {
    type: "tool_use",
    id: "t2",
    name: "Write",
    input: { file_path: "C:/work/hate.txt", content: "我恨你" },
  };

  it("摘要里的文件路径可点，点击不会展开工具卡", () => {
    const open = vi.fn();
    render(
      <ToolCallBlock
        toolUse={writeTool}
        toolResult={{ type: "tool_result", id: "t2", output: "ok", is_error: false }}
        onOpenPath={open}
      />
    );

    const link = screen.getByRole("button", { name: "C:/work/hate.txt" });
    fireEvent.click(link);

    expect(open).toHaveBeenCalledWith("C:/work/hate.txt");
    // 展开态才会渲染的输入区标签
    expect(screen.queryByText("New file")).not.toBeInTheDocument();
  });

  it("没有 onOpenPath 时保持纯文本", () => {
    render(
      <ToolCallBlock
        toolUse={writeTool}
        toolResult={{ type: "tool_result", id: "t2", output: "ok", is_error: false }}
      />
    );

    expect(screen.queryByRole("button", { name: "C:/work/hate.txt" })).not.toBeInTheDocument();
  });
});
