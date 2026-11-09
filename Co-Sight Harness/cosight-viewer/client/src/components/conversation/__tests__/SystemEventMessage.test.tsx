// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for SystemEventMessage component.
 * Verifies rendering of TurnDuration, Compaction, and APIError system events
 * with correct icons, colors, and data display.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SystemEventMessage } from "../SystemEventMessage";
import type { SystemEvent } from "../../../lib/types";

describe("SystemEventMessage", () => {
  it("renders a TurnDuration event with duration info", () => {
    const event: SystemEvent = {
      type: "system",
      subtype: "turn_duration",
      timestamp: "2026-01-01T00:00:02Z",
      data: {
        summary: "Turn completed in 2.0s",
        durationMs: 2000,
      },
    };

    const { container } = render(<SystemEventMessage event={event} />);

    expect(screen.getByText("System")).toBeTruthy();
    expect(screen.getByText("Turn completed in 2.0s")).toBeTruthy();
    expect(screen.getByText("Duration: 2.00s")).toBeTruthy();

    // Should have a colored accent bar matching the shared message layout
    const bar = container.querySelector("[class*='before:bg-cyan']");
    expect(bar).toBeTruthy();
  });

  it("renders a Compaction event with compaction number", () => {
    const event: SystemEvent = {
      type: "system",
      subtype: "compaction",
      timestamp: "2026-01-01T00:00:05Z",
      data: {
        summary: "Context compacted — conversation history compressed (#1)",
        uuid: "compact-1",
        compaction_number: 1,
        total_compactions: 3,
      },
    };

    render(<SystemEventMessage event={event} />);

    expect(screen.getByText("System")).toBeTruthy();
    expect(screen.getByText("compaction")).toBeTruthy();
    expect(screen.getByText("#1 of 3")).toBeTruthy();
  });

  it("renders an APIError event with error type", () => {
    const event: SystemEvent = {
      type: "system",
      subtype: "api_error",
      timestamp: "2026-01-01T00:00:10Z",
      data: {
        summary: "overloaded_error: API overloaded",
        error_type: "overloaded_error",
      },
    };

    render(<SystemEventMessage event={event} />);

    expect(screen.getByText("System")).toBeTruthy();
    expect(screen.getByText("overloaded_error: API overloaded")).toBeTruthy();
    expect(screen.getByText("Type: overloaded_error")).toBeTruthy();
  });

  it("renders without timestamp when timestamp is null", () => {
    const event: SystemEvent = {
      type: "system",
      subtype: "turn_duration",
      timestamp: null,
      data: {
        summary: "Turn completed in 1.5s",
        durationMs: 1500,
      },
    };

    const { container } = render(<SystemEventMessage event={event} />);

    expect(screen.getByText("Turn completed in 1.5s")).toBeTruthy();
    // No timestamp element should be rendered
    const timeElements = container.querySelectorAll("span");
    const hasTimeLike = Array.from(timeElements).some((el) =>
      el.textContent?.match(/\d{2}:\d{2}:\d{2}/)
    );
    expect(hasTimeLike).toBe(false);
  });
});
