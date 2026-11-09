import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { ensureDir, writeJson } from "../lib/cli.mjs";
import {
  extractRunRef,
  readSeedRecords,
  resolveParentJsonl,
  resolveSeedJsonl,
  slugify,
} from "../lib/seed.mjs";
import { evaluateSeedBatch } from "../scripts/seed-batch.mjs";
import { validateInputs } from "../scripts/traceaudit.mjs";
import { buildFixture, cleanup, makeTempRoot, writeMainTrace, writePlainTrace } from "./fixtures.mjs";

const execFileAsync = promisify(execFile);
const ENTRY_SCRIPT = fileURLToPath(new URL("../scripts/traceaudit.mjs", import.meta.url));

function writeSeedFile(filePath, text) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, text, "utf8");
}

async function runCli(argv, options = {}) {
  try {
    const { stdout, stderr } = await execFileAsync(process.execPath, [ENTRY_SCRIPT, ...argv], {
      encoding: "utf8",
      cwd: options.cwd,
    });
    return { code: 0, stdout, stderr };
  } catch (error) {
    return { code: error.code ?? 1, stdout: error.stdout ?? "", stderr: error.stderr ?? "" };
  }
}

test("resolveSeedJsonl finds eval_datasets/seed.jsonl under seed-dir", () => {
  const root = makeTempRoot("traceaudit-seed-");
  try {
    const nested = path.join(root, "eval_datasets", "seed.jsonl");
    writeSeedFile(nested, "{}\n");
    assert.equal(resolveSeedJsonl(root), nested);

    const directRoot = path.join(root, "flat");
    const direct = path.join(directRoot, "seed.jsonl");
    writeSeedFile(direct, "{}\n");
    assert.equal(resolveSeedJsonl(directRoot), direct);

    assert.throws(() => resolveSeedJsonl(path.join(root, "missing")), /seed-dir not found/);
    const empty = path.join(root, "empty");
    ensureDir(empty);
    assert.throws(() => resolveSeedJsonl(empty), /seed.jsonl not found/);
  } finally {
    cleanup(root);
  }
});

test("readSeedRecords handles JSONL, pretty single object and array documents", () => {
  const root = makeTempRoot("traceaudit-seed-");
  try {
    const jsonl = path.join(root, "jsonl", "seed.jsonl");
    writeSeedFile(jsonl, '{"data_id":"a"}\n{"data_id":"b"}\n\n');
    assert.deepEqual(readSeedRecords(jsonl).map((item) => item.data_id), ["a", "b"]);

    const pretty = path.join(root, "pretty", "seed.jsonl");
    writeSeedFile(pretty, `{\n  "data_id": "c",\n  "run": {\n    "session_id": "s1"\n  }\n}\n`);
    const prettyRecords = readSeedRecords(pretty);
    assert.equal(prettyRecords.length, 1);
    assert.equal(prettyRecords[0].run.session_id, "s1");

    const arrayDoc = path.join(root, "array", "seed.jsonl");
    writeJson(arrayDoc, [{ data_id: "d" }, { data_id: "e" }]);
    assert.deepEqual(readSeedRecords(arrayDoc).map((item) => item.data_id), ["d", "e"]);

    const wrapped = path.join(root, "wrapped", "seed.jsonl");
    writeJson(wrapped, { records: [{ data_id: "f" }] });
    assert.deepEqual(readSeedRecords(wrapped).map((item) => item.data_id), ["f"]);

    const concatenated = path.join(root, "concat", "seed.jsonl");
    writeSeedFile(concatenated, '{\n "data_id": "g"\n}\n{\n "data_id": "h"\n}\n');
    assert.deepEqual(readSeedRecords(concatenated).map((item) => item.data_id), ["g", "h"]);
  } finally {
    cleanup(root);
  }
});

test("extractRunRef maps run.session_id / run.session_dir and reports missing run", () => {
  const ref = extractRunRef({
    data_id: "case-1",
    capability_ref: "C01",
    dimension: "functional",
    input: "帮我算一下：3+4*2",
    run: { session_id: "sess-1", session_dir: "/tmp/sessions", case_dir: "/tmp/case-1" },
  });
  assert.equal(ref.dataId, "case-1");
  assert.equal(ref.capabilityRef, "C01");
  assert.equal(ref.dimension, "functional");
  assert.equal(ref.sessionId, "sess-1");
  assert.equal(ref.sessionDir, "/tmp/sessions");
  assert.equal(ref.caseDir, "/tmp/case-1");
  assert.equal(ref.error, null);

  const noRun = extractRunRef({ data_id: "case-2" });
  assert.match(noRun.error, /缺少 run 字段/);

  const noSession = extractRunRef({ data_id: "case-3", run: { exit_code: 0 } });
  assert.match(noSession.error, /缺少 session_id \/ session_dir/);
});

