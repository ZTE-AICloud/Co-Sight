import fs from "node:fs";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { ensureDir, readJson, resolveWorkspaceDir, writeJson } from "../lib/cli.mjs";
import { dimensionKey, dimensionLabel, loadRubrics, rubricVersion } from "../lib/rubrics.mjs";
import {
  extractRunRef,
  readSeedRecords,
  resolveParentJsonl,
  resolveSeedJsonl,
  resolveSubagentsDirPath,
  slugify,
} from "../lib/seed.mjs";

const execFileAsync = promisify(execFile);
const SKILL_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ENTRY_SCRIPT = path.join(SKILL_ROOT, "scripts", "traceaudit.mjs");
const MAX_BUFFER = 32 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 10 * 60 * 1000;

export async function evaluateSeedBatch({ seedDir, outputs, timeoutMs = DEFAULT_TIMEOUT_MS }) {
  const seedJsonlPath = resolveSeedJsonl(seedDir);
  const records = readSeedRecords(seedJsonlPath);
  if (records.length === 0) throw new Error(`seed.jsonl 中没有可评测的记录: ${seedJsonlPath}`);

  const outputRoot = resolveOutputRoot(outputs);
  const casesRoot = path.join(outputRoot, "cases");
  ensureDir(casesRoot);

  const resolvedTimeoutMs = normalizeTimeout(timeoutMs);
  const cases = [];
  const usedSlugs = new Set();

  for (let index = 0; index < records.length; index += 1) {
    const ref = extractRunRef(records[index], index);
    const slug = allocateSlug(ref, index, usedSlugs);
    const caseOutputDir = path.join(casesRoot, slug);
    const result = await evaluateRecord({ ref, seedJsonlPath, caseOutputDir, slug, timeoutMs: resolvedTimeoutMs });
    cases.push(result);
    process.stderr.write(`[seed-batch] ${index + 1}/${records.length} ${ref.dataId ?? slug}: ${result.status}\n`);
  }

  const summary = buildSummary({
    seedDir: path.resolve(String(seedDir)),
    seedJsonlPath,
    outputRoot,
    cases,
    timeoutMs: resolvedTimeoutMs,
  });
  const summaryJsonPath = path.join(outputRoot, "batch-summary.json");
  const summaryMdPath = path.join(outputRoot, "batch-summary.md");
  writeJson(summaryJsonPath, summary);
  fs.writeFileSync(summaryMdPath, renderSummaryMarkdown(summary), "utf8");

  return { outputRoot, seedJsonlPath, summaryJsonPath, summaryMdPath, summary };
}

