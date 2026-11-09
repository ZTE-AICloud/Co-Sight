import { cpSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { NotFoundError } from '../errors.js';
import type { InstanceStage } from '../types/index.js';
import { stageDir, stateDir } from './dir-resolver.js';
import { latestMtimeMs, locateProducedAgent } from './production.js';

/**
 * preview / evaluation 物化。
 *
 * 源定位与完成判定在 production.ts（产物布局 + 生产过程状态 + 交付门禁）；
 * 本文件只负责拷贝与 mtime 标记：源最新 mtime 未变则跳过，变了整体重拷。
 */

export { locateProducedAgent };
export type { ProducedAgent } from './production.js';

/** 标记格式版本：1 = evaluation 副本平铺在沙箱根（旧布局）；2 = 副本收在 `agent/` 下。 */
type MarkerVersion = 1 | 2;

interface MaterializeMarker {
  /** 格式变化时旧标记自然失效，触发一次重拷；evaluation 的 1→2 走保留报告的就地升级。 */
  version: MarkerVersion;
  source: string;
  mtimeMs: number;
}

export interface EnsureResult {
  target: string;
  source: string;
  skipped: boolean;
}

/**
 * 评估沙箱里被测副本的目录名；评估报告目录（`e2e-test-*` / `eval_results`）与它同级。
 *
 * 评估工具要求「产物目录在被测目录之外」（runner 会把被测目录整棵复制进每条用例的
 * workspace，套在一起会递归），服务端又要求报告落在沙箱根下。把副本收进 `agent/`
 * 是唯一能同时满足两边的布局：cwd 是 `<evaluation>/agent/`，报告是
 * `<evaluation>/e2e-test-*`。
 */
const EVALUATION_AGENT_DIRNAME = 'agent';

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function markerPath(agentRootDir: string, stage: 'preview' | 'evaluation'): string {
  return join(stateDir(agentRootDir), `${stage}.json`);
}

/** 各阶段的当前标记版本；evaluation 升到 2 是为了识别并升级平铺旧布局。 */
function markerVersion(stage: 'preview' | 'evaluation'): MarkerVersion {
  return stage === 'evaluation' ? 2 : 1;
}

function readMarker(path: string): MaterializeMarker | null {
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8')) as Partial<MaterializeMarker>;
    if (parsed.version === 1 || parsed.version === 2) {
      if (typeof parsed.source === 'string' && typeof parsed.mtimeMs === 'number') {
        return { version: parsed.version, source: parsed.source, mtimeMs: parsed.mtimeMs };
      }
    }
  } catch {
    // 缺失或损坏都按「没有标记」处理，下一次整体重拷
  }
  return null;
}

interface MaterializeSource {
  agentRoot: string;
  stage: 'preview' | 'evaluation';
  source: string;
  sourceMtimeMs: number;
}

/** 评估沙箱根下不是被测副本的项：报告目录必须原地保留。 */
function isEvaluationReportEntry(name: string): boolean {
  return name.startsWith('e2e-test-') || name === 'eval_results';
}

