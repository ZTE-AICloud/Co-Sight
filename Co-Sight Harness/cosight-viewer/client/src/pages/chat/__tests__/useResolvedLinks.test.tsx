// SPDX-License-Identifier: Apache-2.0
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fsApi } from "../../../api/fs-api";
import { useResolvedLinks } from "../useResolvedLinks";

vi.mock("../../../api/fs-api", () => ({
  fsApi: { resolve: vi.fn() },
}));

const resolve = vi.mocked(fsApi.resolve);

/** 让防抖定时器到点，并把随后的 promise 微任务跑完。 */
async function flushResolve(): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(300);
    await Promise.resolve();
  });
}

beforeEach(() => {
  resolve.mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useResolvedLinks", () => {
  it("只问确认存在的相对链接，绝对链接 / URL 不参与", async () => {
    resolve.mockResolvedValue([]);

    renderHook(() =>
      useResolvedLinks(
        [
          "[图](pics/a.png)",
          "[绝对](F:/out/a.png)",
          "[网页](https://example.com/a.png)",
          "没有链接的正文",
        ],
        ["F:/runtime"]
      )
    );

    await flushResolve();

    expect(resolve).toHaveBeenCalledTimes(1);
    expect(resolve).toHaveBeenCalledWith([{ path: "pics/a.png", roots: ["F:/runtime"] }]);
  });

  it("存在才返回绝对路径；不存在保持 undefined（纯文本）", async () => {
    resolve.mockResolvedValue([
      { path: "pics/a.png", resolved: "F:/runtime/pics/a.png" },
      { path: "pics/b.png", resolved: null },
    ]);

    const { result } = renderHook(() =>
      useResolvedLinks(["[a](pics/a.png) [b](pics/b.png)"], ["F:/runtime"])
    );

    await flushResolve();

    expect(result.current("pics/a.png")).toBe("F:/runtime/pics/a.png");
    expect(result.current("pics/b.png")).toBeUndefined();
    // 未扫到的路径也不会瞎猜
    expect(result.current("pics/c.png")).toBeUndefined();
  });

  it("候选根变化（换智能体）后旧结果作废并重新校验", async () => {
    resolve.mockResolvedValue([{ path: "pics/a.png", resolved: "F:/one/pics/a.png" }]);

    const text = ["[a](pics/a.png)"];
    const { result, rerender } = renderHook(
      ({ roots }: { roots: string[] }) => useResolvedLinks(text, roots),
      { initialProps: { roots: ["F:/one"] } }
    );

    await flushResolve();
    expect(result.current("pics/a.png")).toBe("F:/one/pics/a.png");

    resolve.mockResolvedValue([{ path: "pics/a.png", resolved: "F:/two/pics/a.png" }]);
    rerender({ roots: ["F:/two"] });
    await flushResolve();

    expect(result.current("pics/a.png")).toBe("F:/two/pics/a.png");
  });

  it("把调用方额外登记的行内代码路径一起校验", async () => {
    resolve.mockResolvedValue([
      { path: "B/A.pdf", resolved: "F:/runtime/B/A.pdf" },
    ]);

    const { result } = renderHook(() =>
      useResolvedLinks([], ["F:/runtime"], ["B/A.pdf"])
    );

    await flushResolve();

    expect(resolve).toHaveBeenCalledWith([
      { path: "B/A.pdf", roots: ["F:/runtime"] },
    ]);
    expect(result.current("B/A.pdf")).toBe("F:/runtime/B/A.pdf");
  });
});
