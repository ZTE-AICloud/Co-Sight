#!/usr/bin/env node
import path from "node:path";
import {
  ensureDir,
  isDirectory,
  isFile,
  isMainModule,
  parseArgs,
  resolveWorkspaceDir,
  writeJson,
} from "../lib/cli.mjs";
import { loadRubrics, dimensionKey, dimensionLabel } from "../lib/rubrics.mjs";
import { collectTrace } from "./collect.mjs";
import { preprocessTrace } from "./preprocess.mjs";
import { runL0 } from "./l0.mjs";
import { runL1 } from "./l1.mjs";
import { generateReports } from "./report-generator.mjs";
import { evaluateSeedBatch } from "./seed-batch.mjs";
import { resolveSeedJsonl } from "../lib/seed.mjs";

const HELP = `
Usage:
  node scripts/traceaudit.mjs --parent-jsonl <主trace.jsonl> [--subagents-dir <子Agent trace目录>]
                              [--outputs <输出目录>]

  node scripts/traceaudit.mjs --seed-dir <seed目录> [--outputs <输出目录>]
  node scripts/traceaudit.mjs batch --seed-dir <seed目录> [--outputs <输出目录>]

  node scripts/traceaudit.mjs validate --parent-jsonl <主trace.jsonl> [--subagents-dir <目录>]
  node scripts/traceaudit.mjs validate --seed-dir <seed目录>
  node scripts/traceaudit.mjs list

参数:
  --parent-jsonl    单条评测必填，且不可与 --seed-dir 同时传递。主 trace 的 JSONL 文件路径；
                    session id 取文件名（去掉 .jsonl）。
  --subagents-dir   选填，且不可与 --seed-dir 同时传递。子 Agent trace 目录
                    （默认 <parent-jsonl 所在目录>/<session-id>/subagents）。
  --outputs         选填。单条评测时是报告输出目录本身；
                    批量评测时是父目录，实际产物落在 <outputs>/eval_trace_results/。
                    省略时落到 <当前工作目录>/eval_trace_results/。
  --seed-dir        批量评测必填。目录下固定存在 eval_datasets/seed.jsonl，逐条 run 记录循环评测；
                    给了它就不需要（也不允许）--parent-jsonl / --subagents-dir。
  --timeout-ms      选填。批量模式下单条评测的超时毫秒数（默认 600000，0 表示不限制）。
`;

const EXCLUSIVE_ERROR = "--seed-dir 不能与 --parent-jsonl / --subagents-dir 同时传递：批量模式的 trace 坐标来自 seed.jsonl。";

export async function evaluateTrace({ parentJsonlPath, subagentsDir, outputs }) {
  if (!parentJsonlPath) throw new Error(`--parent-jsonl is required.\n${HELP}`);

  const resolvedParentJsonlPath = path.resolve(String(parentJsonlPath));
  if (!isFile(resolvedParentJsonlPath)) throw new Error(`Parent jsonl not found: ${resolvedParentJsonlPath}`);

  const sessionId = path.basename(resolvedParentJsonlPath, ".jsonl");
  const resolvedSubagentsDir = resolveSubagentsDir({ subagentsDir, resolvedParentJsonlPath, sessionId });
  const claudeProjectDir = path.dirname(resolvedParentJsonlPath);

  const rubrics = loadRubrics();

  const rawTrace = collectTrace({
    sessionId,
    claudeProjectDir,
    parentJsonlPath: resolvedParentJsonlPath,
    subagentsDir: resolvedSubagentsDir,
  });

  // caseId 由 trace 推导（execute 触发命令），推导失败时回退 sessionId
  const caseId = rawTrace.meta.caseId ?? sessionId;
  const resolvedOutputDir = path.resolve(String(
    outputs ?? defaultOutputDir({ caseId, sessionId }),
  ));
  const intermediateDir = path.join(resolvedOutputDir, "_intermediate");
  ensureDir(intermediateDir);
  writeJson(path.join(intermediateDir, "evaluation-trace.json"), rawTrace);

  const processedTrace = preprocessTrace(rawTrace);
  writeJson(path.join(intermediateDir, "evaluation-trace-processed.json"), processedTrace);

  const l0 = runL0(processedTrace, rubrics);
  const l1 = runL1(processedTrace, rubrics);
  writeJson(path.join(intermediateDir, "l0-report.json"), l0);
  writeJson(path.join(intermediateDir, "l1-report.json"), l1);

  const generated = generateReports({
    trace: processedTrace,
    rubrics,
    reports: { L0: l0, L1: l1 },
    outputDir: resolvedOutputDir,
  });

  return {
    caseId,
    outputDir: resolvedOutputDir,
    session: {
      sessionId,
      claudeProjectDir,
      parentJsonlPath: resolvedParentJsonlPath,
      subagentsDir: resolvedSubagentsDir,
      selectedBy: "offline-trace-files",
      traceStatus: rawTrace.summary?.interrupted ? "interrupted" : "collected",
    },
    ...generated,
  };
}

