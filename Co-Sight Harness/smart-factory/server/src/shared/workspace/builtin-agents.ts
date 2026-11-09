import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { config } from '../../config/index.js';
import { DEFAULT_ICON, isReservedTag, readDescription, readIcon, readName, readTags } from '../../modules/agent/agent-fields.js';
import { isAgentId } from './dir-resolver.js';

/**
 * 内置智能体的定义目录（「目录即专家」）。
 *
 * 定义根固定在 `{COSIGHT_HOME}/smart-factory/builtin-agents/{id}/`，与工作区产物目录完全分离：
 * 里面是随产品分发的专家目录（CLAUDE.md + .claude/skills + runtime + data/），
 * runtime 会话直接以定义目录为 cwd，开发 / 预览 / 评估三条产物生产线对内置智能体不存在。
 *
 * 本模块只认识盘上的目录与清单，不碰数据库；登记（seed / 清理）在 agent.service.seedBuiltinAgents。
 */

/** 定义根：`{COSIGHT_HOME}/smart-factory/builtin-agents`。只拼路径，不查存在性。 */
export function builtinAgentsRoot(): string {
  return join(config.cosightHome, 'smart-factory', 'builtin-agents');
}

/** 内置智能体的定义目录 = runtime cwd。id 参与路径拼接，先过形态校验（与 agentRoot 同一边界）。 */
export function builtinAgentDir(agentId: string): string {
  if (!isAgentId(agentId)) {
    throw new TypeError(`内置智能体 id 形态非法：${JSON.stringify(agentId)}`);
  }
  return join(builtinAgentsRoot(), agentId);
}

/** agent.json 清单：内置行的元数据权威（boot seed 按它登记与刷新）。 */
export interface BuiltinManifest {
  name: string;
  description: string;
  tags: string[];
  icon: string;
}

/** 清单文件名，固定放在定义目录根部。 */
const MANIFEST_FILENAME = 'agent.json';

/**
 * 扫描定义根，返回通过校验的内置智能体（id = 目录名）。
 *
 * - 只看**直接子目录**，跳过隐藏目录与过不了 `isAgentId` 的目录名；
 * - 没有 `agent.json`、清单不是 JSON 对象、含未知字段、字段过不了校验 → `console.warn` 跳过该目录，
 *   **不抛**：一颗脏定义目录不该挡住整个启动（与收养「跳过不阻塞」同口径）；
 * - tags 里的保留标签（`内置` / `自定义`）会被剥掉并告警 —— 来源由 `source` 字段表达，
 *   不是清单的一部分。剥而不是跳过，免得一颗过时的标签让整个专家从列表里消失。
 */
export function scanBuiltinAgents(): { id: string; dir: string; manifest: BuiltinManifest }[] {
  const root = builtinAgentsRoot();
  let entries;
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return []; // 定义根不存在（没同步过内置智能体）= 特性整体缺席，静默返回
  }

  const found: { id: string; dir: string; manifest: BuiltinManifest }[] = [];
  for (const entry of entries) {
    const id = entry.name;
    if (!entry.isDirectory() || id.startsWith('.') || !isAgentId(id)) continue;

    const dir = join(root, id);
    try {
      const manifest = readManifest(dir);
      found.push({ id, dir, manifest });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      console.warn(`[smart-factory] 内置智能体跳过：${id}：${reason}`);
    }
  }
  return found;
}

/** 清单允许的字段；多一个都算脏清单（协议明确，不做宽松合并）。 */
const MANIFEST_FIELDS = ['name', 'description', 'tags', 'icon'] as const;

/** 读单个定义目录的清单并校验。任何问题都抛错，由 scanBuiltinAgents 统一告警跳过。 */
function readManifest(dir: string): BuiltinManifest {
  const file = join(dir, MANIFEST_FILENAME);
  if (!existsSync(file)) throw new Error(`缺清单 ${MANIFEST_FILENAME}`);

  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'));
  } catch (error) {
    throw new Error(`${MANIFEST_FILENAME} 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${MANIFEST_FILENAME} 必须是对象`);
  }
  const record = parsed as Record<string, unknown>;
  const unknownFields = Object.keys(record).filter((key) => !(MANIFEST_FIELDS as readonly string[]).includes(key));
  if (unknownFields.length > 0) {
    throw new Error(`${MANIFEST_FILENAME} 含未知字段：${unknownFields.join(' / ')}（只支持 name / description / tags / icon）`);
  }

  const name = readName(record.name);
  const description = readDescription(record.description ?? '');
  // 保留标签先剥掉再走通用校验：清单作者把它写进 tags 是过时写法，不该因此丢掉整个定义目录
  const rawTags = record.tags ?? [];
  const strippedTags = Array.isArray(rawTags)
    ? rawTags.filter((tag) => typeof tag !== 'string' || !isReservedTag(tag.trim()))
    : rawTags;
  const removed = Array.isArray(rawTags) ? rawTags.length - (strippedTags as unknown[]).length : 0;
  if (removed > 0) {
    console.warn(`[smart-factory] 内置清单 ${file} 的 tags 含保留标签，已忽略 ${removed} 个（来源由 source 字段表达）`);
  }
  const tags = readTags(strippedTags);
  const icon = readIcon(record.icon ?? DEFAULT_ICON);

  return { name, description, tags, icon };
}
