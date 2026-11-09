import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { builtinAgentsRoot } from './builtin-agents.js';
import { isAgentId } from './dir-resolver.js';

/**
 * 随模块分发的内置专家定义：`<server>/builtin-agents/{id}/`，boot 时同步进定义根。
 *
 * 与「部署方自己放目录」并不冲突：定义根仍是唯一权威（boot seed 只扫它），
 * 本模块只负责把**随包**的那几颗专家补齐到定义根，好让任意一台机器装完就显示。
 * 源目录随产物包分发（`bundle.include` 含 `server/builtin-agents`），dev 与产物两种布局
 * 都从 server 根解析，路径一致。
 *
 * 同步口径（与 seed 的「不挡启动」同源）：
 * - 只处理**直接子目录**且名字过 `isAgentId`、根部带 `agent.json` 的；隐藏目录 / 非法 id 跳过；
 * - 只写定义文件：目标端已有的 `data/` `workspace/` `.drive/`（及 `.venv` `node_modules` `.git`）
 *   一律不碰 —— 那是专家自己的运行数据，重建会丢用户的项目与流程状态；
 * - 内容相同就不写（`tsx watch` 每次热重启都跑一遍，不该无意义地刷 mtime）；
 * - 源端删掉的文件不会在目标端删除（不做破坏性镜像）；
 * - 单目录失败只告警，不抛：一颗脏定义不该挡住整个启动。
 */

/** 定义源根：`<server>/builtin-agents`。只拼路径，不查存在性。 */
export function bundledBuiltinRoot(): string {
  return fileURLToPath(new URL('../../../builtin-agents/', import.meta.url));
}

/** 目标端由专家自己维护的运行数据：同步时整棵跳过，不覆盖也不删除。 */
const RUNTIME_DATA_ENTRIES = new Set(['data', 'workspace', '.drive', '.venv', 'node_modules', '.git']);

export interface BundledSyncResult {
  /** 实际写入了文件的专家 id → 写入的文件数；内容未变的专家文件数为 0。 */
  synced: { id: string; files: number }[];
  /** 源端有目录但没同步的 id（缺清单等），用于日志与排查。 */
  skipped: string[];
}

/** 内容相同就不写：返回值表示"目标端已是最新"。读失败（不存在 / 是目录）一律算需要写。 */
function isUpToDate(source: string, target: string): boolean {
  try {
    return statSync(target).isFile() && readFileSync(source).equals(readFileSync(target));
  } catch {
    return false;
  }
}

/** 递归同步目录树；`topLevel` 时跳过运行数据目录。返回实际写入的文件数。 */
function syncTree(sourceDir: string, targetDir: string, topLevel: boolean): number {
  mkdirSync(targetDir, { recursive: true });

  let files = 0;
  for (const entry of readdirSync(sourceDir, { withFileTypes: true })) {
    if (topLevel && RUNTIME_DATA_ENTRIES.has(entry.name)) continue;

    const source = join(sourceDir, entry.name);
    const target = join(targetDir, entry.name);
    if (entry.isDirectory()) {
      files += syncTree(source, target, false);
    } else if (entry.isFile() && !isUpToDate(source, target)) {
      cpSync(source, target, { force: true });
      files += 1;
    }
  }
  return files;
}

/**
 * 把随包的内置专家定义同步到定义根（幂等）。`sourceRoot` 只给测试注入用。
 *
 * 源根不存在 = 这份模块没带内置专家（或被人为裁掉），静默返回空：特性缺席，不挡启动。
 */
export function syncBundledBuiltinAgents(sourceRoot: string = bundledBuiltinRoot()): BundledSyncResult {
  const result: BundledSyncResult = { synced: [], skipped: [] };

  let entries;
  try {
    entries = readdirSync(sourceRoot, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      console.warn(`[smart-factory] 读取内置专家定义源失败（${sourceRoot}），跳过同步：`, error);
    }
    return result;
  }

  for (const entry of entries) {
    const id = entry.name;
    if (!entry.isDirectory() || id.startsWith('.') || !isAgentId(id)) continue;

    const source = join(sourceRoot, id);
    if (!existsSync(join(source, 'agent.json'))) {
      result.skipped.push(id);
      console.warn(`[smart-factory] 内置专家定义跳过：${id}：缺 agent.json`);
      continue;
    }

    try {
      const files = syncTree(source, join(builtinAgentsRoot(), id), true);
      result.synced.push({ id, files });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      console.warn(`[smart-factory] 内置专家定义同步失败：${id}：${reason}`);
    }
  }
  return result;
}
