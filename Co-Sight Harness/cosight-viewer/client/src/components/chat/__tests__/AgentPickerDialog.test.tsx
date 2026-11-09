// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { makeHarnessAgents, slicePage } from "../../../test-utils/agent-fixtures";
import { AgentPickerDialog } from "../AgentPickerDialog";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const { fetchAgentPage } = vi.hoisted(() => ({
  fetchAgentPage: vi.fn(),
}));

vi.mock("../../../api/harness-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/harness-api")>();
  return { ...actual, fetchAgentPage };
});

/**
 * 捕获弹框挂的 IntersectionObserver 回调，手动触发“触底”。
 *
 * 用集合而不是单个变量：数据到位后 loadMore 会重建 observer，全量跑测试时
 * 旧回调可能还没被替换；每次取最新注册的那个，才能命中“ready 之后”的版本。
 */
const observers = new Set<IntersectionObserverCallback>();

class MockIntersectionObserver {
  root = null;
  rootMargin = "";
  thresholds = [];

  constructor(private readonly callback: IntersectionObserverCallback) {
    observers.add(callback);
  }

  observe() {}
  disconnect() {
    observers.delete(this.callback);
  }
  unobserve() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

function triggerSentinel() {
  const callbacks = [...observers];
  const latest = callbacks[callbacks.length - 1];
  act(() => {
    latest?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
  });
}

beforeEach(() => {
  observers.clear();
  fetchAgentPage.mockReset();
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── 分页边界 ──────────────────────────────────────────────────────────────────

describe("AgentPickerDialog pagination", () => {
  it("loads the 61st agent from the second page when total exceeds one page", async () => {
    // 60 条一页：第一页满页，第二页只剩 1 条，覆盖 total > pageSize 的边界
    const all = makeHarnessAgents(61, "Expert");
    fetchAgentPage.mockImplementation((_query: unknown, page: number) =>
      Promise.resolve(slicePage(all, page, 60)),
    );

    render(<AgentPickerDialog onClose={vi.fn()} onPicked={vi.fn()} />);

    await screen.findByText("Expert 1");
    expect(screen.getAllByText(/^Expert \d+$/)).toHaveLength(60);
    expect(fetchAgentPage).toHaveBeenCalledTimes(1);

    // 数据落地后 observer 会重建；重试触发直到拿到“ready 之后”的那一版
    await waitFor(() => {
      triggerSentinel();
      expect(fetchAgentPage).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Expert 61")).toBeInTheDocument();
    expect(screen.getAllByText(/^Expert \d+$/)).toHaveLength(61);
    expect(screen.getByText("No more experts")).toBeInTheDocument();
  });
});
