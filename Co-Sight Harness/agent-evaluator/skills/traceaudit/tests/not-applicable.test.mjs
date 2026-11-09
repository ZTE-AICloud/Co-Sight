import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { scoreDimension, makeCheck, weightedTotal, EVIDENCE_COVERAGE_THRESHOLD } from "../lib/scoring.mjs";
import { evaluateTrace } from "../scripts/traceaudit.mjs";
import { buildFixture, buildPlainFixture, cleanup } from "./fixtures.mjs";

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

test("checks without evidence are not-applicable and never counted as passes", () => {
  const checks = [
    makeCheck({ dimension: "skill-invocation", id: "skill_success_rate", passed: null, status: "not-applicable", severity: "high" }),
  ];
  const scored = scoreDimension("skill-invocation", checks, {});
  assert.equal(scored.score, null);
  assert.equal(scored.applicable, false);
  assert.equal(scored.evidenceCoverage, 0);
});

test("a dimension whose evidence is too thin does not score", () => {
  const checks = [
    makeCheck({ dimension: "trace-efficiency", id: "total_duration", passed: true }),
    makeCheck({ dimension: "trace-efficiency", id: "hitl_wait_time", passed: true }),
    makeCheck({ dimension: "trace-efficiency", id: "per_agent_duration", passed: null, status: "not-applicable" }),
    makeCheck({ dimension: "trace-efficiency", id: "thinking_ratio", passed: null, status: "not-applicable" }),
    makeCheck({ dimension: "trace-efficiency", id: "tool_call_density", passed: null, status: "not-applicable" }),
    makeCheck({ dimension: "trace-efficiency", id: "duplicate_operations", passed: null, status: "not-applicable" }),
    makeCheck({ dimension: "trace-efficiency", id: "error_recovery_pattern", passed: null, status: "not-applicable" }),
  ];
  const scored = scoreDimension("trace-efficiency", checks, {});
  assert.equal(scored.score, null);
  assert.equal(scored.evidenceCoverage, 0.29);
  assert.equal(scored.label, "证据不足");
});

test("weightedTotal renormalizes on the scored dimensions and reports coverage", () => {
  const dimensions = {
    a: { key: "a", weight: 0.3, score: null },
    b: { key: "b", weight: 0.2, score: 5 },
    c: { key: "c", weight: 0.5, score: 1 },
  };
  const total = weightedTotal(dimensions);
  assert.equal(total.totalScore, 2.14);
  assert.equal(total.coverage, 0.7);
  assert.equal(total.scoredWeight, 0.7);
  assert.deepEqual(total.scoredDimensions, ["b", "c"]);
});

test("weightedTotal returns no score when nothing is measurable", () => {
  const total = weightedTotal({ a: { key: "a", weight: 0.3, score: null }, b: { key: "b", weight: 0.7, score: null } });
  assert.equal(total.totalScore, null);
  assert.equal(total.coverage, 0);
});

test("a plain session without subagents is undetermined instead of an inflated pass", async () => {
  const fx = buildPlainFixture();
  try {
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath, outputs: path.join(fx.root, "out") });
    const scores = readJson(generated.scoresPath);

    assert.equal(scores.totalScore, null);
    assert.equal(scores.grade, "UNDETERMINED");
    assert.equal(scores.coverage, 0.2);
    assert.deepEqual(
      [...scores.notApplicableDimensions].sort(),
      ["processCompliance", "reviewCompleteness", "ruleCompliance", "traceEfficiency"],
    );

    for (const key of scores.notApplicableDimensions) {
      assert.equal(scores.scores[key].score, null);
      assert.equal(scores.scores[key].weightedScore, null);
      assert.ok(scores.scores[key].label);
    }
    for (const dimension of Object.values(scores.scores)) {
      for (const check of dimension.checks) {
        assert.notEqual(check.passed, false, `${check.checkId} should not be reported as failed without evidence`);
      }
    }
  } finally {
    cleanup(fx.root);
  }
});

test("skill_success_rate counts main-flow Skill calls, not only subagent ones", async () => {
  const fx = buildPlainFixture();
  try {
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath, outputs: path.join(fx.root, "out") });
    const scores = readJson(generated.scoresPath);
    const check = scores.scores.skillInvocation.checks.find((item) => item.checkId === "skill_success_rate");

    assert.equal(check.actual.total, 1);
    assert.equal(check.actual.parent, 1);
    assert.equal(check.actual.subagent, 0);
    assert.equal(check.passed, true);
    assert.equal(scores.scores.skillInvocation.score, 5);
  } finally {
    cleanup(fx.root);
  }
});

test("a failed main-flow Skill call lowers skill invocation", async () => {
  const fx = buildPlainFixture({ skillFails: true });
  try {
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath, outputs: path.join(fx.root, "out") });
    const scores = readJson(generated.scoresPath);
    const check = scores.scores.skillInvocation.checks.find((item) => item.checkId === "skill_success_rate");

    assert.equal(check.passed, false);
    assert.equal(check.actual.failed, 1);
    assert.ok(scores.scores.skillInvocation.score < 5);
  } finally {
    cleanup(fx.root);
  }
});

test("not-applicable dimensions pass the report self-check", async () => {
  const fx = buildPlainFixture();
  try {
    const generated = await evaluateTrace({ parentJsonlPath: fx.parentJsonlPath, outputs: path.join(fx.root, "out") });
    const validation = readJson(generated.reportValidationPath);
    assert.equal(validation.passed, true, JSON.stringify(validation.issues));
    assert.equal(validation.errorCount, 0);

    const markdown = fs.readFileSync(generated.reportMdPath, "utf8");
    assert.equal(markdown.includes("## 不可判定项"), true);
    assert.equal(markdown.includes("| Total Score | 不可判定 |"), true);

    const report = readJson(generated.reportJsonPath);
    assert.equal(report.summary.totalScore, null);
    assert.equal(report.summary.grade, "UNDETERMINED");
    assert.ok(report.summary.coverage < EVIDENCE_COVERAGE_THRESHOLD);
  } finally {
    cleanup(fx.root);
  }
});

test("an orchestrated trace with subagents still gets a real grade", async () => {
  const fx = buildFixture();
  try {
    const generated = await evaluateTrace({
      parentJsonlPath: fx.parentJsonlPath,
      subagentsDir: fx.subagentsDir,
      outputs: path.join(fx.root, "out"),
    });
    const scores = readJson(generated.scoresPath);

    assert.ok(typeof scores.totalScore === "number");
    assert.notEqual(scores.grade, "UNDETERMINED");
    assert.ok(scores.coverage >= EVIDENCE_COVERAGE_THRESHOLD);
    assert.equal(scores.scores.reviewCompleteness.checks.find((item) => item.checkId === "review_spawn_count").passed, false);
  } finally {
    cleanup(fx.root);
  }
});
