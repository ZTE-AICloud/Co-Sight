import path from "node:path";
import fs from "node:fs";
import { ensureDir, writeJson } from "../lib/cli.mjs";
import { dimensionKey, dimensionLabel, rubricVersion } from "../lib/rubrics.mjs";
import { EVIDENCE_COVERAGE_THRESHOLD, weightedTotal } from "../lib/scoring.mjs";
import { buildInsightPack } from "./insight-pack.mjs";
import { validateReportBundle } from "./report-validator.mjs";
import { sanitizeReport, extractProtectionContext } from "../lib/privacy.mjs";

export function generateReports({ trace, rubrics, reports, outputDir }) {
  ensureDir(outputDir);
  const combined = combineReports({ trace, rubrics, reports });
  const reportJsonPath = path.join(outputDir, "trajectory-report.json");
  const scoresPath = path.join(outputDir, "rubric-scores.json");
  const reportMdPath = path.join(outputDir, "trajectory-report.md");
  const insightPackPath = path.join(outputDir, "_intermediate", "insight-pack.json");
  const reportValidationPath = path.join(outputDir, "_intermediate", "report-validation.json");

  // 对 trajectory-report.json 全量递归脱敏（排除 checks[].actual 和 checks[].evidence）
  const protectionContext = extractProtectionContext(trace);
  const sanitizedReport = sanitizeReport(combined.trajectoryReport, protectionContext);

  writeJson(reportJsonPath, sanitizedReport);
  writeJson(scoresPath, combined.rubricScores);
  writeText(reportMdPath, renderMarkdown(combined));
  const insightPack = buildInsightPack({
    trace,
    rubrics,
    reports,
    trajectoryReport: combined.trajectoryReport,
    rubricScores: combined.rubricScores,
  });
  writeJson(insightPackPath, insightPack);
  const reportValidation = validateReportBundle({
    outputDir,
    reportJsonPath,
    scoresPath,
    reportMdPath,
    trajectoryReport: combined.trajectoryReport,
    rubricScores: combined.rubricScores,
    insightPack,
    insightPackPath,
  });
  writeJson(reportValidationPath, reportValidation);

  return { reportJsonPath, scoresPath, reportMdPath, insightPackPath, reportValidationPath, insightPack, reportValidation, ...combined };
}

export function combineReports({ trace, rubrics, reports }) {
  const dimensions = {};
  const caseId = trace.meta.caseId ?? trace.meta.case_id ?? trace.meta.sessionId;

  for (const rubric of rubrics) {
    const id = rubric.dimension.id;
    const layerDims = Object.values(reports)
      .filter(Boolean)
      .map((report) => report.dimensions?.[id])
      .filter(Boolean);

    const checks = layerDims.flatMap((dimension) => dimension.checks ?? []);
    const scoredLayers = layerDims.filter((dimension) => Number.isFinite(dimension.score));
    // 没有拿到分的维度就是 null，不能默认满分
    const score = scoredLayers.length ? Math.min(...scoredLayers.map((dimension) => dimension.score)) : null;
    const lowest = scoredLayers.find((dimension) => dimension.score === score) ?? layerDims[0];
    const weight = Number(rubric.dimension.weight ?? 0);

    dimensions[id] = {
      id,
      key: dimensionKey(id),
      name: rubric.dimension.name ?? dimensionLabel(id),
      score,
      weight,
      applicable: score !== null,
      evidenceCoverage: lowest?.evidenceCoverage ?? null,
      weightedScore: score === null ? null : round(score * weight, 3),
      label: lowest?.label ?? scoreLabel(score),
      failedTasks: failedTasks(checks),
      summary: summarizeDimension(checks),
      checks,
      layers: Object.fromEntries(Object.entries(reports).filter(([, report]) => report?.dimensions?.[id]).map(([layer, report]) => [layer, {
        score: report.dimensions[id].score,
        label: report.dimensions[id].label,
        evidenceCoverage: report.dimensions[id].evidenceCoverage ?? null,
        failedChecks: (report.dimensions[id].checks ?? []).filter((check) => check.passed === false).map((check) => check.checkId),
      }])),
    };
  }

  const weighted = weightedTotal(dimensions);
  const coverage = weighted.coverage;
  const coverageSufficient = coverage >= EVIDENCE_COVERAGE_THRESHOLD;
  // 覆盖率不足时不给总分：只在 20% 权重上算出来的“5 分”不是总分。
  const totalScore = coverageSufficient ? weighted.totalScore : null;
  const renormalizedScore = weighted.totalScore;
  const grade = gradeFor(totalScore, coverage, coverageSufficient);
  const notApplicableDimensions = Object.values(dimensions)
    .filter((dimension) => !dimension.applicable)
    .map((dimension) => dimension.key);
  const rubricScores = {
    meta: {
      sessionId: trace.meta.sessionId,
      caseId,
      evaluatedAt: new Date().toISOString(),
      evaluatorVersion: "0.1.0",
      rubricVersion: rubricVersion(),
    },
    scores: Object.fromEntries(Object.values(dimensions).map((dimension) => [dimension.key, {
      score: dimension.score,
      weight: dimension.weight,
      applicable: dimension.applicable,
      evidenceCoverage: dimension.evidenceCoverage,
      weightedScore: dimension.weightedScore,
      label: dimension.label,
      failedTasks: dimension.failedTasks,
      summary: dimension.summary,
      checks: dimension.checks.map((check) => ({
        checkId: check.checkId,
        passed: check.passed,
        status: check.status,
        evidenceState: check.evidenceLevel,
        actual: check.actual,
        expected: check.expected,
        evidence: check.evidence,
        severity: check.severity,
      })),
    }])),
    totalScore,
    renormalizedScore,
    coverage,
    scoredWeight: round(weighted.scoredWeight, 2),
    totalWeight: weighted.totalWeight,
    scoredDimensions: weighted.scoredDimensions,
    notApplicableDimensions,
    coverageThreshold: EVIDENCE_COVERAGE_THRESHOLD,
    grade,
    verdict: verdictFor(grade, totalScore),
  };

  const trajectoryReport = {
    meta: {
      sessionId: trace.meta.sessionId,
      caseId,
      evaluatedAt: rubricScores.meta.evaluatedAt,
      evaluatorVersion: rubricScores.meta.evaluatorVersion,
      rubricVersion: rubricScores.meta.rubricVersion,
    },
    summary: {
      totalScore,
      renormalizedScore,
      coverage,
      grade,
      verdict: rubricScores.verdict,
      notApplicableDimensions,
      traceSummary: trace.summary,
    },
    dimensions,
    sourceReports: Object.fromEntries(Object.entries(reports).filter(([, report]) => report).map(([layer, report]) => [layer, report.meta])),
  };

  return { trajectoryReport, rubricScores };
}

