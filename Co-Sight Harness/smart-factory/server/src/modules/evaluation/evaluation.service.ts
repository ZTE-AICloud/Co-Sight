import { readdirSync, readFileSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';
import { config } from '../../config/index.js';
import { BadRequestError, ConflictError, NotFoundError, PayloadTooLargeError } from '../../shared/errors.js';
import { runsRepo } from '../../shared/store/runs.repo.js';
import { sessionsRepo } from '../../shared/store/sessions.repo.js';
import type {
  EvaluationAuditSummary,
  EvaluationCaseDetail,
  EvaluationCaseStatus,
  EvaluationCaseSummary,
  EvaluationReportDetail,
  EvaluationReportStatus,
  EvaluationReportSummary,
  EvaluationStep,
  EvaluationStepState,
  PageResult,
} from '../../shared/types/index.js';
import { pageParams, requireEnum } from '../../shared/validate.js';
import { agentRoot, assertAgentId, stageDir } from '../../shared/workspace/dir-resolver.js';
import { resolveAgentWorkspace } from '../../shared/workspace/workspace-resolver.js';

/**
 * 评估报告归一化只读视图（契约 4.09-评估报告）。
 *
 * 报告由评估技能写在 `<agentRoot>/evaluation/` 下的 e2e-test-* 目录里，目录就是真相、不进库；
 * 这里负责「哪份最新、什么算完成、两套分怎么算」的口径，前端只认 DTO。
 * 文件是评估工具的内部格式：工具换格式时只改这一层的字段映射。
 */

/** 报告目录名的唯一形态；不是这个前缀的目录一律不当成报告（§2.2）。 */
const REPORT_ID_PATTERN = /^e2e-test-[A-Za-z0-9._-]+$/;

/** 六个覆盖维度的人话名；eval-plan 里有 coverage[].name 时以文件为准。 */
const DIMENSION_LABELS: Record<string, string> = {
  functional: '功能正确性',
  boundary: '边界与鲁棒性',
  tool_use: '工具调用正确性',
  instruction: '指令遵循与输出格式',
  safety: '安全与越权边界',
  failure: '异常与降级',
};

/** 结果评分四维的缺省权重（eval-manifest 缺 dimension_weights 时的兜底）。 */
const FALLBACK_WEIGHTS = { correctness: 0.4, completeness: 0.3, formatCompliance: 0.15, actionability: 0.15 };

/**
 * 轨迹审计批目录的候选落点。
 *
 * 线上工具写在 `eval_trace_results/`，设计文档 §2.1 写的是 `eval_results/`——
 * 两处都认，按顺序取第一个含 batch-summary.json 的 batch 目录（取字典序最新）。
 */
const AUDIT_BASES = ['eval_trace_results', 'eval_results'] as const;

/** resultPreview 的截断长度（§10）。 */
const RESULT_PREVIEW_MAX = 4000;

// ── 原始文件形状（只声明服务端用到的字段） ─────────────────────────────────

interface GeneratedManifest {
  task_id?: string;
  agent_sha256?: string;
  created_at?: string;
  tool_version?: string;
}

interface EvalPlan {
  tier?: string;
  count_target?: number;
  count_actual?: number;
  coverage?: { dimension?: string; name?: string; weight?: number; actual_total?: number }[];
  totals?: { from_gwt?: number; from_llm?: number };
  repair_rounds?: number;
  rejected?: { source_ref?: string; errors?: string[] }[];
}

interface RunManifest {
  matches?: boolean;
  isolation?: string;
}

interface EvalManifest {
  tool_version?: string;
  input_seed?: string;
  rubric_path?: string;
  rubric_sha256?: string;
  concurrency?: number;
  thresholds?: { weighted?: number; correctness?: number; completeness?: number };
  dimension_weights?: Record<string, number>;
  judge?: { model?: string; main_agent_model?: string };
}

interface EvalItems {
  text?: string;
  verdict?: string;
  note?: string | null;
}

/** eval_datasets/seed.jsonl 的一行；generated / run 两份是它的前缀子集。 */
interface SeedRow {
  data_id?: string;
  dimension?: string;
  capability_ref?: string | null;
  input?: string;
  precondition?: string | null;
  expected_output?: string[];
  eval?: {
    status?: string;
    invalid_reason?: string | null;
    attempts?: number;
    items?: EvalItems[];
    correctness?: number;
    completeness?: number;
    format_compliance?: number;
    actionability?: number;
    weighted_score?: number;
    passed?: boolean;
    reasoning?: string | null;
  } | null;
}

interface BatchSummary {
  meta?: {
    skill?: string;
    generatedAt?: string;
    recordCount?: number;
    failed?: number;
    evaluatorVersion?: string;
    rubricVersion?: string;
  };
  aggregate?: {
    evaluatedCount?: number;
    averageTotalScore?: number;
    dimensionAverages?: Record<
      string,
      { id?: string; name?: string; weight?: number; averageScore?: number; scoredCount?: number }
    >;
  };
  cases?: {
    slug?: string;
    dataId?: string;
    totalScore?: number | null;
    grade?: string | null;
    status?: string | null;
  }[];
}

interface RubricScores {
  scores?: Record<
    string,
    {
      score?: number;
      weight?: number;
      weightedScore?: number;
      label?: string | null;
      summary?: string | null;
      failedTasks?: string[];
      checks?: {
        checkId?: string;
        passed?: boolean;
        severity?: string;
        expected?: unknown;
        actual?: unknown;
        evidence?: string | null;
      }[];
    }
  >;
  totalScore?: number;
  grade?: string;
  verdict?: string;
}

interface TimingFile {
  elapsed_seconds?: number;
  exit_code?: number;
  timed_out?: boolean;
}

interface ResultFile {
  is_error?: boolean;
  num_turns?: number;
  total_cost_usd?: number;
  session_id?: string;
  result?: string;
  usage?: { input_tokens?: number; output_tokens?: number };
}

// ── 文件读取原语 ────────────────────────────────────────────────────────────

type JsonOutcome<T> = { ok: true; data: T } | { ok: false; problem: 'missing' | 'parse' | 'toolarge' };

/** 读单个 JSON 文件；缺失 / 解析失败 / 超限都返回原因，由调用方决定是警告、failed 还是 413。 */
function readJsonFile<T>(absPath: string): JsonOutcome<T> {
  let raw: string;
  try {
    const stats = statSync(absPath);
    if (!stats.isFile()) return { ok: false, problem: 'missing' };
    if (stats.size > config.evaluationMaxJsonBytes) return { ok: false, problem: 'toolarge' };
    raw = readFileSync(absPath, 'utf8');
  } catch {
    return { ok: false, problem: 'missing' };
  }
  try {
    return { ok: true, data: JSON.parse(raw) as T };
  } catch {
    return { ok: false, problem: 'parse' };
  }
}

/** 读 JSONL：逐行解析，任何一行失败整体按 parse 处理（评估工具的落盘是整文件覆盖写）。 */
function readJsonlFile<T>(absPath: string): JsonOutcome<T[]> {
  let raw: string;
  try {
    const stats = statSync(absPath);
    if (!stats.isFile()) return { ok: false, problem: 'missing' };
    if (stats.size > config.evaluationMaxJsonBytes) return { ok: false, problem: 'toolarge' };
    raw = readFileSync(absPath, 'utf8');
  } catch {
    return { ok: false, problem: 'missing' };
  }
  const rows: T[] = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (trimmed === '') continue;
    try {
      rows.push(JSON.parse(trimmed) as T);
    } catch {
      return { ok: false, problem: 'parse' };
    }
  }
  return { ok: true, data: rows };
}

