import { readdirSync, statSync } from 'node:fs';
import { basename, dirname, join, relative } from 'node:path';
import type { AgentCommandItem, AgentSkillItem } from '../types/index.js';
import { listEnabledPluginCommands, listEnabledPluginSkills } from './plugin-skills.js';
import { parseSkillFrontmatter, readSkillFrontmatter, readSkillMdHead, skillMtime } from './skill-md.js';

/**
 * 智能体**可执行**清单：引擎在运行目录（`runtimeDir`）的 `.claude` 下会自动发现、
 * `/` 菜单里能真正调用的条目。
 *
 * ```
 * <runtimeDir>/.claude/skills/<目录名>/SKILL.md   → 技能，调用方式是 /<目录名>
 * <runtimeDir>/.claude/commands/ 下的 .md（含子目录） → 命令，调用方式是 /<文件名去 .md>
 * ```
 *
 * 口径（见 04-api/4.14-可执行技能与命令.md）：
 * - **只看 `runtimeDir`**：内置智能体是定义目录，普通智能体是 latest vN 产物；null 即「此刻没有
 *   可运行的目录」，两项都为空。与 preview / runtime 的起跑门禁同源，不另做一套就绪判定；
 * - **插件技能 / 命令 = 自己声明的 ∪ 产品运行时能力**：`drive@zte-ai-lab` 随产品按 user scope
 *   安装、引擎默认加载 user settings，所以每个智能体的会话都能调 `/drive:*`；其余用户自装插件
 *   （agent-genesis 等）是构建期工具，不列。技能只报 `user-invocable` 不为 false 的条目、
 *   命令报载荷 `commands/` 下的全部 `.md`，名字带插件前缀（如 `cosightbot:pkm`），
 *   与 `/` 菜单一致（见 plugin-skills.ts）；
 * - **不扫 development 工作台**：那是构建会话的目录，不是产物；
 * - 只返回元数据，不读命令正文。
 *
 * 与 `agent-skill.service.ts` 的「产物技能清单」不是一个视图：那边是管理面（缺 SKILL.md 的
 * 坏目录也要列出来才能删），这里只列引擎认得的条目。
 */

const SKILLS_DIR = join('.claude', 'skills');
const COMMANDS_DIR = join('.claude', 'commands');
const COMMAND_EXT = '.md';

export interface AgentExecutables {
  skills: AgentSkillItem[];
  commands: AgentCommandItem[];
}

/** 名称升序。用字节比较而不是 localeCompare：响应顺序不该随运行环境的 locale 变。 */
function byName(a: { name: string }, b: { name: string }): number {
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** `.claude/skills` 的直接子目录；目录不存在按空处理，其它错误照常抛给调用方降级。 */
function skillDirNames(skillsDir: string): string[] {
  let entries;
  try {
    entries = readdirSync(skillsDir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  return entries
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
    .map((entry) => entry.name)
    .sort();
}

/**
 * 可执行技能：`<root>/.claude/skills/<目录名>/`，且根部必须有一份 `SKILL.md`。
 *
 * 缺 `SKILL.md` 的目录不是技能（引擎不会发现它），直接跳过 —— 这也正是它与
 * `GET /agents/{id}/skills` 的唯一口径差异。
 */
export function listExecutableSkills(root: string): AgentSkillItem[] {
  const skillsDir = join(root, SKILLS_DIR);
  const items: AgentSkillItem[] = [];
  for (const dirName of skillDirNames(skillsDir)) {
    const skillDir = join(skillsDir, dirName);
    if (!isFile(join(skillDir, 'SKILL.md'))) continue;
    const updatedAt = skillMtime(skillDir);
    if (updatedAt === null) continue; // 并发删除：跳过该项，不整体失败

    const frontmatter = readSkillFrontmatter(skillDir, '');
    items.push({
      name: dirName,
      displayName: frontmatter.name?.trim() || dirName,
      description: frontmatter.description ?? '',
      version: frontmatter.version?.trim() ?? '',
      path: skillDir,
      updatedAt,
    });
  }
  return items.sort(byName);
}

/** 递归收集命令文件；子目录不存在按空处理，其它错误照常抛给调用方降级。 */
function collectCommandFiles(dir: string, found: string[]): void {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
    throw error;
  }
  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) collectCommandFiles(path, found);
    else if (entry.isFile() && entry.name.endsWith(COMMAND_EXT)) found.push(path);
  }
}

/**
 * 可执行命令：`<root>/.claude/commands/` 下的 `.md`（含子目录）。
 *
 * 命令名只取文件名：`commands/ci/build.md` 就是 `/build`，`ci` 只作为展示分组
 * （引擎的 `/help` 里写作 `(project:ci)`），**不生成 `ci:build`**。
 *
 * 不同子目录出现同名命令时按相对路径升序取第一个：同一个 `/<name>` 只有一个真正生效，
 * 清单里不该出现两个点了名字一样的项。
 */
export function listExecutableCommands(root: string): AgentCommandItem[] {
  const commandsDir = join(root, COMMANDS_DIR);
  const files: string[] = [];
  collectCommandFiles(commandsDir, files);
  files.sort();

  const seen = new Set<string>();
  const items: AgentCommandItem[] = [];
  for (const file of files) {
    const name = basename(file).slice(0, -COMMAND_EXT.length);
    if (name === '' || seen.has(name)) continue;
    const updatedAt = skillMtime(file);
    if (updatedAt === null) continue; // 并发删除：跳过该项，不整体失败
    seen.add(name);

    const head = readSkillMdHead(file);
    const frontmatter = head === null ? {} : parseSkillFrontmatter(head);
    items.push({
      name,
      namespace: relative(commandsDir, dirname(file)).replaceAll('\\', '/'),
      description: frontmatter.description ?? '',
      path: file,
      updatedAt,
    });
  }
  return items.sort(byName);
}

/**
 * 单类读取失败只让那一项退化为空并记日志，不把详情打成 500 ——
 * 与 `agent.service.ts` 里 `withDir` 对产物状态的降级口径一致。
 */
function degrade<T>(kind: string, root: string, read: (root: string) => T, empty: T): T {
  try {
    return read(root);
  } catch (error) {
    console.error(`[smart-factory] 读取可执行${kind}失败（${root}），按空清单处理：`, error);
    return empty;
  }
}

/**
 * 详情端点的可执行清单。`runtimeDir === null` 表示此刻没有可运行的目录；
 * 有目录但没 `.claude` 也是空数组，不是错误。
 */
export function scanExecutables(runtimeDir: string | null): AgentExecutables {
  if (runtimeDir === null) return { skills: [], commands: [] };
  // 目录自带的技能与插件技能合成一份：后者名字是 `plugin:skill`，
  // 只有该插件真装着才出现（见 plugin-skills.ts）。
  const skills = [
    ...degrade('技能', runtimeDir, listExecutableSkills, []),
    ...degrade('插件技能', runtimeDir, listEnabledPluginSkills, []),
  ].sort(byName);
  // 命令同理：产物自己的与插件带来的合成一份，后者名字是 `plugin:command`。
  const commands = [
    ...degrade('命令', runtimeDir, listExecutableCommands, []),
    ...degrade('插件命令', runtimeDir, listEnabledPluginCommands, []),
  ].sort(byName);
  return { skills, commands };
}
