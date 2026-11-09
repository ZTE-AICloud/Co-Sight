import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { ensureDir, resolveWorkspaceDir } from "../lib/cli.mjs";
import { evaluateTrace, validateInputs } from "../scripts/traceaudit.mjs";
import { buildFixture, cleanup, makeTempRoot, outputFiles as OUTPUT_FILES } from "./fixtures.mjs";

const SKILL_ROOT = fileURLToPath(new URL("..", import.meta.url));


test("trace-only evaluation runs the deterministic pipeline", async () => {
  const fx = buildFixture();
  try {
    const generated = await evaluateTrace({
      parentJsonlPath: fx.parentJsonlPath,
      subagentsDir: fx.subagentsDir,
      outputs: path.join(fx.root, "out"),
    });

    for (const filePath of OUTPUT_FILES(generated)) {
      assert.equal(fs.existsSync(filePath), true, `missing output: ${filePath}`);
    }

    const scores = JSON.parse(fs.readFileSync(generated.scoresPath, "utf8"));
    assert.equal(generated.caseId, fx.caseId);
    assert.equal(generated.session.sessionId, fx.sessionId);
    assert.ok(typeof scores.totalScore === "number");
    assert.ok(["EXCELLENT", "ACCEPTABLE", "POOR", "CRITICAL"].includes(scores.grade));

    assert.equal(Object.keys(scores.scores).length, 5);
    assert.equal("redLinesTriggered" in scores, false);
    assert.equal("executionCompleteness" in scores, false);
    assert.equal("executionStatus" in scores.meta, false);
    assert.equal("requirementId" in scores.meta, false);

    const markdown = fs.readFileSync(generated.reportMdPath, "utf8");
    assert.equal(markdown.includes("## 总结"), true);
    assert.equal(markdown.includes("## 执行完整性"), false);
    assert.equal(markdown.includes("Work Dir"), false);
    assert.equal(markdown.includes("Execution Status"), false);

    const validation = JSON.parse(fs.readFileSync(path.join(generated.outputDir, "_intermediate", "report-validation.json"), "utf8"));
    assert.equal(validation.errorCount, 0, JSON.stringify(validation.issues, null, 2));
  } finally {
    cleanup(fx.root);
  }
});

test("subagents-dir defaults to <jsonl dir>/<session>/subagents", async () => {
  const fx = buildFixture();
  try {
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath, outputs: path.join(fx.root, "out") });
    assert.equal(generated.session.subagentsDir, fx.subagentsDir);
  } finally {
    cleanup(fx.root);
  }
});

test("default output dir lands directly under cwd, not the trace directory", async () => {
  const fx = buildFixture();
  const previousCwd = process.cwd();
  const fakeCwd = path.join(fx.root, "cwd");
  ensureDir(fakeCwd);
  try {
    process.chdir(fakeCwd);
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath });

    assert.equal(path.dirname(generated.outputDir), path.join(fakeCwd, "eval_trace_results"));
    assert.equal(generated.outputDir.startsWith(path.dirname(fx.parentJsonlPath)), false);

    const label = path.basename(generated.outputDir);
    assert.equal(label.startsWith(`${fx.caseId}_${fx.sessionId.slice(0, 8)}_`), true);
    assert.equal(fs.existsSync(path.join(fakeCwd, "eval_trace_results", label, "trajectory-report.json")), true);
  } finally {
    process.chdir(previousCwd);
    cleanup(fx.root);
  }
});

test("resolveWorkspaceDir never anchors outputs inside the skill's own directory", () => {
  const root = makeTempRoot("traceaudit-cwd-");
  const previousCwd = process.cwd();
  const previousInitCwd = process.env.INIT_CWD;
  try {
    const workspace = path.join(root, "workspace");
    ensureDir(workspace);

    process.chdir(workspace);
    assert.equal(resolveWorkspaceDir(), fs.realpathSync(workspace));

    process.chdir(SKILL_ROOT);
    delete process.env.INIT_CWD;
    assert.throws(() => resolveWorkspaceDir(), /不能把评测产物写进 skill 自身目录/);

    process.chdir(SKILL_ROOT);
    process.env.INIT_CWD = workspace;
    assert.equal(fs.realpathSync(resolveWorkspaceDir()), fs.realpathSync(workspace));

    process.chdir(SKILL_ROOT);
    process.env.INIT_CWD = path.join(SKILL_ROOT, "scripts");
    assert.throws(() => resolveWorkspaceDir(), /不能把评测产物写进 skill 自身目录/);
  } finally {
    process.chdir(previousCwd);
    if (previousInitCwd === undefined) delete process.env.INIT_CWD;
    else process.env.INIT_CWD = previousInitCwd;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("default output dir is refused when the caller runs from the skill root", async () => {
  const fx = buildFixture();
  const previousCwd = process.cwd();
  try {
    const before = new Set(fs.readdirSync(SKILL_ROOT));
    process.chdir(SKILL_ROOT);
    await assert.rejects(
      () => evaluateTrace({ parentJsonlPath: fx.parentJsonlPath }),
      /不能把评测产物写进 skill 自身目录/,
    );
    assert.deepEqual(fs.readdirSync(SKILL_ROOT).filter((name) => !before.has(name)), []);
  } finally {
    process.chdir(previousCwd);
    cleanup(fx.root);
  }
});

test("validateInputs only requires parent-jsonl", () => {
  const fx = buildFixture();
  try {
    const ok = validateInputs({ parentJsonlPath: fx.parentJsonlPath });
    assert.equal(ok.ok, true);
    assert.equal(ok.errors.length, 0);
    assert.equal(ok.warnings.length, 0);

    const missingParent = validateInputs({ subagentsDir: fx.subagentsDir });
    assert.equal(missingParent.ok, false);
    assert.match(missingParent.errors[0], /parent-jsonl is required/);

    const badSubagents = validateInputs({ parentJsonlPath: fx.parentJsonlPath, subagentsDir: path.join(fx.root, "nope") });
    assert.equal(badSubagents.ok, false);
    assert.match(badSubagents.errors[0], /subagents-dir not found/);
  } finally {
    cleanup(fx.root);
  }
});