/** 可选 JSON：缺失静默，解析失败 / 超限进 warnings（§6：可选文件缺失不改状态）。 */
function readOptionalJson<T>(absPath: string, warnings: string[], label: string): T | null {
  const outcome = readJsonFile<T>(absPath);
  if (outcome.ok) return outcome.data;
  if (outcome.problem === 'parse') warnings.push(`${label} 解析失败，已忽略`);
  if (outcome.problem === 'toolarge') warnings.push(`${label} 超过大小上限，已忽略`);
  return null;
}

function fileExists(absPath: string): boolean {
  try {
    return statSync(absPath).isFile();
  } catch {
    return false;
  }
}

function directoryExists(absPath: string): boolean {
  try {
    return statSync(absPath).isDirectory();
  } catch {
    return false;
  }
}

function mtimeOf(absPath: string): number | null {
  try {
    return statSync(absPath).mtimeMs;
  } catch {
    return null;
  }
}

/** 平均分统一 Number(toFixed(2))，不用 Math.round（§5.3：4.675 应得 4.67）。 */
function round2(value: number): number {
  return Number(value.toFixed(2));
}

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return round2(values.reduce((sum, value) => sum + value, 0) / values.length);
}

/** `goldeval-generate/0.1.0` → { name, version }；没有斜杠就整体当 name。 */
function splitToolVersion(raw: string | undefined): { name: string | null; version: string | null } {
  if (raw === undefined || raw === '') return { name: null, version: null };
  const index = raw.indexOf('/');
  if (index === -1) return { name: raw, version: null };
  return { name: raw.slice(0, index), version: raw.slice(index + 1) };
}

/** 绝对路径的 input_seed 不下发：只还原成报告内约定相对路径（§2.3）。 */
function toRelativeSeed(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  if (raw.includes('eval_datasets/seed.jsonl')) return 'eval_datasets/seed.jsonl';
  if (raw.includes('run_datasets/seed.jsonl')) return 'run_datasets/seed.jsonl';
  return null;
}

function truncate(text: string | undefined): string | null {
  if (text === undefined || text === null) return null;
  return text.length > RESULT_PREVIEW_MAX ? `${text.slice(0, RESULT_PREVIEW_MAX)}…` : text;
}

// ── 路径解析与身份校验 ──────────────────────────────────────────────────────

/** agentId → evaluation 根（绝对）。未知智能体 404、工作区不可用 502，与 artifacts 同口径；内置智能体 409。 */
async function evaluationRootOf(agentId: unknown): Promise<string> {
  assertAgentId(agentId);
  const workspace = await resolveAgentWorkspace(agentId);
  if (workspace.source === 'builtin') throw new ConflictError(`内置智能体没有评估阶段：${String(agentId)}`, 'error.conflict.builtin_agent', { agentId });
  return stageDir(agentRoot(workspace.directory, agentId as string), 'evaluation');
}

function assertReportId(reportId: unknown): asserts reportId is string {
  if (typeof reportId !== 'string' || !REPORT_ID_PATTERN.test(reportId)) {
    throw new BadRequestError(`reportId 形态非法：${JSON.stringify(reportId)}`);
  }
}

/** 单段目录名：不接受 `/`、`\`、`..`、NUL（§4）。 */
function assertCaseId(caseId: unknown): asserts caseId is string {
  if (
    typeof caseId !== 'string' ||
    caseId === '' ||
    caseId === '.' ||
    caseId === '..' ||
    caseId.includes('/') ||
    caseId.includes('\\') ||
    caseId.includes('\u0000')
  ) {
    throw new BadRequestError(`caseId 形态非法：${JSON.stringify(caseId)}`);
  }
}

/**
 * 扫描 evaluation 根下匹配形态的报告目录，reportId 降序（字典序即时间序，§2.2）。
 *
 * 两个落点都认（4.09 文档画的是根下直接放 e2e-test-*，线上工具多套一层
 * `eval_results/`）：同名 reportId 以根下那份优先，不重复返回。
 */
function listReportIds(root: string): string[] {
  const found: string[] = [];
  for (const base of [root, join(root, 'eval_results')]) {
    let names: string[];
    try {
      names = readdirSync(base, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && REPORT_ID_PATTERN.test(entry.name))
        .map((entry) => entry.name);
    } catch {
      continue;
    }
    for (const name of names) {
      if (!found.includes(name)) found.push(name);
    }
  }
  return found.sort((a, b) => b.localeCompare(a));
}

