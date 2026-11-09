// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fileBrowserApi } from "../../../../api/file-browser-api";
import { fsApi } from "../../../../api/fs-api";
import type { SessionFile } from "../../../../pages/chat/useSessionFiles";
import { FilesDrawer } from "../FilesDrawer";

vi.mock("../../../../api/file-browser-api", () => ({
  fileBrowserApi: { list: vi.fn() },
}));

vi.mock("../../../../api/fs-api", () => ({
  fsApi: { read: vi.fn(), rawUrl: vi.fn(() => "blob:mock") },
}));

const list = vi.mocked(fileBrowserApi.list);
const read = vi.mocked(fsApi.read);

afterEach(() => {
  list.mockReset();
  read.mockReset();
});

function sessionFile(overrides: Partial<SessionFile> = {}): SessionFile {
  return {
    path: "F:/ws/output/a.md",
    name: "a.md",
    change: "written",
    tool: "Write",
    at: 1,
    writing: false,
    inRoot: true,
    relativePath: "output/a.md",
    ...overrides,
  };
}

function renderDrawer(overrides: Partial<Parameters<typeof FilesDrawer>[0]> = {}) {
  const props = {
    source: "workspace" as const,
    onClose: vi.fn(),
    workspaceRoot: "F:/ws",
    workspaceRootLoading: false,
    file: null,
    onOpenPath: vi.fn(),
    ...overrides,
  };
  render(<FilesDrawer {...props} />);
  return props;
}

describe("FilesDrawer", () => {
  it("以工作区 root 为边界取目录，点文件回传绝对路径", async () => {
    list.mockResolvedValue({
      path: "F:/ws",
      parent: "F:/",
      truncated: false,
      items: [
        { name: "a.md", path: "F:/ws/a.md", type: "file", size: 2, mtime: "" },
      ],
    });

    const props = renderDrawer();
    fireEvent.click(await screen.findByText("a.md"));

    expect(list).toHaveBeenCalledWith("F:/ws", "F:/ws");
    expect(props.onOpenPath).toHaveBeenCalledWith("F:/ws/a.md");
  });

  it("无法确定工作区时显示提示而不是空树", () => {
    renderDrawer({ workspaceRoot: null });

    expect(screen.getByText(/无法确定|Cannot determine/i)).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
  });

  it("预览时目录树保持可见，可以直接点下一个文件", async () => {
    list.mockResolvedValue({
      path: "F:/ws",
      parent: "F:/",
      truncated: false,
      items: [{ name: "a.md", path: "F:/ws/a.md", type: "file", size: 2, mtime: "" }],
    });
    read.mockResolvedValue({
      path: "F:/ws/a.md",
      name: "a.md",
      size: 2,
      mtime: "",
      content: "# hi\n",
    });

    renderDrawer({
      file: sessionFile({ path: "F:/ws/a.md", name: "a.md" }),
    });

    // 树（list）与预览（read）同时在挂载状态
    await waitFor(() => expect(list).toHaveBeenCalledWith("F:/ws", "F:/ws"));
    await waitFor(() => expect(read).toHaveBeenCalledWith("F:/ws/a.md"));
    expect(screen.getAllByText("a.md").length).toBeGreaterThan(0);
  });

  it("会话文件单独预览，不展示工作区树", async () => {
    read.mockResolvedValue({
      path: "F:/runtime/out/a.md",
      name: "a.md",
      size: 2,
      mtime: "",
      content: "# hi\n",
    });

    renderDrawer({
      source: "session",
      file: sessionFile({ path: "F:/runtime/out/a.md", name: "a.md" }),
    });

    await waitFor(() => expect(read).toHaveBeenCalledWith("F:/runtime/out/a.md"));
    // 会话文件不在工作区：不应该为了它去拉工作区目录树
    expect(list).not.toHaveBeenCalled();
    // 预览只提供关闭，不提供“返回工作区”
    expect(screen.queryByTitle(/返回|Back/)).not.toBeInTheDocument();
  });

  it("预览只提供关闭", async () => {
    list.mockResolvedValue({
      path: "F:/ws",
      parent: "F:/",
      truncated: false,
      items: [],
    });
    read.mockResolvedValue({
      path: "F:/ws/output/a.md",
      name: "a.md",
      size: 2,
      mtime: "",
      content: "# hi\n",
    });

    const props = renderDrawer({ file: sessionFile() });

    await waitFor(() => expect(read).toHaveBeenCalledWith("F:/ws/output/a.md"));
    fireEvent.click(screen.getByRole("button", { name: /关闭|Close/i }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
