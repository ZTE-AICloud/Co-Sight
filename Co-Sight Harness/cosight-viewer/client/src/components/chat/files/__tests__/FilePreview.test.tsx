// SPDX-License-Identifier: Apache-2.0
/**
 * @file FilePreview.test.tsx
 * @description 会话文件面板按类型分流：PDF 内联、二进制提示 + 下载。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { BareJsonError } from "../../../../api/bare-json";
import { FilePreview } from "../FilePreview";
import type { SessionFile } from "../../../../pages/chat/useSessionFiles";

const read = vi.fn();

vi.mock("../../../../api/fs-api", () => ({
  fsApi: {
    read: (path: string) => read(path),
    rawUrl: (path: string) => `/session-files/raw/${encodeURIComponent(path)}`,
  },
}));

vi.mock("react-i18next", () => {
  // `t` 必须是稳定引用：FilePreview 的读取 effect 依赖它，
  // 每次渲染都新建函数会让错误状态反复重试（测试里表现为卡死）。
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function sessionFile(path: string, name: string): SessionFile {
  return {
    path,
    name,
    change: "written",
    tool: "Write",
    at: 0,
    writing: false,
    inRoot: true,
    relativePath: name,
  };
}

describe("<FilePreview />", () => {
  beforeEach(() => {
    read.mockReset();
  });

  it("renders a PDF inline from the raw stream without reading it as text", () => {
    const path = "F:/out/report.pdf";
    render(<FilePreview file={sessionFile(path, "report.pdf")} />);

    const frame = screen.getByTitle("report.pdf");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("src")).toContain(
      `/session-files/raw/${encodeURIComponent(path)}`
    );
    expect(read).not.toHaveBeenCalled();
  });

  it("hides download when the file is missing (404)", async () => {
    read.mockRejectedValue(new BareJsonError(404, "not found"));
    render(<FilePreview file={sessionFile("F:/out/gone.md", "gone.md")} />);

    expect(await screen.findByText("run.fileMissing")).toBeInTheDocument();
    expect(screen.queryAllByRole("link", { name: "run.fileDownload" })).toHaveLength(0);
    // 仍然可以重试：文件可能稍后生成
    expect(screen.getByText("run.fileRetry")).toBeInTheDocument();
  });

  it("keeps download for read failures where the file still exists", async () => {
    read.mockRejectedValue(new BareJsonError(413, "too large"));
    render(<FilePreview file={sessionFile("F:/out/big.md", "big.md")} />);

    expect(await screen.findByText("run.fileTooLarge")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: "run.fileDownload" })).toHaveLength(2)
    );
  });

  it("shows an unsupported-format hint plus download for binary files", () => {
    const path = "F:/out/AI助手能力介绍.pptx";
    render(<FilePreview file={sessionFile(path, "AI助手能力介绍.pptx")} />);

    expect(screen.getByText("run.fileBinary")).toBeInTheDocument();
    // 工具栏图标 + 正文里的下载链接，都指向 raw 流
    const links = screen.getAllByRole("link", { name: "run.fileDownload" });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link.getAttribute("href")).toContain(
        `/session-files/raw/${encodeURIComponent(path)}`
      );
      expect(link.getAttribute("download")).toBe("AI助手能力介绍.pptx");
    }
    expect(read).not.toHaveBeenCalled();
  });
});
