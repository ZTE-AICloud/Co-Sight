import { readdirSync, readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, isAbsolute, join } from 'node:path';
import type { AgentCommandItem, AgentSkillItem } from '../types/index.js';
import { parseSkillFrontmatter, readSkillFrontmatter, readSkillMdHead, skillMtime } from './skill-md.js';

/**
 * 智能体的插件可执行物（技能 + 斜杠命令）：**自己声明的** ∪ **产品运行时能力**。
 *
 * 1. 自己声明：运行目录 `.claude/settings.json` 的 `enabledPlugins` 打开的插件；
 * 2. 产品运行时能力 `drive@zte-ai-lab`：随产品按 user scope 安装，引擎默认加载 user settings
 *    （不传 `settingSources`），所以**每个**智能体的会话都能调 `/drive:*`。清单只看「自己声明」
 *    会漏掉它们 —— 用户智能体的目录里没有这份 settings，但它们确实可用。
 *    显式写 `false` / `null` 的仍以关闭为准：智能体目录优先，其次是用户 settings。
 *
 * 其余用户自装插件（`agent-genesis` / `goldeval` / `skill-optimizer`）不列：它们是构建期工具，
 * 不是运行时能力，而且随机器而异。名单按引擎的注册方式写成 `plugin:skill` / `plugin:command`
 * （如 `cosightbot:pkm`）。
 *
 * 插件载荷里两种东西各扫一个目录：
 *
 * ```
 * <installPath>/skills/<目录名>/SKILL.md   → plugin:skill
 * <installPath>/commands/ 下的 .md（含子目录） → plugin:command
 * ```
 *
 * 只列 `/` 菜单里点得到的技能：SKILL.md 显式写 `user-invocable: false` 的跳过
 * （drive 2.3.4 的 17 个里只有 5 个可点，其余是流水线内部子技能）；命令没有这个开关。
 *
 * 插件载荷的登记文件在用户环境里（`{CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json`），
 * 只读不写；插件没装、登记缺失或清单不可读都不列 —— 「可执行」只报此刻真能调用到的东西。
 */

/** 产品运行时能力：随产品安装、所有智能体的会话都带着的插件。 */
const PRODUCT_PLUGIN_IDS = ['drive@zte-ai-lab'] as const;

/** 插件命令的扩展名；与项目命令（`executables.ts`）同一约定。 */
const COMMAND_EXT = '.md';

