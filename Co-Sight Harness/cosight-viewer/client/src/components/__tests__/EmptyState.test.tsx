// SPDX-License-Identifier: Apache-2.0
/**
 * @file Merged tests for lightweight chrome components: EmptyState + SessionOverview.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { EmptyState } from "../EmptyState";
import { SessionOverview } from "../SessionOverview";
import { Bot } from "lucide-react";
import type { Agent, Session, SessionStats } from "../../lib/types";

// ── SessionOverview mocks (hoisted) ─────────────────────────────────────────

const { statsMock } = vi.hoisted(() => ({ statsMock: vi.fn() }));

vi.mock("../../lib/api", () => ({
  api: {
    sessions: {
      stats: statsMock,
    },
  },
}));

vi.mock("../../lib/eventBus", () => ({
  eventBus: {
    subscribe: vi.fn(() => () => {}),
  },
}));

// ── EmptyState ──────────────────────────────────────────────────────────────

describe("EmptyState", () => {
  it("should render title", () => {
    render(
      <EmptyState icon={Bot} title="No agents" description="Start a session to see agents." />
    );
    expect(screen.getByText("No agents")).toBeInTheDocument();
  });

  it("should render description", () => {
    render(
      <EmptyState icon={Bot} title="No agents" description="Start a session to see agents." />
    );
    expect(screen.getByText("Start a session to see agents.")).toBeInTheDocument();
  });

  it("should render the icon", () => {
    const { container } = render(<EmptyState icon={Bot} title="Title" description="Desc" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("should render action when provided", () => {
    render(
      <EmptyState icon={Bot} title="Title" description="Desc" action={<button>Retry</button>} />
    );
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("should not render action when not provided", () => {
    render(<EmptyState icon={Bot} title="Title" description="Desc" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

// ── SessionOverview — active-agent banner ping animation ────────────────────

const STATS: SessionStats = {
  session_id: "s1",
  total_events: 0,
  events_by_type: [],
  tools_used: [],
  error_count: 0,
  first_event_at: null,
  last_event_at: null,
  agents: { total: 1, main: 1, subagent: 0, compaction: 0, by_status: { working: 1 } },
  subagent_types: [],
  tokens: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  compaction_count: 0,
};

const SESSION: Session = {
  id: "s1",
  name: null,
  status: "active",
  cwd: "/tmp",
  model: null,
  started_at: "2026-08-07T00:00:00.000Z",
  ended_at: null,
  metadata: null,
};

const WORKING_AGENT = { id: "a1", name: "Agent A", status: "working" } as Agent;

describe("SessionOverview — active-agent banner ping animation", () => {
  it("uses the finite animate-ping-finite ring, not infinite animate-ping", async () => {
    statsMock.mockResolvedValue(STATS);
    const { container } = render(<SessionOverview session={SESSION} agents={[WORKING_AGENT]} />);

    await waitFor(() => {
      expect(container.querySelector(".animate-ping-finite")).toBeInTheDocument();
    });

    expect(container.querySelector(".animate-ping")).toBeNull();
  });
});