/** reportId → 报告目录绝对路径：根下没有时回落 `eval_results/` 落点，都没有 = null。 */
function resolveReportDir(root: string, reportId: string): string | null {
  for (const candidate of [join(root, reportId), join(root, 'eval_results', reportId)]) {
    if (directoryExists(candidate)) return candidate;
  }
  return null;
}

interface AuditBatch {
  /** 批目录相对报告根的路径（如 eval_trace_results/batch_x），恒用正斜杠 */
  rel: string;
  /** 绝对路径 */
  abs: string;
  summary: BatchSummary;
  /** 参与审计的用例目录名（slug），按 batch-summary.cases 顺序 */
  caseSlugs: string[];
}

/** 定位最新轨迹审计批：AUDIT_BASES 里第一个含 batch_* 的；批按字典序取最新。 */
function findAuditBatch(reportAbs: string, warnings: string[]): AuditBatch | null {
  for (const base of AUDIT_BASES) {
    const baseAbs = join(reportAbs, base);
    let batchNames: string[];
    try {
      batchNames = readdirSync(baseAbs, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && entry.name.startsWith('batch_'))
        .map((entry) => entry.name)
        .sort((a, b) => b.localeCompare(a));
    } catch {
      continue;
    }
    for (const name of batchNames) {
      const abs = join(baseAbs, name);
      const outcome = readJsonFile<BatchSummary>(join(abs, 'batch-summary.json'));
      if (outcome.ok) {
        return {
          rel: `${base}/${name}`,
          abs,
          summary: outcome.data,
          caseSlugs: (outcome.data.cases ?? [])
            .map((item) => item.slug ?? item.dataId ?? '')
            .filter((slug) => slug !== ''),
        };
      }
      if (outcome.problem === 'parse') {
        warnings.push(`最新审计批 ${base}/${name}/batch-summary.json 解析失败，已跳过`);
      }
    }
  }
  return null;
}

/** 读某条用例的轨迹审计分（batch 的 cases/<slug>/rubric-scores.json）；缺失静默。 */
function readRubricScores(batch: AuditBatch, slug: string): RubricScores | null {
  const outcome = readJsonFile<RubricScores>(join(batch.abs, 'cases', slug, 'rubric-scores.json'));
  return outcome.ok ? outcome.data : null;
}

interface AuditCheckRow {
  dimension: string;
  checkId: string;
  passed: boolean;
  severity: string;
  expected: unknown;
  actual: unknown;
  evidence: string | null;
}

/** 把 rubric-scores.scores 摊平成带 dimension 键的检查行（detail 用）。 */
function flattenAuditChecks(scores: RubricScores): AuditCheckRow[] {
  const rows: AuditCheckRow[] = [];
  for (const [dimension, entry] of Object.entries(scores.scores ?? {})) {
    for (const check of entry.checks ?? []) {
      rows.push({
        dimension,
        checkId: check.checkId ?? '',
        passed: check.passed === true,
        severity: check.severity ?? '',
        expected: check.expected ?? null,
        actual: check.actual ?? null,
        evidence: check.evidence ?? null,
      });
    }
  }
  return rows;
}

// ── 摘要组装 ────────────────────────────────────────────────────────────────

function step(state: EvaluationStepState, at: string | null): EvaluationStep {
  return { state, at };
}

/** 评估会话是否正跑着 run（§6：先判活跃 run 再判解析失败，写一半是中间态不是失败）。 */
async function hasActiveEvalRun(agentId: string): Promise<boolean> {
  const found = await sessionsRepo.list({ agentId, stages: ['evaluation'], page: 1, pageSize: 1 });
  const latest = found.items[0];
  if (!latest) return false;
  return (await runsRepo.findActiveBySession(latest.id)) !== null;
}

interface ReportFileOutcomes {
  generated: JsonOutcome<GeneratedManifest>;
  evalPlan: JsonOutcome<EvalPlan>;
  runManifest: JsonOutcome<RunManifest>;
  evalManifest: JsonOutcome<EvalManifest>;
  runSeed: JsonOutcome<SeedRow[]>;
  evalSeed: JsonOutcome<SeedRow[]>;
  batch: AuditBatch | null;
}

function readReportFiles(reportAbs: string, warnings: string[]): ReportFileOutcomes {
  return {
    generated: readJsonFile<GeneratedManifest>(join(reportAbs, 'generated_datasets', 'manifest.json')),
    evalPlan: readJsonFile<EvalPlan>(join(reportAbs, 'generated_datasets', 'eval-plan.json')),
    runManifest: readJsonFile<RunManifest>(join(reportAbs, 'run_datasets', 'run-manifest.json')),
    evalManifest: readJsonFile<EvalManifest>(join(reportAbs, 'eval_datasets', 'eval-manifest.json')),
    runSeed: readJsonlFile<SeedRow>(join(reportAbs, 'run_datasets', 'seed.jsonl')),
    evalSeed: readJsonlFile<SeedRow>(join(reportAbs, 'eval_datasets', 'seed.jsonl')),
    batch: findAuditBatch(reportAbs, warnings),
  };
}

/** 「存在但解析失败 / 超限」：缺失不算，缺失是未开始（§6）。 */
function isBroken<T>(outcome: JsonOutcome<T>): boolean {
  return !outcome.ok && outcome.problem !== 'missing';
}

/**
 * 用例列表的数据源：按流水线推进程度取最靠后的一份 seed（eval → run → generated）。
 *
 * 评估在「生成 / 执行」阶段还没有 `eval_datasets/seed.jsonl`，但前两份已经有完整
 * 用例定义 —— 右侧不该空着，也不该等到评分阶段才看得到测试集。eval 那份存在但
 * 解析失败或暂时为空（覆盖写期间的半截文件）时继续往前退，半截文件不能把整张
 * 列表清空。
 */
