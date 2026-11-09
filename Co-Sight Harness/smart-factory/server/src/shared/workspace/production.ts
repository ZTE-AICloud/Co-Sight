import { existsSync, lstatSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { ConflictError, NotFoundError } from '../errors.js';
import type {
  AgentProductionStatus,
  AgentProductionView,
  DeliveryVerdict,
  ProductionLane,
} from '../types/index.js';

/**
 * 智能体产物状态：读取 AgentGenesis 的生产过程状态与交付门禁，给出「能否进入预览 / 评估」。
 *
 * 权威口径（agent-genesis / harness-create）：
 * - 过程状态：`development/.agent-genesis/work/{name}/orchestrator-state.yaml`
 *   （`pipeline` = agent-creation | agent-creation-fast，`pipeline_status` =
 *   IN_PROGRESS | COMPLETED | BLOCKED | FAILED，`current_step`）。
 * - 交付门禁：`gate-results/<step>.json` 的 `verdict` ∈ {PASS, CONCERNS}。
 *   优先取 `current_step` 对应的那份（技能统一按 step_id 落盘）；文件缺失时才
 *   回落到已知文件名：full 的 `step-4-implementation.json`（executor 收尾）、
 *   fast 的 `step-f1-fast-build.json`（create）/ `step-f2-fast-optimize.json`（optimize）。
 *   技能文档里提到的 `g028-exit-sanity.json` 优先兼容，当前脚本并不产出它。
 * - 产物布局：`development/output/agents/{name}/{vN}/`，恰好一个 agentName、最新 vN。
 *
 * `pipeline_status === COMPLETED` 通常只在 full 车道收尾时写；fast 车道通常不写
 * （optimize 实测会写 COMPLETED），因此完成判定按车道区分：COMPLETED 或 fast 收尾步都认。
 */

const PRODUCED_DIR = join('output', 'agents');
const WORK_DIR = join('.agent-genesis', 'work');
const STATE_FILE = 'orchestrator-state.yaml';
const VERSION_PATTERN = /^v(\d+)$/;

/** fast 车道的收尾步：create 收在 step-f1，optimize 收在 step-f2。 */
const FAST_FINAL_STEPS: readonly string[] = ['step-f1-fast-build', 'step-f2-fast-optimize'];

/** step_id 只接受文件名安全字符：它会被拼进门禁文件名。 */
const STEP_ID_PATTERN = /^[A-Za-z0-9._-]+$/;

/** 单个门禁文件里允许的 verdict；其余取值按「没有结论」处理。 */
const VERDICTS: readonly DeliveryVerdict[] = ['PASS', 'CONCERNS', 'FAIL'];

export interface ProducedAgent {
  agentName: string;
  version: string;
  /** 版本目录的绝对路径，即 runtime cwd。 */
  dir: string;
  /** 源树内最新的 mtime（含目录），用于判断是否需要重拷。 */
  mtimeMs: number;
}

interface OrchestratorState {
  file: string;
  /** 状态文件所在目录，即 `gate-results/` 的父目录。 */
  workDir: string;
  pipeline: string | null;
  status: string | null;
  currentStep: string | null;
  lastUpdate: string | null;
  retryCount: number | null;
  retryBudget: number | null;
  /** state.steps 里出现过的 step_id 数（去重；重试会重复追加同一步）。 */
  completedSteps: number;
}

interface DeliveryEvidence {
  verdict: DeliveryVerdict | null;
  /** 证据文件名（不含路径）。 */
  source: string;
  concerns: string[];
}

export interface ProductPeek {
  agent: ProducedAgent | null;
  /** 有产物目录但布局不可用时的人读原因；没有产物目录时也为 null。 */
  problem: string | null;
}

interface StatePick {
  state: OrchestratorState | null;
  workDir: string | null;
  /** 状态文件存在但无法唯一确定时的人读原因。 */
  problem: string | null;
}

export interface ProductionStatusOptions {
  /** development 实例是否有 pending / running 的 run；有则一律按「生成中」处理。 */
  hasActiveRun?: boolean;
}

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

/** 直接子目录名（不跟随符号链接），按名称排序保证确定性。 */
function subdirectories(path: string): string[] {
  return readdirSync(path, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** 源树最新 mtime：新增、删除与内容修改都会反映在某一层的目录 / 文件 mtime 上。 */
export function latestMtimeMs(path: string): number {
  let latest = lstatSync(path).mtimeMs;
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isDirectory()) {
      latest = Math.max(latest, latestMtimeMs(child));
    } else {
      latest = Math.max(latest, lstatSync(child).mtimeMs);
    }
  }
  return latest;
}

function compareVersion(a: string, b: string): number {
  const left = Number(VERSION_PATTERN.exec(a)![1]);
  const right = Number(VERSION_PATTERN.exec(b)![1]);
  return left === right ? a.localeCompare(b) : left - right;
}

/** agentName 下至少一个 `v*` 目录，取版本号最大的。 */
function pickVersion(agentDir: string): string {
  const versions = subdirectories(agentDir).filter((name) => VERSION_PATTERN.test(name));
  if (versions.length === 0) throw new ConflictError(`运行产物 ${agentDir} 下没有 v* 版本目录`);
  versions.sort(compareVersion);
  return versions[versions.length - 1]!;
}

/** 递归收集 work 目录下的 orchestrator-state.yaml。 */
function findStateFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...findStateFiles(path));
    } else if (entry.isFile() && entry.name === STATE_FILE) {
      found.push(path);
    }
  }
  return found.sort();
}

