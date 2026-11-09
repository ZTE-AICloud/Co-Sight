// SPDX-License-Identifier: Apache-2.0
/**
 * @file MarkdownContent.test.tsx
 * @description Tests for the lightweight markdown renderer used by the conversation viewer.
 * Focuses on the block parser since the inline parser is well-exercised by snapshot-style
 * DOM assertions.
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MarkdownContent } from "../MarkdownContent";

describe("<MarkdownContent />", () => {
  it("renders fenced code blocks with the language label", () => {
    render(<MarkdownContent text={"Here is some code:\n```js\nconst x = 1;\n```"} />);
    // The CodeBlock header shows the language
    expect(screen.getByText(/javascript/i)).toBeInTheDocument();
    // The code text is present (split across syntax-highlighted spans, so use a substring)
    expect(screen.getByText(/const/)).toBeInTheDocument();
  });

  it("renders headings as semantic-looking elements", () => {
    render(<MarkdownContent text={"# Title\n\nbody"} />);
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("renders unordered and ordered lists", () => {
    const { container } = render(<MarkdownContent text={"- one\n- two\n\n1. first\n2. second"} />);
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("renders blockquotes", () => {
    const { container } = render(<MarkdownContent text={"> a quote"} />);
    expect(container.querySelector("blockquote")).not.toBeNull();
    expect(screen.getByText("a quote")).toBeInTheDocument();
  });

  it("renders inline code, bold, and italic", () => {
    const { container } = render(
      <MarkdownContent text={"This has `code`, **bold**, and *italic*."} />
    );
    expect(container.querySelector("code")).not.toBeNull();
    expect(container.querySelector("strong")).not.toBeNull();
    expect(container.querySelector("em")).not.toBeNull();
  });

  it("auto-links bare URLs and renders explicit markdown links", () => {
    const { container } = render(
      <MarkdownContent text={"See https://example.com or [docs](https://example.com/docs)."} />
    );
    const links = container.querySelectorAll("a");
    expect(links.length).toBe(2);
    expect(links[0]!.getAttribute("href")).toBe("https://example.com");
    expect(links[1]!.getAttribute("href")).toBe("https://example.com/docs");
    // Both should open in a new tab safely
    for (const a of links) {
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toContain("noopener");
    }
  });

  it("renders plain text without any markdown features", () => {
    render(<MarkdownContent text={"just a normal sentence."} />);
    expect(screen.getByText("just a normal sentence.")).toBeInTheDocument();
  });

  it("handles empty input safely", () => {
    const { container } = render(<MarkdownContent text="" />);
    // Wrapper exists but no block elements
    expect(container.firstChild).not.toBeNull();
    expect(container.querySelectorAll("p, ul, ol, blockquote, pre, hr").length).toBe(0);
  });

  it("renders inline code matching the produced set as a clickable file", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"文件已创建完成！我在 `hate.txt` 中写入了“我恨你”。"}
        fileMentions={{
          resolve: (value) => (value === "hate.txt" ? "C:/work/hate.txt" : undefined),
          open,
        }}
      />
    );

    const button = screen.getByRole("button", { name: /hate\.txt/ });
    fireEvent.click(button);
    expect(open).toHaveBeenCalledWith("C:/work/hate.txt");
  });

  it("keeps non-matching inline code as plain code", () => {
    render(
      <MarkdownContent
        text={"配置在 `package.json` 里"}
        fileMentions={{ resolve: () => undefined, open: vi.fn() }}
      />
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("package.json")).toBeInTheDocument();
  });

  it("links a plain absolute path even when it is not in the produced set", () => {
    const open = vi.fn();
    const path = "F:\\code\\out\\report.md";
    render(
      <MarkdownContent
        text={`✅ 文件已成功创建！\n\n文件位置： ${path}`}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    const button = screen.getByRole("button", { name: /report\.md/ });
    fireEvent.click(button);
    expect(open).toHaveBeenCalledWith(path);
  });

  it("links an unsupported path; the panel offers download instead of preview", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"文件位置： F:\\code\\out\\AI助手能力介绍.pptx"}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /AI助手能力介绍\.pptx/ }));
    expect(open).toHaveBeenCalledWith("F:\\code\\out\\AI助手能力介绍.pptx");
  });

  it("uses the verified target for a relative markdown link", () => {
    const open = vi.fn();
    const root = "C:/ws/.smart-factory/agents/agt_1/development/output/agents/demo/v1";
    render(
      <MarkdownContent
        text={"![结果](pics/answer.png)\n\n[报告](pics/report.md)"}
        fileMentions={{
          resolve: () => undefined,
          resolvePath: (value: string) => `${root}/${value}`,
          open,
        }}
      />
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);

    fireEvent.click(buttons[0]!);
    expect(open).toHaveBeenCalledWith(`${root}/pics/answer.png`);
    fireEvent.click(buttons[1]!);
    expect(open).toHaveBeenCalledWith(`${root}/pics/report.md`);
  });

  it("keeps a relative link as plain text when no runtime root is available", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"[报告](pics/report.md)"}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("报告")).toBeInTheDocument();
  });

  it("links an absolute PDF path in inline code", () => {
    const open = vi.fn();
    const path = "F:\\code\\out\\report.pdf";
    render(
      <MarkdownContent
        text={`导出完成：\`${path}\``}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /report\.pdf/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("trims trailing punctuation from a plain path", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"文件位置： F:\\code\\out\\a.md。"}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /a\.md/ }));
    expect(open).toHaveBeenCalledWith("F:\\code\\out\\a.md");
  });

  it("links a fenced block that contains only an absolute file path", () => {
    const open = vi.fn();
    const path =
      "C:\\Users\\test-user\\.cosight-harness\\smart-factory\\builtin-agents\\example-builtin-agent\\data\\example-report.pptx";
    render(
      <MarkdownContent
        text={`📄 **PPT 完整文件路径**：\n\n\`\`\`\n${path}\n\`\`\`\n\n直接双击即可用 PowerPoint 打开。`}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /example-report\.pptx/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("links a Linux absolute path in a fenced block", () => {
    const open = vi.fn();
    const path = "/home/u/run/output/demo/uart_patterns.h";
    render(
      <MarkdownContent
        text={"```\n" + path + "\n```"}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /uart_patterns\.h/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("links a Linux plain-text path with spaces", () => {
    const open = vi.fn();
    const path = "/home/u/my docs/报告 v2.pptx";
    render(
      <MarkdownContent
        text={`文件位置： ${path}，请查收。`}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /报告 v2\.pptx/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("does not swallow English prose after a path with spaces", () => {
    const open = vi.fn();
    const path = "/home/u/my docs/a b.pdf";
    render(
      <MarkdownContent
        text={`文件位置： ${path} v2.0`}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /a b\.pdf/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("keeps a language-tagged code block as code even if it is a single path", () => {
    const { container } = render(
      <MarkdownContent
        text={"```bash\nF:\\code\\out\\a.md\n```"}
        fileMentions={{ resolve: () => undefined, open: vi.fn() }}
      />
    );

    // 文件引用按钮以 title=路径 标识；CodeBlock 自身的复制按钮不算
    expect(screen.queryByTitle("F:\\code\\out\\a.md")).toBeNull();
    expect(container.textContent).toContain("F:\\code\\out\\a.md");
  });

  it("keeps a multi-line fenced block as code", () => {
    render(
      <MarkdownContent
        text={"```\nF:\\code\\out\\a.md\nF:\\code\\out\\b.md\n```"}
        fileMentions={{ resolve: () => undefined, open: vi.fn() }}
      />
    );

    expect(screen.queryByTitle("F:\\code\\out\\a.md")).toBeNull();
    expect(screen.queryByTitle("F:\\code\\out\\b.md")).toBeNull();
  });

  it("does not link bare filenames in plain text", () => {
    render(
      <MarkdownContent
        text={"我创建了 hate.txt"}
        fileMentions={{ resolve: () => undefined, open: vi.fn() }}
      />
    );

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("links a previewable absolute path in inline code even when it is not in the produced set", () => {
    const open = vi.fn();
    const path = "F:\\code\\out\\a.md";
    render(
      <MarkdownContent
        text={`文件位置：\`${path}\``}
        fileMentions={{ resolve: () => undefined, open }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /a\.md/ }));
    expect(open).toHaveBeenCalledWith(path);
  });

  it("links bold bare filenames in a list when they uniquely match the produced set", () => {
    const open = vi.fn();
    const produced: Record<string, string> = {
      "uart_patterns.h": "F:/run/uart_patterns.h",
      "uart_patterns.c": "F:/run/uart_patterns.c",
      "uart_pattern_examples.c": "F:/run/uart_pattern_examples.c",
      "UART_PATTERN_GUIDE.md": "F:/run/UART_PATTERN_GUIDE.md",
    };

    render(
      <MarkdownContent
        text={
          "1. **uart_patterns.h** - 头文件\n" +
          "2. **uart_patterns.c** - 实现\n" +
          "3. **uart_pattern_examples.c** - 示例\n" +
          "4. **UART_PATTERN_GUIDE.md** - 指南"
        }
        fileMentions={{ resolve: (value) => produced[value], open }}
      />
    );

    // 下划线必须保留，且整段名字在同一个按钮里
    expect(screen.getByText("uart_pattern_examples.c")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /UART_PATTERN_GUIDE\.md/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /uart_patterns\.h/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /uart_pattern_examples\.c/ }));
    expect(open).toHaveBeenCalledWith("F:/run/uart_pattern_examples.c");
  });

  it("does not treat intraword underscores as italic", () => {
    const { container } = render(
      <MarkdownContent text={"uart_pattern_examples.c 和 UART_PATTERN_GUIDE.md"} />
    );

    expect(container.querySelector("em")).toBeNull();
    expect(container.textContent).toContain("uart_pattern_examples.c");
    expect(container.textContent).toContain("UART_PATTERN_GUIDE.md");
  });

  it("still renders real underscore emphasis", () => {
    const { container } = render(<MarkdownContent text={"_italic_"} />);
    expect(container.querySelector("em")?.textContent).toBe("italic");
  });

  it("still renders double-underscore bold at word boundaries", () => {
    const { container } = render(<MarkdownContent text={"__bold__"} />);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("does not treat intraword double underscores as bold", () => {
    const { container } = render(<MarkdownContent text={"foo__bar__"} />);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toContain("foo__bar__");
  });

  it("does not link bare filenames that are not in the produced set", () => {
    render(
      <MarkdownContent
        text={"我创建了 uart_patterns.h"}
        fileMentions={{ resolve: () => undefined, open: vi.fn() }}
      />
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/uart_patterns\.h/)).toBeInTheDocument();
  });

  it("links unsupported bare filenames that uniquely match the produced set", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"文件： AI助手能力介绍.pptx"}
        fileMentions={{
          resolve: () => "F:/run/AI助手能力介绍.pptx",
          open,
        }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /AI助手能力介绍\.pptx/ }));
    expect(open).toHaveBeenCalledWith("F:/run/AI助手能力介绍.pptx");
  });

  it("行内代码的相对路径经 resolvePath 校验后可以打开", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"已复制到 `B/A.pdf`"}
        fileMentions={{
          resolve: () => undefined,
          resolvePath: (value) => (value === "B/A.pdf" ? "F:/ws/B/A.pdf" : undefined),
          open,
        }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /B\/A\.pdf/ }));
    expect(open).toHaveBeenCalledWith("F:/ws/B/A.pdf");
  });

  it("Markdown 相对链接在产物集合未命中时由 resolvePath 兜底", () => {
    const open = vi.fn();
    render(
      <MarkdownContent
        text={"[复制件](B/A.pdf)"}
        fileMentions={{
          resolve: () => undefined,
          resolvePath: (value) => (value === "B/A.pdf" ? "F:/ws/B/A.pdf" : undefined),
          open,
        }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /复制件/ }));
    expect(open).toHaveBeenCalledWith("F:/ws/B/A.pdf");
  });
});
