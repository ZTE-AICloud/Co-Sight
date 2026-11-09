import { durationMsBetween, formatDurationMs } from "../lib/cli.mjs";
import { dimensionKey, dimensionLabel, rubricVersion } from "../lib/rubrics.mjs";

export function buildInsightPack({ trace, rubrics, reports, trajectoryReport, rubricScores }) {
  const dimensionReports = trajectoryReport?.dimensions ?? {};
  const executeTasks = getExecuteTasks(trace);
  const traceSignals = buildTraceSignals({ trace, executeTasks, reports, trajectoryReport });
  const dimensions = {};

  for (const rubric of rubrics) {
    const dimensionId = rubric.dimension.id;
    const reportDimension = dimensionReports[dimensionId] ?? null;
    const checks = collectChecks({ reports, dimensionId, reportDimension });
    const checkSummaries = checks.map((check) => summarizeCheck(check));
    const evidenceState = summarizeDimensionState({ reportDimension, checkSummaries });
    const confidence = summarizeConfidence({ reportDimension, checkSummaries, evidenceState });
    dimensions[dimensionId] = {
      dimensionId,
      key: dimensionKey(dimensionId),
      name: rubric.dimension.name ?? dimensionLabel(dimensionId),
      score: reportDimension?.score ?? null,
      weight: Number(rubric.dimension.weight ?? 0),
      label: reportDimension?.label ?? null,
      applicable: Number.isFinite(reportDimension?.score),
      evidenceCoverage: reportDimension?.evidenceCoverage ?? null,
      evidenceState,
      confidence,
      failureReason: summarizeFailureReason({ checkSummaries }),
      checks: checkSummaries,
    };
  }

  return {
    meta: {
      schemaVersion: "traceaudit.insight-pack.v1",
      generatedAt: rubricScores?.meta?.evaluatedAt ?? new Date().toISOString(),
      evaluatorVersion: rubricScores?.meta?.evaluatorVersion ?? "0.1.0",
      rubricVersion: rubricScores?.meta?.rubricVersion ?? rubricVersion(),
    },
    episode: buildEpisode(trace, rubricScores),
    traceSignals,
    dimensions,
    sourceReports: Object.fromEntries(
      Object.entries(reports ?? {})
        .filter(([, report]) => Boolean(report))
        .map(([layer, report]) => [layer, {
          layer,
          meta: report.meta ?? {},
          dimensionCount: Object.keys(report.dimensions ?? {}).length,
        }]),
    ),
  };
}

function buildEpisode(trace, rubricScores) {
  const caseId = rubricScores?.meta?.caseId ?? trace?.meta?.caseId ?? "unknown";
  const sessionId = rubricScores?.meta?.sessionId ?? trace?.meta?.sessionId ?? "unknown";
  return {
    caseId,
    sessionId,
    episodeId: `${caseId}:${sessionId}`,
    parentJsonlPath: trace?.meta?.parentJsonlPath ?? null,
    subagentsDir: trace?.meta?.subagentsDir ?? null,
    totalDurationMs: trace?.meta?.totalDurationMs ?? null,
    totalDuration: trace?.meta?.totalDuration ?? null,
  };
}

function buildTraceSignals({ trace, executeTasks, reports, trajectoryReport }) {
  const executePhase = trace?.phases?.find((phase) => phase.phase === "execute") ?? {};
  const wallDurationMs = Number(trace?.meta?.totalDurationMs ?? durationMsBetween(trace?.meta?.startTime, trace?.meta?.endTime) ?? 0);
  const taskCount = executeTasks.length;
  const totalSkillCalls = Number(trace?.summary?.totalSkillCalls ?? 0);
  const totalAgentSpawns = Number(trace?.summary?.totalAgentSpawns ?? taskCount);
  const totalReviewSpawns = Number(trace?.summary?.totalReviewSpawns ?? 0);
  const mcpCalls = Number(trace?.summary?.mcpCalls ?? 0);
  const duplicateOperationChecks = extractChecks(reports?.["L1"]?.dimensions?.["trace-efficiency"], "duplicate_operations");
  const hitlWaitChecks = extractChecks(reports?.["L1"]?.dimensions?.["trace-efficiency"], "hitl_wait_time");
  return {
    executePhase: {
      startEvent: executePhase.startEvent ?? null,
      endEvent: executePhase.endEvent ?? null,
      interrupted: Boolean(executePhase.interrupted),
      triggerCommand: executePhase.triggerCommand ?? null,
      boundarySource: executePhase.boundarySource ?? null,
    },
    counts: {
      taskCount,
      totalAgentSpawns,
      totalSkillCalls,
      totalReviewSpawns,
      mcpCalls,
    },
    timing: {
      wallDurationMs,
      wallDuration: Number.isFinite(wallDurationMs) ? formatDurationMs(wallDurationMs) : null,
    },
    friction: collectFriction(trajectoryReport),
    efficiency: {
      duplicateOperations: duplicateOperationChecks,
      hitlWaits: hitlWaitChecks,
    },
  };
}

function collectFriction(trajectoryReport) {
  const friction = [];
  for (const dimension of Object.values(trajectoryReport?.dimensions ?? {})) {
    for (const check of dimension.checks ?? []) {
      if (check.passed !== false) continue;
      friction.push({
        dimensionId: dimension.id,
        dimensionName: dimension.name,
        checkId: check.checkId,
        layer: check.layer,
        severity: check.severity,
        evidenceState: evidenceStateForCheck(check),
        evidence: trimText(check.evidence, 240),
      });
    }
  }
  return {
    items: friction.slice(0, 30),
  };
}

