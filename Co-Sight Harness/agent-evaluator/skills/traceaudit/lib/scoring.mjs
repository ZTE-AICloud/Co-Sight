import { dimensionKey, dimensionLabel } from "./rubrics.mjs";

// 证据状态分层 — 5 级证据状态
export const EVIDENCE_LEVEL = Object.freeze({
  MISSING: "missing",
  UNOBSERVED: "unobserved",
  PRESENT: "present",
  EXERCISED: "exercised",
  OUTCOME_SUPPORTED: "outcome-supported",
  NOT_APPLICABLE: "not-applicable",
});

// 一个维度没有可判证据时不给分；可判检查项占比过低时该维度也不给分；
// 整体覆盖率低于阈值时整体不评级。
export const NOT_APPLICABLE = "not-applicable";
export const EVIDENCE_COVERAGE_THRESHOLD = 0.6;
const MIN_DIMENSION_COVERAGE = 0.5;
const UNSCORED_STATUSES = new Set([NOT_APPLICABLE, "skipped", "unobserved"]);

export function isApplicable(check) {
  return !UNSCORED_STATUSES.has(check?.status);
}

export function makeCheck({ dimension, id, name, passed, actual, expected, evidence, severity = "medium", layer = "L0", status, evidenceLevel, ...extra }) {
  const scored = !UNSCORED_STATUSES.has(status);
  return {
    dimension,
    checkId: id,
    name: name ?? id,
    // 无证据的检查项既不算通过也不算失败，passed 记为 null
    passed: scored ? Boolean(passed) : null,
    status: status ?? (passed ? "pass" : "fail"),
    actual,
    expected,
    evidence: evidence ?? "",
    severity,
    layer,
    evidenceLevel: evidenceLevel ?? (scored ? "exercised" : EVIDENCE_LEVEL.NOT_APPLICABLE),
    ...extra,
  };
}

export function scoreDimension(dimensionId, checks, context = {}) {
  // 无证据的检查项不参与打分；证据太薄时该维度不适用（score = null），
  // 不允许“没查成”被折算成“查过了，满分”。
  const applicable = checks.filter(isApplicable);
  const evidenceCoverage = checks.length === 0 ? 0 : roundTo(applicable.length / checks.length, 2);

  if (applicable.length === 0 || evidenceCoverage < MIN_DIMENSION_COVERAGE) {
    return {
      score: null,
      label: applicable.length === 0 ? "不适用" : "证据不足",
      applicable: false,
      evidenceCoverage,
    };
  }

  return { ...scoreApplicable(dimensionId, applicable, context), applicable: true, evidenceCoverage };
}

function scoreApplicable(dimensionId, checks, context = {}) {
  if (dimensionId === "process-compliance") return scoreProcess(checks, context);
  if (dimensionId === "skill-invocation") return scoreSkill(checks);
  if (dimensionId === "review-completeness") return scoreReview(checks);
  if (dimensionId === "rule-compliance") return scoreRules(checks);
  if (dimensionId === "trace-efficiency") return scoreEfficiency(checks);
  return scoreGeneric(checks);
}

function scoreGeneric(checks) {
  const failed = checks.filter((check) => check.passed === false);
  if (failed.some((check) => check.hardFail || check.severity === "critical")) return { score: 1, label: "严重问题" };
  if (failed.some((check) => check.severity === "high")) return { score: 2, label: "不达标" };
  if (failed.length > 0) return { score: 3, label: "部分通过" };
  return { score: 5, label: "通过" };
}

// 只对拿到分的维度做加权平均，并按覆盖率衡量结论可信度。
export function weightedTotal(dimensions) {
  const all = Object.values(dimensions);

  const totalWeight = all.reduce((sum, dimension) => sum + Number(dimension.weight ?? 0), 0);

  const scored = all.filter((dimension) => Number.isFinite(dimension.score));
  const scoredWeight = scored.reduce((sum, dimension) => sum + Number(dimension.weight ?? 0), 0);
  const coverage = totalWeight > 0 ? scoredWeight / totalWeight : 0;

  if (scoredWeight === 0) {
    return { totalScore: null, coverage: 0, scoredWeight: 0, totalWeight, scoredDimensions: [] };
  }

  const totalScore = scored.reduce(
    (sum, dimension) => sum + dimension.score * Number(dimension.weight ?? 0),
    0,
  ) / scoredWeight;

  return {
    totalScore: roundTo(totalScore, 2),
    coverage: roundTo(coverage, 2),
    scoredWeight,
    totalWeight,
    scoredDimensions: scored.map((dimension) => dimension.key ?? dimension.id),
  };
}

function roundTo(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function layerReport({ layer, trace, rubrics, dimensions }) {
  return {
    meta: {
      layer,
      sessionId: trace?.meta?.sessionId ?? "unknown",
      generatedAt: new Date().toISOString(),
    },
    dimensions,
  };
}

function scoreProcess(checks, context = {}) {
  const byId = Object.fromEntries(checks.map((check) => [check.checkId, check]));
  const promptOnlyFailures = new Set(["prompt_contains_agent_def", "skill_instruction_language"]);
  const skillObserved = Number(context.trace?.summary?.totalSkillCalls ?? 0) > 0;
  const structuralFailures = checks.filter((check) => check.passed === false && !promptOnlyFailures.has(check.checkId));
  if (!skillObserved && byId.prompt_contains_agent_def?.passed === false && byId.skill_instruction_language?.passed === false) {
    return { score: 2, label: "Prompt 约束缺失" };
  }
  if (structuralFailures.some((check) => check.severity === "high")) {
    return { score: 2, label: "流程严重偏离" };
  }
  if (structuralFailures.length > 0) {
    return { score: 3, label: "基本合规" };
  }
  if (checks.some((check) => check.passed === false)) {
    return { score: 4, label: "Prompt 约束待优化" };
  }
  return { score: 5, label: "完全合规" };
}

function scoreSkill(checks) {
  if (checks.some((check) => check.passed === false && check.severity === "high")) {
    return { score: 3, label: "Skill 调用有缺陷" };
  }
  return { score: 5, label: "完整调用" };
}

function scoreReview(checks) {
  // 调用成功率那类检查走通用算法；审查完整性只认派生数这一个关键项。
  const spawn = checks.find((check) => check.checkId === "review_spawn_count");
  if (!spawn) return scoreGeneric(checks);
  if (spawn.passed) return { score: 5, label: "审查已执行" };
  return { score: 0, label: "Review 完全缺失" };
}

function scoreRules(checks) {
  const hardFailed = checks.filter((check) => check.passed === false && check.hardFail);
  const softFailed = checks.filter((check) => check.passed === false && !check.hardFail);
  if (hardFailed.length >= 3) return { score: 0, label: "多条严重违规" };
  if (hardFailed.length > 0) return { score: 1, label: "严重违规" };
  if (softFailed.length > 0) return { score: 3, label: "轻微违规" };
  return { score: 5, label: "完全合规" };
}

function scoreEfficiency(checks) {
  const hitl = checks.find((check) => check.checkId === "hitl_wait_time");
  if (hitl?.actual?.maxWaitMs > 12 * 60 * 60 * 1000) return { score: 0, label: "严重低效" };
  if (checks.some((check) => check.passed === false && check.severity === "high")) return { score: 1, label: "低效" };
  if (checks.some((check) => check.passed === false)) return { score: 3, label: "可接受" };
  return { score: 5, label: "高效" };
}
