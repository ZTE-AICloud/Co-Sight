import { lstatSync, readdirSync, readFileSync, realpathSync, statSync } from 'node:fs';
import type { Dirent, Stats } from 'node:fs';
import { basename, join, resolve, sep } from 'node:path';
import { config } from '../../config/index.js';
import { BadRequestError, ConflictError, NotFoundError, PayloadTooLargeError } from '../../shared/errors.js';
import { agentRoot, assertAgentId, assertRelativePath, stageDir } from '../../shared/workspace/dir-resolver.js';
import { locateProducedAgent } from '../../shared/workspace/materialize.js';
import { resolveAgentWorkspace } from '../../shared/workspace/workspace-resolver.js';
import type { ArtifactEntry, ArtifactFile, InstanceStage } from '../../shared/types/index.js';
import { requireEnum } from '../../shared/validate.js';

const STAGES = ['development', 'preview', 'runtime', 'evaluation'] as const satisfies readonly InstanceStage[];

interface ResolvedPath {
  root: string;
  dir: string;
}

/**
 * stage → 绝对根目录。
 *
 * development / preview / evaluation 是 agentRoot 的直接子目录；runtime 的根在开发产物里，
 * 按候选链与最新 vN 现算（与物化同一口径）。预览 / 评估这里只读，不触发物化。
 */
async function stageRootOf(input: { stage: unknown; agentId: unknown }): Promise<string> {
  const stage = requireEnum(input.stage, STAGES, 'stage');
  assertAgentId(input.agentId);

  const workspace = await resolveAgentWorkspace(input.agentId);
  // 内置智能体：runtime 的浏览根就是定义目录；其它阶段不存在（409 与 send 门禁同口径）
  if (workspace.source === 'builtin') {
    if (stage !== 'runtime') throw new ConflictError(`内置智能体只支持 runtime 阶段：${stage}`, 'error.conflict.builtin_agent', { agentId: input.agentId });
    return workspace.directory;
  }
  const root = agentRoot(workspace.directory, input.agentId);
  if (stage === 'runtime') return locateProducedAgent(stageDir(root, 'development')).dir;
  return stageDir(root, stage);
}

/**
 * 真实路径再校验一次：字符串合法不代表落点合法，symlink 可以把它带出 stage 根。
 * 路径不存在时交给后续的 stat / readdir 报 404。
 */
function assertRealPathInside(root: string, target: string, inputPath: unknown): void {
  let realRoot: string;
  let realTarget: string;
  try {
    realRoot = realpathSync(root);
    realTarget = realpathSync(target);
  } catch {
    return;
  }
  if (realTarget !== realRoot && !realTarget.startsWith(realRoot + sep)) {
    throw new BadRequestError(`path 非法：${JSON.stringify(inputPath)}`);
  }
}

/** 解析并守住边界：path 缺省根；resolve 后必须仍落在 stage 根内（与逐段校验双保险）。 */
async function resolveInsideRoot(input: { stage: unknown; agentId: unknown; path?: unknown }): Promise<ResolvedPath> {
  const root = await stageRootOf(input);

  let relative = '';
  if (input.path !== undefined && input.path !== '') {
    assertRelativePath(input.path);
    relative = input.path;
  }

  const dir = resolve(root, relative);
  if (dir !== root && !dir.startsWith(root + sep)) {
    throw new BadRequestError(`path 非法：${JSON.stringify(input.path)}`);
  }
  assertRealPathInside(root, dir, input.path);
  return { root, dir };
}

function statOr404(path: string, what: string): Stats {
  try {
    return statSync(path);
  } catch {
    throw new NotFoundError(what);
  }
}

/** 产物浏览服务：四个 stage 目录的只读视图，目录就是真相，不进库。 */
export const artifactService = {
  /** 列目录：目录项平铺返回，不分页（目录项由文件系统决定，前端整目录渲染）。 */
  async list(input: { stage: unknown; agentId: unknown; path?: unknown }): Promise<{ items: ArtifactEntry[]; total: number }> {
    const { root, dir } = await resolveInsideRoot(input);
    let dirents: Dirent[];
    try {
      dirents = readdirSync(dir, { withFileTypes: true });
    } catch {
      throw new NotFoundError(`目录 ${dir === root ? '（根）' : String(input.path)}`);
    }

    const items = dirents
      .map((dirent): ArtifactEntry => {
        const entryPath = join(dir, dirent.name);
        // lstat：目录项本身是 symlink 时只报链接自身信息，不跟随到根外
        const stats = lstatSync(entryPath);
        return {
          name: dirent.name,
          type: dirent.isDirectory() ? 'dir' : 'file',
          size: dirent.isDirectory() ? 0 : stats.size,
          mtime: stats.mtime.toISOString(),
        };
      })
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });

    return { items, total: items.length };
  },

  /** 读文本文件：仅 utf-8，超上限 413，下载不受限。 */
  async file(input: { stage: unknown; agentId: unknown; path: unknown }): Promise<ArtifactFile> {
    if (input.path === undefined || input.path === null || input.path === '') {
      throw new BadRequestError('path 必填');
    }
    const { dir } = await resolveInsideRoot(input);
    const stats = statOr404(dir, `文件 ${String(input.path)}`);
    if (!stats.isFile()) throw new NotFoundError(`文件 ${String(input.path)}`);
    if (stats.size > config.artifactMaxFileBytes) {
      throw new PayloadTooLargeError(`文件 ${String(input.path)} 超过大小上限 ${config.artifactMaxFileBytes} 字节`);
    }
    return {
      name: basename(dir),
      size: stats.size,
      mtime: stats.mtime.toISOString(),
      content: readFileSync(dir, 'utf8').replace(/^\uFEFF/, ''),
    };
  },

  /** 下载：返回绝对路径与文件名，raw 流由 controller 负责。 */
  async download(input: { stage: unknown; agentId: unknown; path: unknown }): Promise<{ absolutePath: string; fileName: string }> {
    if (input.path === undefined || input.path === null || input.path === '') {
      throw new BadRequestError('path 必填');
    }
    const { dir } = await resolveInsideRoot(input);
    const stats = statOr404(dir, `文件 ${String(input.path)}`);
    if (!stats.isFile()) throw new NotFoundError(`文件 ${String(input.path)}`);
    return { absolutePath: dir, fileName: basename(dir) };
  },
};