/** 清掉沙箱根下除评估报告以外的一切（旧布局的平铺副本、半成品等）。 */
function removeNonReportEntries(stageRoot: string): void {
  for (const name of readdirSync(stageRoot)) {
    if (isEvaluationReportEntry(name)) continue;
    rmSync(join(stageRoot, name), { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
}

/**
 * 物化目标：preview 就是沙箱根本身；evaluation 把副本收进 `agent/`，沙箱根让给评估报告。
 */
function materializeTarget(agentRootDir: string, stage: 'preview' | 'evaluation'): string {
  const root = stageDir(agentRootDir, stage);
  return stage === 'evaluation' ? join(root, EVALUATION_AGENT_DIRNAME) : root;
}

/** 源变了才清空目标并整体拷贝，源未变且目标存在则跳过。 */
function materializeFrom(input: MaterializeSource): EnsureResult {
  const stageRoot = stageDir(input.agentRoot, input.stage);
  const target = materializeTarget(input.agentRoot, input.stage);
  const marker = markerPath(input.agentRoot, input.stage);
  const version = markerVersion(input.stage);

  const existing = readMarker(marker);
  const sourceUnchanged =
    existing !== null && existing.source === input.source && existing.mtimeMs === input.sourceMtimeMs;
  if (sourceUnchanged && existing.version === version && isDirectory(target)) {
    return { target, source: input.source, skipped: true };
  }

  // evaluation 旧标记是平铺布局：源没变时只重置副本，报告原地保留；
  // 源变了仍按「旧报告属于旧源版本」整根清掉。
  const upgrading = sourceUnchanged && input.stage === 'evaluation' && isDirectory(stageRoot);

  // Windows 上文件可能被短暂占用（EBUSY/EPERM），留给内核几轮释放时间
  rmSync(marker, { force: true });
  if (upgrading) {
    removeNonReportEntries(stageRoot);
  } else {
    rmSync(stageRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
  mkdirSync(target, { recursive: true });
  cpSync(input.source, target, { recursive: true });

  mkdirSync(stateDir(input.agentRoot), { recursive: true });
  const markerBody: MaterializeMarker = { version, source: input.source, mtimeMs: input.sourceMtimeMs };
  writeFileSync(marker, JSON.stringify(markerBody));
  return { target, source: input.source, skipped: false };
}

/**
 * 清空某个阶段的沙箱（连物化标记一起删），下一次 ensure 必然整体重拷。
 *
 * 「重新开始预览」/「重新评估」的语义是「拿当前产物重建沙箱」，而不是「源没变就继续用
 * 旧的」；跳过物化的判据（源 mtime 未变）在这两个动作面前是错的。评估的旧报告
 * （`e2e-test-*` / `eval_results/`）就在沙箱根下，一并删掉 —— 它们属于上一轮产物。
 */
export function resetStage(agentRootDir: string, stage: 'preview' | 'evaluation'): void {
  rmSync(stageDir(agentRootDir, stage), { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  rmSync(markerPath(agentRootDir, stage), { force: true });
}

/**
 * run 前 ensure：preview 从 development 产物拷贝，evaluation 从 preview 拷贝。
 * 返回的 `target` 是会话 cwd（evaluation 是 `<evaluation>/agent/`，见 `materializeTarget`）。
 *
 * 标记先删、拷贝成功后再写回：拷贝中途失败时下一轮不会误判为已同步。
 */
export function ensureMaterialized(input: { agentRoot: string; stage: 'preview' | 'evaluation' }): EnsureResult {
  if (input.stage === 'evaluation') {
    const preview = ensureMaterialized({ agentRoot: input.agentRoot, stage: 'preview' });
    return materializeFrom({
      ...input,
      source: preview.target,
      sourceMtimeMs: latestMtimeMs(preview.target),
    });
  }

  const produced = locateProducedAgent(stageDir(input.agentRoot, 'development'));
  return materializeFrom({ ...input, source: produced.dir, sourceMtimeMs: produced.mtimeMs });
}

/**
 * 起 run 时的阶段 cwd：
 *
 * - development：目录必须已存在，缺失报错，不重建；
 * - runtime：原地使用最新 vN 产物目录；
 * - preview：先 ensure，cwd 就是 `<preview>/`；
 * - evaluation：先 ensure，cwd 是收在沙箱根下的副本 `<evaluation>/agent/`。
 */
export function resolveStageCwd(agentRootDir: string, stage: InstanceStage): string {
  if (stage === 'runtime') return locateProducedAgent(stageDir(agentRootDir, 'development')).dir;

  const dir = stageDir(agentRootDir, stage);
  if (stage === 'development') {
    if (!isDirectory(dir)) throw new NotFoundError(`开发目录 ${dir}`);
    return dir;
  }

  // 目录实例（agentId 为 null）没有阶段产物、不参与物化；resolveRunSetup 已按 agentId 提前分流，
  // 本函数只会收到智能体实例的 stage（development / preview / runtime / evaluation）。
  return ensureMaterialized({ agentRoot: agentRootDir, stage }).target;
}
