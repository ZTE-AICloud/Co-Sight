// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FilePickerDialog } from "../FilePickerDialog";

const { browser } = vi.hoisted(() => ({
  browser: {
    roots: vi.fn(),
    list: vi.fn(),
  },
}));

vi.mock("../../../api/file-browser-api", () => ({
  fileBrowserApi: browser,
  FsApiError: class FsApiError extends Error {
    status = 0;
    code = "UNKNOWN";
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  browser.roots.mockResolvedValue({
    items: [{ label: "Home", path: "/home/u", kind: "home" }],
  });
  browser.list.mockResolvedValue({
    path: "/home/u",
    parent: "/home",
    items: [
      { name: "docs", path: "/home/u/docs", type: "dir", size: 0, mtime: "" },
      { name: "a.md", path: "/home/u/a.md", type: "file", size: 12, mtime: "" },
    ],
    truncated: false,
  });
});

describe("FilePickerDialog", () => {
  it("lists a directory and confirms a selected file", async () => {
    const onConfirm = vi.fn();
    render(
      <FilePickerDialog open max={5} onCancel={vi.fn()} onConfirm={onConfirm} />
    );

    const file = await screen.findByRole("option", { name: /a\.md/ });
    fireEvent.click(file);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(onConfirm).toHaveBeenCalledWith([{ path: "/home/u/a.md", name: "a.md" }]);
  });

  it("enters a directory on click", async () => {
    render(<FilePickerDialog open max={5} onCancel={vi.fn()} onConfirm={vi.fn()} />);

    const docs = await screen.findByRole("option", { name: /docs/ });
    fireEvent.click(docs);

    await waitFor(() =>
      expect(browser.list).toHaveBeenLastCalledWith("/home/u/docs")
    );
  });

  it("cancels on Escape", async () => {
    const onCancel = vi.fn();
    render(<FilePickerDialog open max={5} onCancel={onCancel} onConfirm={vi.fn()} />);
    await screen.findByRole("option", { name: /a\.md/ });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCancel).toHaveBeenCalled();
  });
});