export function validateInputs({ parentJsonlPath, subagentsDir, seedDir }) {
  const errors = [];
  const warnings = [];

  if (seedDir && (parentJsonlPath || subagentsDir)) {
    errors.push(EXCLUSIVE_ERROR);
    return { ok: false, errors, warnings };
  }

  if (!parentJsonlPath && !seedDir) {
    errors.push("--parent-jsonl is required.");
  } else if (parentJsonlPath && !isFile(path.resolve(String(parentJsonlPath)))) {
    errors.push(`parent-jsonl not found: ${path.resolve(String(parentJsonlPath))}`);
  }

  if (subagentsDir && !isDirectory(path.resolve(String(subagentsDir)))) {
    errors.push(`subagents-dir not found: ${path.resolve(String(subagentsDir))}`);
  }

  if (seedDir) {
    try {
      resolveSeedJsonl(seedDir);
    } catch (error) {
      errors.push(error.message);
    }
  }

  return { ok: errors.length === 0, errors, warnings };
}

export function listDimensions() {
  return loadRubrics().map((rubric) => ({
    id: rubric.dimension.id,
    key: dimensionKey(rubric.dimension.id),
    name: dimensionLabel(rubric.dimension.id),
    weight: rubric.dimension.weight ?? null,
    deterministicChecks: [
      ...(rubric.rule_checks ?? []).map((check) => check.id),
      ...(rubric.structure_checks ?? []).map((check) => check.id),
    ],
  }));
}

function resolveSubagentsDir({ subagentsDir, resolvedParentJsonlPath, sessionId }) {
  if (subagentsDir) {
    const resolved = path.resolve(String(subagentsDir));
    if (!isDirectory(resolved)) throw new Error(`Subagents dir not found: ${resolved}`);
    return resolved;
  }
  const fallback = path.join(path.dirname(resolvedParentJsonlPath), sessionId, "subagents");
  return isDirectory(fallback) ? fallback : null;
}

function defaultOutputDir({ caseId, sessionId }) {
  const compactTime = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const shortSession = String(sessionId ?? "unknown").slice(0, 8);
  const label = caseId && caseId !== sessionId ? `${caseId}_${shortSession}` : shortSession;
  return path.join(resolveWorkspaceDir(), "eval_trace_results", `${label}_${compactTime}`);
}

async function main() {
  const argv = process.argv.slice(2);
  const command = ["validate", "list", "batch"].includes(argv[0]) ? argv[0] : "run";
  const args = parseArgs(command === "run" ? argv : argv.slice(1));

  if (args.help || args.h) {
    console.log(HELP.trim());
    return;
  }

  if (command === "list") {
    console.log(JSON.stringify(listDimensions(), null, 2));
    return;
  }

  if (command === "validate") {
    const result = validateInputs({
      parentJsonlPath: args["parent-jsonl"],
      subagentsDir: args["subagents-dir"],
      seedDir: args["seed-dir"],
    });
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.ok ? 0 : 1;
    return;
  }

  if (args["seed-dir"] || command === "batch") {
    const conflicts = [
      args["parent-jsonl"] ? "--parent-jsonl" : null,
      args["subagents-dir"] ? "--subagents-dir" : null,
    ].filter(Boolean);
    if (conflicts.length) {
      console.error(JSON.stringify({
        status: "invalid_arguments",
        error: `${EXCLUSIVE_ERROR}（同时传了 ${conflicts.join(" 和 ")}）`,
      }, null, 2));
      process.exitCode = 1;
      return;
    }

    const batch = await evaluateSeedBatch({
      seedDir: args["seed-dir"],
      outputs: args.outputs,
      timeoutMs: args["timeout-ms"],
    });
    console.log(JSON.stringify({
      mode: "seed-batch",
      seedJsonl: batch.seedJsonlPath,
      outputRoot: batch.outputRoot,
      summary: batch.summaryJsonPath,
      markdown: batch.summaryMdPath,
      recordCount: batch.summary.meta.recordCount,
      succeeded: batch.summary.meta.succeeded,
      failed: batch.summary.meta.failed,
      averageTotalScore: batch.summary.aggregate.averageTotalScore,
    }, null, 2));
    if (batch.summary.meta.succeeded === 0) process.exitCode = 1;
    return;
  }

  const generated = await evaluateTrace({
    parentJsonlPath: args["parent-jsonl"],
    subagentsDir: args["subagents-dir"],
    outputs: args.outputs,
  });

  console.log(JSON.stringify({
    caseId: generated.caseId,
    sessionId: generated.session.sessionId,
    outputDir: generated.outputDir,
    report: generated.reportJsonPath,
    scores: generated.scoresPath,
    markdown: generated.reportMdPath,
    totalScore: generated.rubricScores.totalScore,
    grade: generated.rubricScores.grade,
  }, null, 2));
}

export { evaluateSeedBatch };

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(JSON.stringify({ status: "evaluation_failed", error: error.message }, null, 2));
    process.exit(1);
  });
}