/** Claude Code 配置目录：服务与引擎同用户，尊重 `CLAUDE_CONFIG_DIR`。 */
function claudeConfigDir(): string {
  const configured = process.env.CLAUDE_CONFIG_DIR?.trim();
  return configured !== undefined && configured !== '' ? configured : join(homedir(), '.claude');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** `enabledPlugins` 的值算不算「打开」：false / null 是显式关闭，数组与对象是带约束的打开写法。 */
function isEnabled(value: unknown): boolean {
  if (value === false || value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (isRecord(value)) return Object.keys(value).length > 0;
  return value === true;
}

/** 某份 settings 里的 `enabledPlugins`；读不到 / 形状不对都按空处理。 */
function enabledPluginsOf(settingsFile: string): Record<string, unknown> {
  let settings: unknown;
  try {
    settings = JSON.parse(readFileSync(settingsFile, 'utf8'));
  } catch {
    return {};
  }
  return isRecord(settings) && isRecord(settings.enabledPlugins) ? settings.enabledPlugins : {};
}

/** 生效的插件 id（`plugin@marketplace`）：自己声明的 ∪ 产品运行时能力；显式关闭的不算。 */
export function enabledPluginIds(runtimeDir: string): string[] {
  const runtime = enabledPluginsOf(join(runtimeDir, '.claude', 'settings.json'));
  const user = enabledPluginsOf(join(claudeConfigDir(), 'settings.json'));

  const ids = new Set(
    Object.entries(runtime)
      .filter(([id, value]) => isEnabled(value) && id.includes('@') && !id.startsWith('@'))
      .map(([id]) => id),
  );
  for (const id of PRODUCT_PLUGIN_IDS) {
    // 项目层压过用户层；两层都没写 = 产品默认打开
    const value = id in runtime ? runtime[id] : user[id];
    if (value === undefined || isEnabled(value)) ids.add(id);
  }
  return [...ids];
}

/** 已安装插件的载荷目录：优先取登记在**这个定义目录**上的那条，否则取第一条。 */
function installedPluginPath(id: string, runtimeDir: string): string | null {
  let registry: unknown;
  try {
    registry = JSON.parse(readFileSync(join(claudeConfigDir(), 'plugins', 'installed_plugins.json'), 'utf8'));
  } catch {
    return null;
  }
  if (!isRecord(registry) || !isRecord(registry.plugins)) return null;

  const entries = registry.plugins[id];
  if (!Array.isArray(entries)) return null;
  const records = entries.filter(isRecord);
  const match = records.find((entry) => entry.projectPath === runtimeDir) ?? records[0];
  const installPath = match?.installPath;
  return typeof installPath === 'string' && isAbsolute(installPath) ? installPath : null;
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** 插件载荷里的技能：`<installPath>/skills/<目录名>/SKILL.md`，名字带插件前缀。 */
function skillsOf(installPath: string, plugin: string): AgentSkillItem[] {
  const skillsDir = join(installPath, 'skills');
  let entries;
  try {
    entries = readdirSync(skillsDir, { withFileTypes: true });
  } catch {
    return []; // 插件没带技能（或目录不可读）：它不是错误
  }

  const items: AgentSkillItem[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const dir = join(skillsDir, entry.name);
    if (!isFile(join(dir, 'SKILL.md'))) continue;
    const updatedAt = skillMtime(dir);
    if (updatedAt === null) continue; // 并发卸载：跳过该项，不整体失败

    const frontmatter = readSkillFrontmatter(dir, '');
    if (frontmatter.userInvocable === false) continue; // 流水线内部子技能，`/` 菜单里点不到
    items.push({
      name: `${plugin}:${entry.name}`,
      displayName: frontmatter.name?.trim() || entry.name,
      description: frontmatter.description ?? '',
      version: frontmatter.version?.trim() ?? '',
      path: dir,
      updatedAt,
    });
  }
  return items;
}

/** 生效插件里此刻真装着的、`/` 菜单点得到的技能。 */
export function listEnabledPluginSkills(runtimeDir: string): AgentSkillItem[] {
  const items: AgentSkillItem[] = [];
  for (const id of enabledPluginIds(runtimeDir)) {
    const installPath = installedPluginPath(id, runtimeDir);
    if (installPath === null) continue;
    items.push(...skillsOf(installPath, id.slice(0, id.indexOf('@'))));
  }
  return items;
}

/** 递归收集命令文件；子目录不存在按空处理（插件没带命令不是错误）。 */
function commandFiles(dir: string, found: string[]): void {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) commandFiles(path, found);
    else if (entry.isFile() && entry.name.endsWith(COMMAND_EXT)) found.push(path);
  }
}

/**
 * 插件载荷里的命令：`<installPath>/commands/` 下的 `.md`（含子目录），名字带插件前缀。
 *
 * 命令名取文件名、插件前缀才是 `/` 菜单里的真名：`commands/pkm.md` 在装了
 * `cosightbot@cosight-bot` 的机器上就是 `/cosightbot:pkm`。同名命令（不同子目录）
 * 按路径升序取第一个；`namespace` 记插件名，只用于展示「来自哪个插件」。
 */
function commandsOf(installPath: string, plugin: string): AgentCommandItem[] {
  const commandsDir = join(installPath, 'commands');
  const files: string[] = [];
  commandFiles(commandsDir, files);
  files.sort();

  const seen = new Set<string>();
  const items: AgentCommandItem[] = [];
  for (const file of files) {
    const base = basename(file).slice(0, -COMMAND_EXT.length);
    if (base === '') continue;
    const name = `${plugin}:${base}`;
    if (seen.has(name)) continue;
    const updatedAt = skillMtime(file);
    if (updatedAt === null) continue; // 并发卸载：跳过该项，不整体失败
    seen.add(name);

    const head = readSkillMdHead(file);
    const frontmatter = head === null ? {} : parseSkillFrontmatter(head);
    items.push({
      name,
      namespace: plugin,
      description: frontmatter.description ?? '',
      path: file,
      updatedAt,
    });
  }
  return items;
}

/** 名称升序；与项目命令同一口径（字节比较，响应顺序不随 locale 变）。 */
function byName(a: { name: string }, b: { name: string }): number {
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/** 生效插件里此刻真装着的、`/` 菜单点得到的命令。 */
export function listEnabledPluginCommands(runtimeDir: string): AgentCommandItem[] {
  const items: AgentCommandItem[] = [];
  for (const id of enabledPluginIds(runtimeDir)) {
    const installPath = installedPluginPath(id, runtimeDir);
    if (installPath === null) continue;
    items.push(...commandsOf(installPath, id.slice(0, id.indexOf('@'))));
  }
  return items.sort(byName);
}
