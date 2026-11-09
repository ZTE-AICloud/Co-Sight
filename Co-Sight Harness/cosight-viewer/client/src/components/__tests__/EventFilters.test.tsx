// SPDX-License-Identifier: Apache-2.0
/**
 * @file EventFilters.test.tsx
 * @description Smoke tests for the EventFilters toolbar. Verifies that the
 * toolbar renders its inputs, emits debounced text search changes, toggles
 * selected chips, fires the clear-all handler, and fetches facet options on
 * mount via the events API (mocked).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { EventFilters, EMPTY_FILTERS, isEmptyFilters } from "../EventFilters";
import type { EventFiltersValue } from "../EventFilters";
import { api } from "../../lib/api";

describe("EventFilters", () => {
  beforeEach(() => {
    vi.spyOn(api.events, "facets").mockResolvedValue({
      event_types: ["PreToolUse", "PostToolUse", "Stop"],
      tool_names: ["Bash", "Edit"],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("isEmptyFilters treats EMPTY_FILTERS as empty", () => {
    expect(isEmptyFilters(EMPTY_FILTERS)).toBe(true);
    expect(isEmptyFilters({ ...EMPTY_FILTERS, q: "curl" })).toBe(false);
  });

  it("renders the search input with a translated placeholder", () => {
    render(<EventFilters value={EMPTY_FILTERS} onChange={() => {}} />);
    expect(screen.getByPlaceholderText(/search summary/i)).toBeInTheDocument();
  });

  it("fetches facets on mount and opens the event-type dropdown", async () => {
    render(<EventFilters value={EMPTY_FILTERS} onChange={() => {}} />);
    await waitFor(() => expect(api.events.facets).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /event type/i }));
    expect(await screen.findByText("PreToolUse")).toBeInTheDocument();
    expect(screen.getByText("Stop")).toBeInTheDocument();
  });

  it("debounces text search by 300ms", async () => {
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      render(<EventFilters value={EMPTY_FILTERS} onChange={onChange} />);
      fireEvent.change(screen.getByPlaceholderText(/search summary/i), {
        target: { value: "curl" },
      });
      expect(onChange).not.toHaveBeenCalled();
      await act(async () => {
        vi.advanceTimersByTime(300);
      });
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ q: "curl" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("toggles an event_type chip and emits the updated array", async () => {
    const onChange = vi.fn();
    render(<EventFilters value={EMPTY_FILTERS} onChange={onChange} />);
    await waitFor(() => expect(api.events.facets).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /event type/i }));
    const option = await screen.findByText("PreToolUse");
    fireEvent.click(option);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ event_type: ["PreToolUse"] }));
  });

  it("shows the clear-all button only when filters are non-empty", () => {
    const withFilter: EventFiltersValue = { ...EMPTY_FILTERS, q: "curl" };
    const onChange = vi.fn();
    const { rerender } = render(<EventFilters value={EMPTY_FILTERS} onChange={onChange} />);
    expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();

    rerender(<EventFilters value={withFilter} onChange={onChange} />);
    const clear = screen.getByRole("button", { name: /clear filters/i });
    fireEvent.click(clear);
    expect(onChange).toHaveBeenCalledWith(EMPTY_FILTERS);
  });
});