test("resolveParentJsonl resolves <session_dir>/<session_id>.jsonl, relative paths and case_dir", () => {
  const root = makeTempRoot("traceaudit-seed-");
  try {
    const seedJsonlPath = path.join(root, "eval_datasets", "seed.jsonl");
    writeSeedFile(seedJsonlPath, "{}\n");

    const sessionsDir = path.join(root, "run_datasets", "case-1", "sessions");
    writeMainTrace({ dir: sessionsDir, sessionId: "sess-abc" });

    const absolute = resolveParentJsonl({
      ref: extractRunRef({ run: { session_id: "sess-abc", session_dir: sessionsDir } }),
      seedJsonlPath,
    });
    assert.equal(absolute, path.join(sessionsDir, "sess-abc.jsonl"));

    const relative = resolveParentJsonl({
      ref: extractRunRef({ run: { session_id: "sess-abc", session_dir: "run_datasets/case-1/sessions" } }),
      seedJsonlPath,
    });
    assert.equal(relative, path.join(sessionsDir, "sess-abc.jsonl"));

    const onlyJsonl = path.join(root, "solo", "sessions");
    writeMainTrace({ dir: onlyJsonl, sessionId: "whatever" });
    const byListing = resolveParentJsonl({
      ref: extractRunRef({ run: { session_id: "unknown-session", session_dir: onlyJsonl } }),
      seedJsonlPath,
    });
    assert.equal(byListing, path.join(onlyJsonl, "whatever.jsonl"));

    const missing = resolveParentJsonl({
      ref: extractRunRef({ run: { session_id: "sess-abc", session_dir: path.join(root, "nope") } }),
      seedJsonlPath,
    });
    assert.equal(missing, null);
  } finally {
    cleanup(root);
  }
});

test("resolveParentJsonl uses run.case_dir/sessions when only case_dir is present", () => {
  const root = makeTempRoot("traceaudit-seed-");
  try {
    const seedJsonlPath = path.join(root, "eval_datasets", "seed.jsonl");
    writeSeedFile(seedJsonlPath, "{}\n");

    const caseDir = path.join(root, "run_datasets", "case-only");
    const sessionsDir = path.join(caseDir, "sessions");
    writeMainTrace({ dir: sessionsDir, sessionId: "sess-case-only" });

    const ref = extractRunRef({ data_id: "case_only", run: { case_dir: caseDir } });
    assert.equal(ref.error, null);
    assert.equal(ref.sessionId, null);
    assert.equal(
      resolveParentJsonl({ ref, seedJsonlPath }),
      path.join(sessionsDir, "sess-case-only.jsonl"),
    );
  } finally {
    cleanup(root);
  }
});

test("slugify keeps data ids filesystem-safe", () => {
  assert.equal(slugify("runtime_functional_001"), "runtime_functional_001");
  assert.equal(slugify("case/with spaces"), "case-with-spaces");
  assert.equal(slugify(""), "case");
  assert.equal(slugify("..."), "case");
});

