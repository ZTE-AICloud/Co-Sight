import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { basename, isAbsolute, join } from 'node:path';
import { BadRequestError, ConflictError, NotFoundError } from '../../shared/errors.js';
import { detectSkillVersion, readSkillFrontmatter, skillMtime } from '../../shared/skills/skill-md.js';
import { agentsRepo } from '../../shared/store/agents.repo.js';
import { instancesRepo } from '../../shared/store/instances.repo.js';
import { runsRepo } from '../../shared/store/runs.repo.js';
import { assertAgentId, stageDir } from '../../shared/workspace/dir-resolver.js';
import { locateProducedAgent, readProductionStatus, type ProducedAgent } from '../../shared/workspace/production.js';
import { agentRoot, resolveAgentWorkspace } from '../../shared/workspace/workspace-resolver.js';
import type { AgentSkillItem } from '../../shared/types/index.js';
import { optionalString, requireString } from '../../shared/validate.js';

/**
 * 智能体技能装配（2026-10-26 定稿的最小模型）。
 *
 * 装配 = 把库技能（或另一个智能体产出的技能）**整拷**进智能体当前产物的
 * `<product>/.claude/skills/<name>/`。引擎按 cwd 发现技能，复制完当下生效：
 * runtime 原地读产物，preview / evaluation 起 run 前从产物整拷（物化）。
 *
 * 明确不做：
 * - 不落库、不写 manifest、不记来源；
 * - 不改 CLAUDE.md / 规则文件；
 * - 不钉版、不做同步；重建出的新 vN 不会自动带上旧技能（用户重新装配）。
 *
 * 前置门禁：智能体是 user 来源、四个阶段都没有活跃 run、产物 `completed`
 * （判定与 preview / runtime 起跑门禁同源，见 shared/workspace/production.ts）。
 */

const VERSION_PATTERN = /^v\d+$/;
const DEVELOPMENT_STAGE = 'development';

/** 技能条目的形状与详情端点的可执行清单同一份（`AgentSkillItem` 在 shared/types）。 */
export type { AgentSkillItem };

export interface AgentProductRef {
  agentName: string;
  version: string;
  dir: string;
}

export interface AgentSkillList {
  agentId: string;
  /** 产物就绪才为 true；未就绪时 items 为空、reasons 说明原因 */
  ready: boolean;
  reasons: string[];
  product: AgentProductRef | null;
  items: AgentSkillItem[];
}

export interface AttachSkillInput {
  path?: unknown;
  version?: unknown;
}

export interface AttachSkillResult {
  item: AgentSkillItem;
  product: AgentProductRef;
}

export interface RemoveSkillInput {
  name?: unknown;
}

export interface RemoveSkillResult {
  removed: string;
}

function toProductRef(produced: ProducedAgent): AgentProductRef {
  return { agentName: produced.agentName, version: produced.version, dir: produced.dir };
}

/** 技能目录名只接受单段；名字来自盘上的真实目录，这里只挡路径逃逸与隐藏目录。 */
function assertSkillDirName(name: string): void {
  if (
    name === '' ||
    name === '.' ||
    name === '..' ||
    name.startsWith('.') ||
    /[/\\\0]/u.test(name)
  ) {
    throw new BadRequestError(
      `技能目录名不是合法的单段名：${JSON.stringify(name)}`,
      'error.bad_request.invalid_skill_name',
      { name },
    );
  }
}

/** user 智能体：内置定义目录只读，不参与装配。 */
async function resolveUserWorkspace(agentId: string) {
  assertAgentId(agentId);
  const workspace = await resolveAgentWorkspace(agentId);
  if (workspace.source === 'builtin') {
    throw new ConflictError(
      `智能体 ${agentId} 是内置智能体，定义目录只读，不支持装配技能`,
      'error.conflict.builtin_agent',
      { agentId },
    );
  }
  return workspace;
}

/** 四个阶段任一有活跃 run 都拒绝：正在跑的会话可能读着产物里的技能。 */
async function assertNoActiveRun(agentId: string): Promise<void> {
  const instanceIds = await agentsRepo.instanceIdsOf(agentId);
  if (await runsRepo.hasActiveIn(instanceIds)) {
    throw new ConflictError(
      `智能体 ${agentId} 有活跃 run，先 abort 再装配 / 删除技能`,
      'error.conflict.active_run',
      { agentId },
    );
  }
}