async function evaluateRecord({ ref, seedJsonlPath, caseOutputDir, slug, timeoutMs }) {
  const startedAt = Date.now();

  if (ref.error) {
    return failedResult({ ref, slug, caseOutputDir, stage: "resolve", error: ref.error, startedAt });
  }

  const parentJsonlPath = resolveParentJsonl({ ref, seedJsonlPath });
  if (!parentJsonlPath) {
    return failedResult({
      ref,
      slug,
      caseOutputDir,
      stage: "resolve",
      error: `未找到主 trace jsonl（session_id=${ref.sessionId ?? "?"}, session_dir=${ref.sessionDir ?? "?"}）`,
      startedAt,
    });
  }

  const warnings = [];
  const subagentsDir = resolveSubagentsDirPath({ ref, seedJsonlPath });
  if (ref.subagentsDir && !subagentsDir) {
    warnings.push(`run.subagents_dir 指向的目录不存在，已回退到默认子目录解析: ${ref.subagentsDir}`);
  }

  const argv = [ENTRY_SCRIPT, "--parent-jsonl", parentJsonlPath, "--outputs", caseOutputDir];
  if (subagentsDir) argv.push("--subagents-dir", subagentsDir);

  let child;
  try {
    const { stdout } = await execFileAsync(process.execPath, argv, {
      encoding: "utf8",
      maxBuffer: MAX_BUFFER,
      timeout: timeoutMs > 0 ? timeoutMs : 0,
    });
    child = parseChildOutput(stdout);
  } catch (error) {
    const detail = error.killed
      ? `评测进程超过 ${timeoutMs}ms 未结束，已终止`
      : String(error.stderr || error.message || error).trim();
    return failedResult({ ref, slug, caseOutputDir, stage: "evaluate", error: detail, startedAt, parentJsonlPath, subagentsDir, warnings });
  }

  const resolvedOutputDir = child?.outputDir ?? caseOutputDir;
  mergeUnique(warnings, readTraceWarnings(resolvedOutputDir));
  const scoresPath = path.join(resolvedOutputDir, "rubric-scores.json");
  const scoresRead = readScores(scoresPath);
  if (scoresRead.error) {
    return failedResult({
      ref,
      slug,
      caseOutputDir,
      stage: "collect",
      error: scoresRead.error,
      startedAt,
      parentJsonlPath,
      subagentsDir,
      warnings,
      outputDir: resolvedOutputDir,
    });
  }

  return {
    index: ref.index,
    slug,
    data_id: ref.dataId,
    capabilityRef: ref.capabilityRef,
    dimension: ref.dimension,
    kind: ref.kind,
    input: ref.input,
    sessionId: child?.sessionId ?? ref.sessionId,
    sessionDir: ref.sessionDir,
    parentJsonlPath,
    subagentsDir: subagentsDir ?? null,
    subagentsDirRequested: ref.subagentsDir ?? null,
    caseId: child?.caseId ?? null,
    outputDir: resolvedOutputDir,
    reportMarkdown: path.join(resolvedOutputDir, "trajectory-report.md"),
    reportJson: path.join(resolvedOutputDir, "trajectory-report.json"),
    scoresJson: scoresPath,
    status: "ok",
    stage: null,
    error: null,
    warnings,
    totalScore: numberOrNull(scoresRead.scores?.totalScore),
    coverage: numberOrNull(scoresRead.scores?.coverage),
    grade: scoresRead.scores?.grade ?? null,
    verdict: scoresRead.scores?.verdict ?? null,
    notApplicableDimensions: scoresRead.scores?.notApplicableDimensions ?? [],
    dimensions: extractDimensionScores(scoresRead.scores),
    elapsedMs: Date.now() - startedAt,
  };
}

function failedResult({
  ref,
  slug,
  caseOutputDir,
  stage,
  error,
  startedAt,
  parentJsonlPath = null,
  subagentsDir = null,
  warnings = [],
  outputDir = null,
}) {
  return {
    index: ref.index,
    slug,
    dataId: ref.dataId,
    capabilityRef: ref.capabilityRef,
    dimension: ref.dimension,
    kind: ref.kind,
    input: ref.input,
    sessionId: ref.sessionId,
    sessionDir: ref.sessionDir,
    parentJsonlPath,
    subagentsDir: subagentsDir ?? null,
    subagentsDirRequested: ref.subagentsDir ?? null,
    caseId: null,
    outputDir: outputDir ?? caseOutputDir,
    reportMarkdown: null,
    reportJson: null,
    scoresJson: null,
    status: "failed",
    stage,
    error,
    warnings,
    totalScore: null,
    coverage: null,
    grade: null,
    verdict: null,
    notApplicableDimensions: [],
    dimensions: {},
    elapsedMs: Date.now() - startedAt,
  };
}