function caseSeedOf(
  reportAbs: string,
  seeds?: Pick<ReportFileOutcomes, 'evalSeed' | 'runSeed'>,
): SeedRow[] {
  const evalSeed = seeds?.evalSeed ?? readJsonlFile<SeedRow>(join(reportAbs, 'eval_datasets', 'seed.jsonl'));
  if (evalSeed.ok && evalSeed.data.length > 0) return evalSeed.data;
  const runSeed = seeds?.runSeed ?? readJsonlFile<SeedRow>(join(reportAbs, 'run_datasets', 'seed.jsonl'));
  if (runSeed.ok && runSeed.data.length > 0) return runSeed.data;
  const generated = readJsonlFile<SeedRow>(join(reportAbs, 'generated_datasets', 'seed.jsonl'));
  return generated.ok ? generated.data : [];
}

/** 一份报告的完整归一化；list 与 detail 共用，detail 再补 §5.2 的扩展块。 */
async function summarizeReport(input: {
  root: string;
  agentId: string;
  reportId: string;
  reportAbs: string;
  activeRun: boolean;
}): Promise<EvaluationReportSummary> {
  const { agentId, reportId, reportAbs, activeRun } = input;
  const warnings: string[] = [];
  const files = readReportFiles(reportAbs, warnings);

  const generated = files.generated.ok ? files.generated.data : null;
  const runManifest = files.runManifest.ok ? files.runManifest.data : null;
  const evalManifest = files.evalManifest.ok ? files.evalManifest.data : null;

  // 四步完成判据（§6）。必需文件「存在但解析失败 / 超限」记 failed；缺失按未开始。
  const planBroken = isBroken(files.generated) || isBroken(files.evalPlan);
  const planDone = files.generated.ok && files.evalPlan.ok;
  const plan: EvaluationStep =
    planBroken && !activeRun
      ? step('failed', null)
      : planDone
        ? step('done', generated?.created_at ?? null)
        : activeRun
          ? step('running', null)
          : step('pending', null);

  const runSeedRows = files.runSeed.ok ? files.runSeed.data : null;
  const runTimingsComplete =
    runSeedRows !== null &&
    runSeedRows.every((row) => row.data_id !== undefined && fileExists(join(reportAbs, 'run_datasets', String(row.data_id), 'timing.json')));
  const runBroken = isBroken(files.runManifest);
  const runDone = files.runManifest.ok && runTimingsComplete;
  const run: EvaluationStep =
    runBroken && !activeRun
      ? step('failed', null)
      : runDone
        ? step('done', null)
        : files.runManifest.ok && activeRun
          ? step('running', null)
          : step('pending', null);

  const evalSeedRows = files.evalSeed.ok ? files.evalSeed.data : null;
  const evalsComplete =
    evalSeedRows !== null && evalSeedRows.every((row) => row.eval !== undefined && row.eval !== null);
  const scoreBroken = isBroken(files.evalManifest) || isBroken(files.evalSeed);
  const scoreDone = files.evalManifest.ok && evalsComplete;
  const score: EvaluationStep =
    scoreBroken && !activeRun
      ? step('failed', null)
      : scoreDone
        ? step('done', null)
        : files.evalManifest.ok && activeRun
          ? step('running', null)
          : step('pending', null);

  const audit: EvaluationStep =
    files.batch !== null ? step('done', files.batch.summary.meta?.generatedAt ?? null) : step('pending', null);

  if (!files.runSeed.ok && files.runSeed.problem === 'parse') warnings.push('run_datasets/seed.jsonl 解析失败');
  if (!files.evalSeed.ok && files.evalSeed.problem === 'parse') warnings.push('eval_datasets/seed.jsonl 解析失败');
  if (!files.evalSeed.ok && files.evalSeed.problem === 'toolarge') warnings.push('eval_datasets/seed.jsonl 超过大小上限');

  // 计数与评分只统计 eval.status === 'ok' 的用例（§5.3）。
  // 用例来源按阶段回退：评分还没写 eval seed 时，run / generated 的 seed 一样能列出测试集。
  const rows = caseSeedOf(reportAbs, files);
  const validRows = rows.filter((row) => row.eval?.status === 'ok');
  const pendingRows = rows.filter((row) => row.eval === undefined || row.eval === null);
  const invalidRows = rows.filter(
    (row) => row.eval !== undefined && row.eval !== null && row.eval.status !== 'ok',
  );
  const passedRows = validRows.filter((row) => row.eval?.passed === true);
  const weightedScores = validRows
    .map((row) => row.eval?.weighted_score)
    .filter((value): value is number => typeof value === 'number');
  const expectedTotals = validRows.map((row) => {
    const items = row.eval?.items ?? [];
    return {
      hit: items.filter((item) => item.verdict === 'hit').length,
      miss: items.filter((item) => item.verdict === 'miss').length,
    };
  });

  const weightsSource = evalManifest?.dimension_weights ?? {};
  const weightOf = (key: string, fallback: number): number => {
    const raw = weightsSource[key];
    return typeof raw === 'number' ? raw : fallback;
  };
  const dimAvg = (pick: (row: SeedRow) => number | undefined): number | null =>
    average(validRows.map(pick).filter((value): value is number => typeof value === 'number'));
  const correctnessAvg = dimAvg((row) => row.eval?.correctness);
  const completenessAvg = dimAvg((row) => row.eval?.completeness);

  const thresholds = {
    weighted: evalManifest?.thresholds?.weighted ?? null,
    correctness: evalManifest?.thresholds?.correctness ?? null,
    completeness: evalManifest?.thresholds?.completeness ?? null,
    met: null as boolean | null,
  };
  const weightedAverage = average(weightedScores);
  if (
    weightedAverage !== null &&
    thresholds.weighted !== null &&
    correctnessAvg !== null &&
    thresholds.correctness !== null &&
    completenessAvg !== null &&
    thresholds.completeness !== null
  ) {
    thresholds.met =
      weightedAverage >= thresholds.weighted &&
      correctnessAvg >= thresholds.correctness &&
      completenessAvg >= thresholds.completeness;
  }

  // 审计摘要：平均取 aggregate；等级「最差一条决定总体」（§5.3）；failedChecks 去重。
  let auditSummary: EvaluationAuditSummary | null = null;
  if (files.batch !== null) {
    let worst: { totalScore: number; grade: string } | null = null;
    for (const item of files.batch.summary.cases ?? []) {
      if (typeof item.totalScore !== 'number') continue;
      if (worst === null || item.totalScore < worst.totalScore) {
        worst = { totalScore: item.totalScore, grade: item.grade ?? '' };
      }
    }
    const failedCheckIds = new Set<string>();
    for (const slug of files.batch.caseSlugs) {
      const scores = readRubricScores(files.batch, slug);
      if (scores === null) continue;
      for (const row of flattenAuditChecks(scores)) {
        if (!row.passed && row.checkId !== '') failedCheckIds.add(row.checkId);
      }
    }
    auditSummary = {
      average:
        typeof files.batch.summary.aggregate?.averageTotalScore === 'number'
          ? round2(files.batch.summary.aggregate.averageTotalScore)
          : null,
      grade: worst?.grade ?? null,
      evaluated: files.batch.summary.aggregate?.evaluatedCount ?? files.batch.summary.meta?.recordCount ?? 0,
      failed: files.batch.summary.meta?.failed ?? 0,
      failedChecks: failedCheckIds.size,
    };
  }

  // 整体状态（§6，顺序判定）。
  const steps = { plan, run, score, audit };
  const stepList = [plan, run, score, audit];
  const allDone = stepList.every((item) => item.state === 'done');
  const anyBroken = [plan, run, score].some((item) => item.state === 'failed');
  const anyDone = stepList.some((item) => item.state === 'done');
  const anyPending = stepList.some((item) => item.state !== 'done');
  let status: EvaluationReportStatus;
  if (allDone) status = 'completed';
  else if (anyPending && activeRun) status = 'running';
  else if (anyBroken) status = 'failed';
  else if (anyPending && anyDone) status = 'partial';
  else status = 'pending';

  // updatedAt 取已知关键文件的最大 mtime；全缺失退报告目录 mtime。
  const watchedMtimes = [
    join(reportAbs, 'generated_datasets', 'manifest.json'),
    join(reportAbs, 'run_datasets', 'run-manifest.json'),
    join(reportAbs, 'eval_datasets', 'eval-manifest.json'),
    join(reportAbs, 'eval_datasets', 'seed.jsonl'),
    files.batch !== null ? join(files.batch.abs, 'batch-summary.json') : null,
  ]
    .filter((path): path is string => path !== null)
    .map(mtimeOf)
    .filter((value): value is number => value !== null);
  const updatedAt =
    watchedMtimes.length > 0
      ? new Date(Math.max(...watchedMtimes)).toISOString()
      : new Date(mtimeOf(reportAbs) ?? Date.now()).toISOString();

  return {
    reportId,
    agentId,
    title: generated?.task_id ?? reportId,
    status,
    createdAt: generated?.created_at ?? updatedAt,
    updatedAt,
    dir: reportId,
    pipeline: steps,
    counts: {
      total: rows.length,
      valid: validRows.length,
      /** 已在评分但没评出结果（eval.status !== 'ok'） */
      invalid: invalidRows.length,
      /** 还没进入评分：eval 字段缺失（生成 / 执行阶段） */
      pending: pendingRows.length,
      passed: passedRows.length,
      failed: validRows.length - passedRows.length,
      expectedTotal: expectedTotals.reduce((sum, item) => sum + item.hit + item.miss, 0),
      expectedHit: expectedTotals.reduce((sum, item) => sum + item.hit, 0),
      expectedMiss: expectedTotals.reduce((sum, item) => sum + item.miss, 0),
    },
    scores: {
      weightedAverage,
      passRate: validRows.length > 0 ? round2(passedRows.length / validRows.length) : null,
      dimensions: {
        correctness: correctnessAvg,
        completeness: completenessAvg,
        formatCompliance: dimAvg((row) => row.eval?.format_compliance),
        actionability: dimAvg((row) => row.eval?.actionability),
      },
      weights: {
        correctness: weightOf('correctness', FALLBACK_WEIGHTS.correctness),
        completeness: weightOf('completeness', FALLBACK_WEIGHTS.completeness),
        formatCompliance: weightOf('format_compliance', FALLBACK_WEIGHTS.formatCompliance),
        actionability: weightOf('actionability', FALLBACK_WEIGHTS.actionability),
      },
    },
    thresholds,
    audit: auditSummary,
    stale: runManifest ? runManifest.matches === false : null,
    warnings,
  };
}