/** 只读顶层标量一行；不引入 YAML 依赖。 */
function readScalar(text: string, key: string): string | null {
  const match = new RegExp(`^${key}:\\s*['"]?([^'"\\s#]+)['"]?\\s*$`, 'm').exec(text);
  return match?.[1] ?? null;
}

function readNumber(text: string, key: string): number | null {
  const value = readScalar(text, key);
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function countSteps(text: string): number {
  const ids = new Set<string>();
  for (const match of text.matchAll(/^\s*-\s+step_id:\s*['"]?([^'"\s#]+)['"]?\s*$/gm)) {
    ids.add(match[1]!);
  }
  return ids.size;
}

function readState(file: string): OrchestratorState {
  const text = readFileSync(file, 'utf8');
  return {
    file,
    workDir: dirname(file),
    pipeline: readScalar(text, 'pipeline'),
    status: readScalar(text, 'pipeline_status'),
    currentStep: readScalar(text, 'current_step'),
    lastUpdate: readScalar(text, 'last_update'),
    retryCount: readNumber(text, 'total_retry_count'),
    retryBudget: readNumber(text, 'pipeline_retry_budget'),
    completedSteps: countSteps(text),
  };
}

/**
 * 选出一份状态文件。
 *
 * - 只有一个 → 直接用；
 * - 多个且已知 agentName → 只接受 `work/{agentName}/orchestrator-state.yaml`；
 * - 多个且无法唯一匹配 → `state = null` + `problem`，不做猜测。
 */
function pickState(developmentDir: string, agentName: string | null): StatePick {
  const workRoot = join(developmentDir, WORK_DIR);
  const workDirs = isDirectory(workRoot) ? subdirectories(workRoot) : [];
  const files = workDirs.length === 0 ? [] : findStateFiles(workRoot);
  const soleWorkDir = workDirs.length === 1 ? join(workRoot, workDirs[0]!) : null;

  if (files.length === 0) return { state: null, workDir: soleWorkDir, problem: null };
  if (files.length === 1) {
    const state = readState(files[0]!);
    return { state, workDir: state.workDir, problem: null };
  }

  const matched = agentName === null ? [] : files.filter((file) => basename(dirname(file)) === agentName);
  if (matched.length === 1) {
    const state = readState(matched[0]!);
    return { state, workDir: state.workDir, problem: null };
  }
  return { state: null, workDir: null, problem: `产物生产状态不唯一（${files.map((file) => file.replaceAll('\\', '/')).join('、')}）` };
}

/**
 * 只读定位产物：不抛业务错误，布局不唯一 / 缺失时 `agent = null`。
 *
 * 给「不需要就绪门禁、只想知道有没有产物目录」的调用方用（技能库扫描），
 * 免得为了列目录再造一套版本选择规则。运行门禁仍走 `locateProducedAgent`。
 */
export function peekProducedAgent(developmentDir: string): ProductPeek {
  const candidate = join(developmentDir, PRODUCED_DIR);
  if (!isDirectory(candidate)) return { agent: null, problem: null };

  const names = subdirectories(candidate);
  if (names.length === 0) return { agent: null, problem: '生成产物目录为空' };
  if (names.length !== 1) return { agent: null, problem: `生成产物目录必须恰好一个智能体目录，实际 ${names.length} 个` };

  const agentName = names[0]!;
  const agentDir = join(candidate, agentName);
  const versions = subdirectories(agentDir).filter((name) => VERSION_PATTERN.test(name));
  if (versions.length === 0) return { agent: null, problem: `生成产物 ${agentName} 下没有 v* 版本目录` };
  versions.sort(compareVersion);
  const version = versions[versions.length - 1]!;
  const dir = join(agentDir, version);
  return { agent: { agentName, version, dir, mtimeMs: latestMtimeMs(dir) }, problem: null };
}

/** 定位产物（布局错误抛 typed error），不检查完成度。 */
function locateProduct(developmentDir: string): ProducedAgent {
  const candidate = join(developmentDir, PRODUCED_DIR);
  if (!isDirectory(candidate)) {
    throw new NotFoundError(`运行产物（${developmentDir} 下未找到 ${PRODUCED_DIR}）`);
  }

  const names = subdirectories(candidate);
  if (names.length !== 1) {
    throw new ConflictError(`运行产物候选 ${candidate} 下必须恰好一个智能体目录，实际 ${names.length} 个`);
  }
  const agentName = names[0]!;
  const version = pickVersion(join(candidate, agentName));
  const dir = join(candidate, agentName, version);
  return { agentName, version, dir, mtimeMs: latestMtimeMs(dir) };
}

/** 车道：状态文件优先；状态缺失或版本漂移时按 gate-results 的证据文件反推。 */
function inferLane(state: OrchestratorState | null, workDir: string | null): ProductionLane | null {
  if (state?.pipeline === 'agent-creation-fast') return 'fast';
  if (state?.pipeline === 'agent-creation') return 'full';
  if (workDir === null) return null;

  const results = join(workDir, 'gate-results');
  if (FAST_FINAL_STEPS.some((step) => existsSync(join(results, `${step}.json`)))) return 'fast';
  if (existsSync(join(results, 'step-4-implementation.json')) || existsSync(join(results, 'g028-exit-sanity.json'))) {
    return 'full';
  }
  return null;
}

function toConcern(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of ['detail', 'message', 'ref', 'type']) {
      if (typeof record[key] === 'string') return record[key] as string;
    }
    return JSON.stringify(value);
  }
  return null;
}

