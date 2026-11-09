import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { config } from '../../config/index.js';
import { detectSkillVersion, readSkillFrontmatter, skillMtime } from '../../shared/skills/skill-md.js';
import { agentsRepo } from '../../shared/store/agents.repo.js';
import { peekProducedAgent } from '../../shared/workspace/production.js';
import { agentRoot, resolveWorkspaceDirectory } from '../../shared/workspace/workspace-resolver.js';
import { optionalString, readWorkspaceId } from '../../shared/validate.js';

/**
 * 技能库扫描（10-skill-library.md §4）。一次请求内完成，不落库。
 *
 * 三路来源：技能库 `{skillsRoot}/output/skills/*`（全局共享）+ 当前工作区
 * `source=user` 智能体的 `<agent.dir>/development/output/skills/*`（智能体产出的独立技能）
 * + 同一智能体当前产物 `<product>/.claude/skills/*`（构建自带 / 装配进来的技能）。
 * `{skillsRoot}/.agent-genesis/` 是 skill-foundry 的过程目录，不在扫描面内；
 * `preview` / `evaluation` 里的 `.claude/skills` 是物化副本，不扫（否则同一技能会出现多次）。
 */

export type SkillSource = 'library' | 'agent';

export interface SkillItem {
  /** frontmatter name，缺失回落目录名 */
  name: string;
  /** 技能目录绝对路径（不是版本目录） */
  path: string;
  source: SkillSource;
  /** library 恒 null */
  ownerAgentId: string | null;
  ownerName: string | null;
  /** `v<数字>` 子目录按数字取最大；没有则空串 */
  version: string;
  /** frontmatter description，缺失/解析失败为空串 */
  description: string;
  /** 技能目录 mtime 的 ISO 串 */
  updatedAt: string;
}

export interface SkillList {
  /** 技能库目录 = `{skillsRoot}/output/skills`，前端不拼路径 */
  root: string;
  /** 工坊会话 cwd = `{skillsRoot}`，创建目录会话时原样传给 sessions/create */
  cwd: string;
  items: SkillItem[];
}

/** 组内排序：updatedAt 倒序，同毫秒按 name 升序兜底（ISO 串字典序即时间序）。 */
function byRecencyDesc(a: SkillItem, b: SkillItem): number {
  if (a.updatedAt !== b.updatedAt) return a.updatedAt > b.updatedAt ? -1 : 1;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/**
 * 单个技能目录 → 一项。
 *
 * SKILL.md 缺失 / frontmatter 解析失败：name 回落目录名、description 空串 ——
 * 扫描绝不能因为一个坏文件整体失败（spec §4.3）。技能目录 stat 不出来（并发被删）
 * 才跳过该项。
 */
function scanSkillDir(skillDir: string, dirName: string): SkillItem | null {
  const updatedAt = skillMtime(skillDir);
  if (updatedAt === null) return null;

  const version = detectSkillVersion(skillDir);
  const frontmatter = readSkillFrontmatter(skillDir, version);
  return {
    name: typeof frontmatter.name === 'string' && frontmatter.name !== '' ? frontmatter.name : dirName,
    path: skillDir,
    source: 'library',
    ownerAgentId: null,
    ownerName: null,
    version,
    description: typeof frontmatter.description === 'string' ? frontmatter.description : '',
    updatedAt,
  };
}

/** 列一个扫描面下的技能目录；ENOENT（首次使用还没产物）当空，其它错误照常抛。 */
function listSkillDirs(root: string): string[] {
  let entries;
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  return entries.filter((entry) => entry.isDirectory()).map((entry) => join(root, entry.name));
}

export const skillService = {
  async list(query: { workspaceId?: unknown }): Promise<SkillList> {
    const root = join(config.skillsRoot, 'output', 'skills');
    const cwd = config.skillsRoot;

    // library 组在前、agent 组在后；组内 updatedAt 倒序
    const libraryItems = listSkillDirs(root)
      .map((skillDir) => scanSkillDir(skillDir, skillDir.slice(root.length + 1)))
      .filter((item): item is SkillItem => item !== null)
      .sort(byRecencyDesc);

    const workspaceId = optionalString(query.workspaceId);
    if (workspaceId === undefined) return { root, cwd, items: libraryItems };
    readWorkspaceId(workspaceId);

    // 工作区未绑定目录 / 框架不可达 → 502（与 agents 列表同口径，不猜路径）
    const directory = await resolveWorkspaceDirectory(workspaceId);
    const agents = await agentsRepo.listByWorkspace(workspaceId);
    const agentItems: SkillItem[] = [];

    /** 一个扫描面（技能目录的父目录）→ 归到该智能体名下的条目 */
    const collect = (parent: string, owner: { id: string; name: string }): void => {
      for (const skillDir of listSkillDirs(parent)) {
        const item = scanSkillDir(skillDir, skillDir.slice(parent.length + 1));
        if (item === null) continue;
        agentItems.push({ ...item, source: 'agent', ownerAgentId: owner.id, ownerName: owner.name });
      }
    };

    for (const agent of agents) {
      const developmentDir = join(agentRoot(directory, agent.id), 'development');
      // 智能体产出的独立技能（skill-foundry 线）
      collect(join(developmentDir, 'output', 'skills'), agent);
      // 当前产物里自带的技能：构建器直接写进去的，或经 4.13 装配进来的。
      // 只认最新 vN（与运行期一致）；产物布局不唯一时 peek 给 null，这一路按空处理。
      const product = peekProducedAgent(developmentDir).agent;
      if (product !== null) collect(join(product.dir, '.claude', 'skills'), agent);
    }

    return { root, cwd, items: [...libraryItems, ...agentItems.sort(byRecencyDesc)] };
  },
};