function renderMarkdown({ trajectoryReport, rubricScores }) {
  const meta = trajectoryReport.meta;
  const summary = trajectoryReport.summary;
  const rows = Object.values(trajectoryReport.dimensions)
    .map((dimension) => `| ${dimension.name} | ${formatScore(dimension.score)} | ${dimension.weight} | ${dimension.weightedScore ?? "—"} | ${dimension.label} |`)
    .join("\n");

  const failed = Object.values(trajectoryReport.dimensions)
    .flatMap((dimension) => dimension.checks.filter((check) => check.passed === false).map((check) => ({ dimension: dimension.name, ...check })))
    .slice(0, 30);

  const failedLines = failed.length
    ? failed.map((check) => `- **${check.dimension}/${check.checkId}** (${check.severity}): ${check.evidence || "failed"}`).join("\n")
    : "- 无确定性失败项。";

  const notApplicable = Object.values(trajectoryReport.dimensions)
    .flatMap((dimension) => dimension.checks.filter((check) => check.status === "not-applicable").map((check) => ({ dimension: dimension.name, ...check })))
    .slice(0, 30);

  const notApplicableLines = notApplicable.length
    ? notApplicable.map((check) => `- **${check.dimension}/${check.checkId}**: ${check.evidence || "证据不足"}`).join("\n")
    : "- 无不可判定检查项。";

  return `# 轨迹评估报告

## 总结

| 字段 | 值 |
|------|-----|
| Session | ${meta.sessionId} |
| Case | ${rubricScores.meta.caseId ?? "unknown"} |
| Total Score | ${summary.totalScore === null ? "不可判定" : `${summary.totalScore} / 5`} |
| 证据覆盖率 | ${summary.coverage ?? "—"} / 阈值 ${rubricScores.coverageThreshold ?? "—"}（可判维度权重占比） |
| Grade | ${summary.grade} |
| Verdict | ${summary.verdict} |

总分只对可判维度加权；覆盖率低于阈值时不给总分、也不给等级结论（此时 renormalizedScore = ${summary.renormalizedScore ?? "—"} 仅为可判维度的均分，不是总分）。

## 维度评分

| 维度 | 分数 | 权重 | 加权分 | 结论 |
|------|------|------|--------|------|
${rows}

## 失败项

${failedLines}

## 不可判定项

${notApplicableLines}

## Trace 摘要

\`\`\`json
${JSON.stringify(summary.traceSummary, null, 2)}
\`\`\`
`;
}

function formatScore(score) {
  return Number.isFinite(score) ? String(score) : "不适用";
}

function failedTasks(checks) {
  const tasks = new Set();
  for (const check of checks.filter((item) => item.passed === false)) {
    const text = JSON.stringify(check.actual ?? {});
    for (const match of text.matchAll(/\b(task_[A-Za-z0-9_]+|T\d+[A-Za-z]?)\b/g)) tasks.add(match[1]);
  }
  return [...tasks];
}

function summarizeDimension(checks) {
  const failed = checks.filter((check) => check.passed === false);
  if (failed.length === 0) {
    const applicable = checks.filter((check) => check.passed !== null).length;
    if (applicable === 0) return "该维度没有可判证据，未参与打分。";
    return `${applicable} 项确定性检查通过。`;
  }
  return failed.slice(0, 3).map((check) => `${check.checkId}: ${check.evidence}`).join("；");
}

function scoreLabel(score) {
  if (!Number.isFinite(score)) return "不适用";
  if (score >= 5) return "优秀";
  if (score >= 3) return "可接受";
  if (score >= 1) return "不达标";
  return "缺失";
}

function gradeFor(score, coverage = 1, coverageSufficient = coverage >= EVIDENCE_COVERAGE_THRESHOLD) {
  if (!coverageSufficient || !Number.isFinite(score)) return "UNDETERMINED";
  if (score >= 4.5) return "EXCELLENT";
  if (score >= 3.5) return "ACCEPTABLE";
  if (score >= 2.0) return "POOR";
  return "CRITICAL";
}

function verdictFor(grade, score) {
  if (grade === "UNDETERMINED") {
    return "可判证据不足（可判维度权重低于阈值），本次评测不给出等级结论；请按维度明细人工复核或补充可判证据后重跑。";
  }
  if (grade === "EXCELLENT") return "轨迹过程质量优秀，可作为参考执行样本。";
  if (grade === "ACCEPTABLE") return "轨迹过程基本可接受，存在少量需改进项。";
  if (grade === "POOR") return "轨迹过程存在明显缺陷，建议定位失败维度后重跑。";
  return "轨迹过程不可用，建议修复 harness/Agent 定义后重新执行。";
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function writeText(filePath, text) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, text, "utf8");
}