function readVerdictFile(path: string): DeliveryEvidence | null {
  if (!existsSync(path)) return null;
  const source = basename(path);
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>;
    const raw = parsed.verdict;
    const verdict = typeof raw === 'string' && (VERDICTS as readonly string[]).includes(raw) ? (raw as DeliveryVerdict) : null;
    const concerns = Array.isArray(parsed.concerns)
      ? parsed.concerns.map(toConcern).filter((item): item is string => item !== null)
      : [];
    return { verdict, source, concerns: concerns.slice(0, 20) };
  } catch {
    return { verdict: null, source, concerns: [] };
  }
}

/**
 * 交付门禁证据。
 *
 * 优先 `current_step` 对应的 `gate-results/<step_id>.json`（技能统一按 step_id 落盘，
 * fast 的 create / optimize 各有一个收尾步）；该文件缺失时再按车道回落：
 * `g028-exit-sanity.json`（技能文档口径）→ full `step-4-implementation.json` /
 * fast `step-f1-fast-build.json`。只认第一个存在的文件，不合并多份 verdict。
 */
function readDelivery(
  workDir: string,
  lane: ProductionLane | null,
  currentStep: string | null,
): DeliveryEvidence | null {
  const results = join(workDir, 'gate-results');

  if (currentStep !== null && STEP_ID_PATTERN.test(currentStep)) {
    const current = readVerdictFile(join(results, `${currentStep}.json`));
    if (current !== null) return current;
  }

  const preferred = lane === 'fast'
    ? ['g028-exit-sanity.json', 'step-f1-fast-build.json', 'step-f2-fast-optimize.json', 'step-4-implementation.json']
    : lane === 'full'
      ? ['g028-exit-sanity.json', 'step-4-implementation.json', 'step-f1-fast-build.json']
      : ['g028-exit-sanity.json', 'step-4-implementation.json', 'step-f1-fast-build.json'];

  for (const name of preferred) {
    const evidence = readVerdictFile(join(results, name));
    if (evidence !== null) return evidence;
  }
  return null;
}