function developmentDirOf(directory: string, agentId: string): string {
  return stageDir(agentRoot(directory, agentId), DEVELOPMENT_STAGE);
}

/**
 * 写操作的就绪门禁：未就绪统一 409（与 preview / runtime 起跑同源），
 * 不把「还没生成」透成 404 —— 对调用方来说这是状态问题，不是资源不存在。
 */
function assertProductReady(developmentDir: string): ProducedAgent {
  const production = readProductionStatus(developmentDir);
  if (!production.ready) {
    const reason = production.reasons.join('；');
    throw new ConflictError(
      `产物未就绪，不能修改技能：${reason}`,
      'error.conflict.production_not_ready',
      { reason },
    );
  }
  return locateProducedAgent(developmentDir);
}

/** `.claude/skills` 下的直接子目录名；目录不存在按空处理。 */
function listSkillDirNames(skillsDir: string): string[] {
  let entries;
  try {
    entries = readdirSync(skillsDir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  return entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function itemOf(skillDir: string, dirName: string): AgentSkillItem {
  const frontmatter = readSkillFrontmatter(skillDir, '');
  const displayName = frontmatter.name?.trim() || dirName;
  return {
    name: dirName,
    displayName,
    description: frontmatter.description ?? '',
    version: frontmatter.version?.trim() ?? '',
    path: skillDir,
    updatedAt: skillMtime(skillDir) ?? new Date(0).toISOString(),
  };
}

/** 产物 `.claude/skills` 的清单：不记来源，构建生成的与装配进来的完全同构。 */
function scanProductSkills(productDir: string): AgentSkillItem[] {
  const skillsDir = join(productDir, '.claude', 'skills');
  const items: AgentSkillItem[] = [];
  for (const dirName of listSkillDirNames(skillsDir)) {
    const skillDir = join(skillsDir, dirName);
    if (skillMtime(skillDir) === null) continue; // 并发删除：跳过该项，不整体失败
    items.push(itemOf(skillDir, dirName));
  }
  return items;
}

/**
 * 来源版本：显式给了就校验形态与存在性；没给就取目录内数字最大的 `vN`，
 * 没有版本子目录时为空串（SKILL.md 直接在技能目录下）。
 */
function readSourceVersion(value: unknown, sourcePath: string): string {
  const raw = optionalString(value);
  if (raw === undefined) return detectSkillVersion(sourcePath);
  if (!VERSION_PATTERN.test(raw)) {
    throw new BadRequestError(
      `version 形态非法：${JSON.stringify(raw)}（应为 v1 / v2 这类版本目录名）`,
      'error.bad_request.invalid_value',
      { name: 'version', value: JSON.stringify(raw), allowed: 'v<数字>' },
    );
  }
  let stat;
  try {
    stat = statSync(join(sourcePath, raw));
  } catch {
    throw new BadRequestError(`技能版本 ${raw} 不存在：${sourcePath}`, 'error.bad_request.invalid_value', {
      name: 'version',
      value: raw,
      allowed: '来源目录下已存在的 v<数字>',
    });
  }
  if (!stat.isDirectory()) {
    throw new BadRequestError(`技能版本 ${raw} 不是目录：${sourcePath}`, 'error.bad_request.invalid_value', {
      name: 'version',
      value: raw,
      allowed: '来源目录下已存在的 v<数字>',
    });
  }
  return raw;
}

/**
 * 同名判定同时看目录名与 frontmatter name：
 * 引擎按目录发现技能，但模型侧按 SKILL.md 的 name 识别 —— 两者任一撞上都算冲突。
 */
function assertNoNameConflict(skillsDir: string, installName: string, displayName: string): void {
  for (const existing of listSkillDirNames(skillsDir)) {
    const existingDir = join(skillsDir, existing);
    const existingName = readSkillFrontmatter(existingDir, '').name?.trim() ?? '';
    if (
      existing === installName ||
      existing === displayName ||
      existingName === installName ||
      existingName === displayName
    ) {
      throw new ConflictError(
        `目标产物已有同名技能：${displayName}`,
        'error.conflict.skill_exists',
        { name: displayName },
      );
    }
  }
}

export const agentSkillService = {
  /** 产物技能清单。未就绪也是 200，用 ready / reasons 表达，前端不用靠错误码区分状态。 */
  async listSkills(agentId: string): Promise<AgentSkillList> {
    const workspace = await resolveUserWorkspace(agentId);
    const developmentDir = developmentDirOf(workspace.directory, agentId);

    // 只读查实例，不 getOrCreate：列技能不该顺手建出一行实例
    const instance = await instancesRepo.findByAgentAndStage(agentId, DEVELOPMENT_STAGE);
    const hasActiveRun = instance === null ? false : await runsRepo.hasActiveIn([instance.id]);
    const production = readProductionStatus(developmentDir, { hasActiveRun });
    if (!production.ready) {
      return { agentId, ready: false, reasons: production.reasons, product: null, items: [] };
    }

    const product = locateProducedAgent(developmentDir);
    return {
      agentId,
      ready: true,
      reasons: [],
      product: toProductRef(product),
      items: scanProductSkills(product.dir),
    };
  },

  /**
   * 装配：把来源技能的最新版本整拷进产物 `.claude/skills/<目录名>/`。
   *
   * 顺序固定：形态 → 来源存在 → 产物就绪（含活跃 run 守卫）→ 同名 → 复制。
   * 400 / 404 / 409 都不产生半成品：复制是最后一步，且 `errorOnExist` 兜住并发。
   */
  async attachSkill(agentId: string, input: AttachSkillInput): Promise<AttachSkillResult> {
    const sourcePath = requireString(input.path, 'path');
    if (!isAbsolute(sourcePath)) {
      throw new BadRequestError(`path 必须是绝对路径：${sourcePath}`, 'error.bad_request.absolute_path', {
        name: 'path',
        path: sourcePath,
      });
    }

    let sourceStat;
    try {
      sourceStat = statSync(sourcePath);
    } catch {
      throw new NotFoundError(`技能目录 ${sourcePath}`, 'error.not_found.skill', { name: sourcePath });
    }
    if (!sourceStat.isDirectory()) {
      throw new BadRequestError(`path 不是目录：${sourcePath}`, 'error.bad_request.invalid_value', {
        name: 'path',
        value: sourcePath,
        allowed: '目录',
      });
    }

    const version = readSourceVersion(input.version, sourcePath);
    const sourceDir = version === '' ? sourcePath : join(sourcePath, version);
    if (!existsSync(join(sourceDir, 'SKILL.md'))) {
      throw new BadRequestError(
        `不是可运行的技能：${sourceDir} 缺少 SKILL.md`,
        'error.bad_request.skill_md_missing',
        { path: sourceDir },
      );
    }

    const installName = basename(sourcePath);
    assertSkillDirName(installName);
    const displayName = readSkillFrontmatter(sourcePath, version).name?.trim() || installName;

    // 副作用从这一行之后才开始：工作区解析、就绪门禁、活跃 run 守卫都不落盘
    const workspace = await resolveUserWorkspace(agentId);
    await assertNoActiveRun(agentId);
    const product = assertProductReady(developmentDirOf(workspace.directory, agentId));

    const skillsDir = join(product.dir, '.claude', 'skills');
    mkdirSync(skillsDir, { recursive: true });
    assertNoNameConflict(skillsDir, installName, displayName);

    const target = join(skillsDir, installName);
    try {
      cpSync(sourceDir, target, { recursive: true, force: false, errorOnExist: true });
    } catch (error) {
      // 预检与复制之间的并发窗口：目录刚被别的请求建出来
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
        throw new ConflictError(
          `目标产物已有同名技能：${displayName}`,
          'error.conflict.skill_exists',
          { name: displayName },
        );
      }
      throw error;
    }

    return { item: itemOf(target, installName), product: toProductRef(product) };
  },

  /** 从产物删除一个技能目录；不存在 404，不幂等。 */
  async removeSkill(agentId: string, input: RemoveSkillInput): Promise<RemoveSkillResult> {
    const name = requireString(input.name, 'name').trim();
    assertSkillDirName(name);

    const workspace = await resolveUserWorkspace(agentId);
    await assertNoActiveRun(agentId);
    const product = assertProductReady(developmentDirOf(workspace.directory, agentId));

    const target = join(product.dir, '.claude', 'skills', name);
    let stat;
    try {
      stat = statSync(target);
    } catch {
      throw new NotFoundError(`技能 ${name}`, 'error.not_found.skill', { name });
    }
    if (!stat.isDirectory()) {
      throw new NotFoundError(`技能 ${name}`, 'error.not_found.skill', { name });
    }

    // Windows 上文件可能被短暂占用（EBUSY / EPERM），留给内核几轮释放时间
    rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
    return { removed: name };
  },
};