function buildSummary({ seedDir, seedJsonlPath, outputRoot, cases, timeoutMs }) {
  const ok = cases.filter((item) => item.status === "ok");
  const failed = cases.filter((item) => item.status !== "ok");
  // 不可判定（证据不足）的用例单独成桶：它们的总分不参与任何平均。
  const undetermined = ok.filter((item) => item.grade === "UNDETERMINED" || !Number.isFinite(item.totalScore));
  const scored = ok.filter((item) => Number.isFinite(item.totalScore));
  const rubrics = loadRubrics();

  const dimensionAverages = {};
  for (const rubric of rubrics) {
    const key = dimensionKey(rubric.dimension.id);
    // 维度均分按“该维度本身是否可判”统计，与用例总分是否可评级无关。
    const values = ok.map((item) => item.dimensions?.[key]?.score).filter((score) => Number.isFinite(score));
    dimensionAverages[key] = {
      id: rubric.dimension.id,
      name: dimensionLabel(rubric.dimension.id),
      weight: Number(rubric.dimension.weight ?? 0),
      averageScore: values.length ? round(average(values), 2) : null,
      scoredCount: values.length,
      notApplicableCount: ok.length - values.length,
    };
  }

  const scoreValues = scored.map((item) => item.totalScore);
  const gradeDistribution = {};
  for (const item of ok) {
    if (!item.grade) continue;
    gradeDistribution[item.grade] = (gradeDistribution[item.grade] ?? 0) + 1;
  }

  return {
    meta: {
      skill: "traceaudit",
      mode: "seed-batch",
      seedDir,
      seedJsonl: seedJsonlPath,
      outputRoot,
      generatedAt: new Date().toISOString(),
      recordCount: cases.length,
      succeeded: ok.length,
      failed: failed.length,
      undetermined: undetermined.length,
      scored: scored.length,
      warned: cases.filter((item) => (item.warnings?.length ?? 0) > 0).length,
      timeoutMs: timeoutMs > 0 ? timeoutMs : null,
      evaluatorVersion: skillVersion(),
      rubricVersion: rubricVersion(),
    },
    aggregate: {
      evaluatedCount: ok.length,
      scoredCount: scored.length,
      undeterminedCount: undetermined.length,
      undeterminedCases: undetermined.map((item) => ({ data_id: item.dataId, slug: item.slug, coverage: item.coverage, notApplicableDimensions: item.notApplicableDimensions })),
      averageTotalScore: scoreValues.length ? round(average(scoreValues), 2) : null,
      highestTotalScore: scoreValues.length ? Math.max(...scoreValues) : null,
      lowestTotalScore: scoreValues.length ? Math.min(...scoreValues) : null,
      averageCoverage: ok.length ? round(average(ok.map((item) => Number.isFinite(item.coverage) ? item.coverage : 0)), 2) : null,
      gradeDistribution,
      dimensionAverages,
    },
    cases,
  };
}

function renderSummaryMarkdown(summary) {
  const { meta, aggregate, cases } = summary;

  const dimensionRows = Object.values(aggregate.dimensionAverages)
    .map((item) => `| ${item.name} | ${item.weight} | ${item.averageScore ?? "n/a"} | ${item.scoredCount} | ${item.notApplicableCount ?? 0} |`)
    .join("\n");

  const caseRows = cases
    .map((item) => {
      const report = item.reportMarkdown ? relativeLink(meta.outputRoot, item.reportMarkdown) : "-";
      return `| ${item.index + 1} | ${item.dataId ?? "-"} | ${item.dimension ?? "-"} | ${shortSession(item.sessionId)} | ${item.totalScore ?? "不可判定"} | ${item.coverage ?? "-"} | ${item.grade ?? "-"} | ${item.status === "ok" ? "成功" : "失败"} | ${report} |`;
    })
    .join("\n");

  const gradeRows = Object.entries(aggregate.gradeDistribution)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([grade, count]) => `| ${grade} | ${count} |`)
    .join("\n");

  const failedSection = cases.filter((item) => item.status !== "ok");
  const warnedSection = cases.filter((item) => (item.warnings?.length ?? 0) > 0);
  const undeterminedSection = aggregate.undeterminedCases ?? [];

  return `# 轨迹批量评估汇总报告

## 概览

| 项 | 值 |
|---|---|
| seed 目录 | \`${meta.seedDir}\` |
| seed.jsonl | \`${meta.seedJsonl}\` |
| 输出根目录 | \`${meta.outputRoot}\` |
| 生成时间 | ${meta.generatedAt} |
| 用例总数 | ${meta.recordCount} |
| 成功 / 失败 | ${meta.succeeded} / ${meta.failed} |
| 可评级 / 不可判定 | ${meta.scored ?? "-"} / ${meta.undetermined ?? 0} |
| 平均总分 | ${aggregate.averageTotalScore ?? "n/a"}（仅统计可评级用例） |
| 最高 / 最低总分 | ${aggregate.highestTotalScore ?? "n/a"} / ${aggregate.lowestTotalScore ?? "n/a"} |
| 平均证据覆盖率 | ${aggregate.averageCoverage ?? "n/a"} |
| 单条超时 | ${meta.timeoutMs ? `${meta.timeoutMs}ms` : "不限制"} |
| 评估器版本 | ${meta.evaluatorVersion} (rubric ${meta.rubricVersion}) |

## 等级分布

| 等级 | 数量 |
|---|---|
${gradeRows || "| - | 0 |"}

## 维度平均分

| 维度 | 权重 | 平均分 | 计分用例数 | 不适用用例数 |
|---|---:|---:|---:|---:|
${dimensionRows}

## 用例明细

| # | data_id | 维度 | session | 总分 | 覆盖率 | 等级 | 状态 | 报告 |
|---|---|---|---|---|---|---|---|---|
${caseRows}

## 不可判定用例

证据覆盖率不足时不给出等级结论，也不计入平均分。

${undeterminedSection.length ? undeterminedSection.map((item) => `- **${item.dataId ?? item.slug}**：覆盖率 ${item.coverage ?? "-"}，不适用维度 ${(item.notApplicableDimensions ?? []).join(", ") || "-"}`).join("\n") : "- 无不可判定用例。"}

## 失败用例

${failedSection.length ? failedSection.map((item) => `- **${item.dataId ?? item.slug}** (${item.stage}): ${item.error}`).join("\n") : "- 无失败用例。"}

## 警告

${warnedSection.length ? warnedSection.map((item) => `- **${item.dataId ?? item.slug}**：${item.warnings.join("；")}`).join("\n") : "- 无警告。"}

## 产物

- 结构化汇总：\`batch-summary.json\`
- 逐用例报告：\`cases/<data_id>/trajectory-report.md\`、\`cases/<data_id>/rubric-scores.json\`
`;
}