function isDeliveryOk(evidence: DeliveryEvidence | null): boolean {
  return evidence !== null && (evidence.verdict === 'PASS' || evidence.verdict === 'CONCERNS');
}

/** 是否 fast 车道的收尾步（create 的 step-f1 / optimize 的 step-f2）。 */
function isFastFinalStep(step: string | null): boolean {
  return step !== null && FAST_FINAL_STEPS.includes(step);
}

/** 流程已收尾：full 认 COMPLETED，fast 认收尾步（fast 驱动不写 COMPLETED）。 */
function isPipelineDone(state: OrchestratorState, lane: ProductionLane | null): boolean {
  return state.status === 'COMPLETED' || (lane === 'fast' && isFastFinalStep(state.currentStep));
}

function notReadyMessage(state: OrchestratorState, evidence: DeliveryEvidence | null): string {
  const status = state.status ?? '缺失';
  if (evidence === null) {
    return `产物生产未完成：pipeline_status=${status}，未找到交付门禁证据（需要流程结束且 PASS/CONCERNS）`;
  }
  if (evidence.verdict === null) {
    return `产物生产未完成：pipeline_status=${status}，${evidence.source} 缺少 verdict（需要 PASS/CONCERNS）`;
  }
  return `产物生产未完成：pipeline_status=${status}，交付门禁 ${evidence.source} 的 verdict 为 ${evidence.verdict}（需要 PASS/CONCERNS）`;
}

/** 门禁：产物布局 + 流程收尾 + 交付门禁；unready 时抛 NotFound / Conflict。 */
function requireReady(developmentDir: string, produced: ProducedAgent): void {
  const pick = pickState(developmentDir, produced.agentName);
  if (pick.state === null) {
    if (pick.problem !== null) throw new ConflictError(pick.problem);
    throw new NotFoundError(`产物生产未完成（${developmentDir} 下未找到 ${STATE_FILE}）`);
  }

  const lane = inferLane(pick.state, pick.state.workDir);
  const evidence = readDelivery(pick.state.workDir, lane, pick.state.currentStep);
  if (pick.state.status === 'BLOCKED' || pick.state.status === 'FAILED' || !isPipelineDone(pick.state, lane) || !isDeliveryOk(evidence)) {
    throw new ConflictError(notReadyMessage(pick.state, evidence));
  }
}

/** 定位并校验产物；preview / runtime / evaluation 的统一起跑门禁。 */
export function locateProducedAgent(developmentDir: string): ProducedAgent {
  const produced = locateProduct(developmentDir);
  requireReady(developmentDir, produced);
  return produced;
}

/** 只校验完成度（调用方自己已有产物定位时用）。 */
export function assertProductionReady(developmentDir: string): void {
  requireReady(developmentDir, locateProduct(developmentDir));
}

/**
 * 有没有生产过程痕迹：`.agent-genesis/work/` 下已经有工作目录。
 *
 * 技能一启动就会建这个目录（最早落盘的是 `env-readiness.yaml` 这类），比
 * `orchestrator-state.yaml` 早得多。服务重启 / run 被杀时可能只留下它 ——
 * 有痕迹就不能再报「未开始」。
 */
function hasWorkArtifacts(developmentDir: string): boolean {
  const workRoot = join(developmentDir, WORK_DIR);
  return isDirectory(workRoot) && subdirectories(workRoot).length > 0;
}