test("evaluateSeedBatch evaluates every seed record then writes an aggregate report", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  try {
    const seedDir = path.join(root, "seed");
    const seedJsonlPath = path.join(seedDir, "eval_datasets", "seed.jsonl");

    const sessionsA = path.join(seedDir, "run_datasets", "case_a", "sessions");
    const sessionsB = path.join(seedDir, "run_datasets", "case_b", "sessions");
    writeMainTrace({ dir: sessionsA, sessionId: "sess-a", caseId: "BATCH-A" });
    writeMainTrace({ dir: sessionsB, sessionId: "sess-b", caseId: "BATCH-B" });

    const records = [
      { data_id: "case_a", capability_ref: "C01", dimension: "functional", run: { session_id: "sess-a", session_dir: sessionsA } },
      { data_id: "case_b", capability_ref: "C02", dimension: "boundary", run: { session_id: "sess-b", session_dir: "run_datasets/case_b/sessions" } },
      { data_id: "case_missing", run: { session_id: "sess-x", session_dir: path.join(root, "nope") } },
      { data_id: "case_broken", run: { exit_code: 0 } },
    ];
    writeSeedFile(seedJsonlPath, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`);

    const batch = await evaluateSeedBatch({ seedDir, outputs: path.join(root, "out") });

    assert.equal(batch.seedJsonlPath, seedJsonlPath);
    assert.equal(batch.summary.meta.recordCount, 4);
    assert.equal(batch.summary.meta.succeeded, 2);
    assert.equal(batch.summary.meta.failed, 2);
    assert.equal(batch.summary.cases.length, 4);

    const [okA, okB, missing, broken] = batch.summary.cases;
    assert.equal(okA.status, "ok");
    assert.equal(okA.caseId, "BATCH-A");
    assert.equal(okA.sessionId, "sess-a");
    assert.ok(typeof okA.totalScore === "number");
    assert.equal(okA.parentJsonlPath, path.join(sessionsA, "sess-a.jsonl"));
    assert.equal(fs.existsSync(okA.reportMarkdown), true);
    assert.equal(Object.keys(okA.dimensions).length, 5);

    assert.equal(okB.status, "ok");
    assert.equal(okB.caseId, "BATCH-B");
    assert.equal(okB.parentJsonlPath, path.join(sessionsB, "sess-b.jsonl"));

    assert.equal(missing.status, "failed");
    assert.equal(missing.stage, "resolve");
    assert.match(missing.error, /未找到主 trace jsonl/);

    assert.equal(broken.status, "failed");
    assert.match(broken.error, /缺少 session_id \/ session_dir/);

    assert.equal(batch.summary.aggregate.evaluatedCount, 2);
    assert.ok(batch.summary.aggregate.averageTotalScore > 0);
    assert.equal(Object.keys(batch.summary.aggregate.dimensionAverages).length, 5);
    assert.equal(batch.summary.aggregate.dimensionAverages.processCompliance.scoredCount, 2);

    assert.equal(fs.existsSync(batch.summaryJsonPath), true);
    assert.equal(fs.existsSync(batch.summaryMdPath), true);
    assert.equal(fs.existsSync(path.join(batch.outputRoot, "cases", "case_a", "trajectory-report.json")), true);

    const markdown = fs.readFileSync(batch.summaryMdPath, "utf8");
    assert.equal(markdown.includes("# 轨迹批量评估汇总报告"), true);
    assert.equal(markdown.includes("case_a"), true);
    assert.equal(markdown.includes("case_broken"), true);
    assert.equal(markdown.includes("## 失败用例"), true);
  } finally {
    cleanup(root);
  }
});

test("duplicate data_ids get distinct output dirs and an unresolvable subagents_dir is warned", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  try {
    const seedDir = path.join(root, "seed");
    const sessions = path.join(seedDir, "run_datasets", "dup", "sessions");
    writeMainTrace({ dir: sessions, sessionId: "sess-dup", caseId: "BATCH-DUP" });

    const missingSubagents = path.join(root, "missing-subagents");
    const records = [
      { data_id: "x", run: { session_id: "sess-dup", session_dir: sessions } },
      { data_id: "x", run: { session_id: "sess-dup", session_dir: sessions } },
      { data_id: "x-2", run: { session_id: "sess-dup", session_dir: sessions } },
      { data_id: "y", run: { session_id: "sess-dup", session_dir: sessions, subagents_dir: missingSubagents } },
    ];
    writeSeedFile(path.join(seedDir, "eval_datasets", "seed.jsonl"), `${records.map((r) => JSON.stringify(r)).join("\n")}\n`);

    const batch = await evaluateSeedBatch({ seedDir, outputs: path.join(root, "out") });
    const slugs = batch.summary.cases.map((item) => item.slug);

    assert.deepEqual(slugs, ["x", "x-2", "x-2-2", "y"]);
    assert.equal(new Set(slugs).size, 4);
    assert.equal(new Set(batch.summary.cases.map((item) => item.outputDir)).size, 4);

    for (const item of batch.summary.cases) {
      assert.equal(item.status, "ok");
      assert.equal(fs.existsSync(item.reportMarkdown), true);
      assert.equal(fs.existsSync(item.scoresJson), true);
    }

    const warned = batch.summary.cases[3];
    assert.equal(warned.subagentsDirRequested, missingSubagents);
    assert.equal(warned.subagentsDir, null);
    const traceWarningCount = process.env.CLAUDE_PLUGIN_ROOT ? 0 : 1;
    assert.equal(warned.warnings.length, 1 + traceWarningCount);
    assert.match(warned.warnings[0], /subagents_dir 指向的目录不存在/);
    assert.equal(batch.summary.meta.warned, traceWarningCount > 0 ? 4 : 1);

    const markdown = fs.readFileSync(batch.summaryMdPath, "utf8");
    assert.equal(markdown.includes("## 警告"), true);
    assert.equal(markdown.includes("missing-subagents"), true);
  } finally {
    cleanup(root);
  }
});

test("evaluateSeedBatch records a timed-out record instead of hanging", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  try {
    const seedDir = path.join(root, "seed");
    const sessions = path.join(seedDir, "run_datasets", "slow", "sessions");
    writeMainTrace({ dir: sessions, sessionId: "sess-slow" });
    writeSeedFile(
      path.join(seedDir, "eval_datasets", "seed.jsonl"),
      `${JSON.stringify({ data_id: "slow_case", run: { session_id: "sess-slow", session_dir: sessions } })}\n`,
    );

    const batch = await evaluateSeedBatch({ seedDir, outputs: path.join(root, "out"), timeoutMs: 50 });

    assert.equal(batch.summary.meta.recordCount, 1);
    assert.equal(batch.summary.meta.succeeded, 0);
    assert.equal(batch.summary.meta.failed, 1);
    assert.equal(batch.summary.meta.timeoutMs, 50);

    const [timedOut] = batch.summary.cases;
    assert.equal(timedOut.status, "failed");
    assert.equal(timedOut.stage, "evaluate");
    assert.match(timedOut.error, /未结束，已终止/);

    const markdown = fs.readFileSync(batch.summaryMdPath, "utf8");
    assert.equal(markdown.includes("| 单条超时 | 50ms |"), true);
  } finally {
    cleanup(root);
  }
});

test("batch artifacts land under <outputs>/eval_trace_results/", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  const previousCwd = process.cwd();
  try {
    const seedDir = path.join(root, "seed");
    const sessions = path.join(seedDir, "run_datasets", "layout", "sessions");
    writeMainTrace({ dir: sessions, sessionId: "sess-layout" });
    writeSeedFile(
      path.join(seedDir, "eval_datasets", "seed.jsonl"),
      `${JSON.stringify({ data_id: "layout_case", run: { session_id: "sess-layout", session_dir: sessions } })}\n`,
    );

    const explicitParent = path.join(root, "explicit");
    ensureDir(explicitParent);
    const withOutputs = await evaluateSeedBatch({ seedDir, outputs: explicitParent });
    assert.equal(path.dirname(withOutputs.outputRoot), explicitParent);
    assert.equal(path.basename(withOutputs.outputRoot), "eval_trace_results");
    assert.equal(fs.existsSync(withOutputs.summaryJsonPath), true);

    const fakeCwd = path.join(root, "cwd");
    ensureDir(fakeCwd);
    process.chdir(fakeCwd);
    const withoutOutputs = await evaluateSeedBatch({ seedDir });
    assert.equal(path.dirname(withoutOutputs.outputRoot), fs.realpathSync(fakeCwd));
    assert.equal(path.basename(withoutOutputs.outputRoot), "eval_trace_results");
    assert.equal(fs.existsSync(path.join(withoutOutputs.outputRoot, "cases", "layout_case", "trajectory-report.json")), true);
  } finally {
    process.chdir(previousCwd);
    cleanup(root);
  }
});

test("validateInputs and the CLI reject --seed-dir combined with parent-jsonl / subagents-dir", async () => {
  const fx = buildFixture();
  try {
    const seedDir = path.join(fx.root, "seed");
    writeSeedFile(path.join(seedDir, "eval_datasets", "seed.jsonl"), "{}\n");

    for (const extra of [
      { parentJsonlPath: fx.parentJsonlPath },
      { subagentsDir: fx.subagentsDir },
      { parentJsonlPath: fx.parentJsonlPath, subagentsDir: fx.subagentsDir },
    ]) {
      const result = validateInputs({ seedDir, ...extra });
      assert.equal(result.ok, false);
      assert.match(result.errors[0], /不能与 --parent-jsonl \/ --subagents-dir 同时传递/);
    }

    assert.equal(validateInputs({ seedDir }).ok, true);
    assert.equal(validateInputs({ parentJsonlPath: fx.parentJsonlPath, subagentsDir: fx.subagentsDir }).ok, true);

    const cli = await runCli([
      "--seed-dir", seedDir,
      "--parent-jsonl", fx.parentJsonlPath,
      "--subagents-dir", fx.subagentsDir,
    ]);
    assert.equal(cli.code, 1);
    assert.equal(cli.stdout, "");
    assert.match(cli.stderr, /invalid_arguments/);
    assert.match(cli.stderr, /不能与 --parent-jsonl \/ --subagents-dir 同时传递/);
    assert.equal(fs.existsSync(path.join(seedDir, "eval_results")), false);
  } finally {
    cleanup(fx.root);
  }
});

test("batch without --outputs refuses to write into the skill root", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  const previousCwd = process.cwd();
  try {
    const seedDir = path.join(root, "seed");
    const sessions = path.join(seedDir, "run_datasets", "cwd", "sessions");
    writeMainTrace({ dir: sessions, sessionId: "sess-cwd" });
    writeSeedFile(
      path.join(seedDir, "eval_datasets", "seed.jsonl"),
      `${JSON.stringify({ data_id: "cwd_case", run: { session_id: "sess-cwd", session_dir: sessions } })}\n`,
    );

    const skillRoot = fileURLToPath(new URL("..", import.meta.url));
    const before = new Set(fs.readdirSync(skillRoot));

    process.chdir(skillRoot);
    await assert.rejects(() => evaluateSeedBatch({ seedDir }), /不能把评测产物写进 skill 自身目录/);

    const cli = await runCli(["--seed-dir", seedDir], { cwd: skillRoot });
    assert.equal(cli.code, 1);
    assert.match(cli.stderr, /不能把评测产物写进 skill 自身目录/);

    const created = fs.readdirSync(skillRoot).filter((name) => !before.has(name));
    assert.deepEqual(created, []);
  } finally {
    process.chdir(previousCwd);
    cleanup(root);
  }
});

test("evaluateSeedBatch rejects an empty seed file", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  try {
    const seedDir = path.join(root, "seed");
    writeSeedFile(path.join(seedDir, "eval_datasets", "seed.jsonl"), "\n");
    await assert.rejects(() => evaluateSeedBatch({ seedDir, outputs: path.join(root, "out") }), /没有可评测的记录/);
  } finally {
    cleanup(root);
  }
});

test("undetermined cases form their own bucket and stay out of the average", async () => {
  const root = makeTempRoot("traceaudit-batch-");
  try {
    const seedDir = path.join(root, "seed");
    const seedJsonlPath = path.join(seedDir, "eval_datasets", "seed.jsonl");

    const sessionsPlain = path.join(seedDir, "run_datasets", "plain", "sessions");
    const sessionsOrch = path.join(seedDir, "run_datasets", "orch", "sessions");
    writePlainTrace({ dir: sessionsPlain, sessionId: "sess-plain" });
    writeMainTrace({ dir: sessionsOrch, sessionId: "sess-orch", caseId: "BATCH-ORCH" });

    const records = [
      { data_id: "plain", run: { session_id: "sess-plain", session_dir: sessionsPlain } },
      { data_id: "orch", run: { session_id: "sess-orch", session_dir: sessionsOrch } },
    ];
    writeSeedFile(seedJsonlPath, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`);

    const batch = await evaluateSeedBatch({ seedDir, outputs: path.join(root, "out") });
    const { meta, aggregate, cases } = batch.summary;

    assert.equal(meta.succeeded, 2);
    assert.equal(meta.scored, 1);
    assert.equal(meta.undetermined, 1);
    assert.equal(aggregate.undeterminedCount, 1);
    assert.deepEqual(aggregate.undeterminedCases.map((item) => item.dataId), ["plain"]);
    assert.equal(aggregate.gradeDistribution.UNDETERMINED, 1);

    const plain = cases.find((item) => item.dataId === "plain");
    const orch = cases.find((item) => item.dataId === "orch");
    assert.equal(plain.totalScore, null);
    assert.equal(plain.grade, "UNDETERMINED");
    assert.equal(orch.totalScore, aggregate.averageTotalScore);

    assert.equal(aggregate.dimensionAverages.skillInvocation.scoredCount, 1);
    assert.equal(aggregate.dimensionAverages.skillInvocation.notApplicableCount, 1);
    assert.equal(aggregate.dimensionAverages.processCompliance.scoredCount, 1);
    assert.equal(aggregate.dimensionAverages.processCompliance.notApplicableCount, 1);

    const markdown = fs.readFileSync(batch.summaryMdPath, "utf8");
    assert.equal(markdown.includes("## 不可判定用例"), true);
    assert.equal(markdown.includes("| 可评级 / 不可判定 | 1 / 1 |"), true);
  } finally {
    cleanup(root);
  }
});
