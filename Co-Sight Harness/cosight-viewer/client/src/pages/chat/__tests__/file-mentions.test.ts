// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import {
  collectInlineCodePaths,
  collectRelativeMarkdownLinks,
  comparableBaseName,
  resolveMention,
} from "../file-mentions";
import { looksLikeAbsoluteFilePath } from "../../../components/conversation/MarkdownContent";
import { normalizePath, pathKey, writtenPathOfMessage } from "../useSessionFiles";
import type { ChatMessage } from "../useChatSession";

describe("collectInlineCodePaths", () => {
  it("只收集形似相对路径的行内代码", () => {
    expect(
      collectInlineCodePaths([
        "已复制到 `B/A.pdf`，也可以看 `src/api/client.ts`；`A.pdf` 不算路径。",
        "重复 `B/A.pdf` 只算一次",
      ]),
    ).toEqual(["B/A.pdf", "src/api/client.ts"]);
  });
});

describe("comparableBaseName", () => {
  it("取 basename 并忽略大小写", () => {
    expect(comparableBaseName("C:/ws/B/Report.PDF")).toBe("report.pdf");
    expect(comparableBaseName("B/Report.PDF")).toBe("report.pdf");
  });
});

describe("normalizePath", () => {
  it("keeps POSIX absolute paths as-is", () => {
    expect(normalizePath("/home/u/report.md")).toBe("/home/u/report.md");
  });

  it("converts Windows backslashes to forward slashes", () => {
    expect(normalizePath("C:\\work\\out\\hate.txt")).toBe("C:/work/out/hate.txt");
  });

  it("strips file:// and the leading slash before a drive letter", () => {
    expect(normalizePath("file:///C:/work/out/hate.txt")).toBe("C:/work/out/hate.txt");
  });

  it("decodes percent-encoded paths", () => {
    expect(normalizePath("C:/work/%E6%96%B0%E6%96%87%E4%BB%B6%202.txt")).toBe(
      "C:/work/新文件 2.txt"
    );
  });

  it("preserves the leading double slash of UNC paths", () => {
    expect(normalizePath("\\\\server\\share\\out\\a.txt")).toBe("//server/share/out/a.txt");
  });
});

describe("pathKey", () => {
  it("is case-insensitive for Windows drive paths", () => {
    expect(pathKey("C:/Work/Out.TXT")).toBe("c:/work/out.txt");
  });

  it("stays case-sensitive on POSIX", () => {
    expect(pathKey("/home/u/Out.TXT")).toBe("/home/u/Out.TXT");
  });
});

describe("resolveMention", () => {
  const produced = [
    "C:/ws/.smart-factory/agents/agt_1/development/hate.txt",
    "C:/ws/.smart-factory/agents/agt_1/development/love.txt",
    "/home/u/notes/report.md",
  ];

  it("matches an exact absolute path", () => {
    expect(resolveMention("C:/ws/.smart-factory/agents/agt_1/development/hate.txt", produced)).toBe(
      "C:/ws/.smart-factory/agents/agt_1/development/hate.txt"
    );
  });

  it("matches a unique basename", () => {
    expect(resolveMention("hate.txt", produced)).toBe(
      "C:/ws/.smart-factory/agents/agt_1/development/hate.txt"
    );
  });

  it("matches a unique suffix", () => {
    expect(resolveMention("development/love.txt", produced)).toBe(
      "C:/ws/.smart-factory/agents/agt_1/development/love.txt"
    );
  });

  it("matches Windows paths case-insensitively", () => {
    expect(resolveMention("HATE.TXT", produced)).toBe(
      "C:/ws/.smart-factory/agents/agt_1/development/hate.txt"
    );
  });

  it("strips #L24 and file:// before matching", () => {
    expect(resolveMention("file:///C:/ws/notes/other.md#L24", produced)).toBeUndefined();
    expect(resolveMention("file:///home/u/notes/report.md#L24", produced)).toBe(
      "/home/u/notes/report.md"
    );
  });

  it("returns undefined when the basename is ambiguous", () => {
    const ambiguous = ["C:/a/x.ts", "C:/b/x.ts"];
    expect(resolveMention("x.ts", ambiguous)).toBeUndefined();
  });

  it("带目录的路径不退回同名产物的 basename", () => {
    const onlyA = ["C:/ws/out/A.pdf"];
    // B 是复制出来的，不在产物集合里；不能因为 basename 相同就指到 A
    expect(resolveMention("B/A.pdf", onlyA)).toBeUndefined();
    expect(resolveMention("C:/ws/B/A.pdf", onlyA)).toBeUndefined();
    // 纯文件名仍然保留 basename 兜底
    expect(resolveMention("A.pdf", onlyA)).toBe("C:/ws/out/A.pdf");
  });

  it("复制出的文件进入产物集合后按路径命中", () => {
    const both = ["C:/ws/out/A.pdf", "C:/ws/B/A.pdf"];
    expect(resolveMention("B/A.pdf", both)).toBe("C:/ws/B/A.pdf");
  });

  it("does not guess for words outside the produced set", () => {
    expect(resolveMention("package.json", produced)).toBeUndefined();
  });

  it("matches Linux absolute paths, suffixes and basenames", () => {
    const linux = [
      "/home/u/run/output/demo/UART_PATTERN_GUIDE.md",
      "/home/u/run/output/demo/uart_patterns.h",
    ];

    expect(resolveMention("/home/u/run/output/demo/uart_patterns.h", linux)).toBe(
      "/home/u/run/output/demo/uart_patterns.h"
    );
    expect(resolveMention("output/demo/UART_PATTERN_GUIDE.md", linux)).toBe(
      "/home/u/run/output/demo/UART_PATTERN_GUIDE.md"
    );
    expect(resolveMention("uart_patterns.h", linux)).toBe(
      "/home/u/run/output/demo/uart_patterns.h"
    );
  });

  it("keeps Linux matching case-sensitive", () => {
    const linux = ["/home/u/run/Report.md"];
    expect(resolveMention("report.md", linux)).toBeUndefined();
    expect(resolveMention("Report.md", linux)).toBe("/home/u/run/Report.md");
  });
});