/**
 * 只读快照：永远不抛业务错误，等不开始时用 status / reasons 表达。
 *
 * 判定顺序（先命中先返回）：
 * 1. development 有活跃 run → building（重建期间不信任旧状态与旧产物）；
 * 2. 无状态、无产物、无门禁：有生产痕迹 → failed（生成中断）；毫无痕迹 → not_started；
 * 3. BLOCKED → blocked；FAILED / 门禁 FAIL → failed；
 * 4. 产物布局不完整、状态缺失或不唯一 → failed；
 * 5. 流程收尾 + 门禁 PASS/CONCERNS → completed；
 * 6. 其余 → building。
 */
export function readProductionStatus(
  developmentDir: string,
  options: ProductionStatusOptions = {},
): Omit<AgentProductionView, 'agentId'> {
  const productPeek = peekProducedAgent(developmentDir);
  const product = productPeek.agent;
  const pick = pickState(developmentDir, product?.agentName ?? null);
  const state = pick.state;
  const workDir = state?.workDir ?? pick.workDir;
  const lane = inferLane(state, workDir);
  const delivery = workDir === null ? null : readDelivery(workDir, lane, state?.currentStep ?? null);

  let status: AgentProductionStatus;
  let reasons: string[];

  if (options.hasActiveRun === true) {
    status = 'building';
    reasons = ['智能体正在生成中，请等待本次运行结束'];
  } else if (state === null && pick.problem === null && product === null && delivery === null) {
    // 状态文件通常比工作目录晚很多：中途被杀（服务重启 / run 失败）时只剩 work/。
    // 这时报「未开始」会让用户以为自己的输入丢了，按「开过工但没完成」处理。
    if (hasWorkArtifacts(developmentDir)) {
      status = 'failed';
      reasons = ['生成流程已开始但未完成，请重新发起生成'];
    } else {
      status = 'not_started';
      reasons = ['尚未开始生成智能体'];
    }
  } else if (state?.status === 'BLOCKED') {
    status = 'blocked';
    reasons = ['生成流程已暂停，等待处理'];
  } else if (state?.status === 'FAILED') {
    status = 'failed';
    reasons = ['生成流程失败'];
  } else if (delivery?.verdict === 'FAIL') {
    status = 'failed';
    reasons = ['生成产物未通过质量门禁'];
  } else if (product === null) {
    status = 'failed';
    reasons = [productPeek.problem ?? pick.problem ?? '生成产物缺失'];
  } else if (state === null) {
    status = 'failed';
    reasons = [pick.problem ?? '缺少生成过程状态，无法确认产物完成'];
  } else if (state.status === 'COMPLETED') {
    if (isDeliveryOk(delivery)) {
      status = 'completed';
      reasons = [];
    } else {
      status = 'failed';
      reasons = ['生成流程已结束，但交付门禁未通过'];
    }
  } else if (lane === 'fast' && isFastFinalStep(state.currentStep)) {
    if (isDeliveryOk(delivery)) {
      status = 'completed';
      reasons = [];
    } else if (delivery === null) {
      // current_step 已到收尾步、但门禁证据尚未落盘：仍在收尾，不当作完成
      status = 'building';
      reasons = ['智能体正在生成中'];
    } else {
      status = 'failed';
      reasons = ['生成流程已结束，但交付门禁未通过'];
    }
  } else {
    status = 'building';
    reasons = ['智能体正在生成中'];
  }

  return {
    status,
    ready: status === 'completed',
    lane,
    pipeline: state === null
      ? null
      : {
          status: state.status,
          currentStep: state.currentStep,
          completedSteps: state.completedSteps,
          lastUpdate: state.lastUpdate,
          retryCount: state.retryCount,
          retryBudget: state.retryBudget,
        },
    delivery: delivery === null
      ? null
      : { verdict: delivery.verdict, source: delivery.source, concerns: delivery.concerns },
    product: product === null
      ? null
      : {
          name: product.agentName,
          version: product.version,
          path: join(PRODUCED_DIR, product.agentName, product.version).replaceAll('\\', '/'),
          updatedAt: new Date(product.mtimeMs).toISOString(),
        },
    reasons,
  };
}
