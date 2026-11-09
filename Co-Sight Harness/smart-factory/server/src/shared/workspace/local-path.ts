import { realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute } from 'node:path';
import { BadRequestError, NotFoundError } from '../errors.js';
import { fetchWorkspaces } from '../framework/client.js';
import { builtinAgentsRoot } from './builtin-agents.js';

/**
 * 本机路径的解析与校验：这个绝对路径能不能用。
 *
 * 端侧形态下（前端与 Claude Code 同机）没有「上传附件」，发送框挂的就是一个本机路径。
 * 路径既然由服务端给出、又要进引擎的 prompt，就必须有一处统一判定 ——
 * `modules/fs`（列目录）与 `modules/session`（发送时校验附件）共用本文件，
 * 不各写一份，否则两边的口径迟早分叉。
 *
 * **浏览范围不设限**：整台机器上的目录都能浏览、都能选（用户自己的端侧机器、只读）。
 * 这里只校验形态（绝对路径、无 NUL）、存在性与类型。`localRoots()` 给的主目录 /
 * 工作区只是选择器里的**快捷入口**，不是边界。
 * 但仍先 realpath 再返回：字符串合法不代表落点合法，symlink 要解掉，
 * 后续按真实路径列表 / 校验才与用户看到的目录一致。
 */

export interface LocalRoot {
  label: string;
  /** 真实绝对路径（已解掉 symlink） */
  path: string;
  /** 该根对应的工作区 id；主目录为 null */
  workspaceId: string | null;
  /** 是否框架当前生效的工作区 */
  active: boolean;
}

/** 工作区是从框架现查的：缓存一小段时间，避免每列一层目录都打一次上游。 */
const ROOTS_TTL_MS = 15_000;
let rootsCache: { value: LocalRoot[]; expiresAt: number } | null = null;

/** 目录存在且可解析时给出真实路径；不存在 / 不是目录返回 null（调用方决定是跳过还是报错）。 */
function realDirectory(path: string): string | null {
  try {
    const real = realpathSync(path);
    return statSync(real).isDirectory() ? real : null;
  } catch {
    return null;
  }
}

/**
 * 选择器里的快捷入口：主目录 + 框架登记的工作区。
 *
 * 只是入口，不是可浏览范围的边界 —— 任意绝对路径都能列（见文件头）。
 * 框架不可达时**退化成只有主目录**，不把 502 抛给浏览器：选本机文件这件事
 * 不该因为上游挂了就做不了（同机、只读、用户自己的目录）。
 */
export async function localRoots(): Promise<LocalRoot[]> {
  const now = Date.now();
  if (rootsCache !== null && rootsCache.expiresAt > now) return rootsCache.value;

  const items: LocalRoot[] = [];

  const home = realDirectory(homedir());
  if (home !== null) {
    items.push({ label: '主目录', path: home, workspaceId: null, active: false });
  }

  // 内置智能体的定义根：内置 runtime 会话里选附件 / 浏览文件需要它进入白名单。
  // 注意不加裸 COSIGHT_HOME —— 那里有 .module-token 与数据库，不进任何浏览白名单。
  const builtinRoot = realDirectory(builtinAgentsRoot());
  if (builtinRoot !== null && !items.some((item) => item.path === builtinRoot)) {
    items.push({ label: '内置智能体', path: builtinRoot, workspaceId: null, active: false });
  }

  try {
    const list = await fetchWorkspaces();
    for (const workspace of list.items) {
      const directory = workspace.directory?.trim() ?? '';
      if (directory === '') continue;
      const real = realDirectory(directory);
      // 同一个目录只留一条（工作区目录本身位于主目录下是常态，但仍单独列出来当快捷入口）
      if (real === null || items.some((item) => item.path === real)) continue;
      items.push({
        label: `工作区：${workspace.name}`,
        path: real,
        workspaceId: workspace.id,
        active: workspace.id === list.activeId,
      });
    }
  } catch {
    // 上游不可用：只给主目录，见函数头
  }

  rootsCache = { value: items, expiresAt: now + ROOTS_TTL_MS };
  return items;
}

/**
 * 把入参解析成一个**可用的真实路径**。
 *
 * `kind` 决定最后一道校验：`dir` 要求是目录（浏览用），`file` 要求是文件（附件用）。
 * 路径不存在是 404 —— 与 artifacts 的口径一致：形态非法 400、合法但不存在 404。
 * 不检查是否落在主目录 / 工作区内：端侧整机可浏览，见文件头。
 */
export function resolveLocalTarget(input: unknown, kind: 'dir' | 'file'): string {
  if (typeof input !== 'string' || input.trim() === '') {
    throw new BadRequestError('path 必填');
  }
  if (input.includes('\u0000')) {
    throw new BadRequestError(`path 非法：${JSON.stringify(input)}`);
  }
  /*
   * `~/` 在这里展开：模型在正文里很爱写 `~/xxx`，而这一步只认绝对路径。
   * 展开放在服务端（而不是让前端拼）是因为主目录只有服务端知道；
   * 展开后的 realpath 仍会走下面同一条校验，软链不会因此绕过什么。
   */
  const expanded = input.replace(/^~(?=\/|$)/, homedir());
  // 相对路径在服务端没有确定基准，仍不收
  if (!isAbsolute(expanded)) {
    throw new BadRequestError(`path 必须是绝对路径：${JSON.stringify(input)}`);
  }

  let real: string;
  let stats;
  try {
    real = realpathSync(expanded);
    stats = statSync(real);
  } catch {
    throw new NotFoundError(`路径 ${input}`);
  }

  if (kind === 'dir' && !stats.isDirectory()) {
    throw new BadRequestError(`不是目录：${JSON.stringify(input)}`);
  }
  if (kind === 'file' && !stats.isFile()) {
    throw new BadRequestError(`不是文件：${JSON.stringify(input)}`);
  }

  return real;
}

/** 一轮最多带多少份本机文件：够用即可，别让一屏路径把 prompt 撑成清单。 */
export const ATTACHMENTS_MAX = 20;

/**
 * 附件入参 → 去重后的真实绝对路径。
 *
 * 每一项只需给一个绝对路径（也接受裸字符串，手写调试方便），两种形态在
 * `messages/send` 与 `agents/create` 的 `init.attachments` 上完全一致。
 * 校验统一走 `resolveLocalTarget`：存在、是文件 ——
 * 与文件选择器同一份实现，不能只信前端挑出来的路径。
 *
 * 同一路径重复出现只留一份：附件最终会拼进 prompt，重复列一遍纯属浪费上下文。
 * `what` 只用来拼报错措辞（`attachments` / `init.attachments`）。
 */
export async function resolveAttachmentPaths(value: unknown, what = 'attachments'): Promise<string[]> {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new BadRequestError(`${what} 必须是数组`, 'error.bad_request.attachments_array');
  if (value.length > ATTACHMENTS_MAX) {
    throw new BadRequestError(`${what} 最多 ${ATTACHMENTS_MAX} 项`, 'error.bad_request.attachments_max', { max: ATTACHMENTS_MAX });
  }

  const paths: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const raw = typeof item === 'string' ? item : (item as { path?: unknown } | null)?.path;
    const path = resolveLocalTarget(raw, 'file');
    if (seen.has(path)) continue;
    seen.add(path);
    paths.push(path);
  }
  return paths;
}