// ── 用例组装 ────────────────────────────────────────────────────────────────

function dimensionLabelOf(evalPlan: EvalPlan | null, dimension: string): string {
  const hit = evalPlan?.coverage?.find((item) => item.dimension === dimension);
  if (hit?.name) return hit.name;
  return DIMENSION_LABELS[dimension] ?? dimension;
}

/** 单条用例的 run 元数据：timing + result 现读，判定口径见 §2.3（不用 seed 里的 run.status 字符串）。 */
function runMetaOf(
  reportAbs: string,
  caseId: string,
): {
  status: EvaluationCaseSummary['run']['status'];
  elapsedMs: number | null;
  turns: number | null;
  exitCode: number | null;
} {
  const timing = readJsonFile<TimingFile>(join(reportAbs, 'run_datasets', caseId, 'timing.json'));
  const result = readJsonFile<ResultFile>(join(reportAbs, 'run_datasets', caseId, 'result.json'));
  if (!timing.ok && !result.ok) {
    return { status: null, elapsedMs: null, turns: null, exitCode: null };
  }
  const timedOut = timing.ok && timing.data.timed_out === true;
  const isError = result.ok && result.data.is_error === true;
  const exitCode = timing.ok && typeof timing.data.exit_code === 'number' ? timing.data.exit_code : null;
  let status: EvaluationCaseSummary['run']['status'];
  if (timedOut) status = 'timeout';
  else if (isError) status = 'error';
  else if (exitCode !== null && exitCode !== 0) status = 'failed';
  else status = 'passed';
  return {
    status,
    elapsedMs:
      timing.ok && typeof timing.data.elapsed_seconds === 'number'
        ? Math.round(timing.data.elapsed_seconds * 1000)
        : null,
    turns: result.ok && typeof result.data.num_turns === 'number' ? result.data.num_turns : null,
    exitCode,
  };
}