function parseChildOutput(stdout) {
  const text = String(stdout ?? "");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) {
    throw new Error(`traceaudit 未输出可解析的 JSON: ${text.slice(0, 200)}`);
  }
  return JSON.parse(text.slice(start, end + 1));
}

function extractDimensionScores(scores) {
  if (!scores?.scores) return {};
  const out = {};
  for (const [key, value] of Object.entries(scores.scores)) {
    out[key] = {
      score: numberOrNull(value?.score),
      weight: numberOrNull(value?.weight),
      weightedScore: numberOrNull(value?.weightedScore),
      label: value?.label ?? null,
    };
  }
  return out;
}

function allocateSlug(ref, index, usedSlugs) {
  const base = slugify(ref.dataId ?? (ref.sessionId ? String(ref.sessionId).slice(0, 8) : null), `case-${index + 1}`);
  let candidate = base;
  let suffix = 1;
  while (usedSlugs.has(candidate)) {
    suffix += 1;
    candidate = `${base}-${suffix}`;
  }
  usedSlugs.add(candidate);
  return candidate;
}

function resolveOutputRoot(outputs) {
  const compactTime = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const baseDir = outputs ? path.resolve(String(outputs)) : resolveWorkspaceDir();
  return path.join(baseDir, "eval_trace_results");
}

function shortSession(sessionId) {
  const text = String(sessionId ?? "");
  return text ? text.slice(0, 8) : "-";
}

function relativeLink(fromDir, target) {
  return `[报告](${path.relative(fromDir, target)})`;
}

function readTraceWarnings(outputDir) {
  try {
    const trace = readJson(path.join(outputDir, "_intermediate", "evaluation-trace.json"));
    return Array.isArray(trace?.meta?.warnings) ? trace.meta.warnings.map(String).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function mergeUnique(target, values) {
  for (const value of values) {
    if (!target.includes(value)) target.push(value);
  }
  return target;
}

function readScores(filePath) {
  try {
    return { scores: readJson(filePath), error: null };
  } catch (error) {
    if (error.code === "ENOENT") return { scores: null, error: `缺少 rubric-scores.json: ${filePath}` };
    return { scores: null, error: `rubric-scores.json 不可读: ${filePath}（${error.message}）` };
  }
}

function normalizeTimeout(value) {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num : 0;
}

function skillVersion() {
  try {
    return readJson(path.join(SKILL_ROOT, "package.json"))?.version ?? "0.1.0";
  } catch {
    return "0.1.0";
  }
}

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function round(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}
