import fs from "node:fs";

export function validateReportBundle({ outputDir, reportJsonPath, scoresPath, reportMdPath, trajectoryReport, rubricScores, insightPack, insightPackPath }) {
  const issues = [];
  const addIssue = (severity, code, message, details = {}) => {
    issues.push({
      severity,
      code,
      message,
      ...details,
    });
  };

  checkFile(reportJsonPath, "trajectory-report.json", addIssue, "report_missing");
  checkFile(scoresPath, "rubric-scores.json", addIssue, "scores_missing");
  checkFile(reportMdPath, "trajectory-report.md", addIssue, "markdown_missing");
  if (insightPackPath) checkFile(insightPackPath, "insight-pack.json", addIssue, "insight_pack_missing");

  const report = trajectoryReport ?? {};
  const scores = rubricScores ?? {};
  if ((report.summary?.totalScore ?? null) !== (scores.totalScore ?? null)) {
    addIssue("error", "score_mismatch", "trajectory-report.json 与 rubric-scores.json 的总分不一致", {
      trajectoryScore: report.summary?.totalScore ?? null,
      rubricScore: scores.totalScore ?? null,
    });
  }
  if ((report.summary?.grade ?? null) !== (scores.grade ?? null)) {
    addIssue("error", "grade_mismatch", "trajectory-report.json 与 rubric-scores.json 的等级不一致", {
      trajectoryGrade: report.summary?.grade ?? null,
      rubricGrade: scores.grade ?? null,
    });
  }

  const dimensionEntries = Object.entries(report.dimensions ?? {});
  const insightEntries = Object.entries(insightPack?.dimensions ?? {});
  if (dimensionEntries.length === 0) {
    addIssue("error", "dimension_missing", "报告中未找到任何维度", {});
  }
  if (insightEntries.length === 0) {
    addIssue("error", "insight_dimension_missing", "证据包中未找到任何维度", {});
  }

  for (const [dimensionId, dimension] of dimensionEntries) {
    const insightDimension = insightPack?.dimensions?.[dimensionId];
    if (!insightDimension) {
      addIssue("error", "insight_dimension_missing", `证据包缺少维度 ${dimensionId}`, { dimensionId });
      continue;
    }

    // score 为 null 表示该维度无可判证据，不计入总分 —— 这不是缺分，也不能被当成 0 分。
    if (dimension.score === null || dimension.score === undefined) {
      if (!dimension.label) {
        addIssue("error", "not_applicable_label_missing", `维度 ${dimensionId} 不适用但没有给出结论说明`, { dimensionId });
      }
      if (dimension.weightedScore !== null && dimension.weightedScore !== undefined) {
        addIssue("error", "not_applicable_weighted", `维度 ${dimensionId} 不适用却计入了加权分`, {
          dimensionId,
          weightedScore: dimension.weightedScore,
        });
      }
      continue;
    }

    const score = Number(dimension.score);
    if (!Number.isFinite(score)) {
      addIssue("error", "dimension_score_invalid", `维度 ${dimensionId} 分数不是有效数值`, { dimensionId, score: dimension.score });
      continue;
    }
    if (score < 0 || score > 5) {
      addIssue("error", "dimension_score_out_of_range", `维度 ${dimensionId} 分数越界`, {
        dimensionId,
        score,
      });
    }

    const evidenceState = insightDimension.evidenceState ?? "unobserved";
    if (evidenceState === "not_applicable") {
      addIssue("error", "applicable_dimension_without_evidence", `维度 ${dimensionId} 有分数但证据状态为 not_applicable`, {
        dimensionId,
        score,
        evidenceState,
      });
    }
    if (score >= 4 && ["missing", "unobserved"].includes(evidenceState)) {
      addIssue("error", "evidence_overclaim", `维度 ${dimensionId} 分数过高但证据状态不足`, {
        dimensionId,
        score,
        evidenceState,
      });
    }
    if (score <= 1 && ["present", "wired", "exercised", "outcome_supported"].includes(evidenceState)) {
      addIssue("error", "evidence_contradiction", `维度 ${dimensionId} 分数过低但证据状态过强`, {
        dimensionId,
        score,
        evidenceState,
      });
    }
  }

  const coverage = scores.coverage === null || scores.coverage === undefined ? null : Number(scores.coverage);
  if (coverage !== null && Number.isFinite(coverage)) {
    const threshold = Number(scores.coverageThreshold ?? 0.6);
    if (coverage < threshold && scores.grade !== "UNDETERMINED") {
      addIssue("error", "grade_should_be_undetermined", "证据覆盖率低于阈值却给出了等级结论", {
        coverage,
        threshold,
        grade: scores.grade ?? null,
      });
    }
    if (coverage >= threshold && scores.grade === "UNDETERMINED") {
      addIssue("error", "grade_undetermined_without_reason", "证据覆盖率达标却给出不可判定结论", {
        coverage,
        threshold,
        grade: scores.grade,
      });
    }
  }
  if (coverage === null) {
    addIssue("warning", "coverage_missing", "报告未给出证据覆盖率", {});
  }

  const markdown = readText(reportMdPath);
  if (markdown) {
    for (const section of ["## 总结", "## 维度评分", "## 失败项"]) {
      if (!markdown.includes(section)) {
        addIssue("error", "markdown_section_missing", `Markdown 缺少段落 ${section}`, { section });
      }
    }
  }

  const privacyWarnings = collectPrivacyWarnings({ trajectoryReport: report, insightPack });
  for (const warning of privacyWarnings) issues.push(warning);

  return {
    schemaVersion: "traceaudit.report-validation.v1",
    generatedAt: new Date().toISOString(),
    outputDir: outputDir ?? null,
    passed: issues.every((issue) => issue.severity !== "error"),
    issueCount: issues.length,
    errorCount: issues.filter((issue) => issue.severity === "error").length,
    warningCount: issues.filter((issue) => issue.severity === "warning").length,
    issues,
  };
}

function checkFile(filePath, label, addIssue, code) {
  if (!filePath || !fs.existsSync(filePath)) {
    addIssue("error", code, `缺少输出文件: ${label}`, {
      filePath: filePath ?? null,
    });
  }
}

function readText(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return "";
  return fs.readFileSync(filePath, "utf8");
}

function collectPrivacyWarnings({ trajectoryReport, insightPack }) {
  const warnings = [];
  const scan = (value, scope) => {
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {});
    if (!text) return;
    if (text.includes("artifact_content") || text.includes("knowledge_base_sample")) {
      warnings.push({
        severity: "warning",
        code: "internal_prompt_material_present",
        message: `${scope} 包含内部裁判模板材料，建议仅在内部调试中查看`,
      });
    }
    if (text.length > 250000) {
      warnings.push({
        severity: "warning",
        code: "large_payload",
        message: `${scope} 体积较大，建议检查是否包含过多内嵌内容`,
      });
    }
  };

  scan(trajectoryReport, "trajectory-report");
  scan(insightPack, "insight-pack");
  return warnings;
}