interface CaseContext {
  reportAbs: string;
  evalPlan: EvalPlan | null;
  batch: AuditBatch | null;
}

/** cases 两个端点共用的上下文：eval-plan 与审计批。 */
async function caseContextOf(reportAbs: string): Promise<CaseContext> {
  const warnings: string[] = [];
  const evalPlan = readOptionalJson<EvalPlan>(
    join(reportAbs, 'generated_datasets', 'eval-plan.json'),
    warnings,
    'generated_datasets/eval-plan.json',
  );
  const batch = findAuditBatch(reportAbs, warnings);
  return { reportAbs, evalPlan, batch };
}

function toCaseSummary(row: SeedRow, index: number, context: CaseContext): EvaluationCaseSummary | null {
  const caseId = row.data_id;
  if (caseId === undefined || caseId === '') return null;
  const evalOf = row.eval;
  const scored = evalOf !== undefined && evalOf !== null;
  const valid = evalOf?.status === 'ok';
  const status: EvaluationCaseStatus = !valid ? 'invalid' : evalOf?.passed === true ? 'passed' : 'failed';
  const items = evalOf?.items ?? [];

  let audit: EvaluationCaseSummary['audit'] = null;
  if (context.batch !== null) {
    const hit = (context.batch.summary.cases ?? []).find(
      (item) => item.slug === caseId || item.dataId === caseId,
    );
    if (hit !== undefined) {
      audit = { totalScore: typeof hit.totalScore === 'number' ? hit.totalScore : null, grade: hit.grade ?? null };
    }
  }

  const warnings: string[] = [];
  if (!valid && evalOf?.invalid_reason) warnings.push(`评分失败：${evalOf.invalid_reason}`);

  return {
    caseId,
    index,
    dimension: row.dimension ?? '',
    dimensionLabel: dimensionLabelOf(context.evalPlan, row.dimension ?? ''),
    capabilityRef: row.capability_ref ?? null,
    input: row.input ?? '',
    status,
    /** false = 还没评分（生成 / 执行阶段），与「评了但失败」的 invalid 区分 */
    scored,
    weightedScore: valid && typeof evalOf?.weighted_score === 'number' ? evalOf.weighted_score : null,
    scores: {
      correctness: valid && typeof evalOf?.correctness === 'number' ? evalOf.correctness : null,
      completeness: valid && typeof evalOf?.completeness === 'number' ? evalOf.completeness : null,
      formatCompliance: valid && typeof evalOf?.format_compliance === 'number' ? evalOf.format_compliance : null,
      actionability: valid && typeof evalOf?.actionability === 'number' ? evalOf.actionability : null,
    },
    expected: {
      total: items.filter((item) => item.verdict === 'hit' || item.verdict === 'miss').length,
      hit: items.filter((item) => item.verdict === 'hit').length,
      miss: items.filter((item) => item.verdict === 'miss').length,
    },
    run: { ...runMetaOf(context.reportAbs, caseId), attempts: evalOf?.attempts ?? 1 },
    audit,
    warnings,
  };
}

// ── 对外服务 ────────────────────────────────────────────────────────────────

