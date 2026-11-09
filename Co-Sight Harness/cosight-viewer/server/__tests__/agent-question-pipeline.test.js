// SPDX-License-Identifier: Apache-2.0
const { describe, it } = require("node:test");
const assert = require("node:assert");

/**
 * Test the agent_question → pending logic pattern.
 * This tests the logic that daemon.js applies when it encounters
 * an agent_question event: mark in-progress steps as pending.
 */
describe("agent_question → pending status", () => {
  function applyAgentQuestion(task) {
    // This mirrors the logic in daemon.js
    for (const phase of (task.substep || [])) {
      for (const step of (phase.subStep || [])) {
        if (step.status === "in-progress") {
          step.status = "pending";
        }
      }
      if (phase.status === "in-progress" &&
          (phase.subStep || []).some(s => s.status === "pending")) {
        phase.status = "pending";
      }
    }
    if (!task.state) task.state = {};
    if (!task.state.pending_calls) task.state.pending_calls = {};
    task.state.pending_calls.agent_question = { timestamp: new Date().toISOString() };
  }

  it("marks active step as pending when agent_question received", () => {
    const task = {
      taskId: "test-task-1",
      status: "in-progress",
      substep: [
        {
          index: 1,
          name: "P1 构思",
          status: "in-progress",
          subStep: [
            { index: 1, name: "brainstorming 主体", status: "in-progress", subStep: [] },
          ],
        },
      ],
      state: { current_phase: "P1 构思", pending_calls: {} },
    };

    applyAgentQuestion(task);

    assert.strictEqual(task.substep[0].subStep[0].status, "pending");
    assert.strictEqual(task.substep[0].status, "pending");
    assert.ok(task.state.pending_calls.agent_question);
  });

  it("does not affect completed steps", () => {
    const task = {
      taskId: "test-task-2",
      status: "in-progress",
      substep: [
        {
          index: 1,
          name: "P1 构思",
          status: "completed",
          subStep: [
            { index: 1, name: "brainstorming 主体", status: "completed", subStep: [] },
          ],
        },
        {
          index: 2,
          name: "P2 计划",
          status: "in-progress",
          subStep: [
            { index: 1, name: "writing-plans", status: "in-progress", subStep: [] },
          ],
        },
      ],
      state: { pending_calls: {} },
    };

    applyAgentQuestion(task);

    // P1 should remain completed
    assert.strictEqual(task.substep[0].status, "completed");
    assert.strictEqual(task.substep[0].subStep[0].status, "completed");
    // P2 step should become pending
    assert.strictEqual(task.substep[1].subStep[0].status, "pending");
    assert.strictEqual(task.substep[1].status, "pending");
  });

  it("handles task with no substep gracefully", () => {
    const task = {
      taskId: "test-task-3",
      status: "in-progress",
      substep: [],
      state: {},
    };

    // Should not throw
    applyAgentQuestion(task);
    assert.ok(task.state.pending_calls.agent_question);
  });
});
