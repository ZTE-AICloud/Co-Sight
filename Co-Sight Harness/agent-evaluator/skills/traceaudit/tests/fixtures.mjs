import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ensureDir } from "../lib/cli.mjs";

export function event(type, content, timestamp) {
  return { type, timestamp, message: { content } };
}

export function writeJsonl(filePath, entries) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${entries.map((entry) => JSON.stringify(entry)).join("\n")}\n`, "utf8");
}

export function writeMainTrace({ dir, sessionId, caseId = "SMOKE-001" }) {
  const parentJsonlPath = path.join(dir, `${sessionId}.jsonl`);
  const subagentsDir = path.join(dir, sessionId, "subagents");
  ensureDir(subagentsDir);

  writeJsonl(parentJsonlPath, [
    event("user", [{ type: "text", text: `<command-message>drive:execute ${caseId}</command-message><command-name>/drive:execute</command-name>` }], "2026-07-23T08:00:00.000Z"),
    event("assistant", [{ type: "tool_use", id: "task1", name: "Task", input: { subagent_type: "协议分析-agent", description: "smoke business task", prompt: "按照工作流执行任务目标，必须通过 Skill 工具调用。" } }], "2026-07-23T08:00:01.000Z"),
    event("user", [{ type: "tool_result", tool_use_id: "task1", content: "done", is_error: false }], "2026-07-23T08:00:02.000Z"),
  ]);

  writeJsonl(path.join(subagentsDir, "agent-1.jsonl"), [
    event("user", [{ type: "text", text: "执行 smoke 任务。" }], "2026-07-23T08:00:01.100Z"),
    event("assistant", [{ type: "text", text: "已完成 smoke 任务。" }], "2026-07-23T08:00:01.900Z"),
  ]);
  fs.writeFileSync(
    path.join(subagentsDir, "agent-1.meta.json"),
    `${JSON.stringify({ toolUseId: "task1", agentType: "协议分析-agent", description: "smoke business task" }, null, 2)}\n`,
    "utf8",
  );

  return { parentJsonlPath, subagentsDir };
}

export function makeTempRoot(prefix = "traceaudit-") {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

// 普通单轮会话：没有派生任何子 Agent，只有一次 Skill 调用和一次 Bash 调用。
export function writePlainTrace({ dir, sessionId = "sess-plain", skillFails = false }) {
  const parentJsonlPath = path.join(dir, `${sessionId}.jsonl`);
  ensureDir(dir);

  writeJsonl(parentJsonlPath, [
    event("user", [{ type: "text", text: "帮我算一下：3+4*2" }], "2026-07-23T09:00:00.000Z"),
    event("assistant", [{ type: "tool_use", id: "skill1", name: "Skill", input: { skill: "calculate" } }], "2026-07-23T09:00:01.000Z"),
    event("user", [{ type: "tool_result", tool_use_id: "skill1", content: "11", is_error: skillFails }], "2026-07-23T09:00:02.000Z"),
    event("assistant", [{ type: "tool_use", id: "bash1", name: "Bash", input: { command: "python3 calculate.py '3+4*2'" } }], "2026-07-23T09:00:03.000Z"),
    event("user", [{ type: "tool_result", tool_use_id: "bash1", content: "11", is_error: false }], "2026-07-23T09:00:04.000Z"),
  ]);

  return { parentJsonlPath, sessionId };
}

export function buildPlainFixture({ prefix = "traceaudit-plain-", sessionId = "sess-plain", skillFails = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const traceRoot = path.join(root, "traces");
  const { parentJsonlPath } = writePlainTrace({ dir: traceRoot, sessionId, skillFails });
  return { root, sessionId, parentJsonlPath };
}

export function buildFixture({ prefix = "traceaudit-", caseId = "SMOKE-001", sessionId = "sess-mock" } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const traceRoot = path.join(root, "traces");
  const { parentJsonlPath, subagentsDir } = writeMainTrace({ dir: traceRoot, sessionId, caseId });
  return { root, caseId, sessionId, parentJsonlPath, subagentsDir };
}

export function outputFiles(generated) {
  const intermediateDir = path.join(generated.outputDir, "_intermediate");
  return [
    generated.reportJsonPath,
    generated.scoresPath,
    generated.reportMdPath,
    path.join(intermediateDir, "evaluation-trace.json"),
    path.join(intermediateDir, "evaluation-trace-processed.json"),
    path.join(intermediateDir, "l0-report.json"),
    path.join(intermediateDir, "l1-report.json"),
    path.join(intermediateDir, "insight-pack.json"),
    path.join(intermediateDir, "report-validation.json"),
  ];
}

export function cleanup(root) {
  if (!process.env.KEEP_SMOKE_TMP) fs.rmSync(root, { recursive: true, force: true });
}