export const evaluationService = {
  /** 报告列表：评估目录不存在 / 还没有任何报告 → 200 空页，不 404（§4）。 */
  async listReports(input: {
    agentId: unknown;
    status?: unknown;
    page?: unknown;
    pageSize?: unknown;
  }): Promise<PageResult<EvaluationReportSummary>> {
    const agentId = input.agentId;
    const root = await evaluationRootOf(agentId);
    const reportIds = listReportIds(root);
    const { page, pageSize } = pageParams(input.page, input.pageSize);
    const statusFilter =
      input.status === undefined || input.status === ''
        ? undefined
        : requireEnum(input.status, ['pending', 'running', 'completed', 'partial', 'failed'] as const, 'status');

    const activeRun = await hasActiveEvalRun(String(agentId));
    /** 带 status 过滤必须全量解析（状态在文件里）；不带则只解析当前页（§10）。 */
    const summarize = (reportId: string): Promise<EvaluationReportSummary> => {
      const reportAbs = resolveReportDir(root, reportId);
      if (reportAbs === null) {
        return Promise.resolve({
          reportId,
          agentId: String(agentId),
          title: reportId,
          status: 'pending',
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          dir: reportId,
          pipeline: {
            plan: step('pending', null),
            run: step('pending', null),
            score: step('pending', null),
            audit: step('pending', null),
          },
          counts: {
            total: 0,
            valid: 0,
            invalid: 0,
            pending: 0,
            passed: 0,
            failed: 0,
            expectedTotal: 0,
            expectedHit: 0,
            expectedMiss: 0,
          },
          scores: {
            weightedAverage: null,
            passRate: null,
            dimensions: { correctness: null, completeness: null, formatCompliance: null, actionability: null },
            weights: { ...FALLBACK_WEIGHTS },
          },
          thresholds: { weighted: null, correctness: null, completeness: null, met: null },
          audit: null,
          stale: null,
          warnings: [],
        });
      }
      return summarizeReport({ root, agentId: String(agentId), reportId, reportAbs, activeRun });
    };

    if (statusFilter === undefined) {
      const slice = reportIds.slice((page - 1) * pageSize, page * pageSize);
      const items = await Promise.all(slice.map(summarize));
      return { items, total: reportIds.length, page, pageSize };
    }

    const all = await Promise.all(reportIds.map(summarize));
    const filtered = all.filter((item) => item.status === statusFilter);
    return {
      items: filtered.slice((page - 1) * pageSize, page * pageSize),
      total: filtered.length,
      page,
      pageSize,
    };
  },

  /** 报告详情：摘要 + §5.2 扩展块。报告目录不存在 404。 */
  async getReportDetail(input: { agentId: unknown; reportId: unknown }): Promise<EvaluationReportDetail> {
    const agentId = input.agentId;
    const root = await evaluationRootOf(agentId);
    assertReportId(input.reportId);
    const reportId = input.reportId;
    const reportAbs = resolveReportDir(root, reportId);
    if (reportAbs === null) throw new NotFoundError(`评估报告 ${reportId}`, 'error.not_found.report', { reportId });

    const activeRun = await hasActiveEvalRun(String(agentId));
    const summary = await summarizeReport({ root, agentId: String(agentId), reportId, reportAbs, activeRun });
    const files = readReportFiles(reportAbs, summary.warnings);

    const generated = files.generated.ok ? files.generated.data : null;
    const evalPlan = files.evalPlan.ok ? files.evalPlan.data : null;
    const runManifest = files.runManifest.ok ? files.runManifest.data : null;
    const batch = files.batch;

    if (!files.evalManifest.ok && files.evalManifest.problem === 'toolarge') {
      throw new PayloadTooLargeError('eval_datasets/eval-manifest.json 超过大小上限', 'error.payload_too_large.manifest');
    }
    const evalManifest = files.evalManifest.ok ? files.evalManifest.data : null;

    // 覆盖计划（§2.3：rejected.reason = errors 用「；」连接）。
    const coverage =
      evalPlan !== null
        ? {
            tier: evalPlan.tier ?? null,
            target: evalPlan.count_target ?? null,
            actual: evalPlan.count_actual ?? null,
            fromGwt: evalPlan.totals?.from_gwt ?? null,
            fromLlm: evalPlan.totals?.from_llm ?? null,
            repairRounds: evalPlan.repair_rounds ?? null,
            dimensions: (evalPlan.coverage ?? []).map((item) => ({
              key: item.dimension ?? '',
              name: item.name ?? DIMENSION_LABELS[item.dimension ?? ''] ?? item.dimension ?? '',
              weight: item.weight ?? 0,
              count: item.actual_total ?? 0,
            })),
            rejected: (evalPlan.rejected ?? []).map((item) => ({
              sourceRef: item.source_ref ?? '',
              reason: (item.errors ?? []).join('；'),
            })),
          }
        : null;

    // 审计明细：维度均分来自 aggregate；检查行逐用例摊平。
    let auditDetails: EvaluationReportDetail['auditDetails'] = null;
    if (batch !== null) {
      const dimensions = Object.entries(batch.summary.aggregate?.dimensionAverages ?? {}).map(([key, value]) => ({
        key: value.id ?? key,
        name: value.name ?? key,
        weight: value.weight ?? 0,
        average: typeof value.averageScore === 'number' ? round2(value.averageScore) : null,
        scoredCount: value.scoredCount ?? 0,
      }));
      const checks = batch.caseSlugs.flatMap((slug) => {
        const scores = readRubricScores(batch, slug);
        return scores === null ? [] : flattenAuditChecks(scores).map((row) => ({ caseId: slug, ...row }));
      });
      auditDetails = { dimensions, checks };
    }

    const reportMdRel = 'eval_datasets/report.md';
    const generatedReportMdRel = 'generated_datasets/report.md';
    return {
      ...summary,
      tools: {
        generate: splitToolVersion(generated?.tool_version),
        evaluate: splitToolVersion(evalManifest?.tool_version),
        audit: batch
          ? {
              name: batch.summary.meta?.skill ?? null,
              version: batch.summary.meta?.evaluatorVersion ?? null,
              rubricVersion: batch.summary.meta?.rubricVersion ?? null,
            }
          : { name: null, version: null, rubricVersion: null },
      },
      judge: {
        model: evalManifest?.judge?.model ?? null,
        mainAgentModel: evalManifest?.judge?.main_agent_model ?? null,
      },
      coverage,
      auditDetails,
      environment: {
        generatedAt: generated?.created_at ?? null,
        auditedAt: batch?.summary.meta?.generatedAt ?? null,
        concurrency: evalManifest?.concurrency ?? null,
        rubric: {
          file: evalManifest?.rubric_path !== undefined ? basename(evalManifest.rubric_path) : null,
          sha256: evalManifest?.rubric_sha256 ?? null,
        },
        inputSeed: toRelativeSeed(evalManifest?.input_seed),
        agentSha256: generated?.agent_sha256 ?? null,
        agentShaMatches: runManifest ? runManifest.matches === true : null,
        isolation: runManifest?.isolation ?? null,
      },
      files: {
        generatedReportMd: fileExists(join(reportAbs, generatedReportMdRel)) ? generatedReportMdRel : null,
        reportMd: fileExists(join(reportAbs, reportMdRel)) ? reportMdRel : null,
        auditReportMd:
          batch !== null && fileExists(join(batch.abs, 'batch-summary.md'))
            ? `${batch.rel}/batch-summary.md`
            : null,
        seedJsonl: files.evalSeed.ok ? 'eval_datasets/seed.jsonl' : null,
      },
    };
  },

  /** 用例摘要列表：按阶段回退取 seed（eval → run → generated），可按结果 / 维度过滤（§4）。 */
  async listCases(input: {
    agentId: unknown;
    reportId: unknown;
    status?: unknown;
    dimension?: unknown;
    page?: unknown;
    pageSize?: unknown;
  }): Promise<PageResult<EvaluationCaseSummary>> {
    const root = await evaluationRootOf(input.agentId);
    assertReportId(input.reportId);
    const reportId = input.reportId;
    const reportAbs = resolveReportDir(root, reportId);
    if (reportAbs === null) throw new NotFoundError(`评估报告 ${reportId}`, 'error.not_found.report', { reportId });

    const statusFilter =
      input.status === undefined || input.status === ''
        ? undefined
        : requireEnum(input.status, ['passed', 'failed', 'invalid'] as const, 'status');
    const dimensionFilter =
      input.dimension === undefined || input.dimension === ''
        ? undefined
        : requireEnum(input.dimension, ['functional', 'boundary', 'tool_use', 'instruction', 'safety', 'failure'] as const, 'dimension');
    const { page, pageSize } = pageParams(input.page, input.pageSize);

    const context = await caseContextOf(reportAbs);
    const all = caseSeedOf(reportAbs)
      .map((row, index) => toCaseSummary(row, index, context))
      .filter((item): item is EvaluationCaseSummary => item !== null)
      .filter((item) => (statusFilter === undefined ? true : item.status === statusFilter))
      .filter((item) => (dimensionFilter === undefined ? true : item.dimension === dimensionFilter));
    return { items: all.slice((page - 1) * pageSize, page * pageSize), total: all.length, page, pageSize };
  },

  /** 用例详情：期望项、裁判理由、运行元数据、审计检查项（§5.5）。 */
  async getCaseDetail(input: { agentId: unknown; reportId: unknown; caseId: unknown }): Promise<EvaluationCaseDetail> {
    const root = await evaluationRootOf(input.agentId);
    assertReportId(input.reportId);
    assertCaseId(input.caseId);
    const reportId = input.reportId;
    const caseId = input.caseId;
    const reportAbs = join(root, reportId);
    if (!directoryExists(reportAbs)) throw new NotFoundError(`评估报告 ${reportId}`, 'error.not_found.report', { reportId });

    const context = await caseContextOf(reportAbs);
    const rows = caseSeedOf(reportAbs);
    const index = rows.findIndex((row) => row.data_id === caseId);
    if (index === -1) throw new NotFoundError(`用例 ${caseId}`, 'error.not_found.case', { caseId });
    const row = rows[index]!;
    const summary = toCaseSummary(row, index, context);
    if (summary === null) throw new NotFoundError(`用例 ${caseId}`, 'error.not_found.case', { caseId });

    const resultOutcome = readJsonFile<ResultFile>(join(reportAbs, 'run_datasets', caseId, 'result.json'));
    if (!resultOutcome.ok && resultOutcome.problem === 'toolarge') {
      throw new PayloadTooLargeError(`run_datasets/${caseId}/result.json 超过大小上限`, 'error.payload_too_large.result', { caseId });
    }
    const result = resultOutcome.ok ? resultOutcome.data : null;

    // 审计明细：rubric-scores 的五维 + 检查项；维度人话名从 batch aggregate 借。
    let auditDetails: EvaluationCaseDetail['auditDetails'] = null;
    if (context.batch !== null) {
      const scores = readRubricScores(context.batch, caseId);
      if (scores !== null) {
        const averageName = (key: string): string | null =>
          context.batch?.summary.aggregate?.dimensionAverages?.[key]?.name ?? null;
        const dimensions = Object.entries(scores.scores ?? {}).map(([key, entry]) => ({
          key,
          name: averageName(key),
          weight: typeof entry.weight === 'number' ? entry.weight : null,
          score: typeof entry.score === 'number' ? entry.score : null,
          weightedScore: typeof entry.weightedScore === 'number' ? entry.weightedScore : null,
          label: entry.label ?? null,
          summary: entry.summary ?? null,
          failedTasks: entry.failedTasks ?? [],
        }));
        auditDetails = {
          verdict: scores.verdict ?? null,
          dimensions,
          checks: flattenAuditChecks(scores),
        };
      }
    }

    const caseDirRel = `run_datasets/${caseId}`;
    const sessionRel =
      result?.session_id !== undefined ? `${caseDirRel}/sessions/${result.session_id}.jsonl` : null;
    const auditMdRel =
      context.batch !== null ? `${context.batch.rel}/cases/${caseId}/trajectory-report.md` : null;
    const auditJsonRel =
      context.batch !== null ? `${context.batch.rel}/cases/${caseId}/trajectory-report.json` : null;
    const evalOf = row.eval;

    return {
      ...summary,
      precondition: row.precondition ?? null,
      // 还没评分时 eval.items 为空：退回 seed 里的 expected_output，全部标 unknown，
      // 让「待评分」的用例展开后也能看到会检查什么。
      expectedItems:
        evalOf?.items !== undefined && evalOf.items.length > 0
          ? evalOf.items.map((item) => ({
              text: item.text ?? '',
              verdict: item.verdict === 'hit' || item.verdict === 'miss' ? item.verdict : 'unknown',
              note: item.note ?? null,
            }))
          : (row.expected_output ?? []).map((text) => ({ text, verdict: 'unknown' as const, note: null })),
      reasoning: evalOf?.reasoning ?? null,
      resultPreview: truncate(result?.result),
      usage: result
        ? {
            inputTokens: result.usage?.input_tokens ?? null,
            outputTokens: result.usage?.output_tokens ?? null,
            costUsd: typeof result.total_cost_usd === 'number' ? result.total_cost_usd : null,
          }
        : null,
      auditDetails,
      files: {
        result: fileExists(join(reportAbs, caseDirRel, 'result.json')) ? `${caseDirRel}/result.json` : null,
        timing: fileExists(join(reportAbs, caseDirRel, 'timing.json')) ? `${caseDirRel}/timing.json` : null,
        stdout: fileExists(join(reportAbs, caseDirRel, 'stdout.txt')) ? `${caseDirRel}/stdout.txt` : null,
        stderr: fileExists(join(reportAbs, caseDirRel, 'stderr.txt')) ? `${caseDirRel}/stderr.txt` : null,
        session: sessionRel !== null && fileExists(join(reportAbs, sessionRel)) ? sessionRel : null,
        auditReportMd: auditMdRel !== null && fileExists(join(reportAbs, auditMdRel)) ? auditMdRel : null,
        auditReportJson:
          auditJsonRel !== null && fileExists(join(reportAbs, auditJsonRel)) ? auditJsonRel : null,
      },
    };
  },
};