describe("looksLikeAbsoluteFilePath", () => {
  it("accepts previewable absolute paths", () => {
    expect(looksLikeAbsoluteFilePath("F:\\code\\out\\report.md")).toBe(true);
    expect(looksLikeAbsoluteFilePath("/home/u/report.md")).toBe(true);
    expect(looksLikeAbsoluteFilePath("~/notes/report.md")).toBe(true);
    expect(looksLikeAbsoluteFilePath("file:///C:/work/a.png")).toBe(true);
    expect(looksLikeAbsoluteFilePath("F:\\code\\out\\index.html")).toBe(true);
  });

  it("accepts unsupported file types too; the panel decides preview or download", () => {
    expect(looksLikeAbsoluteFilePath("F:\\code\\out\\AI助手能力介绍.pptx")).toBe(true);
    expect(looksLikeAbsoluteFilePath("/home/u/archive.zip")).toBe(true);
    expect(looksLikeAbsoluteFilePath("F:\\code\\out\\doc.pdf")).toBe(true);
  });

  it("rejects bare filenames and extension-less paths", () => {
    expect(looksLikeAbsoluteFilePath("hate.txt")).toBe(false);
    expect(looksLikeAbsoluteFilePath("C:\\Windows\\System32")).toBe(false);
    expect(looksLikeAbsoluteFilePath("output/agents/demo/v1")).toBe(false);
  });

  it("rejects non-path prose", () => {
    expect(looksLikeAbsoluteFilePath("and/or")).toBe(false);
    expect(looksLikeAbsoluteFilePath("https://example.com/a.png")).toBe(false);
  });
});

describe("writtenPathOfMessage", () => {
  const base: ChatMessage = {
    id: "tool_1",
    role: "tool",
    content: "",
    timestamp: 1,
    toolName: "Write",
    toolInput: { file_path: "C:/work/hate.txt" },
  };

  it("returns the path for a successful write tool", () => {
    expect(writtenPathOfMessage(base)).toBe("C:/work/hate.txt");
  });

  it("ignores failed and pending writes", () => {
    expect(writtenPathOfMessage({ ...base, toolError: true })).toBeNull();
    expect(writtenPathOfMessage({ ...base, toolPending: true })).toBeNull();
  });

  it("ignores non-write tools", () => {
    expect(writtenPathOfMessage({ ...base, toolName: "Read" })).toBeNull();
    expect(writtenPathOfMessage({ ...base, toolName: "Bash" })).toBeNull();
  });

  it("reads notebook_path", () => {
    expect(
      writtenPathOfMessage({
        ...base,
        toolName: "NotebookEdit",
        toolInput: { notebook_path: "/home/u/demo.ipynb" },
      })
    ).toBe("/home/u/demo.ipynb");
  });
});

describe("collectRelativeMarkdownLinks", () => {
  it("只收相对文件路径，绝对路径 / URL / 锚点 / 无扩展名都不算", () => {
    const text = [
      "[图](pics/answer.png)",
      "![预览](output/agents/demo/v1/render.png)",
      "[绝对](F:\code\out\a.md)",
      "[链接](https://example.com/a.png)",
      "[锚点](#section)",
      "[文档](docs)",
      "[相对](./notes/a.md)",
    ].join("\n");

    expect(collectRelativeMarkdownLinks(text)).toEqual([
      "pics/answer.png",
      "output/agents/demo/v1/render.png",
      "./notes/a.md",
    ]);
  });

  it("重复目标只出现一次，并忽略带 title 的写法", () => {
    const text =
      '[a](pics/a.png "标题")\n[b](pics/a.png)\n[c](pics/a.png "另一个标题")';

    expect(collectRelativeMarkdownLinks(text)).toEqual(["pics/a.png"]);
  });
});