function collectChecks({ reports, dimensionId, reportDimension }) {
  if (reportDimension?.checks?.length) return reportDimension.checks;
  return Object.values(reports ?? {})
    .flatMap((report) => report?.dimensions?.[dimensionId]?.checks ?? []);
}

function summarizeCheck(check) {
  const evidenceState = evidenceStateForCheck(check);
  return {
    checkId: check.checkId,
    name: check.name ?? check.checkId,
    layer: check.layer ?? null,
    severity: check.severity ?? null,
    passed: check.passed ?? null,
    status: check.status ?? null,
    evidenceState,
    confidence: confidenceForCheck(check, evidenceState),
    evidence: trimText(check.evidence, 240),
    actualSummary: summarizeValue(check.actual),
    expectedSummary: summarizeValue(check.expected),
  };
}

function summarizeDimensionState({ reportDimension, checkSummaries }) {
  const states = checkSummaries.map((check) => check.evidenceState);
  if (states.length === 0) return "unobserved";
  // 维度没有分数 = 没有形成结论：证据状态记为 not_applicable，而不是假装有证据
  if (reportDimension && reportDimension.score === null) return "not_applicable";
  if (states.every((state) => state === "not_applicable")) return "not_applicable";
  if (Number.isFinite(reportDimension?.score) && Number(reportDimension.score) <= 1) return "missing";
  if (states.includes("outcome_supported")) return "outcome_supported";
  if (states.includes("exercised")) return "exercised";
  if (states.includes("wired")) return "wired";
  if (states.includes("present")) return "present";
  if (states.includes("missing")) return "missing";
  return "unobserved";
}

function summarizeConfidence({ reportDimension, checkSummaries, evidenceState }) {
  if (evidenceState === "not_applicable") return "none";
  if (evidenceState === "outcome_supported") return "high";
  if (evidenceState === "exercised") return hasHardFailures(checkSummaries) ? "medium" : "high";
  if (evidenceState === "wired" || evidenceState === "present") return "medium";
  if (evidenceState === "missing") return "low";
  if (Number.isFinite(reportDimension?.score) && reportDimension.score >= 4) return "medium";
  return "low";
}

function summarizeFailureReason({ checkSummaries }) {
  const failed = checkSummaries.filter((check) => check.passed === false);
  if (failed.length === 0) return null;
  const head = failed.sort((a, b) => severityRank(a.severity) - severityRank(b.severity))[0];
  return `${head.checkId}: ${head.evidence ?? "failed"}`;
}

function confidenceForCheck(check, evidenceState) {
  if (evidenceState === "not_applicable") return "none";
  if (evidenceState === "outcome_supported") return "high";
  if (evidenceState === "exercised") return check.passed ? "high" : "medium";
  if (evidenceState === "wired" || evidenceState === "present") return "medium";
  if (evidenceState === "missing") return "low";
  return "low";
}

function evidenceStateForCheck(check) {
  if (!check) return "unobserved";
  if (check.passed === null || check.status === "skipped" || check.status === "not-applicable") return "not_applicable";
  if (check.passed) {
    if (check.actual !== undefined) return "exercised";
    return "present";
  }
  if (check.severity === "critical" || check.severity === "high") return "missing";
  return "unobserved";
}

function extractChecks(dimension, checkId) {
  if (!dimension?.checks) return [];
  return dimension.checks.filter((check) => check.checkId === checkId).map((check) => ({
    checkId: check.checkId,
    passed: check.passed,
    status: check.status,
    evidenceState: evidenceStateForCheck(check),
    evidence: trimText(check.evidence, 240),
  }));
}

function hasHardFailures(checkSummaries) {
  return checkSummaries.some((check) => check.passed === false && ["critical", "high"].includes(String(check.severity ?? "").toLowerCase()));
}

function severityRank(severity) {
  if (severity === "critical") return 0;
  if (severity === "high") return 1;
  if (severity === "medium") return 2;
  if (severity === "low") return 3;
  return 4;
}

function getExecuteTasks(trace) {
  const phase = trace?.phases?.find((item) => item.phase === "execute");
  return phase?.tasks ?? [];
}

function summarizeValue(value, depth = 0) {
  if (value === null || value === undefined) return value;
  if (typeof value === "string") return trimText(value, 160);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    return {
      type: "array",
      length: value.length,
      sample: value.slice(0, 3).map((item) => summarizeValue(item, depth + 1)),
    };
  }
  if (typeof value === "object") {
    if (depth >= 2) {
      return { type: "object", keys: Object.keys(value).slice(0, 8) };
    }
    const omitKeys = new Set(["workItem", "result", "prompt", "raw", "traceEvidence", "artifact_content", "knowledge_base_sample"]);
    const entries = Object.entries(value)
      .filter(([key]) => !omitKeys.has(key))
      .slice(0, 12)
      .map(([key, item]) => [key, summarizeValue(item, depth + 1)]);
    return Object.fromEntries(entries);
  }
  return trimText(String(value), 160);
}

function trimText(text, maxLength = 160) {
  const value = String(text ?? "");
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}…`;
}
